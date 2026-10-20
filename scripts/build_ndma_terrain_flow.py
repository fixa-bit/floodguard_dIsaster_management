"""Export a conservative, uncalibrated diffusion-wave replay from local NDMA rasters.

Does not modify inputs. Run with .venv/Scripts/python.exe scripts/build_ndma_terrain_flow.py.
The source is an assumed localized inflow, not an observed event or river discharge.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path('D:/Projects/NDMA_tasks/NDMA_tasks/dataset/sen1floods11_sar_handlabeled_v1_1')


def face_flux(z, h, dx, dy, roughness):
    """Discharge per unit width, positive east/south; dry bed steps block flow."""
    eta = z + h
    sx = (eta[:, 1:] - eta[:, :-1]) / dx
    sy = (eta[1:] - eta[:-1]) / dy
    hx = np.maximum(0, np.maximum(eta[:, 1:], eta[:, :-1]) - np.maximum(z[:, 1:], z[:, :-1]))
    hy = np.maximum(0, np.maximum(eta[1:], eta[:-1]) - np.maximum(z[1:], z[:-1]))
    qx = -hx ** (5/3) * sx / (roughness * np.sqrt(np.maximum(np.abs(sx), 1e-5)))
    qy = -hy ** (5/3) * sy / (roughness * np.sqrt(np.maximum(np.abs(sy), 1e-5)))
    return qx, qy


def step(z, h, dx, dy, dt, roughness):
    qx, qy = face_flux(z, h, dx, dy, roughness)
    outgoing = np.zeros_like(h)
    outgoing[:, :-1] += np.maximum(qx, 0)/dx
    outgoing[:, 1:] += np.maximum(-qx, 0)/dx
    outgoing[:-1] += np.maximum(qy, 0)/dy
    outgoing[1:] += np.maximum(-qy, 0)/dy
    factor = np.minimum(1, .9*h / np.maximum(outgoing*dt, 1e-30))
    qx *= np.where(qx >= 0, factor[:, :-1], factor[:, 1:])
    qy *= np.where(qy >= 0, factor[:-1], factor[1:])
    h[:, :-1] -= dt*qx/dx
    h[:, 1:] += dt*qx/dx
    h[:-1] -= dt*qy/dy
    h[1:] += dt*qy/dy
    return qx, qy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--sample', default='Pakistan_849790')
    parser.add_argument('--output', type=Path, default=ROOT/'frontend/public/ndma-terrain-flow')
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    sources = {}
    arrays = {}
    for role in ('elevation', 'slope'):
        path = args.dataset/'features'/role/'chips'/f'{args.sample}_{role}.tif'
        provenance = json.loads((args.dataset/'metadata/features'/role/f'{args.sample}.json').read_text())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != provenance['sha256']:
            raise ValueError(f'{role}: checksum does not match NDMA provenance')
        with rasterio.open(path) as src:
            if role == 'elevation':
                bounds = list(src.bounds)
                transform, crs, shape = src.transform, src.crs, src.shape
            elif src.transform != transform or src.crs != crs or src.shape != shape:
                raise ValueError('Slope and elevation must be aligned')
            a = src.read(1, out_shape=(96, 96), resampling=Resampling.average, masked=True)
            if np.ma.getmaskarray(a).any() or not np.isfinite(a).all():
                raise ValueError('This replay requires complete terrain coverage; NoData is not filled')
            arrays[role] = np.asarray(a, dtype=np.float64)
        sources[role] = {**provenance, 'file': path.name, 'sha256': digest}
    z, slope = arrays['elevation'], arrays['slope']
    rows, cols = z.shape
    west, south, east, north = bounds
    dx = (east-west)*111320*np.cos(np.deg2rad((north+south)/2))/cols
    dy = (north-south)*111320/rows
    cell_area = dx*dy
    # Hypothetical inflow patch on higher ground; selection is deterministic and recorded.
    rr, cc = np.indices(z.shape)
    candidates = (rr > 12) & (rr < 50) & (cc > 20) & (cc < 75) & (z >= np.percentile(z, 80))
    score = np.where(candidates, (rr-28)**2 + (cc-48)**2, np.inf)
    row, col = np.unravel_index(np.argmin(score), z.shape)
    inlet = (rr-row)**2 + (cc-col)**2 <= 3**2
    h = np.zeros_like(z)
    dt, duration, interval, roughness = 1., 10800, 90, .045
    hydrograph = [[0, 0], [900, 50], [2700, 50], [5400, 0], [10800, 0]]
    injected = 0.
    frames, packed = [], []
    qx, qy = np.zeros((rows, cols-1)), np.zeros((rows-1, cols))
    max_error = 0.
    for second in range(duration+1):
        if second % interval == 0:
            vx, vy = np.zeros_like(z), np.zeros_like(z)
            vx[:, :-1] += qx/2; vx[:, 1:] += qx/2
            vy[:-1] += qy/2; vy[1:] += qy/2
            wet = h >= .02
            vx = np.where(wet, vx/np.maximum(h, .02), 0)
            vy = np.where(wet, vy/np.maximum(h, .02), 0)
            speed = np.hypot(vx, vy)
            if h.max()*1000 > 32767 or speed.max()*10000 > 32767:
                raise ValueError('Replay exceeds int16 packing range')
            packed.append(np.stack([np.rint(h*1000), np.rint(vx*10000), np.rint(vy*10000)]).astype('<i2').tobytes())
            volume = float(h.sum()*cell_area)
            error = abs(volume-injected)/max(1, injected)
            max_error = max(error, max_error)
            frames.append({'seconds': second, 'inflow_m3s': float(np.interp(second, *np.array(hydrograph).T)),
                           'volume_m3': volume, 'injected_m3': injected, 'mass_error': error,
                           'wet_area_km2': float(wet.sum()*cell_area/1e6), 'max_depth_m': float(h.max()),
                           'max_speed_ms': float(speed.max())})
        if second == duration:
            break
        inflow = float(np.interp(second+.5, *np.array(hydrograph).T))
        h[inlet] += inflow*dt/(inlet.sum()*cell_area)
        injected += inflow*dt
        qx, qy = step(z, h, dx, dy, dt, roughness)
        if h.min() < -1e-10 or not np.isfinite(h).all():
            raise ValueError('Nonphysical depth produced')
    if max_error > 1e-8:
        raise ValueError('Water balance failed')
    # Grey-green terrain relief provides a fully local fallback to satellite imagery.
    gy, gx = np.gradient(z, dy, dx)
    shade = np.clip(.6 + (gx-gy)*25, .2, 1)
    relative = np.clip((z-np.percentile(z, 2))/max(.1, np.ptp(z)), 0, 1)
    rgb = np.stack([(60+relative*80)*shade, (90+relative*70)*shade, (78+relative*55)*shade], axis=-1)
    Image.fromarray(rgb.astype('uint8')).resize((768, 768)).save(out/'terrain.png')
    (out/'frames.bin').write_bytes(b''.join(packed))
    meta = {'version': 1, 'sample': args.sample, 'bounds': bounds, 'rows': rows, 'cols': cols,
            'dx_m': dx, 'dy_m': dy, 'duration_seconds': duration, 'interval_seconds': interval,
            'depth_unit_m': .001, 'velocity_unit_ms': .0001, 'wet_threshold_m': .02,
            'solver': 'Conservative explicit 2D diffusion-wave approximation', 'manning_n': roughness,
            'dt_seconds': dt, 'boundaries': 'Closed study edges; water is retained inside this window',
            'hydrograph_seconds_m3s': hydrograph, 'inlet': {'row': int(row), 'col': int(col), 'radius_cells': 3},
            'sources': sources, 'frames': frames, 'max_mass_error': max_error,
            'elevation_m': np.round(z, 3).ravel().tolist(), 'slope_degrees': np.round(slope, 4).ravel().tolist(),
            'numerical_checks': {'mass_balance_passed': True, 'nonnegative_depth_passed': True},
            'method_url': 'https://www.hec.usace.army.mil/confluence/hecras/beta/technical-reference/hydraulic-equations/shallow-water-equations',
            'credit': 'Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018; provided under COPERNICUS by the EU and ESA.',
            'limitations': ['Assumed inflow and roughness; no gauge calibration or historical validation.',
                            'Copernicus surface elevation is not surveyed bathymetry; native resolution is 30 m.',
                            'Inertia, infiltration, rainfall, culverts and surveyed levees are omitted.',
                            'Closed edges can cause artificial ponding; results only describe this window.',
                            'Particle travel is visually accelerated; speed labels retain model units.']}
    (out/'results.json').write_text(json.dumps(meta, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'output': str(out), 'frames': len(frames), 'max_mass_error': max_error,
                      'max_depth_m': max(f['max_depth_m'] for f in frames),
                      'max_speed_ms': max(f['max_speed_ms'] for f in frames), 'inlet': meta['inlet']}))


if __name__ == '__main__':
    main()
