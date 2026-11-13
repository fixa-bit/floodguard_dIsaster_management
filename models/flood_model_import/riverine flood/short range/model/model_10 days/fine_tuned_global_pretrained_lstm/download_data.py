"""Obtain the compatible 14 ERA5 variables and measured-source HydroATLAS statics."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.request import urlopen


FEATURES = {
    'snow_depth_water_equivalent_mean': ['snow_depth_water_equivalent', 1000., 0.],
    'surface_net_solar_radiation_mean': ['surface_net_solar_radiation_sum', 1 / 86400., 0.],
    'surface_net_thermal_radiation_mean': ['surface_net_thermal_radiation_sum', 1 / 86400., 0.],
    'surface_pressure_mean': ['surface_pressure', .001, 0.],
    'temperature_2m_mean': ['temperature_2m', 1., -273.15],
    'dewpoint_temperature_2m_mean': ['dewpoint_temperature_2m', 1., -273.15],
    'u_component_of_wind_10m_mean': ['u_component_of_wind_10m', 1., 0.],
    'v_component_of_wind_10m_mean': ['v_component_of_wind_10m', 1., 0.],
    'volumetric_soil_water_layer_1_mean': ['volumetric_soil_water_layer_1', 1., 0.],
    'volumetric_soil_water_layer_2_mean': ['volumetric_soil_water_layer_2', 1., 0.],
    'volumetric_soil_water_layer_3_mean': ['volumetric_soil_water_layer_3', 1., 0.],
    'volumetric_soil_water_layer_4_mean': ['volumetric_soil_water_layer_4', 1., 0.],
    'total_precipitation_sum': ['total_precipitation_sum', 1000., 0.],
    'potential_evaporation_sum': ['potential_evaporation_sum', -1000., 0.]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('extraction.json')))
    args = parser.parse_args()
    root = Path(args.config).resolve().parent
    cfg = json.loads(Path(args.config).read_text())
    import ee
    ee.Initialize(project=cfg['earth_engine_project'])
    polygon_path = (root / cfg['catchment_file']).resolve()
    polygon = ee.FeatureCollection(json.loads(polygon_path.read_text())).geometry()
    output = root / cfg['raw_directory']; output.mkdir(parents=True, exist_ok=True)
    weather = output / 'era5land_daily'; weather.mkdir(exist_ok=True)
    area = polygon.area(1).divide(1e6).getInfo()
    print(f'Marala area: {area:.3f} km2', flush=True)
    # All selected HydroATLAS suffixes are spatial means or area percentages.
    climate_names = ['p_mean', 'pet_mean', 'aridity', 'frac_snow', 'high_prec_freq', 'high_prec_dur',
                     'low_prec_freq', 'low_prec_dur', 'moisture_index', 'seasonality', 'area']
    base = json.loads((root / 'pretrained/caravan_base/config.json').read_text())
    names = [name for name in base['static_attributes'] if name not in climate_names]
    static_path = output / 'hydroatlas_intersections.json'
    if not static_path.exists():
        atlas = ee.FeatureCollection(cfg['hydroatlas_collection']).filterBounds(polygon)
        available = ee.Feature(atlas.first()).propertyNames().getInfo()
        selected = [name for name in names if name in available]
        def intersect(feature):
            feature = ee.Feature(feature)
            weight = feature.geometry().intersection(polygon, 10).area(10).divide(1e6)
            return ee.Feature(None, feature.toDictionary(selected)).set('intersection_km2', weight)
        features = atlas.map(intersect).filter(ee.Filter.gt('intersection_km2', 0)).getInfo()['features']
        records = [item['properties'] for item in features]
        static_path.write_text(json.dumps({'collection': cfg['hydroatlas_collection'], 'area_km2': area,
                                           'requested': names, 'available': selected, 'records': records}, indent=2) + '\n')
        print(f'Saved HydroATLAS: {len(records)} overlapping sub-basins, {len(selected)} required attributes', flush=True)
    collection = ee.ImageCollection(cfg['collection'])
    projection = ee.Image(collection.filterDate('2020-01-01', '2020-01-02').first()).select('temperature_2m').projection()
    def daily(item):
        image = ee.Image(item)
        fields = [image.select(band).multiply(factor).add(offset).rename(name) for name, (band, factor, offset) in FEATURES.items()]
        means = ee.Image.cat(fields).reduceRegion(reducer=ee.Reducer.mean(), geometry=polygon,
                                                  crs=projection, scale=projection.nominalScale(),
                                                  maxPixels=1000000, tileScale=4)
        return ee.Feature(None, means).set('date', image.date().format('YYYY-MM-dd', 'UTC'))
    selectors = ['date', *FEATURES]
    def request(start, end):
        for attempt in range(3):
            try:
                images = collection.filterDate(str(start), str(end))
                table = ee.FeatureCollection(images.toList(images.size()).map(daily))
                url = table.getDownloadURL(filetype='CSV', selectors=selectors)
                with urlopen(url, timeout=180) as response:
                    rows = list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
                if len(rows) != (end - start).days or len({row['date'] for row in rows}) != len(rows):
                    raise ValueError('Unexpected or duplicate weather dates')
                if any(not row[name] for row in rows for name in FEATURES):
                    raise ValueError('An ERA5 predictor is missing')
                print(f'Extracted {start} to {end}', flush=True)
                return sorted(rows, key=lambda row: row['date'])
            except Exception as error:
                print(f'Retry weather {start}: {type(error).__name__}: {str(error)[:180]}', flush=True)
                if attempt == 2:
                    raise
                time.sleep(attempt + 2)
    receipt_path = output / 'download_receipt.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
        'collection': cfg['collection'], 'units_and_conversions': FEATURES, 'time_standard': 'UTC',
        'catchment_sha256': hashlib.sha256(polygon_path.read_bytes()).hexdigest(), 'area_km2': area, 'files': []}
    verified = {item['year']: item for item in receipt['files']}
    for year in range(cfg['start_year'], cfg['end_year'] + 1):
        target = weather / f'{year}.csv'
        if target.exists():
            if year not in verified or hashlib.sha256(target.read_bytes()).hexdigest() != verified[year]['sha256']:
                raise ValueError('Raw weather file differs from its receipt')
            continue
        start, limit = date(year, 1, 1), date(year + 1, 1, 1)
        chunks = []
        while start < limit:
            end = min(limit, start + timedelta(days=cfg['chunk_days']))
            chunks.append((start, end)); start = end
        with ThreadPoolExecutor(max_workers=cfg['workers']) as pool:
            rows = [row for result in pool.map(lambda bounds: request(*bounds), chunks) for row in result]
        with target.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=selectors); writer.writeheader(); writer.writerows(rows)
        receipt['files'].append({'year': year, 'days': len(rows), 'path': str(target.resolve()),
                                  'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        receipt['retrieved_at_utc'] = datetime.now(timezone.utc).isoformat()
        receipt['hydroatlas_sha256'] = hashlib.sha256(static_path.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        print(f'Saved {year}: {len(rows)} daily records, 14 variables', flush=True)


if __name__ == '__main__':
    main()
