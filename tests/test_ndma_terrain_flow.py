"""Physical invariants for the separate NDMA terrain-flow experiment."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from build_ndma_terrain_flow import step


def test_sloped_lake_at_rest():
    z = np.tile(np.linspace(0, 1, 16), (16, 1))
    h = 2-z
    before = h.copy()
    step(z, h, 10, 10, .1, .045)
    np.testing.assert_allclose(h, before, atol=1e-12)


def test_downhill_transport_and_roughness():
    z = np.tile(np.linspace(1, 0, 16), (16, 1))
    h = np.zeros_like(z)
    h[:, 3] = .2
    rough, smooth = h.copy(), h.copy()
    qx, _ = step(z, smooth, 10, 10, .1, .025)
    step(z, rough, 10, 10, .1, .08)
    assert qx[:, 3].min() > 0
    assert smooth[:, 4].min() > rough[:, 4].min() > 0
    assert abs(smooth.sum()-h.sum()) < 1e-12


def test_dry_ridge_blocks_water():
    z = np.zeros((16, 16))
    z[:, 8] = 10
    h = np.zeros_like(z)
    h[:, :8] = 1
    for _ in range(100):
        step(z, h, 10, 10, 1, .045)
    assert (h[:, 8:] == 0).all()


def test_limiter_preserves_water_and_nonnegative_depth():
    z = np.tile(np.linspace(5, 0, 16), (16, 1))
    h = np.zeros_like(z)
    h[:, 3] = 2
    volume = h.sum()
    for _ in range(100):
        step(z, h, 10, 10, 10, .02)
    assert abs(h.sum()-volume) < 1e-10
    assert h.min() >= -1e-12


def test_packaged_replay_matches_metadata():
    base = Path(__file__).resolve().parents[1]/'frontend/public/ndma-terrain-flow'
    data = json.loads((base/'results.json').read_text(encoding='utf-8'))
    count = data['rows']*data['cols']
    packed = np.fromfile(base/'frames.bin', dtype='<i2').reshape(len(data['frames']), 3, count)
    assert data['max_mass_error'] < 1e-8
    assert (packed[:, 0] >= 0).all()
    assert packed[0].max() == 0
    assert np.abs(packed[:, 1:]).max() > 0
    assert data['sources']['elevation']['units'] == 'metres'
    assert data['sources']['slope']['units'] == 'degrees'
    for index, frame in enumerate(data['frames']):
        assert abs(frame['volume_m3']-frame['injected_m3']) < 1e-5
        assert abs(packed[index, 0].max()*.001-frame['max_depth_m']) <= .00051
