"""Run the same population engine outside HTTP for larger regional analyses."""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.gis.exposure_engine import timestamp, write_json
from app.schemas.population import PopulationRequest
from app.services.population_service import PopulationService

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',default='trimmu_jhang')
    parser.add_argument('--source',choices=['historical_reference','provided','segmentation','sample'],default='historical_reference')
    parser.add_argument('--flood-file',type=Path)
    parser.add_argument('--flood-crs',default='EPSG:4326')
    parser.add_argument('--grid-km',type=float,default=2)
    args=parser.parse_args()
    request=PopulationRequest(region=args.region,flood_source=args.source,grid_km=args.grid_km,flood_crs=args.flood_crs,
        flood_extent=json.loads(args.flood_file.read_text(encoding='utf-8')) if args.flood_file else None)
    service=PopulationService(); ident=str(uuid4()); folder=service.folder(args.region,ident)
    write_json(folder/'status.json',{'status':'RUNNING','analysis_id':ident,'started_at':timestamp()})
    try:
        result=service.calculate(request,ident)
        write_json(folder/'status.json',{'status':'COMPLETED','analysis_id':ident,'completed_at':timestamp()})
        print(json.dumps({'analysis_id':ident,'summary':str(folder/'summary.json'),'population':result['population'],'checks':result['aggregation_checks']},indent=2))
    except Exception as exc:
        write_json(folder/'status.json',{'status':'FAILED','analysis_id':ident,'error':str(exc)})
        raise
