"""Population fixtures are synthetic; operational inventories remain read-only."""
import json
import time
from types import SimpleNamespace

import fiona
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from test_exposure import exposure_data
from app.core.exceptions import AppError
from app.gis.exposure_engine import DatasetBundle, polygon_extent
from app.gis.population_analysis import administrative_units, analyze_population, segmentation_flood


def boundaries(pilot, geometries, ids=None, layer='ADM2'):
    path=pilot/'boundaries/boundaries.gpkg'; path.parent.mkdir(exist_ok=True)
    with fiona.open(path,'w',driver='GPKG',layer=layer,crs='EPSG:4326',
                    schema={'geometry':'Polygon','properties':{'shapeID':'str','shapeName':'str'}}) as target:
        for i,g in enumerate(geometries):
            target.write({'geometry':mapping(g),'properties':{'shapeID':ids[i] if ids else str(i),'shapeName':f'Synthetic region {i}'}})


def test_fractional_admin_totals_distribution_and_no_double_count(exposure_data):
    root,pilot,aoi=exposure_data
    boundaries(pilot,[box(0,0,.5,2),box(.5,0,2,2)])
    bundle=DatasetBundle(root,'fixture'); levels,notes=administrative_units(bundle)
    flood=polygon_extent({'type':'FeatureCollection','features':[{'type':'Feature','geometry':mapping(box(0,0,.75,2))},{'type':'Feature','geometry':mapping(box(.25,0,.5,2))}]})
    before=bundle.paths['population'].read_bytes()
    result,admin,checks,histogram,_,grid=analyze_population(bundle.paths['population'],aoi,flood,levels,2)
    assert result['known_population_total']==pytest.approx(60)
    assert result['estimated_exposed_population']==pytest.approx(30)
    assert result['percentage_exposed_of_known_population']==pytest.approx(50)
    assert admin['ADM2'][0]['known_population_total']==pytest.approx(20)
    assert admin['ADM2'][0]['estimated_exposed_population']==pytest.approx(20)
    assert admin['ADM2'][1]['estimated_exposed_population']==pytest.approx(10)
    assert checks['ADM2']['unassigned_exposed_population']==pytest.approx(0,abs=1e-7)
    assert sum(r['exposed_population'] for r in histogram)==pytest.approx(30)
    assert sum(f['properties']['exposed_population'] for f in grid)==pytest.approx(30)
    assert bundle.paths['population'].read_bytes()==before
    assert any('ADM3' in note for note in notes)


def test_unknown_empty_partial_aoi_and_administrative_gaps(exposure_data):
    root,pilot,aoi=exposure_data
    boundaries(pilot,[box(0,0,.5,2)])
    levels,_=administrative_units(DatasetBundle(root,'fixture'))
    path=pilot/'population/population_2025.tif'
    result,_,checks,*_=analyze_population(path,aoi,box(0,0,.75,2),levels)
    assert checks['ADM2']['unassigned_exposed_population']==pytest.approx(10)
    result,*_=analyze_population(path,box(.5,0,2,2),box(.5,0,.75,2),{})
    assert result['known_population_total']==pytest.approx(40)
    assert result['estimated_exposed_population']==pytest.approx(10)
    result,*_=analyze_population(path,aoi,box(1.1,.1,1.9,.9),{})
    assert result['estimated_exposed_population'] is None
    assert result['status']=='UNKNOWN'
    result,*_=analyze_population(path,aoi,box(5,5,6,6),{})
    assert result['estimated_exposed_population']==0
    assert result['percentage_exposed_of_known_population']==0


def test_overlapping_boundaries_block_and_same_id_dissolves(exposure_data):
    root,pilot,_=exposure_data
    boundaries(pilot,[box(0,0,1.5,2),box(.5,0,2,2)])
    with pytest.raises(AppError,match='overlap'):
        administrative_units(DatasetBundle(root,'fixture'))
    (pilot/'boundaries/boundaries.gpkg').unlink()
    boundaries(pilot,[box(0,0,1.5,2),box(.5,0,2,2)],ids=['same','same'])
    levels,_=administrative_units(DatasetBundle(root,'fixture'))
    assert len(levels['ADM2'])==1
    assert levels['ADM2'][0]['geometry'].area==4


def test_segmentation_crs_nodata_and_binary_labels(exposure_data):
    root,pilot,_=exposure_data
    path=pilot/'test_segmentation.tif'
    with rasterio.open(path,'w',driver='GTiff',crs=4326,count=1,width=2,height=2,dtype='uint8',nodata=255,transform=from_origin(0,2,1,1)) as source:
        source.write(np.array([[1,0],[0,255]],dtype='uint8'),1)
    bundle=DatasetBundle(root,'fixture')
    bundle.configuration['population_analysis']={'segmentation':{'path':str(path.relative_to(root)),'flood_values':[1]}}
    water,provenance=segmentation_flood(bundle)
    assert water.equals(box(0,1,1,2))
    assert provenance['kind']=='segmentation_output'
    assert provenance['is_sample'] is False
    bundle.configuration['population_analysis']['segmentation']['path']='../outside.tif'
    with pytest.raises(AppError):
        segmentation_flood(bundle)


def test_population_api_jobs_artifacts_and_missing_boundaries(client,exposure_data,tmp_path,monkeypatch):
    import app.services.exposure_service as module
    root,pilot,_=exposure_data
    boundaries(pilot,[box(0,0,2,2)])
    monkeypatch.setattr(module,'get_settings',lambda:SimpleNamespace(exposure_dataset_root=str(root),exposure_output_root=str(tmp_path/'results')))
    assert client.get('/api/v1/population/regions/fixture/latest').json() is None
    payload={'region':'fixture','flood_source':'provided','flood_extent':mapping(box(0,0,.75,2))}
    response=client.post('/api/v1/population/analyses',json=payload)
    assert response.status_code==202,response.text
    job=response.json()
    for _ in range(300):
        state=client.get(job['status_url']).json()
        if state['status'] in ('COMPLETED','FAILED'): break
        time.sleep(.02)
    assert state['status']=='COMPLETED',state
    summary=client.get(state['summary_url']).json()
    assert summary['population']['estimated_exposed_population']==pytest.approx(30)
    assert summary['administrative_availability']['ADM3']=='UNAVAILABLE'
    assert client.get('/api/v1/population/regions/fixture/latest').json()['analysis_id']==job['analysis_id']
    for url in summary['layers'].values():
        layer=client.get(url)
        assert layer.status_code==200
        assert layer.json()['metadata']['flood_kind']=='user_provided_unverified'
    assert client.get(state['summary_url']+'/layers/not-a-layer').status_code==404
    (pilot/'boundaries/boundaries.gpkg').unlink()
    response=client.post('/api/v1/population/analyses',json={'region':'fixture','flood_source':'sample'})
    for _ in range(300):
        state=client.get(response.json()['status_url']).json()
        if state['status'] in ('COMPLETED','FAILED'): break
        time.sleep(.02)
    assert state['status']=='FAILED'
    assert state['error']['code']=='MISSING_BOUNDARIES'
    boundaries(pilot,[box(0,0,2,2)])
    response=client.post('/api/v1/population/analyses',json={'region':'fixture','flood_source':'sample'})
    for _ in range(300):
        state=client.get(response.json()['status_url']).json()
        if state['status'] in ('COMPLETED','FAILED'): break
        time.sleep(.02)
    assert state['status']=='COMPLETED',state
    sample=client.get(state['summary_url']).json()
    assert sample['flood']['is_sample'] is True
    assert sample['flood']['kind']=='synthetic_sample'
    for url in sample['layers'].values():
        data=client.get(url).json()
        assert data['metadata']['is_sample'] is True
        assert all(feature['properties']['is_sample'] for feature in data['features'])
