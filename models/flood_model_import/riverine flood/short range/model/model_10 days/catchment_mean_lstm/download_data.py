"""Extract actual elevation-band weather/snow from native ERA5-Land grids."""
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
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.request import urlopen


def read_settings(path):
    path = Path(path).resolve()
    settings = json.loads(path.read_text())
    settings['_root'] = path.parent
    return settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('extraction.json')))
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    settings = read_settings(args.config)
    root = settings['_root']
    import ee
    ee.Initialize(project=settings['earth_engine_project'])
    output = root / settings['raw_directory']
    output.mkdir(parents=True, exist_ok=True)
    catchment = (root / settings['catchment_file']).resolve()
    document = json.loads(catchment.read_text())
    polygon = ee.FeatureCollection(document).geometry()
    region = polygon.bounds().buffer(20000).bounds()
    collection = ee.ImageCollection(settings['weather_collection'])
    reference = ee.Image(collection.filterDate('2020-01-01', '2020-01-02').first())
    projection = reference.select('temperature_2m').projection()
    dem = ee.Image(settings['dem_image']).select('dem')
    inside = ee.Image.constant(1).clip(polygon).unmask(0).reproject(dem.projection())
    edges = settings['elevation_edges_m']
    masks = [dem.lt(edges[0]), dem.gte(edges[0]).And(dem.lt(edges[1])),
             dem.gte(edges[1]).And(dem.lte(edges[2])), dem.gt(edges[2])]
    weights = []
    for index, mask in enumerate(masks):
        indicator = mask.And(inside).unmask(0).setDefaultProjection(dem.projection())
        # Fraction of each native weather cell occupied by this band and catchment.
        fraction = indicator.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=65536).reproject(projection)
        area = fraction.multiply(ee.Image.pixelArea().reproject(projection)).rename(f'b{index}_area_m2')
        # Convert fractional masks to explicit weights once. updateMask later
        # must not accidentally replace boundary fractions with ones.
        area = area.multiply(area.mask()).unmask(0).updateMask(ee.Image.constant(1))
        weights.append(area)
    weight_image = ee.Image.cat(weights)
    reduction = dict(reducer=ee.Reducer.sum(), geometry=region, crs=projection,
                     scale=projection.nominalScale(), maxPixels=1000000, tileScale=4)
    area_totals = weight_image.reduceRegion(**reduction).getInfo()
    total_area = sum(area_totals.values())
    geometric_area = polygon.area(1).getInfo()
    if any(value <= 0 for value in area_totals.values()) or abs(total_area / geometric_area - 1) > .02:
        raise ValueError('Elevation masks do not cover the catchment within 2% raster tolerance')
    metadata = {'catchment_file': str(catchment), 'catchment_sha256': hashlib.sha256(catchment.read_bytes()).hexdigest(),
                'weather_collection': settings['weather_collection'], 'weather_projection': projection.getInfo(),
                'dem_image': settings['dem_image'], 'dem_projection': dem.projection().getInfo(),
                'method': 'MERIT elevation/catchment indicators averaged to native ERA5-Land cells, multiplied by native cell area; weather weighted by resulting band areas',
                'area_totals_m2': area_totals, 'area_fractions': [area_totals[f'b{i}_area_m2'] / total_area for i in range(4)],
                'raster_catchment_area_km2': total_area / 1e6, 'geometric_catchment_area_km2': geometric_area / 1e6,
                'elevation_edges_m': edges, 'bands': ['<1500', '1500-<3000', '3000-4500', '>4500']}
    manifest = output / 'band_metadata.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        stable = ['catchment_sha256', 'weather_collection', 'weather_projection', 'dem_image', 'dem_projection', 'elevation_edges_m']
        if any(saved[key] != metadata[key] for key in stable) or any(abs(saved['area_totals_m2'][key] / value - 1) > 1e-5 for key, value in area_totals.items()):
            raise ValueError('Extraction metadata changed; choose a new raw directory')
        metadata = saved
        area_totals = saved['area_totals_m2']
    else:
        manifest.write_text(json.dumps(metadata, indent=2) + '\n')
    print('Elevation bands:', json.dumps(metadata['area_fractions']), 'area km2:', total_area / 1e6, flush=True)
    variables = ['precipitation_mm', 'temperature_c', 'swe_mm', 'snowmelt_mm']
    names = [f'b{i}_{v}' for i in range(4) for v in variables]
    selectors = ['date'] + names + [f'b{i}_coverage_fraction' for i in range(4)]

    def daily(item):
        image = ee.Image(item)
        weather = ee.Image.cat([image.select('total_precipitation_sum').multiply(1000),
                                image.select('temperature_2m').subtract(273.15),
                                image.select('snow_depth_water_equivalent').multiply(1000),
                                image.select('snowmelt_sum').multiply(1000)]).rename(variables)
        valid = weather.mask().reduce(ee.Reducer.min())
        images = []
        for band in range(4):
            images.append(weather.multiply(weights[band]).rename([f'b{band}_{v}' for v in variables]))
            images.append(weights[band].multiply(valid).rename(f'b{band}_valid_area'))
        sums = ee.Image.cat(images).reduceRegion(**reduction)
        properties = {'date': image.date().format('YYYY-MM-dd', 'UTC')}
        for band in range(4):
            total = area_totals[f'b{band}_area_m2']
            coverage = ee.Number(sums.get(f'b{band}_valid_area')).divide(total)
            properties[f'b{band}_coverage_fraction'] = coverage
            for variable in variables:
                key = f'b{band}_{variable}'
                complete = coverage.gte(.9999).And(coverage.lte(1.0001))
                properties[key] = ee.Algorithms.If(complete, ee.Number(sums.get(key)).divide(total), None)
        return ee.Feature(None, properties)

    def request(start, end):
        for attempt in range(2):
            try:
                selected = collection.filterDate(str(start), str(end))
                table = ee.FeatureCollection(selected.toList(selected.size()).map(daily))
                url = table.getDownloadURL(filetype='CSV', selectors=selectors)
                with urlopen(url, timeout=240) as response:
                    rows = list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
                expected = (end - start).days
                if len(rows) != expected or len({row['date'] for row in rows}) != expected:
                    raise ValueError('Incomplete or duplicate daily weather dates')
                if any(not row[name] for row in rows for name in names):
                    raise ValueError('Weather export contains incomplete band coverage')
                return sorted(rows, key=lambda row: row['date'])
            except Exception as error:
                print(f'Extract {start}..{end}: {type(error).__name__}: {str(error)[:220]}', flush=True)
                if attempt == 0:
                    time.sleep(2)
        if (end - start).days <= 14:
            raise RuntimeError('Earth Engine extraction failed for the minimum chunk')
        middle = start + timedelta(days=(end - start).days // 2)
        return request(start, middle) + request(middle, end)

    if args.probe:
        start = date(settings['start_year'], 1, 1)
        rows = request(start, start + timedelta(days=3))
        print(json.dumps(rows[0], indent=2), flush=True)
        return
    receipt_file = output / 'download_receipt.json'
    receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else {'files': []}
    known = {row['path']: row for row in receipt['files']}
    for year in range(settings['start_year'], settings['end_year'] + 1):
        target = output / f'{year}.csv'
        if target.exists():
            record = known.get(str(target.resolve()))
            if record is None or hashlib.sha256(target.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('Existing raw weather file lacks a matching receipt')
            continue
        chunks = []
        start = date(year, 1, 1)
        year_end = date(year + 1, 1, 1)
        while start < year_end:
            end = min(year_end, start + timedelta(days=settings.get('request_chunk_days', 92)))
            chunks.append((start, end))
            start = end
        def fetch_chunk(bounds):
            chunk = request(*bounds)
            print(f'Extracted {bounds[0]} to {bounds[1]}', flush=True)
            return chunk
        with ThreadPoolExecutor(max_workers=settings.get('max_workers', 1)) as pool:
            rows = [row for result in pool.map(fetch_chunk, chunks) for row in result]
        with target.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=selectors)
            writer.writeheader(); writer.writerows(rows)
        receipt['files'].append({'path': str(target.resolve()), 'year': year, 'days': len(rows),
                                  'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        receipt['collection'] = settings['weather_collection']
        receipt['metadata_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        receipt['retrieved_at_utc'] = datetime.now(timezone.utc).isoformat()
        receipt_file.write_text(json.dumps(receipt, indent=2) + '\n')
        print(f'Saved {year}: {len(rows)} days x 4 actual elevation-band records', flush=True)


if __name__ == '__main__':
    main()
