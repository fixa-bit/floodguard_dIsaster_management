"""Precompute a small, explicitly experimental connected-fill study, never hydraulics.

Reads only a window of Copernicus GLO-30 and the existing WorldPop count raster.
Browser assets contain a continuous sill surface and sampled impact summaries;
no solver runs in the portal.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import heapq
import json
from pathlib import Path
import tempfile

import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from rasterio.windows import from_bounds, transform as window_transform
from scipy.ndimage import distance_transform_edt, gaussian_filter1d, median_filter
import shapely
from shapely.geometry import LineString, box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'frontend/public/jhang-terrain-prototype'
DATA = ROOT / 'frontend/src/data/jhang-terrain-prototype'
CACHE = Path(tempfile.gettempdir()) / 'floodguard-jhang-pilot'
BOUNDS = [72.18, 31.23, 72.35, 31.37]
RISES = [0, .5, 1, 1.5, 2, 3]
DISPLAY_RISES = np.round(np.arange(0, 3.0001, .05), 2)
CELL = 30
DEM_URL = ('https://copernicus-dem-30m.s3.amazonaws.com/'
           'Copernicus_DSM_COG_10_N31_00_E072_00_DEM/'
           'Copernicus_DSM_COG_10_N31_00_E072_00_DEM.tif')
OVERPASS = 'https://maps.mail.ru/osm/tools/overpass/api/interpreter'
QUERY = '[out:json][timeout:25];way["waterway"](31.23,72.18,31.37,72.35);out geom;'
CREDIT = ('produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and '
          '© Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS '
          'by the European Union and ESA; all rights reserved')
LIABILITY = ('The organisations in charge of the Copernicus programme by law or by '
             'delegation do not incur any liability for any use of the Copernicus WorldDEM-30')
TO_LOCAL = Transformer.from_crs(4326, 32643, always_xy=True).transform
TO_GEO = Transformer.from_crs(32643, 4326, always_xy=True).transform


def project(fn, geometry):
    return shapely.transform(geometry, fn, interleaved=False)


def geographic(geometry):
    # Adjacent raster bands share the same 30m vertices after reprojection.
    # Transforming long unsplit edges creates slightly different geographic
    # straight chords on either side of a shared edge, causing narrow overlaps.
    return project(TO_GEO, shapely.segmentize(geometry, CELL))


def signature(path):
    return {'file': path.name, 'bytes': path.stat().st_size,
            'sha256': sha256(path.read_bytes()).hexdigest()}


def collection(features):
    return {'type': 'FeatureCollection', 'features': features}


def feature(geometry, **properties):
    # Topology-aware ~0.1m snapping is far finer than the 30m source grid.
    geometry = shapely.set_precision(geometry, 0.000001)
    return {'type': 'Feature', 'properties': properties, 'geometry': mapping(geometry)}


def connected_threshold(relative, seeds):
    """Minimum maximum cell height along any four-neighbour path from a seed.

    NoData is an impermeable barrier. A below-stage but isolated depression stays
    dry until its connecting sill is crossed. Parent pointers are connection paths,
    not a flow-direction, velocity, travel-time or discharge solution.
    """
    height, width = relative.shape
    valid = np.isfinite(relative)
    costs = np.full(relative.shape, np.inf)
    parents = np.full(relative.size, -1, dtype=np.int32)
    visited = np.zeros(relative.size, dtype=bool)
    flat = costs.ravel()
    terrain = relative.ravel()
    queue = []
    serial = 0
    for index in np.flatnonzero(seeds & valid):
        flat[index] = 0
        heapq.heappush(queue, (0., serial, int(index)))
        serial += 1
    while queue:
        cost, _, index = heapq.heappop(queue)
        if visited[index]:
            continue
        visited[index] = True
        row, col = divmod(index, width)
        neighbours = []
        if row: neighbours.append(index - width)
        if row + 1 < height: neighbours.append(index + width)
        if col: neighbours.append(index - 1)
        if col + 1 < width: neighbours.append(index + 1)
        for other in neighbours:
            if visited[other] or not np.isfinite(terrain[other]):
                continue
            candidate = max(cost, float(terrain[other]))
            if candidate < flat[other]:
                flat[other] = candidate
                parents[other] = index
                heapq.heappush(queue, (candidate, serial, other))
                serial += 1
    return costs, parents.reshape(relative.shape)


def fetch_inputs():
    CACHE.mkdir(exist_ok=True)
    dem_path, osm_path = CACHE / 'cop30-buffered-window.tif', CACHE / 'osm-probe.json'
    if not dem_path.exists():
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
                          CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif', GDAL_HTTP_TIMEOUT='40'):
            with rasterio.open(DEM_URL) as source:
                west, south, east, north = BOUNDS
                raw = from_bounds(west-.001, south-.001, east+.001, north+.001, source.transform)
                left, top = int(np.floor(raw.col_off)), int(np.floor(raw.row_off))
                right, bottom = int(np.ceil(raw.col_off+raw.width)), int(np.ceil(raw.row_off+raw.height))
                window = rasterio.windows.Window(left, top, right-left, bottom-top)
                values = source.read(1, window=window)
                profile = source.profile.copy()
                profile.update(width=values.shape[1], height=values.shape[0],
                               transform=source.window_transform(window))
                with rasterio.open(dem_path, 'w', **profile) as target:
                    target.write(values, 1)
    if not osm_path.exists():
        response = httpx.get(OVERPASS, params={'data': QUERY}, timeout=40, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
        if payload.get('remark') or not payload.get('elements'):
            raise RuntimeError('Incomplete Overpass response; do not publish an empty network')
        osm_path.write_bytes(response.content)
    return dem_path, osm_path


def polygonize(mask, transform):
    parts = [shape(geometry) for geometry, value in shapes(mask.astype('uint8'),
             mask=mask, transform=transform, connectivity=4) if value]
    return unary_union(parts) if parts else shapely.GeometryCollection()


def population_overlap(mask, transform, cells, tree, aoi):
    """Exact intersections with disjoint raster row-runs, avoiding giant polygons."""
    rectangles = []
    for row, values in enumerate(mask):
        changes = np.diff(np.r_[False, values, False].astype('int8'))
        for left, right in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
            rectangles.append(box(transform.c+left*transform.a, transform.f+(row+1)*transform.e,
                                  transform.c+right*transform.a, transform.f+row*transform.e))
    totals = np.zeros(len(cells))
    if rectangles:
        rectangles = shapely.intersection(np.asarray(rectangles, dtype=object), aoi)
        runs, pixels = tree.query(rectangles, predicate='intersects')
        areas = shapely.area(shapely.intersection(rectangles[runs], cells[pixels]))
        totals += np.bincount(pixels, weights=areas, minlength=len(cells))
    return totals


def population_inputs(path, aoi):
    """Keep native counts: exact planar overlap fractions of each native pixel.

    Uniform distribution within a native ~100m population pixel is an assumption.
    Never bilinearly resample counts. NoData is excluded, not converted to zero.
    """
    with rasterio.open(path) as source:
        if source.crs != rasterio.crs.CRS.from_epsg(4326):
            raise ValueError('Expected the native geographic WorldPop raster')
        window = from_bounds(*BOUNDS, source.transform)
        left, top = int(np.floor(window.col_off)), int(np.floor(window.row_off))
        right, bottom = int(np.ceil(window.col_off + window.width)), int(np.ceil(window.row_off + window.height))
        window = rasterio.windows.Window(left, top, right - left, bottom - top)
        values = source.read(1, window=window, masked=True)
        transform = window_transform(window, source.transform)
        valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data) & (values.data >= 0)
        rr, cc = np.nonzero(valid)
        corners = []
        for dx, dy in [(0, 0), (1, 0), (1, 1), (0, 1)]:
            lon = transform.c + (cc + dx) * transform.a
            lat = transform.f + (rr + dy) * transform.e
            x, y = TO_LOCAL(lon, lat)
            corners.append(np.stack([x, y], axis=-1))
        native = shapely.polygons(np.stack(corners, axis=1))
        native_area = shapely.area(native)
        cells = shapely.intersection(native, aoi)
        return values, valid, transform, cells, native_area, values.data[rr, cc].astype(float)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--population-raster', type=Path, required=True)
    args = parser.parse_args()
    dem_path, osm_path = fetch_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    aoi_geo = box(*BOUNDS)
    aoi = project(TO_LOCAL, shapely.segmentize(aoi_geo, .001))
    x0, y0, x1, y1 = aoi.bounds
    transform = from_origin(np.floor(x0/CELL)*CELL, np.ceil(y1/CELL)*CELL, CELL, CELL)
    width = int(np.ceil((x1-transform.c)/CELL))
    height = int(np.ceil((transform.f-y0)/CELL))
    inside = rasterize([(aoi, 1)], out_shape=(height, width), transform=transform).astype(bool)
    dem = np.full((height, width), np.nan, dtype='float32')
    with rasterio.open(dem_path) as source:
        reproject(source=rasterio.band(source, 1), destination=dem,
                  src_transform=source.transform, src_crs=source.crs,
                  dst_transform=transform, dst_crs='EPSG:32643', dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
    dem[~inside] = np.nan
    osm = json.loads(osm_path.read_text(encoding='utf-8-sig'))
    lines, main_lines = [], []
    for element in osm['elements']:
        tags = element.get('tags', {})
        geometry = LineString([(v['lon'], v['lat']) for v in element['geometry']]).intersection(aoi_geo)
        if geometry.is_empty:
            continue
        lines.append(feature(geometry, osm_id=element['id'], waterway=tags['waterway'],
                             name=tags.get('name:en', 'Unnamed ' + tags['waterway']),
                             review_note=tags.get('fixme', '')))
        if tags['waterway'] == 'river':
            main_lines.append(project(TO_LOCAL, geometry))
    if not main_lines:
        raise RuntimeError('No mapped river seed; refuse to invent a channel')
    seeds = rasterize([(line, 1) for line in main_lines], out_shape=dem.shape,
                      transform=transform, all_touched=True).astype(bool) & np.isfinite(dem)
    if not seeds.any():
        raise RuntimeError('Mapped river has no valid elevation source cells')
    # Sample a smoothed longitudinal DEM reference; not a gauge or channel bed.
    ref_sum, ref_count = np.zeros(dem.shape), np.zeros(dem.shape)
    for line in main_lines:
        parts = list(line.geoms) if line.geom_type == 'MultiLineString' else [line]
        for part in parts:
            distances = np.linspace(0, part.length, max(2, int(np.ceil(part.length/60))+1))
            points = [part.interpolate(distance) for distance in distances]
            cols = np.clip(((np.array([p.x for p in points])-transform.c)/CELL).astype(int), 0, width-1)
            rows = np.clip(((transform.f-np.array([p.y for p in points]))/CELL).astype(int), 0, height-1)
            # Lower local surface statistic avoids treating high bars/vegetation
            # directly under a centerline as a measured river-water elevation.
            # This reference remains an assumption, not surveyed bathymetry.
            radius = 10  # 300m at the chosen analysis resolution
            samples = []
            for row, col in zip(rows, cols):
                rr0, rr1 = max(0, row-radius), min(height, row+radius+1)
                cc0, cc1 = max(0, col-radius), min(width, col+radius+1)
                rr, cc = np.mgrid[rr0:rr1, cc0:cc1]
                values = dem[rr0:rr1, cc0:cc1][(rr-row)**2+(cc-col)**2 <= radius**2]
                samples.append(np.nanpercentile(values, 10))
            samples = np.asarray(samples)
            finite = np.isfinite(samples)
            samples = np.interp(distances, distances[finite], samples[finite])
            smoothed = gaussian_filter1d(median_filter(samples, size=17, mode='nearest'), sigma=4, mode='nearest')
            np.add.at(ref_sum, (rows, cols), smoothed)
            np.add.at(ref_count, (rows, cols), 1)
    indices = distance_transform_edt(ref_count == 0, return_distances=False, return_indices=True)
    reference = (ref_sum / np.maximum(1, ref_count))[tuple(indices)]
    relative = dem-reference
    relative[seeds] = 0  # Source cells are assumed connected; no other cells are burned.
    costs, parents = connected_threshold(relative, seeds)
    print('Terrain connectivity complete', flush=True)
    baseline = costs <= 0
    footprints = [(costs <= rise) & ~baseline & inside for rise in RISES]
    geometries = [polygonize(mask, transform).intersection(aoi) for mask in footprints]
    population, valid, pop_transform, pop_cells, pop_area, pop_counts = population_inputs(args.population_raster, aoi)
    tree = shapely.STRtree(pop_cells)
    known_area = float(shapely.area(pop_cells).sum())
    total_population = float((pop_counts * shapely.area(pop_cells) / pop_area).sum())
    levels = []
    features = []
    for level, (rise, geometry) in enumerate(zip(RISES, geometries)):
        overlap = population_overlap(footprints[level], transform, pop_cells, tree, aoi)
        levels.append({'level': level, 'assumed_rise_m': rise,
                       'flood_area_km2': round(geometry.area/1e6, 6),
                       'exposed_population': round(float((pop_counts*overlap/pop_area).sum()), 3),
                       'known_raster_area_fraction': round(float(overlap.sum()/geometry.area), 6) if geometry.area else None,
                       'touches_study_edge': bool(np.any(footprints[level] & (distance_transform_edt(inside) <= 1)))})
        print(f'Level {level}: {levels[-1]["flood_area_km2"]} km2, {levels[-1]["exposed_population"]} people', flush=True)
        if level:
            ring = polygonize(footprints[level] & ~footprints[level-1], transform).intersection(aoi)
            if not ring.is_empty:
                features.append(feature(geographic(ring), min_level=level))
    # Representative connection-tree paths: spatial guides, explicitly not streams.
    # Start from spatially separated wet cells and trace the parent tree to the river.
    paths, selected = [], np.zeros(dem.shape, dtype=bool)
    flat_parent = parents.ravel()
    for r in range(12, height, 28):
        for c in range(12, width, 28):
            if not footprints[-1][r, c] or selected[r, c]:
                continue
            trail, index = [], r*width+c
            while index >= 0 and len(trail) < dem.size:
                rr, cc = divmod(index, width)
                trail.append((transform.c+(cc+.5)*CELL, transform.f-(rr+.5)*CELL))
                if seeds[rr, cc] or selected[rr, cc]: break
                selected[rr, cc] = True
                index = int(flat_parent[index])
            if len(trail) >= 9:
                route = LineString(trail[::-1]).simplify(12, preserve_topology=True)
                paths.append(feature(project(TO_GEO, route), kind='inferred_connection_path', min_level=int(np.searchsorted(RISES, costs[r, c]))))
    # Allocate native WorldPop counts to the same 30m cells by exact projected
    # overlap. Weighted cumulative sums make continuous map stages/counters fast.
    rr, cc = np.nonzero(inside & np.isfinite(costs))
    indices = rr * width + cc
    cell_polygons = shapely.box(transform.c+cc*CELL, transform.f-(rr+1)*CELL,
                                transform.c+(cc+1)*CELL, transform.f-rr*CELL)
    cell_area = shapely.area(shapely.intersection(cell_polygons, aoi))
    grid_ids, pixel_ids = tree.query(cell_polygons, predicate='intersects')
    overlap_areas = shapely.area(shapely.intersection(cell_polygons[grid_ids], pop_cells[pixel_ids]))
    cell_population = np.bincount(grid_ids, weights=pop_counts[pixel_ids]*overlap_areas/pop_area[pixel_ids], minlength=len(indices))
    cell_coverage = np.bincount(grid_ids, weights=overlap_areas, minlength=len(indices))
    cell_cost = costs.ravel()[indices]
    order = np.argsort(cell_cost)
    sorted_cost = cell_cost[order]
    sorted_area = cell_area[order]
    sorted_population = cell_population[order]
    sorted_coverage = cell_coverage[order]
    cumulative_area = np.cumsum(sorted_area)
    cumulative_population = np.cumsum(sorted_population)
    cumulative_coverage = np.cumsum(sorted_coverage)
    touches_edge = (distance_transform_edt(inside) <= 1)[rr, cc][order]
    edge_prefix = np.cumsum(touches_edge.astype('uint8'))
    continuous = []
    baseline_count = int(np.searchsorted(sorted_cost, 0, side='right'))
    edge_before_added = int(edge_prefix[baseline_count-1]) if baseline_count else 0
    for value in DISPLAY_RISES:
        count = int(np.searchsorted(sorted_cost, value, side='right'))
        # cost==0 is the assumed reference extent; do not count it as flooding.
        active = max(0, count-baseline_count)
        start = baseline_count
        area_value = float(cumulative_area[count-1]-cumulative_area[start-1]) if active and start else float(cumulative_area[count-1]) if active else 0.
        people_value = float(cumulative_population[count-1]-cumulative_population[start-1]) if active and start else float(cumulative_population[count-1]) if active else 0.
        covered_value = float(cumulative_coverage[count-1]-cumulative_coverage[start-1]) if active and start else float(cumulative_coverage[count-1]) if active else 0.
        continuous.append({'rise_m': float(value), 'flood_area_km2': round(area_value/1e6, 6),
                           'exposed_population': round(people_value, 3),
                           'known_raster_area_fraction': round(covered_value/area_value, 6) if area_value else None,
                           'touches_study_edge': bool(active and edge_prefix[count-1] > edge_before_added)})
    bundle = {'schema_version': 1, 'id': 'jhang-chenab-pilot', 'name': 'Jhang · Chenab pilot',
              'bounds': BOUNDS, 'cell_size_m': CELL, 'study_area_km2': round(aoi.area/1e6, 3),
              'baseline_connected_area_km2': round(float(baseline.sum()*CELL**2/1e6), 3),
              'known_population_2025': round(total_population, 3),
              'population_coverage_fraction': round(known_area/aoi.area, 6),
              'levels': levels, 'continuous_metrics': continuous,
              'stream_corridor': collection([feature(project(TO_GEO, unary_union(main_lines).buffer(45).intersection(aoi)), min_level=0, kind='illustrative_centerline_ribbon', width_m=90)]),
              'water': collection(features), 'waterways': collection(lines),
              'connection_paths': collection(paths), 'study_boundary': collection([feature(aoi_geo)]),
              'reference_extent': collection([feature(geographic(polygonize(baseline, transform).intersection(aoi)))])}
    (DATA/'jhang-pilot.geojson').write_text(json.dumps(bundle, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    # Geographic image grids align exactly with the visible study bounds.
    image_transform = rasterio.transform.from_bounds(*BOUNDS, 612, 504)
    elevation = np.full((504, 612), np.nan, dtype='float32')
    reproject(dem, elevation, src_transform=transform, src_crs='EPSG:32643',
              dst_transform=image_transform, dst_crs='EPSG:4326', dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    filled = np.where(np.isfinite(elevation), elevation, np.nanmedian(elevation))
    gy, gx = np.gradient(filled, CELL)
    shade = np.clip(.7-.9*gx+.9*gy, .15, 1)
    terrain_image = np.zeros((*elevation.shape, 4), dtype='uint8')
    terrain_image[:, :, :3] = (shade[:, :, None]*np.array([165, 185, 156])).astype('uint8')
    terrain_image[:, :, 3] = np.where(np.isfinite(elevation), 255, 0)
    Image.fromarray(terrain_image).save(OUT/'terrain.png', optimize=True)
    # Continuous sill-height surface. Two color channels encode a 16-bit float
    # threshold image; alpha marks valid terrain. This drives the web flood layer.
    cost_4326 = np.full((height, width), np.nan, dtype='float32')
    cost_4326[np.isfinite(costs)] = costs[np.isfinite(costs)]
    target_size = (532, 554)
    threshold = np.full(target_size, np.nan, dtype='float32')
    threshold_transform = rasterio.transform.from_bounds(*BOUNDS, target_size[1], target_size[0])
    reproject(cost_4326, threshold, src_transform=transform, src_crs='EPSG:32643',
              dst_transform=threshold_transform, dst_crs='EPSG:4326', dst_nodata=np.nan,
              resampling=Resampling.nearest)
    encoded = np.clip(np.nan_to_num(threshold, nan=0.) / 8 * 65535, 0, 65535).astype('uint16')
    threshold_rgba = np.zeros((*target_size, 4), dtype='uint8')
    threshold_rgba[:, :, 0] = (encoded >> 8).astype('uint8')
    threshold_rgba[:, :, 1] = (encoded & 255).astype('uint8')
    threshold_rgba[:, :, 2] = 255
    threshold_rgba[:, :, 3] = np.where(np.isfinite(threshold), 255, 0)
    Image.fromarray(threshold_rgba).save(OUT/'flood-threshold.png', optimize=True)
    # Native population pixels, no count resampling or spatial aggregation.
    density = np.zeros(population.shape)
    density[valid] = population.data[valid]/(pop_area/1e6)
    stops = np.array([0, 100, 500, 2000, 10000])
    palette = np.array([[45, 91, 85], [130, 156, 95], [225, 192, 98], [235, 135, 89], [239, 83, 110]])
    rgba = np.zeros((*population.shape, 4), dtype='uint8')
    for channel in range(3): rgba[:, :, channel] = np.interp(density, stops, palette[:, channel])
    rgba[:, :, 3] = np.where(valid, 210, 0)
    Image.fromarray(rgba).save(OUT/'population.png', optimize=True)
    pop_bounds = rasterio.transform.array_bounds(*population.shape, pop_transform)
    with rasterio.open(OUT/'elevation-30m.tif', 'w', driver='GTiff', height=height,
                       width=width, count=1, dtype='float32', crs='EPSG:32643',
                       transform=transform, nodata=np.nan, compress='deflate', predictor=3) as target:
        target.write(dem, 1)
    np.savez_compressed(CACHE/'derived-check.npz', dem=dem, relative=relative, seeds=seeds,
                        costs=costs, parents=parents, inside=inside, baseline=baseline)
    # The compact clipped OSM derivative remains accessible under ODbL.
    mapped = {**collection(lines), 'attribution': '© OpenStreetMap contributors',
              'license': 'https://opendatacommons.org/licenses/odbl/1-0/',
              'source_endpoint': OVERPASS, 'timestamp_osm_base': osm.get('osm3s', {}).get('timestamp_osm_base')}
    (OUT/'mapped-waterways.geojson').write_text(json.dumps(mapped, ensure_ascii=False)+'\n', encoding='utf-8')
    manifest = {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                'method': 'Four-neighbour minimax connected fill above a smoothed DEM river-line reference',
                'hydraulic_model': False, 'calibrated': False,
                'bounds': BOUNDS, 'population_image_bounds': list(pop_bounds),
                'grid': {'crs': 'EPSG:32643', 'cell_m': CELL, 'width': width, 'height': height,
                         'valid_cells': int(np.isfinite(dem).sum()), 'nodata_cells_inside': int((inside & ~np.isfinite(dem)).sum()),
                         'elevation_min_m': float(np.nanmin(dem)), 'elevation_max_m': float(np.nanmax(dem))},
                'assumptions': {'example_rise_m': RISES, 'continuous_map_raster': {'minimum_m': 0, 'maximum_m': 3, 'threshold_encoding': '16-bit value in red and green PNG channels, decoded linearly to 0-8m'}, 'impact_metric_sample_m': .05,
                                'stream_ribbon': {'width_m': 90, 'basis': 'illustrative buffer around mapped Chenab centerline; not measured channel width'},
                                'river_reference': '10th percentile DEM within 300m of river samples every ~60m; 17-sample median then sigma=4 Gaussian; nearest reference sample',
                                'seed': 'OSM river centerline rasterized with all_touched; seed height zero only',
                                'baseline': 'Connected cells at relative rise 0; excluded from incremental footprint and population',
                                'canals': 'Context only; never seeded or artificially lowered',
                                'population': 'Native WorldPop count multiplied by exact UTM polygon intersection fraction; uniform within native pixel',
                                'playback': 'Continuous presentation sequence, not flood arrival or travel time',
                                'paths': 'Representative minimax parent-tree connections; not mapped streams or hydraulic flow vectors'},
                'sources': {'dem': {'url': DEM_URL, 'cached_window': signature(dem_path), 'source_release': 'AWS public GLO-30 2021 COG', 'vertical_reference': 'Provider EGM2008 heights; not station gauge datum'},
                            'osm': {'endpoint': OVERPASS, 'query': QUERY, 'timestamp_osm_base': osm.get('osm3s', {}).get('timestamp_osm_base'),
                                    'cached_response': signature(osm_path), 'ways': len(lines), 'water_area_query_count': 0, 'license': 'ODbL 1.0', 'credit': '© OpenStreetMap contributors'},
                            'population': {'file': args.population_raster.name, 'year': 2025, 'release': 'R2025A v1 (alpha)', 'license': 'CC BY 4.0',
                                           'url': 'https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/100m/constrained/pak_pop_2025_CN_100m_R2025A_v1.tif'}},
                'dem_credit': CREDIT, 'dem_liability_notice': LIABILITY,
                'dem_license_url': 'https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf',
                'limits': ['Surface model includes vegetation and structures; no surveyed channel bathymetry.',
                           'No flow conservation, rainfall-runoff, inflow hydrograph, roughness, culvert or levee inventory.',
                           'Sub-metre increments are sensitivity inputs, not accuracy claims.',
                           'No observed flood extent validation; not an operational warning or safety tool.',
                           'Study-edge truncation and NoData can alter connectivity.'],
                'outputs': [signature(p) for p in [DATA/'jhang-pilot.geojson', OUT/'terrain.png', OUT/'population.png', OUT/'flood-threshold.png', OUT/'elevation-30m.tif', OUT/'mapped-waterways.geojson']]}
    (OUT/'metadata.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (OUT/'NOTICE.txt').write_text(CREDIT+'\n\n'+LIABILITY+'\n\nOSM: © OpenStreetMap contributors, ODbL 1.0.\nPopulation: WorldPop 2025, CC BY 4.0.\nExperimental derivative; no official endorsement.\n', encoding='utf-8')
    print(json.dumps({'grid': manifest['grid'], 'study_area_km2': bundle['study_area_km2'], 'baseline_km2': bundle['baseline_connected_area_km2'], 'levels': levels, 'paths': len(paths), 'outputs': manifest['outputs']}, indent=2))


if __name__ == '__main__':
    main()
