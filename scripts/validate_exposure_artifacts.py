"""Check saved exposure layers against their summary without recalculating exposure."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fiona
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.prepared import prep

from app.gis.exposure_engine import DatasetBundle, GEOD, timestamp, write_json
from app.services.exposure_service import ExposureService


def validate(region, analysis_id):
    service = ExposureService()
    bundle = DatasetBundle(service.root, region)
    # Reuse the API's UUID, region and completion checks before reading a path.
    summary_path = service.artifact(region, analysis_id)
    folder = summary_path.parent
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    with fiona.open(folder / 'flood_extent.geojson') as source:
        water = unary_union([shape(feature['geometry']) for feature in source])
    # A sub-millimetre tolerance accommodates coordinates serialized to GeoJSON.
    boundary = prep(bundle.aoi.buffer(1e-9))
    flooded = prep(water.buffer(1e-9))
    report = {'checked_at': timestamp(), 'region': region, 'analysis_id': analysis_id,
              'tolerance_degrees': 1e-9, 'layers': {}, 'status': 'PASSED'}
    for name, expected in summary['infrastructure'].items():
        path = folder / (name + '.geojson')
        count = invalid = outside = duplicates = wrong_labels = 0
        identities = set()
        road_length = 0.
        with fiona.open(path) as source:
            for feature in source:
                count += 1
                geometry = shape(feature['geometry'])
                properties = dict(feature['properties'])
                invalid += int(geometry.is_empty or not geometry.is_valid)
                outside += int(not boundary.covers(geometry) or not flooded.covers(geometry))
                identity = properties.get('exposure_id')
                duplicates += int(identity is None or identity in identities)
                identities.add(identity)
                wrong_labels += int(properties.get('is_sample') != summary['flood']['is_sample']
                                    or properties.get('flood_kind') != summary['flood']['kind'])
                if name == 'roads':
                    road_length += abs(GEOD.geometry_length(geometry)) / 1000
        checks = {'feature_count': count, 'expected_count': expected['affected_count'],
                  'invalid_geometries': invalid, 'outside_flood_or_region': outside,
                  'duplicate_or_missing_ids': duplicates, 'incorrect_source_labels': wrong_labels}
        failed = count != expected['affected_count'] or any((invalid, outside, duplicates, wrong_labels))
        if name == 'roads':
            checks['recomputed_length_km'] = road_length
            checks['length_matches_summary'] = math.isclose(road_length, expected['affected_length_km'], rel_tol=1e-9, abs_tol=1e-7)
            failed |= not checks['length_matches_summary']
        checks['status'] = 'FAILED' if failed else 'PASSED'
        report['layers'][name] = checks
        if failed:
            report['status'] = 'FAILED'
    write_json(folder / 'artifact_validation.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', required=True)
    parser.add_argument('--analysis-id', required=True)
    arguments = parser.parse_args()
    result = validate(arguments.region, arguments.analysis_id)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'PASSED' else 1)
