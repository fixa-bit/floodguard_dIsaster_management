"""Read the public 2026_11 release without mixing it with documented GRRR v0.

This release has Zarr v3 metadata. Only bytes + Zstd codecs are supported here;
fail closed if the upstream schema changes. The official notebook still links v0.
"""
import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from numcodecs import Zstd

from collect import HERE

BASE = 'https://storage.googleapis.com/flood-forecasting/'
PREFIX = 'hydrologic_predictions/distributed_model_2026_11/'


def fetch(key):
    path = HERE / 'sources' / 'distributed_model_2026_11' / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(urllib.request.urlopen(BASE + PREFIX + key, timeout=90).read())
    return path.read_bytes()


def decode(metadata, key, dtype):
    assert [c['name'] for c in metadata['codecs']] == ['bytes', 'zstd']
    return np.frombuffer(Zstd().decode(fetch(key)), dtype=dtype)


def main():
    # collect.py must run first to establish station reach by independent geometry.
    old = json.loads((HERE / 'source_receipt.json').read_text())
    assert old['model_id'] == '8583a5c2_v0', 'Run collect.py before collect_current.py'
    shutil.copyfile(HERE / 'source_receipt.json', HERE / 'source_receipt_v0.json')
    shutil.copyfile(HERE / 'grrr_marala_reanalysis.csv', HERE / 'grrr_marala_reanalysis_v0.csv')
    root = 'reanalysis/streamflow.zarr/'
    meta = json.loads(fetch(root + 'zarr.json'))['consolidated_metadata']['metadata']
    wanted = old['gauge_id'].replace('hybas_', 'subhybas_')
    gm = meta['gauge_id']
    assert gm['data_type']['name'] == 'fixed_length_utf32'
    width = gm['data_type']['configuration']['length_bytes'] // 4
    size = gm['chunk_grid']['configuration']['chunk_shape'][0]
    index = None
    for chunk in range((gm['shape'][0] + size - 1) // size):
        values = decode(gm, root + f'gauge_id/c/{chunk}', f'<U{width}')
        found = np.flatnonzero(values == wanted)
        if len(found):
            index = chunk * size + int(found[0])
            break
    assert index is not None, 'No matched reach in new release'
    sm = meta['streamflow']
    gs, ts = sm['chunk_grid']['configuration']['chunk_shape']
    assert ts == sm['shape'][1], 'Expected full-time chunks'
    flow = decode(sm, root + f'streamflow/c/{index // gs}/0', '<f4').reshape(gs, ts)[index % gs]
    tm = meta['time']
    assert tm['attributes']['units'] == 'days since 1980-12-31 00:00:00'
    time = decode(tm, root + 'time/c/0', '<i8')
    days = pd.Timestamp('1980-12-31') + pd.to_timedelta(time, unit='D')
    pd.DataFrame(dict(date=days, grrr_discharge_m3_s=flow, gauge_id=wanted)).to_csv(HERE / 'grrr_marala_reanalysis.csv', index=False)
    # Retain the newer release's independently published outlet coordinates too.
    import zarr
    from collect import CachedStore
    class NewOutlets(CachedStore):
        def __getitem__(self, key):
            return fetch(self.name + '/' + key)
    outlets = zarr.open_consolidated(NewOutlets('subhybas_outlet_locations_UNOFFICIAL.zarr'), mode='r')
    ids = outlets['gauge_id'][:]
    ix = int(np.flatnonzero(ids == wanted)[0])
    outlet = dict(latitude=float(outlets['latitude'][ix]), longitude=float(outlets['longitude'][ix]))
    assert abs(outlet['latitude'] - old['selected_outlet']['latitude']) < 1e-6
    assert abs(outlet['longitude'] - old['selected_outlet']['longitude']) < 1e-6
    listing_url = 'https://storage.googleapis.com/storage/v1/b/flood-forecasting/o?prefix=' + urllib.parse.quote(PREFIX + root + 'zarr.json', safe='')
    listing = json.load(urllib.request.urlopen(listing_url, timeout=30))
    (HERE / 'sources/current_release_listing.json').write_text(json.dumps(listing, indent=2))
    receipt = {**old, 'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'model_id': 'distributed_model_2026_11',
               'source_base': BASE + PREFIX, 'gauge_id': wanted, 'selected_outlet': {**old['selected_outlet'], 'gauge_id': wanted},
               'start': str(days.min().date()), 'end': str(days.max().date()),
               'units': 'm3/s and daily-mean left-labeled intervals inferred from the documented GRRR family; new-release interval metadata unconfirmed',
               'metadata_status': 'Public bucket release (metadata creation timestamp retained). Official access notebook still links v0. Daily-mean units/interval convention inferred from GRRR family, not independently documented for this new release.',
               'limitations': old['limitations'][:3] + ['New release metadata incompletely documented; separate v0 comparison retained.', 'No 2026 values; keep them NaN.'],
               'files': {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE / 'sources').rglob('*') if p.is_file()}}
    (HERE / 'source_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k:v for k,v in receipt.items() if k != 'files'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
