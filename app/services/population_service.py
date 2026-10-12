"""Durable population jobs; no expensive GIS calculation blocks an HTTP request."""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from shapely.geometry import box, mapping

from app.core.exceptions import AppError
from app.gis.exposure_engine import DatasetBundle, SLUG, area_m2, infrastructure_exposure, polygon_extent, timestamp, write_json
from app.gis.population_analysis import administrative_units, analyze_population, segmentation_flood
from app.schemas.population import PopulationRequest
from app.services.exposure_service import ExposureService

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='population-gis')
_job_lock = threading.Lock()
LAYERS = {'flood_extent', 'administrative_exposure', 'population_grid', 'settlements'}


class PopulationService:
    def __init__(self, dataset_root=None, output_root=None):
        exposure = ExposureService(dataset_root, output_root)
        self.root = exposure.root
        self.outputs = exposure.outputs / 'population'

    def folder(self, region, ident):
        if not SLUG.fullmatch(region):
            raise AppError('INVALID_REGION', 'Invalid region', 422)
        try:
            ident = str(UUID(ident))
        except ValueError as exc:
            raise AppError('INVALID_ANALYSIS_ID', 'Analysis ID must be a UUID', 422) from exc
        return self.outputs / region / ident

    def status(self, region, ident):
        path = self.folder(region, ident) / 'status.json'
        if not path.exists():
            raise AppError('POPULATION_JOB_NOT_FOUND', 'Population analysis not found', 404)
        return json.loads(path.read_text(encoding='utf-8'))

    def artifact(self, region, ident, layer=None):
        if layer is not None and layer not in LAYERS:
            raise AppError('UNKNOWN_POPULATION_LAYER', 'Unknown population layer', 404)
        if self.status(region, ident)['status'] != 'COMPLETED':
            raise AppError('POPULATION_NOT_COMPLETE', 'Results are available only after completion', 409)
        path = self.folder(region, ident) / (layer+'.geojson' if layer else 'summary.json')
        if not path.exists():
            raise AppError('POPULATION_ARTIFACT_MISSING', 'Requested artifact is unavailable', 404)
        return path

    def latest(self, region):
        if not SLUG.fullmatch(region):
            raise AppError('INVALID_REGION', 'Invalid region', 422)
        folder = self.outputs / region
        paths = sorted(folder.glob('*/status.json'), key=lambda p:p.stat().st_mtime, reverse=True) if folder.exists() else []
        for path in paths:
            if json.loads(path.read_text(encoding='utf-8')).get('status') == 'COMPLETED':
                return json.loads((path.parent/'summary.json').read_text(encoding='utf-8'))
        return None

    def start(self, request):
        DatasetBundle(self.root, request.region)
        if request.flood_source == 'provided':
            polygon_extent(request.flood_extent, request.flood_crs)
        if not _job_lock.acquire(blocking=False):
            raise AppError('POPULATION_BUSY', 'A population calculation is running; wait for completion', 409)
        ident = str(uuid4())
        destination = self.folder(request.region, ident)
        try:
            status = {'status':'QUEUED', 'analysis_id':ident, 'region':request.region,
                      'status_url':f'/api/v1/population/analyses/{request.region}/{ident}/status'}
            write_json(destination/'request.json', request.model_dump())
            write_json(destination/'status.json', status)
            future = _executor.submit(self._run, request, ident, status)
            def check_failure(done):
                error = done.exception()
                if error:
                    logging.getLogger(__name__).error('Population job %s could not persist its final status: %s', ident, error)
            future.add_done_callback(check_failure)
            return status
        except Exception:
            _job_lock.release()
            raise

    def _run(self, request, ident, status):
        destination = self.folder(request.region, ident)
        try:
            write_json(destination/'status.json', dict(status,status='RUNNING',started_at=timestamp()))
            self.calculate(request, ident)
            write_json(destination/'status.json', dict(status,status='COMPLETED',completed_at=timestamp(),
                summary_url=f'/api/v1/population/analyses/{request.region}/{ident}'))
        except Exception as exc:
            write_json(destination/'status.json', dict(status,status='FAILED',failed_at=timestamp(),
                error={'code':getattr(exc,'code','POPULATION_FAILED'),'message':str(getattr(exc,'message',exc))}))
        finally:
            _job_lock.release()

    def calculate(self, request: PopulationRequest, ident):
        bundle = DatasetBundle(self.root, request.region)
        if request.flood_source == 'historical_reference':
            flood, provenance = bundle.historical_flood()
        elif request.flood_source == 'segmentation':
            flood, provenance = segmentation_flood(bundle)
        elif request.flood_source == 'provided':
            flood = polygon_extent(request.flood_extent, request.flood_crs)
            provenance = {'kind':'user_provided_unverified','is_sample':False,'label':request.flood_label,'declared_crs':request.flood_crs}
        else:
            station = bundle.configuration.get('area',{}).get('station',{}).get('coordinates')
            x,y = station if station else bundle.aoi.representative_point().coords[0]
            flood = box(x-.04,y-.03,x+.04,y+.03)
            provenance = {'kind':'synthetic_sample','is_sample':True,'label':'SYNTHETIC TEST — not observed or forecast flooding'}
        from app.gis.exposure_engine import polygonal
        flood = polygonal(flood.intersection(bundle.aoi))
        levels, notes = administrative_units(bundle)
        population, administrative, checks, distribution, admin_features, grid_features = analyze_population(bundle.paths['population'],bundle.aoi,flood,levels,request.grid_km)
        destination = self.folder(request.region,ident)
        metadata = {'region':request.region,'flood_kind':provenance['kind'],'is_sample':provenance['is_sample'],'flood_label':provenance['label'],'crs':'EPSG:4326'}
        def layer(name, features, extra=None):
            for feature in features:
                feature['properties'].update(is_sample=provenance['is_sample'],flood_kind=provenance['kind'])
            write_json(destination/(name+'.geojson'),{'type':'FeatureCollection','features':features,'metadata':dict(metadata,**(extra or {}))})
        layer('flood_extent', [] if flood.is_empty else [{'type':'Feature','geometry':mapping(flood),'properties':{}}])
        layer('administrative_exposure',admin_features)
        layer('population_grid',grid_features,{'grid_km':request.grid_km,'method':'Display aggregation by native cell centre; exact admin statistics use polygon fractions.'})
        if bundle.paths['settlements'].exists():
            settlements = infrastructure_exposure(bundle.paths['settlements'],'settlements',flood,bundle.aoi,destination/'settlements.geojson',metadata)
        else:
            settlements = {'affected_count':None,'status':'MISSING'}
            notes.append('Settlement inventory missing; exposed settlement count is unknown.')
            layer('settlements',[])
        summary = {'analysis_id':ident,'region':request.region,'calculated_at':timestamp(),'population':population,
                   'flood':dict(provenance,analyzed_extent_area_km2=area_m2(flood)/1e6),'administrative':administrative,
                   'administrative_availability':{level:'AVAILABLE' if level in levels else 'UNAVAILABLE' for level in ('ADM2','ADM3')},
                   'aggregation_checks':checks,'density_distribution':distribution,'settlements':settlements,
                   'bounds':list(bundle.aoi.bounds),'sources':bundle.sources,'notes':notes,
                   'warnings':['Estimates cover known population cells only; nodata is unknown, never zero.',
                               'Percentage uses known population within the study polygon as denominator; it is not a complete census percentage.',
                               'Uniform within-cell population is assumed. Original raster values and grid remain unchanged.',
                               'Display grid groups native cell centres; use administrative polygons for exact regional totals.',
                               'Settlement exposure does not establish isolation or evacuation needs.'],
                   'alignment':{'status':'OVERLAPS' if not flood.is_empty else 'NO_FLOOD_OVERLAP','population_crs_checked':True,'flood_kind':provenance['kind']}}
        prefix = f'/api/v1/population/analyses/{request.region}/{ident}'
        summary.update(summary_url=prefix,layers={name:prefix+'/layers/'+name for name in LAYERS})
        write_json(destination/'summary.json',summary)
        return summary
