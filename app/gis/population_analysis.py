"""Native count-cell intersections, disjoint administrative totals and display grids."""
import math
from collections import defaultdict
from pathlib import Path

import fiona
import geopandas as gpd
import numpy as np
import rasterio
import shapely
from pyproj import Transformer
from rasterio.features import geometry_mask, shapes
from shapely.geometry import GeometryCollection, box, mapping, shape
from shapely.ops import unary_union

from app.core.exceptions import AppError
from app.gis.exposure_engine import area_m2, convert_geometry, polygonal


def segmentation_flood(bundle):
    config = bundle.configuration.get('population_analysis', {}).get('segmentation', {})
    path = (bundle.root / config.get('path', '')).resolve()
    if not config.get('path') or not path.is_relative_to(bundle.root) or not path.is_file():
        raise AppError('SEGMENTATION_UNAVAILABLE', 'Configure population_analysis.segmentation.path in the prepared manifest, or explicitly select another source', 503)
    geometries = []
    with rasterio.open(path) as src:
        if not src.crs or src.count != 1:
            raise AppError('INVALID_SEGMENTATION', 'Segmentation requires one band and a declared CRS', 503)
        aoi = convert_geometry(bundle.aoi, 4326, src.crs)
        for _, window in src.block_windows(1):
            values = src.read(1, window=window, masked=True)
            valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
            water = np.isin(values.data, config.get('flood_values', [1])) & valid
            water &= geometry_mask([mapping(aoi)], out_shape=values.shape, transform=src.window_transform(window), invert=True, all_touched=True)
            for geometry, _ in shapes(water.astype('uint8'), mask=water, transform=src.window_transform(window)):
                geometries.append(convert_geometry(shape(geometry), src.crs))
                if len(geometries) > 250000:
                    raise AppError('SEGMENTATION_TOO_COMPLEX', 'Prepare a simplified, verified flood vector for this raster', 503)
        water = polygonal(unary_union(geometries).intersection(bundle.aoi))
    if not water.is_empty and not water.is_valid:
        raise AppError('INVALID_SEGMENTATION', 'Polygonized segmentation is invalid; repair explicitly before analysis', 503)
    return water, {'kind': 'segmentation_output', 'is_sample': False, 'label': config.get('label', 'Configured segmentation output'),
                   'source': str(path.relative_to(bundle.root)), 'flood_values': config.get('flood_values', [1]),
                   'note': 'Spatial compatibility does not establish model accuracy.'}


def administrative_units(bundle):
    path = bundle.pilot / 'boundaries/boundaries.gpkg'
    if not path.exists():
        raise AppError('MISSING_BOUNDARIES', 'Prepared administrative GeoPackage is missing', 503)
    available = fiona.listlayers(path)
    levels = {}; notes = []
    for level in ('ADM2', 'ADM3'):
        if level not in available:
            notes.append(f'{level}: unavailable; no boundaries or statistics fabricated.')
            continue
        frame = gpd.read_file(path, layer=level, engine='fiona')
        if frame.crs is None or frame.geometry.isna().any() or not frame.geometry.is_valid.all():
            raise AppError('INVALID_BOUNDARIES', f'{level}: missing CRS or invalid geometry', 503)
        frame = frame.to_crs(4326)
        grouped = {}
        n = level[-1]
        for index, row in frame.iterrows():
            geometry = polygonal(row.geometry.intersection(bundle.aoi))
            if geometry.is_empty:
                continue
            ident = str(row.get(f'adm{n}_pcode') or row.get('shapeID') or index)
            name = str(row.get(f'adm{n}_name') or row.get('shapeName') or ident)
            if ident in grouped:
                grouped[ident]['geometry'] = unary_union([grouped[ident]['geometry'], geometry])
            else:
                grouped[ident] = {'id': ident, 'name': name, 'level': level, 'geometry': geometry}
        units = list(grouped.values())
        if not units:
            notes.append(f'{level}: no polygons overlap this study area; statistics unavailable.')
            continue
        tree = shapely.STRtree([u['geometry'] for u in units])
        for i, unit in enumerate(units):
            for j in tree.query(unit['geometry'], predicate='intersects'):
                if int(j) > i and area_m2(unit['geometry'].intersection(units[int(j)]['geometry'])) > .01:
                    raise AppError('OVERLAPPING_BOUNDARIES', f'{level}: {unit["name"]} and {units[int(j)]["name"]} overlap; correct provenance instead of double-counting', 503)
        levels[level] = units
    return levels, notes


def analyze_population(path, aoi, flood, levels, grid_km=2):
    """Count values stay unchanged; weights are intersection area / native cell area."""
    flood = polygonal(flood.intersection(aoi))
    metric = Transformer.from_crs(4326, 6933, always_xy=True)
    inverse = Transformer.from_crs(6933, 4326, always_xy=True)
    def project(coords):
        x, y = metric.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])
    total = exposed = known_water_area = 0.
    valid_count = nodata_count = flooded_valid = 0
    grids = defaultdict(lambda: [0., 0., 0.])
    bins = np.array([0., 100., 500., 1000., 5000., np.inf])
    distribution = np.zeros(5)
    per_unit = {level: {u['id']: {'known_population_total': 0., 'estimated_exposed_population': 0., 'known_flood_area_km2': 0.} for u in units} for level, units in levels.items()}
    shapely.prepare(aoi); shapely.prepare(flood)
    for units in levels.values():
        for unit in units:
            shapely.prepare(unit['geometry'])
            unit['covers_study_area'] = unit['geometry'].equals(aoi)
    aoi_metric = convert_geometry(aoi, 4326, 6933)
    w,s,e,n = aoi_metric.bounds
    if (e-w)*(n-s)/(grid_km*1000)**2 > 20000:
        raise AppError('DISPLAY_GRID_TOO_LARGE', 'Increase grid_km for this region (up to 25 km); display grid is limited to approximately 20,000 cells', 422)
    with rasterio.open(path) as src:
        if src.crs is None or src.count != 1 or src.nodata is None:
            raise AppError('INVALID_POPULATION', 'Population requires CRS, one band and nodata', 503)
        native_aoi = convert_geometry(aoi, 4326, src.crs)
        for _, window in src.block_windows(1):
            values = src.read(1, window=window, masked=True)
            t = src.window_transform(window)
            touched = geometry_mask([mapping(native_aoi)], out_shape=values.shape, transform=t, invert=True, all_touched=True)
            rr, cc = np.nonzero(touched)
            if not len(rr):
                continue
            corners = [np.column_stack([t.a*(cc+dx)+t.b*(rr+dy)+t.c, t.d*(cc+dx)+t.e*(rr+dy)+t.f]) for dx, dy in ((0,0),(1,0),(1,1),(0,1))]
            cells = shapely.polygons(np.stack(corners, axis=1))
            cells = shapely.transform(cells, Transformer.from_crs(src.crs, 4326, always_xy=True).transform, interleaved=False)
            areas = shapely.area(shapely.transform(cells, project))
            def intersections(boundary, candidates=cells):
                full = shapely.covers(boundary, candidates)
                cross = ~full & shapely.intersects(boundary, candidates)
                parts = np.empty(len(candidates), dtype=object)
                parts[:] = GeometryCollection()
                parts[full] = candidates[full]
                parts[cross] = shapely.intersection(candidates[cross], boundary)
                return parts
            study = intersections(aoi)
            study_area = shapely.area(shapely.transform(study, project))
            positive = study_area > 0
            good = ~np.ma.getmaskarray(values)[rr, cc] & positive
            raw = values.data[rr, cc].astype('float64')
            if np.any(~np.isfinite(raw[good])) or np.any(raw[good] < 0) or np.any(areas <= 0):
                raise AppError('INVALID_POPULATION', 'Invalid population count or cell area', 503)
            water = intersections(flood, study)
            water_area = shapely.area(shapely.transform(water, project))
            native_total = np.where(good, raw * np.clip(study_area / areas, 0, 1), 0)
            native_exposed = np.where(good, raw * np.clip(water_area / areas, 0, 1), 0)
            total += float(native_total.sum()); exposed += float(native_exposed.sum())
            known_water_area += float(water_area[good].sum())
            valid_count += int(good.sum()); nodata_count += int((positive & ~good).sum())
            flooded_valid += int((good & (water_area > 0)).sum())
            density = np.divide(raw, areas/1e6)
            categories = np.clip(np.searchsorted(bins, density[good], side='right')-1, 0, 4)
            distribution += np.bincount(categories, weights=native_exposed[good], minlength=5)
            centers = shapely.get_coordinates(shapely.centroid(cells))
            x, y = metric.transform(centers[:,0], centers[:,1])
            keys = np.column_stack([np.floor(x/(grid_km*1000)).astype(int), np.floor(y/(grid_km*1000)).astype(int)])
            for key, pop, affected, covered in zip(keys[good], native_total[good], native_exposed[good], study_area[good]):
                slot = grids[tuple(key)]
                slot[0] += float(pop); slot[1] += float(affected); slot[2] += float(covered)
            block = box(*shapely.total_bounds(cells))
            for level, units in levels.items():
                for unit in units:
                    if not unit['geometry'].intersects(block):
                        continue
                    if unit.get('covers_study_area'):
                        admin_area = study_area
                        admin_water_area = water_area
                    else:
                        admin = intersections(unit['geometry'], study)
                        admin_area = shapely.area(shapely.transform(admin, project))
                        admin_water = intersections(unit['geometry'], water)
                        admin_water_area = shapely.area(shapely.transform(admin_water, project))
                    row = per_unit[level][unit['id']]
                    row['known_population_total'] += float((raw[good]*np.clip(admin_area[good]/areas[good],0,1)).sum())
                    row['estimated_exposed_population'] += float((raw[good]*np.clip(admin_water_area[good]/areas[good],0,1)).sum())
                    row['known_flood_area_km2'] += float(admin_water_area[good].sum()/1e6)
    if not valid_count:
        raise AppError('POPULATION_COVERAGE_MISSING', 'No valid population cells overlap the study area; verify raster coverage and CRS', 503)
    water_area = area_m2(flood)
    unknown = water_area > 0 and flooded_valid == 0
    result = {'known_population_total': total, 'estimated_exposed_population': None if unknown else exposed,
              'percentage_exposed_of_known_population': None if not total or unknown else 100*exposed/total,
              'valid_cells': valid_count, 'nodata_cells': nodata_count, 'flooded_valid_cells': flooded_valid,
              'known_flood_area_km2': known_water_area/1e6,
              'flood_area_with_known_population_fraction': min(1., known_water_area/water_area) if water_area else None,
              'status': 'UNKNOWN' if unknown else ('PARTIAL_COVERAGE' if water_area and known_water_area/water_area < .999 else 'ESTIMATED')}
    admin_features = []; admin_stats = {}; checks = {}
    for level, units in levels.items():
        rows = []
        for unit in units:
            row = dict(per_unit[level][unit['id']], id=unit['id'], name=unit['name'], level=level)
            extent_area = area_m2(flood.intersection(unit['geometry']))/1e6
            if extent_area > 0 and not row['known_flood_area_km2']:
                row['estimated_exposed_population'] = None
            row['percentage_exposed_of_known_population'] = (100*row['estimated_exposed_population']/row['known_population_total']) if row['known_population_total'] and row['estimated_exposed_population'] is not None else None
            row['flood_area_km2'] = extent_area
            row['known_flood_area_fraction'] = min(1.,row['known_flood_area_km2']/extent_area) if extent_area else None
            rows.append(row)
            admin_features.append({'type':'Feature','geometry':mapping(unit['geometry']),'properties':row})
        allocated = math.fsum(r['estimated_exposed_population'] or 0 for r in rows)
        allocated_total = math.fsum(r['known_population_total'] for r in rows)
        checks[level] = {'allocated_exposed_population':allocated, 'unassigned_exposed_population':max(0.,exposed-allocated),
                         'allocated_known_population':allocated_total,'unassigned_known_population':max(0.,total-allocated_total),
                         'aggregation_within_total':allocated <= exposed+max(1e-6,exposed*1e-9) and allocated_total <= total+max(1e-6,total*1e-9)}
        if not checks[level]['aggregation_within_total']:
            raise AppError('POPULATION_DOUBLE_COUNT', 'Administrative sum exceeds overall exposure', 503)
        admin_stats[level] = rows
    grid_features = []
    for (x,y), (pop, affected, covered) in grids.items():
        geometry = convert_geometry(box(x*grid_km*1000,y*grid_km*1000,(x+1)*grid_km*1000,(y+1)*grid_km*1000),6933).intersection(aoi)
        if geometry.is_empty:
            continue
        grid_features.append({'type':'Feature','geometry':mapping(polygonal(geometry)), 'properties':{'known_population':pop,'exposed_population':affected,'population_density_km2':pop/(covered/1e6) if covered else None}})
    distribution_rows = [{'density_min_people_km2':float(bins[i]), 'density_max_people_km2':float(bins[i+1]) if np.isfinite(bins[i+1]) else None, 'exposed_population':float(v)} for i,v in enumerate(distribution)]
    return result, admin_stats, checks, distribution_rows, admin_features, grid_features
