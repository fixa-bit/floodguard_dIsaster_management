"""Run the same engine as the FastAPI exposure routes without an HTTP timeout."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.schemas.exposure import ExposureRequest
from app.services.exposure_service import ExposureService


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',default='trimmu_jhang')
    parser.add_argument('--data-root')
    parser.add_argument('--output-root')
    parser.add_argument('--source',choices=['historical_reference','sample','provided'],default='historical_reference')
    parser.add_argument('--flood-geojson',help='Required for provided source; never inferred from arbitrary local files')
    parser.add_argument('--flood-crs',default='EPSG:4326')
    parser.add_argument('--population-method',choices=['fractional_area','cell_center'],default='fractional_area')
    parser.add_argument('--without-reference-buildings',action='store_true')
    args=parser.parse_args()
    payload=json.loads(Path(args.flood_geojson).read_text(encoding='utf-8')) if args.flood_geojson else None
    request=ExposureRequest(region=args.region,flood_source=args.source,flood_extent=payload,flood_crs=args.flood_crs,
                            population_method=args.population_method,include_reference_buildings=not args.without_reference_buildings)
    service=ExposureService(args.data_root,args.output_root)
    print('Auditing source files and calculating exposure...',flush=True)
    result=service.analyze(request)
    print(json.dumps(result,indent=2,ensure_ascii=True),flush=True)
