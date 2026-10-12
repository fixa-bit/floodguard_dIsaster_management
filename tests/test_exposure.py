"""Synthetic GIS fixtures are test data only and never enter operational datasets."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import fiona
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import Point, LineString, box, mapping
from shapely.ops import transform

from app.core.exceptions import AppError
from app.gis.exposure_engine import DatasetBundle, GEOD, audit_bundle, calculate, polygon_extent, population_exposure
from app.schemas.exposure import ExposureRequest
from app.services.exposure_service import ExposureService


@pytest.fixture
def exposure_data(tmp_path):
    root=tmp_path/'datasets'; pilot=root/'processed/fixture'
    aoi=box(0,0,2,2)
    population=pilot/'population/population_2025.tif'; population.parent.mkdir(parents=True)
    with rasterio.open(population,'w',driver='GTiff',height=2,width=2,count=1,dtype='float32',crs=4326,transform=from_origin(0,2,1,1),nodata=-999) as src:
        src.write(np.array([[10,20],[30,-999]],dtype='float32'),1)
    props={'osm_id':'str','osm_type':'str','feature_id':'str','tags_json':'str','name':'str','building':'str','amenity':'str','place':'str',
           'highway':'str','u':'str','v':'str','direction':'str','length_m':'float'}
    defaults={k:None for k in props}
    def record(g,ident,**extra):
        p=dict(defaults,osm_id=str(ident),osm_type='way' if g.geom_type!='Point' else 'node',feature_id=f'object/{ident}',tags_json='{"test_fixture":true}',**extra)
        return {'geometry':mapping(g),'properties':p}
    road=LineString([(0,1),(2,1)])
    building=box(.1,.1,.3,.3)
    layers={
        'roads':[record(road,1,highway='residential',u='node/1',v='node/2',direction='bidirectional',length_m=GEOD.geometry_length(road)),record(road,1,highway='residential',u='node/1',v='node/2',direction='bidirectional',length_m=GEOD.geometry_length(road))],
        'buildings':[record(building,2,building='yes'),record(building,3,building='yes'),record(box(.5,.1,.7,.3),4,building='yes')],
        'hospitals':[record(Point(.25,.5),5,amenity='hospital',name='Synthetic hospital fixture')],
        'schools':[record(Point(.5,1.5),6,amenity='school')],
        'settlements':[record(Point(1.5,.5),7,place='village')]}
    for name,features in layers.items():
        path=pilot/name/(name+('.geojson' if name in ('hospitals','schools') else '.gpkg'))
        path.parent.mkdir(parents=True)
        with fiona.open(path,'w',driver='GeoJSON' if path.suffix=='.geojson' else 'GPKG',crs='EPSG:4326',schema={'geometry':'Unknown','properties':props},**({'layer':name} if path.suffix=='.gpkg' else {})) as dst:
            dst.writerecords(features)
    metadata=root/'metadata'; metadata.mkdir()
    sources={'worldpop':{'year':2025,'license':'Synthetic fixture; not actual WorldPop'},'osm':{'version':'synthetic','license':'Test fixtures only'}}
    m={'runs':{'fixture':{'area':{'geometry':mapping(aoi),'selection':{'name':'fixture','mode':'bbox','verified':True,'note':'Synthetic unit test AOI'}},'source_snapshots':sources}}}
    (metadata/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
    return root,pilot,aoi


def test_fractional_population_preserves_counts_and_nodata(exposure_data):
    root,pilot,aoi=exposure_data
    path=pilot/'population/population_2025.tif'
    before=path.read_bytes()
    result=population_exposure(path,box(0,0,.5,2),aoi)
    assert result['estimated_exposed_population']==pytest.approx(20,rel=1e-10)
    assert result['known_population_total']==60
    assert result['nodata_cells_in_flood']==0
    assert path.read_bytes()==before
    unknown=population_exposure(path,box(1.1,.1,1.9,.9),aoi)
    assert unknown['estimated_exposed_population'] is None
    assert unknown['nodata_cells_in_flood']==1


def test_union_holes_empty_and_projected_flood_crs(exposure_data):
    _,pilot,aoi=exposure_data
    overlapping={'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':mapping(box(0,0,.75,2))},{'type':'Feature','properties':{},'geometry':mapping(box(.25,0,.5,2))}]}
    flood=polygon_extent(overlapping)
    assert population_exposure(pilot/'population/population_2025.tif',flood,aoi)['estimated_exposed_population']==pytest.approx(30)
    projected=transform(Transformer.from_crs(4326,3857,always_xy=True).transform,flood)
    restored=polygon_extent(mapping(projected),'EPSG:3857')
    assert restored.symmetric_difference(flood).area<1e-10
    holed=box(0,0,2,2).difference(box(0,0,1,1))
    assert population_exposure(pilot/'population/population_2025.tif',holed,aoi)['estimated_exposed_population']==pytest.approx(30)
    empty=polygon_extent({'type':'FeatureCollection','features':[]})
    assert population_exposure(pilot/'population/population_2025.tif',empty,aoi)['estimated_exposed_population']==0
    with pytest.raises(AppError) as error:
        polygon_extent({'type':'Polygon','coordinates':[[[0,0],[1,1],[0,1],[1,0],[0,0]]]})
    assert error.value.status_code==422


def test_intersections_geodesic_roads_deduplication_and_boundary_rules(exposure_data,tmp_path):
    root,_,_=exposure_data
    bundle=DatasetBundle(root,'fixture')
    flood=box(0,0,.5,2)
    summary=calculate(bundle,flood,{'kind':'synthetic_sample','label':'TEST ONLY','is_sample':True},tmp_path/'result',include_reference=False)
    infra=summary['infrastructure']
    assert infra['buildings']['affected_count']==1
    assert infra['buildings']['duplicate_footprints_skipped']==1
    assert infra['roads']['affected_count']==1
    assert infra['roads']['duplicate_ids_skipped']==1
    assert infra['roads']['affected_unique_osm_ways']==1
    expected=GEOD.geometry_length(LineString([(0,1),(.5,1)]))/1000
    assert infra['roads']['affected_length_km']==pytest.approx(expected,rel=1e-10)
    assert infra['hospitals']['affected_count']==1
    assert infra['schools']['affected_count']==1  # Point on flood boundary is included.
    assert infra['settlements']['affected_count']==0
    for file in (tmp_path/'result').glob('*.geojson'):
        layer=json.loads(file.read_text(encoding='utf-8'))
        assert layer['metadata']['is_sample'] is True
        assert layer['metadata']['crs']=='EPSG:4326'
        assert len(layer['features'])==layer['metadata']['feature_count']


def test_audit_missing_data_and_disjoint_extent(exposure_data,tmp_path):
    root,pilot,aoi=exposure_data
    bundle=DatasetBundle(root,'fixture')
    report=audit_bundle(bundle,include_reference=False)
    assert report['technical_status']=='PASSED'
    assert report['datasets']['roads']['duplicate_ids']==1
    result=calculate(bundle,box(10,10,11,11),{'kind':'synthetic_sample','label':'TEST ONLY','is_sample':True},tmp_path/'outside',include_reference=False)
    assert result['population']['estimated_exposed_population']==0
    assert all(v['affected_count']==0 for v in result['infrastructure'].values())
    touching=calculate(bundle,box(2,0,3,2),{'kind':'synthetic_sample','label':'TOUCH ONLY','is_sample':True},tmp_path/'touching',include_reference=False)
    assert touching['flood']['analyzed_extent_area_km2']==0
    assert touching['population']['estimated_exposed_population']==0
    (pilot/'roads/roads.gpkg').unlink()
    service=ExposureService(root,tmp_path/'results')
    with pytest.raises(AppError) as error:
        service.analyze(ExposureRequest(region='fixture',flood_source='sample',include_reference_buildings=False))
    assert error.value.code=='EXPOSURE_DATASET_BLOCKED'
    assert error.value.status_code==503


def test_api_outputs_and_sample_labels(client,exposure_data,tmp_path,monkeypatch):
    import app.services.exposure_service as module
    root,_,_=exposure_data
    monkeypatch.setattr(module,'get_settings',lambda:SimpleNamespace(exposure_dataset_root=str(root),exposure_output_root=str(tmp_path/'api-results')))
    assert client.get('/api/v1/exposure/regions').json()['regions'][0]['region']=='fixture'
    audit=client.get('/api/v1/exposure/regions/fixture/audit?include_reference_buildings=false')
    assert audit.status_code==200
    assert audit.json()['technical_status']=='PASSED'
    response=client.post('/api/v1/exposure/analyses',json={'region':'fixture','flood_source':'sample','include_reference_buildings':False})
    assert response.status_code==201,response.text
    summary=response.json()
    assert summary['flood']['is_sample'] is True
    assert summary['flood']['kind']=='synthetic_sample'
    assert client.get(summary['summary_url']).json()['analysis_id']==summary['analysis_id']
    for url in summary['layers'].values():
        layer=client.get(url)
        assert layer.status_code==200
        assert layer.json()['metadata']['is_sample'] is True
    assert client.post('/api/v1/exposure/analyses',json={'region':'../escape','flood_source':'sample'}).status_code==422
    assert client.post('/api/v1/exposure/analyses',json={'region':'fixture','flood_source':'provided'}).status_code==422
    assert client.get('/api/v1/exposure/analyses/fixture/not-a-uuid').status_code==422
    assert client.get(summary['summary_url']+'/layers/unknown').status_code==404


def test_unfinished_artifacts_are_not_published(tmp_path):
    service=ExposureService(tmp_path/'data',tmp_path/'results')
    ident=str(uuid4()); folder=service.outputs/'fixture'/ident; folder.mkdir(parents=True)
    (folder/'summary.json').write_text('{}')
    (folder/'status.json').write_text('{"status":"FAILED"}')
    with pytest.raises(AppError) as error:
        service.artifact('fixture',ident)
    assert error.value.status_code==404
