"""Check native river setup, vector reconstruction and exported replay integrity."""
import gzip
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

from models.river_channel_hydraulics.export import reconstruct_velocity

ROOT = Path(__file__).resolve().parents[1]


def test_signed_face_normals_recover_known_vector():
    nodes = np.array([[0., 0.], [4., 0.], [4., 2.], [0., 2.]])
    centres = np.array([[2., 1.]])
    faces = np.array([[0, -1, 0, 1], [0, -1, 1, 2], [0, -1, 2, 3], [0, -1, 3, 0]])
    normals = np.array([[0., -1.], [1., 0.], [0., 1.], [-1., 0.]])
    expected = np.array([[3., -2.], [-1., 4.], [0., 0.]])
    face_speed = expected @ normals.T
    vx, vy = reconstruct_velocity(nodes, centres, faces, face_speed)
    np.testing.assert_allclose(vx[:, 0], expected[:, 0], atol=1e-12)
    np.testing.assert_allclose(vy[:, 0], expected[:, 1], atol=1e-12)


def test_native_model_is_wet_and_uses_river_boundaries():
    result = ROOT/'models/river_channel_hydraulics/white-river-initialized.h5'
    with h5py.File(result) as f:
        assert int(f['Results/Compute Summary'].attrs['Success']) == 1
        initial = f['Results/Initial Conditions/2D Flow Areas/Mesh/Cell Depth'][:]
        assert np.count_nonzero(initial>.3) > 500
        payloads = f['Boundary Conditions/BC Lines/Payloads/Payloads'][:]
        assert set(payloads['Variable']) == {b'Flow', b'Normal Depth', b'Stage'}
        assert len(f['Results/Output Blocks/Base Output/Time']) == 25
        assert len(f['Geometry/2D Flow Areas/Mesh/Cell Coordinates']) == 7257


def test_exported_depths_velocities_and_sources():
    base = ROOT/'frontend/public/river-channel-flow'
    data = json.loads((base/'results.json').read_text(encoding='utf-8'))
    raw = gzip.decompress((base/'frames.bin.gz').read_bytes())
    assert hashlib.sha256(raw).hexdigest() == data['frame_payload_sha256']
    result = ROOT/'models/river_channel_hydraulics/white-river-initialized.h5'
    assert hashlib.sha256(result.read_bytes()).hexdigest() == data['native_result_sha256']
    packed = np.frombuffer(raw,dtype='<i2').reshape(len(data['frames']),3,data['rows']*data['cols'])
    assert packed[:, 0].min() >= 0
    assert np.count_nonzero(packed[0,0]>=100)>100
    assert data['frames'][0]['additional_wet_area_km2'] == 0
    assert max(f['wet_area_km2'] for f in data['frames']) > data['frames'][0]['wet_area_km2']*3
    assert np.abs(packed[:,1:]).max() > 0
    assert np.abs(packed[0,1:]).max() > 0
    assert all(f['max_speed_ms'] < 20 for f in data['frames'])
    assert len(data['boundary_lines']) == 3
    assert data['numerical_checks']['source_verified']
    assert data['initialization']['final_hour_relative_volume_drift'] < .02
    for t,frame in enumerate(data['frames']):
        assert abs(packed[t,0].max()*.001-frame['max_depth_m']) <= .00051
