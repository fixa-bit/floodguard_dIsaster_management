"""Create a wet-channel HEC-RAS restart using a native baseflow spin-up.

Only copies are edited. The original USACE geometry, terrain and roughness stay
unchanged. Warm-up uses 1,000 cfs and the original starting downstream stage;
the flood run restores the original rising hydrograph and stage series.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT/'tools/hec_ras/runs/muncie_trial/Plans/Base Plan/Base Plan.dwe.r2r.h5'
RAS = ROOT/'tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def solve(source, output):
    if output.exists():
        with h5py.File(output) as f:
            if int(f['Results/Compute Summary'].attrs['Success'])==1:
                print(f'Reusing completed native solve: {output.name}',flush=True)
                return
        raise FileExistsError(f'Incomplete retained result requires a fresh filename: {output}')
    subprocess.run([str(RAS),'plan','solve',str(source),str(output),'--core-count','2'],check=True)
    with h5py.File(output) as f:
        if int(f['Results/Compute Summary'].attrs['Success'])!=1:
            raise ValueError('HEC-RAS solver did not complete')


def main():
    warm_input = HERE/'baseflow.r2r.h5'
    warm_result = HERE/'baseflow-computed.h5'
    flood_input = HERE/'wet-channel-flood.r2r.h5'
    flood_result = HERE/'white-river-initialized.h5'
    if not warm_input.exists():
        shutil.copy2(SOURCE,warm_input)
        with h5py.File(warm_input,'r+') as f:
            group=f['Boundary Conditions/BC Lines/Payloads']
            definitions=group['Time Series Definitions'][:]
            values=group['Values'][:]
            for definition in definitions:
                start,count=int(definition['Start (Value)']),int(definition['Count'])
                values[start:start+count]=values[start]
            group['Values'][:]=values
    print('Running native HEC-RAS low-flow channel spin-up',flush=True)
    solve(warm_input,warm_result)
    with h5py.File(warm_result) as f:
        group=f['Results/Output Blocks/Base Output/2D Flow Areas/Mesh']
        depth=group['Cell Depth'][-1]
        velocity=group['Face Velocity'][-1]
        volumes=group['DEBUG/CellVolume'][:].sum(axis=1)
        drift=float(abs(volumes[-1]-volumes[-2])/max(1,volumes[-1]))
        wet=int(np.count_nonzero(depth>=.1/(1200/3937)))
        if not np.isfinite(depth).all() or not np.isfinite(velocity).all() or depth.min() < -1e-5 or wet<200:
            raise ValueError('Baseflow did not establish an existing wet river')
        if drift>.02:
            raise ValueError(f'Baseflow not sufficiently settled: final hour volume drift {drift}')
    if not flood_input.exists():
        shutil.copy2(SOURCE,flood_input)
        with h5py.File(flood_input,'r+') as f:
            f['Results/Initial Conditions/2D Flow Areas/Mesh/Cell Depth'][:]=depth
            f['Results/Initial Conditions/2D Flow Areas/Mesh/Face Velocity'][:]=velocity
    print(f'Wet restart: {wet} cells, final hour baseflow volume drift {drift:.5f}',flush=True)
    solve(flood_input,flood_result)
    with h5py.File(flood_result) as f:
        np.testing.assert_allclose(f['Results/Initial Conditions/2D Flow Areas/Mesh/Cell Depth'][:],depth,atol=1e-6)
        np.testing.assert_allclose(f['Results/Initial Conditions/2D Flow Areas/Mesh/Face Velocity'][:],velocity,atol=1e-6)
    record={'original_prepared_model_sha256':sha(SOURCE),'baseflow_input_sha256':sha(warm_input),
            'baseflow_result_sha256':sha(warm_result),'initialized_flood_input_sha256':sha(flood_input),
            'initialized_flood_result_sha256':sha(flood_result),'wet_cells_at_restart':wet,
            'baseflow_duration_hours':24,'baseflow_cfs':1000,'final_hour_relative_volume_drift':drift,
            'changes':['Baseflow copy holds original boundary time series at their first values.',
                       'Flood copy uses final native baseflow cell depths and signed face velocities as initial conditions.',
                       'Flood boundary conditions, geometry, roughness and terrain match original USACE inputs.']}
    (HERE/'initialization.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print('Completed baseflow initialization and native rising-flow run',flush=True)


if __name__=='__main__':
    main()
