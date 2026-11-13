"""Extract public GRRR with cached source chunks and auditable station matching."""
import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import shapefile
import zarr
from matplotlib.path import Path as PolygonPath

HERE = Path(__file__).resolve().parent
BASE = 'https://storage.googleapis.com/flood-forecasting/hydrologic_predictions/model_id_8583a5c2_v0/'
NOTEBOOK = 'https://drive.google.com/uc?export=download&id=1FnXXSEQqU1TJhMPiNeWUTr9LnbJwZzMm'


class CachedStore(MutableMapping):
    def __init__(self, name):
        self.name = name
        self.root = HERE / 'sources' / name

    def __getitem__(self, key):
        path = self.root / key
        if not path.exists():
            try:
                response = urllib.request.urlopen(BASE + self.name + '/' + key, timeout=90)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise KeyError(key) from exc
                raise
            data = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path.read_bytes()

    def __setitem__(self, key, value):
        raise TypeError('read only')

    def __delitem__(self, key):
        raise TypeError('read only')

    def __iter__(self):
        return iter(str(p.relative_to(self.root)).replace('\\', '/') for p in self.root.rglob('*') if p.is_file())

    def __len__(self):
        return sum(1 for _ in self)


def main():
    sources = HERE / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    notebook = sources / 'official_access_notebook.ipynb'
    if not notebook.exists():
        notebook.write_bytes(urllib.request.urlopen(NOTEBOOK, timeout=60).read())
    outlets = zarr.open_consolidated(CachedStore('hybas_outlet_locations_UNOFFICIAL.zarr'), mode='r')
    lat, lon, ids = outlets['latitude'][:], outlets['longitude'][:], outlets['gauge_id'][:]
    dlat, dlon = np.radians(lat - 32.67), np.radians(lon - 74.46)
    distance = 6371 * 2 * np.arcsin(np.sqrt(np.sin(dlat / 2)**2 + np.cos(np.radians(lat)) * np.cos(np.radians(32.67)) * np.sin(dlon / 2)**2))
    nearest = np.argsort(np.where(np.isfinite(distance), distance, np.inf))[:20]
    candidates = pd.DataFrame({'gauge_id': ids[nearest], 'latitude': lat[nearest], 'longitude': lon[nearest], 'distance_km': distance[nearest]})
    candidates.to_csv(HERE / 'outlet_candidates.csv', index=False)
    print(candidates.to_string(index=False), flush=True)
    hydrobasins_url = 'https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev12_v1c.zip'
    archive = sources / 'hybas_as_lev12_v1c.zip'
    if not archive.exists():
        request = urllib.request.Request(hydrobasins_url, headers={'User-Agent': 'Mozilla/5.0'})
        archive.write_bytes(urllib.request.urlopen(request, timeout=120).read())
    with zipfile.ZipFile(archive) as zipped:
        names = {n.rsplit('.', 1)[-1]: n for n in zipped.namelist() if '.' in n}
        reader = shapefile.Reader(**{ext: io.BytesIO(zipped.read(names[ext])) for ext in ('shp', 'shx', 'dbf')})
        matches = []
        for item in reader.iterShapeRecords(bbox=(74.459, 32.669, 74.461, 32.671)):
            parts = list(item.shape.parts) + [len(item.shape.points)]
            inside = sum(PolygonPath(item.shape.points[a:b]).contains_point((74.46, 32.67)) for a, b in zip(parts, parts[1:])) % 2
            if inside:
                matches.append(item)
        assert len(matches) == 1, 'Station must be in exactly one HydroBasins polygon'
        attributes = matches[0].record.as_dict()
        selected = f"hybas_{attributes['HYBAS_ID']}"
        assert abs(attributes['UP_AREA'] / 29192 - 1) < 0.05, 'Upstream area mismatch'
        (HERE / 'selected_hydrobasin.geojson').write_text(json.dumps(dict(type='Feature', properties=attributes, geometry=matches[0].shape.__geo_interface__)))
    ds = zarr.open_consolidated(CachedStore('reanalysis/streamflow.zarr'), mode='r')
    gauges = ds['gauge_id'][:]
    # Select by geometry and upstream area before inspecting any flow scores.
    assert selected in set(gauges)
    idx = int(np.flatnonzero(gauges == selected)[0])
    q = ds['streamflow'][idx, :]
    days = pd.Timestamp('1980-01-01') + pd.to_timedelta(ds['time'][:], unit='D')
    frame = pd.DataFrame({'date': days, 'grrr_discharge_m3_s': q, 'gauge_id': selected})
    frame.to_csv(HERE / 'grrr_marala_reanalysis.csv', index=False)
    receipt = dict(retrieved_utc=datetime.now(timezone.utc).isoformat(), model_id='8583a5c2_v0',
                   source_base=BASE, official_notebook_url=NOTEBOOK, license='CC BY 4.0; attribute Google Research GRRR',
                   gauge_id=selected, selected_outlet=candidates.loc[candidates.gauge_id == selected].iloc[0].to_dict(),
                   hydrobasins_url=hydrobasins_url, hydrobasins_attributes=attributes,
                   published_station_upstream_area_km2=29192,
                   selection='HydroBasins polygon containing Marala, confirmed upstream area within 5% of published area. Closest outlet rejected as tributary; selection independent of flow scores.',
                   start=str(days.min().date()), end=str(days.max().date()),
                   units='m3/s as documented for streamflow; daily mean, UTC left-labeled [T,T+1 day]',
                   limitations=['Outlet coordinates are explicitly UNOFFICIAL in the source notebook.',
                                'Observed Marala mostly has unconfirmed point-reading times; matching calendar dates does not equate measurement intervals.',
                                'Reanalysis is retrospective and no operational publication latency is established.',
                                'No 2024-2026 values exist in this archive; do not extrapolate them.'],
                   files={str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.rglob('*') if p.is_file()})
    (HERE / 'source_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k:v for k,v in receipt.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
