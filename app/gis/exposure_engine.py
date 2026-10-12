"""GIS exposure calculations over prepared count rasters and source-identified vectors."""
from __future__ import annotations

import hashlib
import json
import re
import time
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import fiona
import numpy as np
import rasterio
import shapely
from pyproj import CRS, Geod, Transformer
from rasterio.features import geometry_mask
from rasterio.warp import transform_bounds
from shapely.geometry import GeometryCollection, Point, box, mapping, shape
from shapely.ops import transform, unary_union
from shapely.prepared import prep

from app.core.exceptions import AppError

GEOD = Geod(ellps="WGS84")
EQUAL_AREA = Transformer.from_crs(4326, 6933, always_xy=True)
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VECTOR_NAMES = ("roads", "buildings", "hospitals", "schools", "settlements")
REQUIRED = {"roads": {"osm_id", "u", "v", "highway", "direction", "length_m", "tags_json"},
            "buildings": {"osm_id", "building", "tags_json"},
            "hospitals": {"osm_id", "tags_json"}, "schools": {"osm_id", "tags_json"},
            "settlements": {"osm_id", "place", "tags_json"},
            "reference_buildings": {"reference_id", "source_file", "quadkey"}}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    # Windows readers can briefly hold a sharing lock during status polling.
    # Keep atomic publication and retry the replace rather than losing a job update.
    try:
        for attempt in range(10):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(min(.01 * 2**attempt, .2))
    finally:
        temporary.unlink(missing_ok=True)


def convert_geometry(g, source, target=4326):
    source, target = CRS.from_user_input(source), CRS.from_user_input(target)
    return g if source == target else transform(Transformer.from_crs(source, target, always_xy=True).transform, g)


def area_m2(g):
    return transform(EQUAL_AREA.transform, g).area if not g.is_empty else 0.0


def polygonal(g):
    if g.geom_type in ('Polygon','MultiPolygon'):
        return g
    if g.geom_type=='GeometryCollection':
        return unary_union([polygonal(part) for part in g.geoms if part.geom_type in ('Polygon','MultiPolygon','GeometryCollection')])
    return GeometryCollection()


def polygon_extent(payload, crs="EPSG:4326"):
    """Reject invalid/nonpolygon input; union overlapping features before any counts."""
    try:
        if not isinstance(payload, dict):
            raise ValueError("Expected a GeoJSON object")
        kind = payload.get("type")
        if kind == "FeatureCollection":
            features = payload.get("features", [])
            if len(features) > 1000:
                raise ValueError("At most 1000 flood features are accepted per analysis")
            geometries = [f.get("geometry") for f in features]
        elif kind == "Feature":
            geometries = [payload.get("geometry")]
        else:
            geometries = [payload]
        output=[]; coordinates=0
        for raw in geometries:
            g=shape(raw)
            if g.geom_type not in ("Polygon", "MultiPolygon") or g.is_empty or not g.is_valid:
                raise ValueError("Each flood geometry must be a nonempty valid polygon; repair explicitly before submitting")
            coordinates+=shapely.get_num_coordinates(g)
            if coordinates > 250000:
                raise ValueError("Flood request exceeds the total coordinate limit")
            g=shapely.force_2d(convert_geometry(g, crs))
            bounds=g.bounds
            if not np.isfinite(bounds).all() or not (-180<=bounds[0]<=bounds[2]<=180 and -90<=bounds[1]<=bounds[3]<=90):
                raise ValueError("Flood coordinates are incompatible with the declared CRS")
            if not g.is_valid:
                raise ValueError("Flood geometry became invalid after CRS transformation")
            output.append(g)
        return unary_union(output) if output else GeometryCollection()
    except AppError:
        raise
    except Exception as exc:
        raise AppError("INVALID_FLOOD_EXTENT", str(exc), 422) from exc


@dataclass
class DatasetBundle:
    root: Path
    region: str

    def __post_init__(self):
        self.root=Path(self.root).resolve()
        if not SLUG.fullmatch(self.region):
            raise AppError("INVALID_REGION", "Region must be a safe configured dataset name", 422)
        self.pilot=self.root/"processed"/self.region
        local=self.pilot/"metadata/manifest.json"
        try:
            if local.exists():
                m=json.loads(local.read_text(encoding="utf-8"))
                self.run=m["run"]; self.sources=m["sources"]
                self.configuration=m.get("configuration", {})
            else:
                m=json.loads((self.root/"metadata/manifest.json").read_text(encoding="utf-8"))
                self.run=m["runs"][self.region]; self.sources=self.run["source_snapshots"]
                self.configuration={"area":self.run["area"]["selection"]}
            self.aoi=shape(self.run["area"]["geometry"])
            if not self.aoi.is_valid or self.aoi.is_empty or self.aoi.geom_type not in ("Polygon", "MultiPolygon"):
                raise ValueError("Study polygon invalid")
        except Exception as exc:
            raise AppError("EXPOSURE_DATASET_NOT_READY", f"Prepared manifest/study area unavailable for {self.region}: {exc}", 503) from exc
        self.paths={name:self.pilot/name/(name+(".geojson" if name in ("hospitals", "schools") else ".gpkg")) for name in VECTOR_NAMES}
        self.paths["population"]=self.pilot/"population/population_2025.tif"
        self.paths["reference_buildings"]=self.pilot/"reference_buildings/buildings.gpkg"
        verification=self.pilot/"validation_reports/source_verification.json"
        if not verification.exists():
            verification=self.root/f"validation_reports/{self.region}_source_verification.json"
        self.verification=json.loads(verification.read_text(encoding="utf-8")) if verification.exists() else {}

    def signatures(self, include_reference=True):
        names=("population", *VECTOR_NAMES, *(("reference_buildings",) if include_reference else ()))
        return tuple((n,self.paths[n].stat().st_size,self.paths[n].stat().st_mtime_ns) if self.paths[n].exists() else (n,None,None) for n in names)

    def historical_flood(self):
        info=self.verification.get("flood_reference", {})
        if info.get("status") != "COMPATIBLE_REFERENCE_EXTENT" or not info.get("path"):
            raise AppError("FLOOD_REFERENCE_UNAVAILABLE", "No verified historical reference is configured; provide polygons or explicitly choose sample", 503)
        path=(self.root/info["path"]).resolve()
        if not path.is_relative_to(self.root) or not path.exists():
            raise AppError("FLOOD_REFERENCE_UNAVAILABLE", "Reference layer is missing from configured storage", 503)
        geoms=[]
        for layer in info["layers"]:
            with fiona.open(path,layer=layer["layer"]) as src:
                if not src.crs:
                    raise AppError("FLOOD_REFERENCE_INVALID", "Reference CRS missing", 503)
                for f in src:
                    g=convert_geometry(shape(f["geometry"]),src.crs)
                    if not g.is_valid:
                        raise AppError("FLOOD_REFERENCE_INVALID", "Reference geometry invalid", 503)
                    geoms.append(g)
        return unary_union(geoms), {"kind":"historical_reference","is_sample":False,
            "label":"UNOSAT historical satellite-detected water reference", "source":info.get("source"),
            "observation_period":info.get("observation_period"), "resolution_m":info.get("resolution_m"),
            "limitations":info.get("limitations"), "geometry_repairs":info.get("geometry_repairs", [])}


def vector_rows(path, extent=None):
    with fiona.open(path) as src:
        if not src.crs:
            raise AppError("MISSING_CRS", f"CRS missing: {path.name}", 503)
        source_crs = CRS.from_user_input(src.crs)
        converter = None if source_crs == CRS.from_epsg(4326) else Transformer.from_crs(source_crs,4326,always_xy=True).transform
        rows=src.filter(bbox=convert_geometry(extent,4326,src.crs).bounds) if extent is not None and not extent.is_empty else src
        for f in rows:
            props=dict(f["properties"])
            g=shape(f["geometry"]) if f["geometry"] else GeometryCollection()
            if converter is not None:
                g=transform(converter,g)
            yield str(f["id"]),props,shapely.force_2d(g)


def object_id(props, fallback, name):
    if name == "reference_buildings":
        return str(props.get("reference_id") or fallback)
    if props.get("feature_id"):
        return str(props["feature_id"])
    return str(props.get("osm_type", "unknown"))+"/"+str(props.get("osm_id") or fallback)


def audit_bundle(bundle, include_reference=True):
    report={"region":bundle.region,"audited_at":timestamp(),"datasets":{},"warnings":[],
            "source_provenance":{k:{f:v.get(f) for f in ("version","year","license","raw_path","sha256")} for k,v in bundle.sources.items()},
            "coverage_status":"Real-world completeness is not established by file validity or OSM source counts"}
    names=["population",*VECTOR_NAMES]
    if include_reference and bundle.verification.get("buildings_reference",{}).get("status")=="ASSESSED":
        names.append("reference_buildings")
    contained=prep(bundle.aoi.buffer(1e-9))
    for name in names:
        path=bundle.paths[name]
        d={"status":"READY","issues":[],"bytes":path.stat().st_size if path.exists() else 0}
        try:
            if not path.exists():
                raise ValueError("Required file is missing")
            if name == "population":
                with rasterio.open(path) as src:
                    if not src.crs or src.count!=1 or src.nodata is None:
                        raise ValueError("Population requires one count band, CRS and nodata metadata")
                    footprint=box(*transform_bounds(src.crs,4326,*src.bounds,densify_pts=21))
                    if footprint.intersection(bundle.aoi).area <= 0:
                        raise ValueError("Population does not overlap study area")
                    total=0.; valid=negative=nonfinite=0
                    for _,window in src.block_windows(1):
                        a=src.read(1,window=window,masked=True); good=~np.ma.getmaskarray(a)
                        valid+=int(good.sum()); negative+=int(((a.data<0)&good).sum()); nonfinite+=int((~np.isfinite(a.data)&good).sum())
                        total+=float(a.sum(dtype="float64")) if a.count() else 0
                    if not valid or negative or nonfinite:
                        raise ValueError(f"Invalid counts: valid={valid}, negative={negative}, nonfinite={nonfinite}")
                    d.update(crs=src.crs.to_string(),bbox=list(footprint.bounds),valid_cells=valid,known_population_total=total,nodata=src.nodata)
            else:
                with fiona.open(path) as src:
                    missing=REQUIRED[name]-set(src.schema["properties"])
                    if missing:
                        raise ValueError("Required columns missing: "+", ".join(sorted(missing)))
                    d['crs']=CRS.from_user_input(src.crs).to_string()
                count=invalid=outside=duplicates=coincident=0; ids=set(); geoms=set(); missing_values={}
                for fid,p,g in vector_rows(path):
                    count+=1
                    invalid+=int(g.is_empty or not g.is_valid)
                    allowed = ('LineString','MultiLineString') if name=='roads' else ('Polygon','MultiPolygon') if name in ('buildings','reference_buildings') else ('Point','MultiPoint','Polygon','MultiPolygon')
                    invalid+=int(g.geom_type not in allowed)
                    outside+=int(not contained.covers(g))
                    ident=object_id(p,fid,name)
                    duplicates+=int(ident in ids); ids.add(ident)
                    h=hashlib.sha256(g.normalize().wkb).digest()
                    coincident+=int(h in geoms); geoms.add(h)
                    for field in REQUIRED[name]:
                        if p.get(field) is None or p.get(field)=='':
                            missing_values[field]=missing_values.get(field,0)+1
                    if name=='roads' and (not p.get('u') or not p.get('v') or p.get('direction') not in ('forward','reverse','bidirectional') or not p.get('length_m') or p['length_m']<=0):
                        invalid+=1
                d.update(feature_count=count,invalid_geometries=invalid,outside_aoi=outside,duplicate_ids=duplicates,coincident_geometries=coincident,missing_attribute_values=missing_values)
                expected=bundle.run.get('datasets',{}).get(name,{}).get('feature_count')
                if name=='reference_buildings':
                    expected=bundle.verification.get('buildings_reference',{}).get('feature_count')
                if expected is not None and expected!=count:
                    raise ValueError(f'Record count differs from preparation manifest: expected={expected}, actual={count}')
                if invalid or outside or missing_values:
                    raise ValueError(f"Invalid geometries/road edges={invalid}; outside study area={outside}; missing attributes={missing_values}")
                if duplicates or coincident or not count:
                    d['status']='REVIEW'; d['issues'].append('Duplicates, coincident geometry or an empty source require coverage review; duplicate IDs are suppressed in analysis')
        except Exception as exc:
            d['status']='BLOCKED'; d['issues'].append(str(exc))
        report['datasets'][name]=d
    if any(d['status']=='BLOCKED' for d in report['datasets'].values()):
        report['technical_status']='BLOCKED'
    else:
        report['technical_status']='PASSED'
    report['warnings'].extend(['OSM counts are mapped-source counts, not complete building/facility inventories.',
        'Constrained WorldPop nodata remains unknown, not zero population.',
        'Administrative geometry vintage must be reviewed for the analysis date.'])
    report['building_reference_coverage']=bundle.verification.get('buildings_reference',{})
    # Avoid returning large tile receipts in the API audit; the saved provenance report retains them.
    report['building_reference_coverage']={k:v for k,v in report['building_reference_coverage'].items() if k!='tiles'}
    return report


def population_exposure(path, flood, aoi, method='fractional_area'):
    result={'method':method,'units':'people','known_population_total':0.,'estimated_exposed_population':0.,
            'valid_cells_in_flood':0,'nodata_cells_in_flood':0,'covered_flood_area_km2':0.,
            'assumption':'Fractional method assumes uniform population within each source cell; count values are not reprojected or resampled.'}
    flood_area=area_m2(flood)
    with rasterio.open(path) as src:
        if not src.crs or src.nodata is None:
            raise AppError('INVALID_POPULATION','Population CRS/nodata missing',503)
        raster_flood=convert_geometry(flood,4326,src.crs)
        raster_aoi=convert_geometry(aoi,4326,src.crs)
        shapely.prepare(raster_flood)
        equal=Transformer.from_crs(src.crs,6933,always_xy=True)
        def metric(coords):
            x,y=equal.transform(coords[:,0],coords[:,1])
            return np.column_stack([x,y])
        for _,window in src.block_windows(1):
            values=src.read(1,window=window,masked=True)
            t=src.window_transform(window)
            inside=geometry_mask([mapping(raster_aoi)],out_shape=values.shape,transform=t,invert=True)
            valid=inside & ~np.ma.getmaskarray(values)
            if np.any(~np.isfinite(values.data[valid])) or np.any(values.data[valid]<0):
                raise AppError('INVALID_POPULATION','Negative/nonfinite population counts',503)
            result['known_population_total']+=float(values.data[valid].sum(dtype='float64'))
            if flood.is_empty:
                continue
            touched=geometry_mask([mapping(raster_flood)],out_shape=values.shape,transform=t,invert=True,all_touched=True)&inside
            rr,cc=np.nonzero(touched)
            if not len(rr):
                continue
            corners=[]
            for dx,dy in ((0,0),(1,0),(1,1),(0,1)):
                corners.append(np.column_stack([t.a*(cc+dx)+t.b*(rr+dy)+t.c,t.d*(cc+dx)+t.e*(rr+dy)+t.f]))
            cells=shapely.polygons(np.stack(corners,axis=1))
            cell_areas=shapely.area(shapely.transform(cells,metric))
            full=shapely.covers(raster_flood,cells)
            fractions=np.ones(len(cells))
            if (~full).any():
                partial=shapely.intersection(cells[~full],raster_flood)
                fractions[~full]=shapely.area(shapely.transform(partial,metric))/cell_areas[~full]
            fractions=np.clip(fractions,0,1)
            has_area=fractions>0
            good=valid[rr,cc]&has_area
            result['valid_cells_in_flood']+=int(good.sum())
            result['nodata_cells_in_flood']+=int((~valid[rr,cc]&has_area).sum())
            result['covered_flood_area_km2']+=float((cell_areas[good]*fractions[good]).sum()/1e6)
            if method=='cell_center':
                center=geometry_mask([mapping(raster_flood)],out_shape=values.shape,transform=t,invert=True)[rr,cc]
                weights=center.astype(float)
            else:
                weights=fractions
            result['estimated_exposed_population']+=float((values.data[rr[good],cc[good]]*weights[good]).sum(dtype='float64'))
    result['flood_area_with_known_population_fraction']=min(1.,result['covered_flood_area_km2']*1e6/flood_area) if flood_area else None
    if flood_area and not result['valid_cells_in_flood']:
        result['estimated_exposed_population']=None
        result['status']='UNKNOWN_NO_VALID_POPULATION_IN_FLOOD'
    else:
        result['status']='PARTIAL_COVERAGE' if flood_area and (result['nodata_cells_in_flood'] or result['flood_area_with_known_population_fraction']<0.999) else 'ESTIMATED'
    return result


class GeoJSONWriter:
    def __init__(self,path,metadata):
        self.stream=Path(path).open('w',encoding='utf-8'); self.count=0; self.metadata=metadata
        self.stream.write('{"type":"FeatureCollection","features":[')
    def add(self,g,props):
        if self.count:
            self.stream.write(',')
        self.stream.write(json.dumps({'type':'Feature','geometry':mapping(g),'properties':props},ensure_ascii=False,allow_nan=False,default=str))
        self.count+=1
    def close(self):
        self.stream.write('],"metadata":'+json.dumps(dict(self.metadata,feature_count=self.count),ensure_ascii=False,allow_nan=False)+'}')
        self.stream.close()


def infrastructure_exposure(path,name,flood,aoi,destination,metadata):
    writer=GeoJSONWriter(destination,metadata)
    result={'affected_count':0,'duplicate_ids_skipped':0,'duplicate_footprints_skipped':0,'affected_length_km':0.}
    identities=set(); footprints=set(); road_ways=set(); selected=prep(flood); boundary=prep(aoi)
    try:
        if not flood.is_empty:
            for fid,p,g in vector_rows(path,extent=flood):
                if g.is_empty or not g.is_valid:
                    raise AppError('INVALID_VECTOR',f'Invalid {name} geometry; run dataset audit',503)
                if not selected.intersects(g):
                    continue
                identity=object_id(p,fid,name)
                if identity in identities:
                    result['duplicate_ids_skipped']+=1; continue
                identities.add(identity)
                if not boundary.covers(g):
                    g=g.intersection(aoi)
                if name in ('buildings','reference_buildings'):
                    fingerprint=hashlib.sha256(g.normalize().wkb).digest()
                    if fingerprint in footprints:
                        result['duplicate_footprints_skipped']+=1; continue
                    footprints.add(fingerprint)
                if name=='roads':
                    fingerprint=(str(p.get('osm_type','way')),str(p.get('osm_id',identity)),hashlib.sha256(g.normalize().wkb).digest())
                    if fingerprint in footprints:
                        result.setdefault('duplicate_road_segments_skipped',0)
                        result['duplicate_road_segments_skipped']+=1
                        continue
                    footprints.add(fingerprint)
                part=g if selected.covers(g) else g.intersection(flood)
                if name=='roads':
                    if part.geom_type not in ('LineString','MultiLineString','GeometryCollection'):
                        continue
                    lines=[part] if part.geom_type in ('LineString','MultiLineString') else [x for x in part.geoms if x.geom_type in ('LineString','MultiLineString')]
                    if not lines:
                        continue
                    part=unary_union(lines); length=abs(GEOD.geometry_length(part))/1000
                    if not length:
                        continue
                    result['affected_length_km']+=length
                    p['affected_length_km']=length
                    road_ways.add(str(p.get('osm_type','way'))+'/'+str(p.get('osm_id',identity)))
                elif g.geom_type in ('Polygon','MultiPolygon'):
                    part=polygonal(part)
                    if part.is_empty or part.area<=0:
                        continue
                    p['affected_area_m2']=area_m2(part)
                elif g.geom_type in ('Point','MultiPoint'):
                    if part.is_empty:
                        continue
                else:
                    raise AppError('INVALID_VECTOR',f'Unsupported geometry in {name}: {g.geom_type}',503)
                p.update(exposure_id=identity,geometry_role='flood_intersection',flood_kind=metadata['flood_kind'],is_sample=metadata['is_sample'])
                writer.add(part,p); result['affected_count']+=1
    finally:
        writer.close()
    if name=='roads':
        result['affected_unique_osm_ways']=len(road_ways)
    return result


def calculate(bundle,flood,provenance,destination,method='fractional_area',include_reference=True):
    if method not in ('fractional_area','cell_center'):
        raise AppError('INVALID_POPULATION_METHOD','Unsupported population method',422)
    if not flood.is_empty and (not flood.is_valid or flood.geom_type not in ('Polygon','MultiPolygon')):
        raise AppError('INVALID_FLOOD_EXTENT','Flood union must be valid polygonal geometry',422)
    original_area=area_m2(flood)
    flood=polygonal(flood.intersection(bundle.aoi))
    destination=Path(destination); destination.mkdir(parents=True,exist_ok=True)
    metadata={'region':bundle.region,'flood_kind':provenance['kind'],'flood_label':provenance['label'],'is_sample':provenance['is_sample'],'crs':'EPSG:4326'}
    writer=GeoJSONWriter(destination/'flood_extent.geojson',metadata)
    if not flood.is_empty:
        writer.add(flood,{'source':provenance.get('source'),'is_sample':provenance['is_sample']})
    writer.close()
    population=population_exposure(bundle.paths['population'],flood,bundle.aoi,method)
    infrastructure={}; names=list(VECTOR_NAMES)
    if include_reference and bundle.verification.get('buildings_reference',{}).get('status')=='ASSESSED':
        names.append('reference_buildings')
    for name in names:
        infrastructure[name]=infrastructure_exposure(bundle.paths[name],name,flood,bundle.aoi,destination/f'{name}.geojson',metadata)
    summary={'schema_version':1,'region':bundle.region,'calculated_at':timestamp(),'flood':dict(provenance,
        original_extent_area_km2=original_area/1e6,analyzed_extent_area_km2=area_m2(flood)/1e6,overlaps_region=not flood.is_empty),
        'population':population,'infrastructure':infrastructure,'study_area':bundle.run['area']['selection'],
        'sources':{k:{f:v.get(f) for f in ('version','year','license','sha256')} for k,v in bundle.sources.items()},
        'rules':{'polygons':'Positive intersection area required; boundary-only touch is excluded.',
                 'points':'Flood polygon covers point, including boundary.', 'roads':'Positive geodesic length of unioned flood intersection; split segments counted separately from unique ways.',
                 'duplicates':'Repeated feature IDs suppressed; exact building footprints deduplicated per inventory. Co-located distinct facilities are retained.'},
        'warnings':['Population is a modelled estimate, not an observed affected-person count.',
                    'OSM inventories are incomplete; zero mapped exposure does not establish absence.',
                    'OSM buildings and reference detections overlap and MUST NOT be added together.',
                    'Infrastructure intersection indicates geometric exposure, not damage, road closure, facility functionality or settlement isolation.']}
    write_json(destination/'summary.json',summary)
    return summary
