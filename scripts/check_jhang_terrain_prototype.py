"""Connectivity fixtures, exact population overlap and portable asset consistency."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import binary_propagation
import shapely
from shapely.geometry import box, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_jhang_terrain_prototype import (OUT, DATA, CELL, RISES, TO_LOCAL,
    connected_threshold, population_overlap, polygonize, project)


def fixtures():
    terrain = np.array([[0., 4, -2], [0, 4, -2], [0, 4, -2]])
    seeds = np.zeros((3, 3), dtype=bool); seeds[1, 0] = True
    costs, parents = connected_threshold(terrain, seeds)
    assert costs[1, 2] == 4, 'Isolated depression cannot flood before its sill'
    terrain[2, 1] = 1
    costs, _ = connected_threshold(terrain, seeds)
    assert costs[1, 2] == 1, 'A lower connected gap must admit water'
    terrain[:, 1] = np.nan
    costs, _ = connected_threshold(terrain, seeds)
    assert np.isinf(costs[:, 2]).all(), 'NoData must block connectivity'
    terrain = np.array([[0., np.nan], [np.nan, -1]])
    seeds = np.array([[True, False], [False, False]])
    costs, _ = connected_threshold(terrain, seeds)
    assert np.isinf(costs[1, 1]), 'No diagonal corner leaks'
    rng = np.random.default_rng(184)
    terrain = rng.integers(-2, 6, (35, 41)).astype(float)
    terrain[rng.random(terrain.shape) < .06] = np.nan
    seeds = np.zeros(terrain.shape, dtype=bool); seeds[16, 3] = True; seeds[3, 30] = True
    terrain[seeds] = 0
    costs, parents = connected_threshold(terrain, seeds)
    for rise in range(7):
        allowed = np.isfinite(terrain) & (terrain <= rise)
        expected = binary_propagation(seeds, mask=allowed)
        assert np.array_equal(costs <= rise, expected), 'Minimax must equal independent threshold flood-fill'
    for index in np.flatnonzero(np.isfinite(costs.ravel()) & ~seeds.ravel()):
        parent = int(parents.ravel()[index])
        r, c = divmod(index, terrain.shape[1]); rr, cc = divmod(parent, terrain.shape[1])
        assert parent >= 0 and abs(r-rr)+abs(c-cc) == 1
        assert costs.ravel()[parent] <= costs.ravel()[index]
    # Exact native-pixel area weighting: a half-covered 10-person pixel contributes 5.
    transform = from_origin(0, 4, 1, 1)
    mask = np.array([[1, 0, 1, 1], [1, 1, 0, 0], [0, 0, 1, 0], [1, 0, 1, 1]], dtype=bool)
    cells = np.array([box(0, 0, 2, 4), box(2, 0, 4, 4)], dtype=object)
    overlap = population_overlap(mask, transform, cells, shapely.STRtree(cells), box(0, 0, 4, 4))
    expected = shapely.area(shapely.intersection(cells, polygonize(mask, transform)))
    np.testing.assert_allclose(overlap, expected, rtol=0, atol=1e-12)
    assert (overlap / shapely.area(cells) * np.array([10, 20])).sum() == 17.5
    clipped = box(.25, .25, 3.8, 3.7)
    exact = shapely.area(shapely.intersection(shapely.intersection(cells, clipped), polygonize(mask, transform)))
    np.testing.assert_allclose(population_overlap(mask, transform, cells, shapely.STRtree(cells), clipped), exact, atol=1e-12)


def artifacts():
    data = json.loads((DATA/'jhang-pilot.geojson').read_text(encoding='utf-8'))
    meta = json.loads((OUT/'metadata.json').read_text(encoding='utf-8'))
    assert not meta['hydraulic_model'] and not meta['calibrated']
    assert meta['grid']['nodata_cells_inside'] == 0, 'Buffered source window must cover study grid'
    for record in meta['outputs']:
        path = DATA/record['file'] if record['file'].endswith('pilot.geojson') else OUT/record['file']
        assert path.stat().st_size == record['bytes']
        assert sha256(path.read_bytes()).hexdigest() == record['sha256']
    with rasterio.open(OUT/'elevation-30m.tif') as dem:
        assert dem.crs.to_epsg() == 32643 and dem.res == (30, 30)
        assert (dem.width, dem.height) == (meta['grid']['width'], meta['grid']['height'])
        assert np.nanmin(dem.read(1)) > 100 and np.nanmax(dem.read(1)) < 200
    for key in ['water', 'waterways', 'connection_paths', 'study_boundary', 'reference_extent']:
        for feature in data[key]['features']:
            assert shape(feature['geometry']).is_valid, f'Invalid geometry in {key}'
    aoi = project(TO_LOCAL, shapely.segmentize(shape(data['study_boundary']['features'][0]['geometry']), .001))
    assert len(data['waterways']['features']) == 3
    assert [item['properties']['waterway'] for item in data['waterways']['features']].count('river') == 1
    previous_area = previous_population = 0
    for level, rise in enumerate(RISES):
        entry = data['levels'][level]
        assert entry['assumed_rise_m'] == rise
        assert entry['flood_area_km2'] >= previous_area and entry['exposed_population'] >= previous_population
        assert entry['exposed_population'] <= data['known_population_2025']
        rings = [project(TO_LOCAL, shape(f['geometry'])) for f in data['water']['features'] if f['properties']['min_level'] <= level]
        footprint = unary_union(rings)
        assert abs(footprint.area-entry['flood_area_km2']*1e6) < CELL**2/2, 'Displayed geometry must agree within half one source pixel'
        assert footprint.difference(aoi.buffer(.2)).area < 1, 'No water beyond study boundary'
        if level:
            assert 0 <= entry['known_raster_area_fraction'] <= 1
            # Reprojection and ~0.1m coordinate snapping can make very thin
            # display slivers. The underlying raster bands are disjoint.
            assert abs(sum(ring.area for ring in rings)-footprint.area) < CELL**2*.05, 'Display-band overlap must stay below 5% of one source pixel'
        else:
            assert entry['flood_area_km2'] == entry['exposed_population'] == 0
        previous_area, previous_population = entry['flood_area_km2'], entry['exposed_population']
    print(json.dumps({'status': 'passed', 'grid': meta['grid'], 'levels': data['levels']}, indent=2))


if __name__ == '__main__':
    fixtures()
    artifacts()
