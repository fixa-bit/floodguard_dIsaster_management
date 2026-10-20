"""Dated channel geometry + continuous connected-fill display, never hydraulics.

Run the terrain prototype builder first. Uses existing GIS libraries only.
"""
from collections import deque
import heapq
import json
from pathlib import Path

import numpy as np
from PIL import Image
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.windows import Window, from_bounds as window_from_bounds
from scipy.ndimage import label
import shapely
from shapely.geometry import LineString, box, shape

from build_jhang_terrain_prototype import (ROOT, OUT, CACHE, BOUNDS, CELL, TO_LOCAL,
    TO_GEO, feature, collection, project, geographic, polygonize, population_inputs, signature)

DATA = ROOT/'frontend/src/data/jhang-channel-replay'
SOURCE = ('https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/'
          'ESA_WorldCover_10m_2021_v200_N30E072_Map.tif')
CREDIT = ('© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) '
          'processed by ESA WorldCover consortium')


def thin_water(mask):
    """Zhang-Suen thinning: preserve raster branches; never draw across dry land."""
    result = np.pad(mask.astype(bool), 1)
    for _ in range(max(mask.shape)):
        changed = False
        for second in [False, True]:
            p = [result[:-2, 1:-1], result[:-2, 2:], result[1:-1, 2:], result[2:, 2:],
                 result[2:, 1:-1], result[2:, :-2], result[1:-1, :-2], result[:-2, :-2]]
            neighbours = sum(v.astype('uint8') for v in p)
            transitions = sum((~p[i] & p[(i+1) % 8]).astype('uint8') for i in range(8))
            a = ~(p[0] & p[2] & (p[6] if second else p[4]))
            b = ~((p[0] if second else p[2]) & p[4] & p[6])
            remove = result[1:-1, 1:-1] & (neighbours >= 2) & (neighbours <= 6) & (transitions == 1) & a & b
            if remove.any():
                result[1:-1, 1:-1][remove] = False
                changed = True
        if not changed: break
    return result[1:-1, 1:-1]


def skeleton_paths(mask, transform):
    skeleton = thin_water(mask)
    height, width = skeleton.shape
    nodes = set(map(int, np.flatnonzero(skeleton)))
    neighbours = {}
    for index in nodes:
        r, c = divmod(index, width)
        neighbours[index] = [rr*width+cc for rr in range(max(0, r-1), min(height, r+2))
                             for cc in range(max(0, c-1), min(width, c+2))
                             if (rr != r or cc != c) and rr*width+cc in nodes]
    # Geometric orientation toward southern study exits, not a hydraulic field.
    max_row = max(index//width for index in nodes)
    outlets = [index for index in nodes if index//width >= max_row-2]
    distance = {index: 0. for index in outlets}
    queue = [(0., index) for index in outlets]
    heapq.heapify(queue)
    while queue:
        value, index = heapq.heappop(queue)
        if value != distance[index]: continue
        r, c = divmod(index, width)
        for other in neighbours[index]:
            rr, cc = divmod(other, width)
            candidate = value + np.hypot(rr-r, cc-c)
            if candidate < distance.get(other, float('inf')):
                distance[other] = candidate
                heapq.heappush(queue, (candidate, other))
    junctions = {index for index in nodes if len(neighbours[index]) != 2}
    visited, paths = set(), []
    for start in list(junctions) + sorted(nodes):
        for nxt in neighbours[start]:
            if (min(start, nxt), max(start, nxt)) in visited: continue
            trail = [start]
            previous, current = start, nxt
            while True:
                visited.add((min(previous, current), max(previous, current)))
                trail.append(current)
                if current in junctions or current == start: break
                candidates = [n for n in neighbours[current] if n != previous]
                if not candidates: break
                previous, current = current, candidates[0]
            if len(trail) < 4: continue
            if distance.get(trail[0], 0) < distance.get(trail[-1], 0): trail.reverse()
            coords = [(transform.c+(i % width+.5)*transform.a, transform.f+(i//width+.5)*transform.e) for i in trail]
            geometry = LineString(coords)
            if project(TO_LOCAL, geometry).length >= 45:
                paths.append(feature(geometry, kind='water_mask_skeleton', direction='illustrative_southern_outlet'))
    return paths, skeleton


def grid_population_weights(transform, inside, aoi, pop_cells, pop_areas, counts):
    """Exact overlap per analysis cell, batched to keep native counts conserved."""
    tree = shapely.STRtree(pop_cells)
    area, known, people = [np.zeros(inside.size) for _ in range(3)]
    active = np.flatnonzero(inside)
    width = inside.shape[1]
    for start in range(0, len(active), 4096):
        indices = active[start:start+4096]
        rr, cc = indices//width, indices % width
        cells = shapely.box(transform.c+cc*CELL, transform.f-(rr+1)*CELL,
                            transform.c+(cc+1)*CELL, transform.f-rr*CELL)
        cells = shapely.intersection(cells, aoi)
        area[indices] = shapely.area(cells)
        grid, native = tree.query(cells, predicate='intersects')
        overlap = shapely.area(shapely.intersection(cells[grid], pop_cells[native]))
        known[indices] = np.bincount(grid, weights=overlap, minlength=len(indices))
        people[indices] = np.bincount(grid, weights=overlap*counts[native]/pop_areas[native], minlength=len(indices))
    return area, known, people


def main(population_path):
    DATA.mkdir(parents=True, exist_ok=True)
    cached = CACHE/'worldcover-2021-window.tif'
    if not cached.exists():
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif', GDAL_HTTP_TIMEOUT='40'):
            with rasterio.open(SOURCE) as source:
                west, south, east, north = BOUNDS
                window = window_from_bounds(west-.001, south-.001, east+.001, north+.001, source.transform)
                left, top = int(np.floor(window.col_off)), int(np.floor(window.row_off))
                right, bottom = int(np.ceil(window.col_off+window.width)), int(np.ceil(window.row_off+window.height))
                window = Window(left, top, right-left, bottom-top)
                values = source.read(1, window=window)
                profile = source.profile.copy()
                profile.update(width=values.shape[1], height=values.shape[0], transform=source.window_transform(window))
                with rasterio.open(cached, 'w', **profile) as target: target.write(values, 1)
    pilot = json.loads((ROOT/'frontend/src/data/jhang-terrain-prototype/jhang-pilot.geojson').read_text(encoding='utf-8'))
    aoi_geo = box(*BOUNDS)
    aoi = project(TO_LOCAL, shapely.segmentize(aoi_geo, .001))
    with rasterio.open(cached) as source:
        raw = source.read(1)
        wc_transform = source.transform
        inside_water = rasterize([(aoi_geo, 1)], out_shape=raw.shape, transform=wc_transform).astype(bool)
        water = (raw == 80) & inside_water
    labels, _ = label(water, np.ones((3, 3)))
    counts = np.bincount(labels.ravel()); counts[0] = 0
    main_mask = labels == int(np.argmax(counts))
    main_geometry = polygonize(main_mask, wc_transform)
    river = shapely.union_all([shape(f['geometry']) for f in pilot['waterways']['features'] if f['properties']['waterway'] == 'river'])
    if not main_geometry.intersects(river.buffer(.002)) or counts.max() < 1000:
        raise RuntimeError('Largest water component cannot be matched to the mapped Chenab')
    other = polygonize(water & ~main_mask, wc_transform)
    paths, skeleton = skeleton_paths(main_mask, wc_transform)
    print(f'WorldCover channel: {int(main_mask.sum())} native water pixels, {len(paths)} skeleton paths', flush=True)
    # The original cell thresholds remain unchanged; expose them for reproduction.
    activation_path = OUT/'activation-thresholds.tif'
    with rasterio.open(OUT/'elevation-30m.tif') as source:
        dem = source.read(1); transform = source.transform; profile = source.profile.copy()
    if activation_path.exists():
        with rasterio.open(activation_path) as source: costs = source.read(1)
    else:
        derived = np.load(CACHE/'derived-check.npz')
        if not np.allclose(derived['dem'], dem, equal_nan=True):
            raise RuntimeError('Cached thresholds do not match the published DEM. Rebuild the terrain prototype first.')
        costs = derived['costs'].astype('float32')
        costs[~np.isfinite(dem)] = np.nan
        with rasterio.open(activation_path, 'w', **profile) as target: target.write(costs, 1)
    inside = np.isfinite(dem)
    _, _, _, pop_cells, pop_areas, pop_counts = population_inputs(population_path, aoi)
    area, known, people = grid_population_weights(transform, inside, aoi, pop_cells, pop_areas, pop_counts)
    # Prefix sums make 301 values cheap; no repeated national raster reads.
    positive = np.flatnonzero(np.isfinite(costs.ravel()) & (costs.ravel() > 0))
    order = positive[np.argsort(costs.ravel()[positive], kind='stable')]
    heights = costs.ravel()[order]
    prefixes = [np.r_[0, np.cumsum(weights[order])] for weights in [area, known, people]]
    samples = []
    for cm in range(301):
        end = int(np.searchsorted(heights, cm/100, side='right'))
        flooded, covered, population = [float(values[end]) for values in prefixes]
        samples.append({'rise_m': cm/100, 'flood_area_km2': round(flooded/1e6, 6),
                        'exposed_population': round(population, 3),
                        'known_raster_area_fraction': round(covered/flooded, 6) if flooded else None})
    # RG encodes the original connected-fill threshold in millimetres, not depth.
    # Reproject using nearest neighbours; never interpolate across a barrier.
    raster_transform = from_bounds(*BOUNDS, 612, 504)
    display_costs = np.full((504, 612), np.nan, dtype='float32')
    reproject(costs, display_costs, src_transform=transform, src_crs='EPSG:32643', dst_transform=raster_transform,
              dst_crs='EPSG:4326', dst_nodata=np.nan, resampling=Resampling.nearest)
    valid = np.isfinite(display_costs) & (display_costs > 0) & (display_costs <= 3)
    encoded = np.full(display_costs.shape, 65535, dtype='uint16')
    encoded[valid] = np.ceil(display_costs[valid]*1000).astype('uint16')
    pixels = np.zeros((*encoded.shape, 4), dtype='uint8')
    pixels[:, :, 0] = encoded >> 8; pixels[:, :, 1] = encoded & 255; pixels[:, :, 3] = 255
    Image.fromarray(pixels).save(OUT/'continuous-thresholds.png', optimize=True)
    geometry = feature(main_geometry, min_level=1, source_year=2021, water_class=80)
    bundle = {'schema_version': 1, 'id': 'jhang-channel-replay', 'year': 2021, 'nominal_resolution_m': 10,
              'bounds': BOUNDS, 'channel_area_km2': round(project(TO_LOCAL, main_geometry).area/1e6, 6),
              'channel_water': collection([geometry]), 'other_water': collection([feature(other)]),
              'flow_lines': collection(paths), 'continuous_samples': samples,
              'activation': {'width': 612, 'height': 504, 'bounds': BOUNDS, 'encoding': 'R*256+G = activation millimetres; 65535 = excluded', 'maximum_rise_m': 3},
              'attribution': CREDIT, 'license': 'CC BY 4.0', 'source_url': SOURCE,
              'limits': ['2021 land-cover classification, not live water or a complete stream inventory.',
                         'Animation follows skeleton geometry; direction and speed are illustrative.',
                         'Flood extent remains uncalibrated connected fill; no water-volume or arrival-time model.']}
    bundle_path = DATA/'jhang-channels.geojson'
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    manifest = {'method': 'WorldCover class-80 largest connected Chenab component; skeleton-clipped animation; continuous original connected-fill thresholds',
                'source': {'url': SOURCE, 'year': 2021, 'class': 80, 'cached_window': signature(cached), 'credit': CREDIT,
                           'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'data_documentation': 'https://esa-worldcover.org/en/data-access'},
                'population_weights': 'Native pixel count times exact UTM overlap fraction; NoData excluded; one-centimetre sample spacing',
                'presentation': 'Only mapped 2021 river water receives moving streaks. Potential floodplain is a separate static material; 0.03m alpha fade after cell activation.',
                'hydraulic_model': False, 'calibrated': False,
                'outputs': [signature(p) for p in [bundle_path, activation_path, OUT/'continuous-thresholds.png']]}
    (OUT/'channel-metadata.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (OUT/'channel-NOTICE.txt').write_text(CREDIT+'\nCC BY 4.0: https://creativecommons.org/licenses/by/4.0/\nClass 80 water mask and skeleton are derived from 2021 data; not live channel positions.\n', encoding='utf-8')
    print(json.dumps({'channel_area_km2': bundle['channel_area_km2'], 'samples': len(samples), 'peak': samples[-1], 'outputs': manifest['outputs']}, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--population-raster', type=Path, required=True)
    main(parser.parse_args().population_raster)
