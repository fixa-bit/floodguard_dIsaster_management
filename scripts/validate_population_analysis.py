"""Independently verify persisted population totals, source labels and map geometries."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shapely.geometry import shape
from shapely.prepared import prep
from app.gis.exposure_engine import DatasetBundle, timestamp, write_json
from app.services.population_service import PopulationService


def validate(region, ident):
    service=PopulationService()
    summary=json.loads(service.artifact(region,ident).read_text(encoding='utf-8'))
    bundle=DatasetBundle(service.root,region)
    boundary=prep(bundle.aoi.buffer(1e-9))
    failures=[]; layers={}; grid_exposure=grid_total=0.
    for name in summary['layers']:
        data=json.loads(service.artifact(region,ident,name).read_text(encoding='utf-8'))
        invalid=outside=incorrect_labels=0
        for feature in data['features']:
            geometry=shape(feature['geometry']); props=feature['properties']
            invalid+=int(geometry.is_empty or not geometry.is_valid)
            outside+=int(not boundary.covers(geometry))
            incorrect_labels+=int(props.get('is_sample')!=summary['flood']['is_sample'] or props.get('flood_kind')!=summary['flood']['kind'])
            if name=='population_grid':
                grid_exposure+=props['exposed_population']; grid_total+=props['known_population']
        layers[name]={'feature_count':len(data['features']),'invalid_geometries':invalid,'outside_region':outside,'incorrect_labels':incorrect_labels}
        if invalid or outside or incorrect_labels:
            failures.append(name+' geometry/source validation failed')
    pop=summary['population']; exposure=pop['estimated_exposed_population']
    checks={'grid_known_population_matches':math.isclose(grid_total,pop['known_population_total'],rel_tol=1e-9,abs_tol=1e-6)}
    if exposure is not None:
        checks['grid_exposure_matches']=math.isclose(grid_exposure,exposure,rel_tol=1e-9,abs_tol=1e-6)
        checks['density_distribution_matches']=math.isclose(sum(r['exposed_population'] for r in summary['density_distribution']),exposure,rel_tol=1e-9,abs_tol=1e-6)
        for level,rows in summary['administrative'].items():
            allocated=math.fsum(r['estimated_exposed_population'] or 0 for r in rows)
            unassigned=summary['aggregation_checks'][level]['unassigned_exposed_population']
            checks[level+'_exposure_matches']=math.isclose(allocated+unassigned,exposure,rel_tol=1e-9,abs_tol=1e-6)
            checks[level+'_unique_ids']=len({r['id'] for r in rows})==len(rows)
    failures.extend(name for name,passed in checks.items() if not passed)
    report={'checked_at':timestamp(),'region':region,'analysis_id':ident,'status':'FAILED' if failures else 'PASSED',
            'checks':checks,'layers':layers,'failures':failures,'containment_tolerance_degrees':1e-9}
    write_json(service.folder(region,ident)/'validation.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',required=True)
    parser.add_argument('--analysis-id',required=True)
    args=parser.parse_args(); result=validate(args.region,args.analysis_id)
    print(json.dumps(result,indent=2))
    sys.exit(0 if result['status']=='PASSED' else 1)
