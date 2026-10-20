"""Export an existing wet river and floodplain from a completed HEC-RAS solve.

Uses the unmodified official USACE Muncie model. No point sources, channel
carving, river buffers or invented velocity fields are used by this exporter.
"""
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import h5py
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.warp import reproject
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUN = ROOT/'tools/hec_ras/runs/muncie_trial'
RAS = ROOT/'tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe'
RESULT = HERE/'white-river-initialized.h5'
OUT = ROOT/'frontend/public/river-channel-flow'
FT = 1200/3937


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reconstruct_velocity(nodes, centres, faces, velocities):
    """Length-weighted least-squares vector from native signed face normals.

    Face node ordering in this mesh yields a right normal from left to right
    cell. Reversal of both normal and signed face speed leaves the vector intact.
    This is a derived cell vector, not a new hydraulic solve or subcell velocity.
    """
    a, b = nodes[faces[:, 2]], nodes[faces[:, 3]]
    normals = np.column_stack((b[:, 1]-a[:, 1], a[:, 0]-b[:, 0]))
    lengths = np.linalg.norm(normals, axis=1)
    normals /= lengths[:, None]
    interior = (faces[:, 0]>=0) & (faces[:, 1]>=0)
    if not np.all(np.sum(normals[interior]*(centres[faces[interior, 1]]-centres[faces[interior, 0]]), axis=1)>0):
        raise ValueError('Unsupported face orientation')
    count = len(centres)
    aa, ab, bb = [np.zeros(count) for _ in range(3)]
    bx, by = [np.zeros((len(velocities), count)) for _ in range(2)]
    for side in (0, 1):
        ids = faces[:, side]
        keep = ids>=0
        ids, normal, weight = ids[keep], normals[keep], lengths[keep]
        np.add.at(aa, ids, weight*normal[:, 0]**2)
        np.add.at(ab, ids, weight*normal[:, 0]*normal[:, 1])
        np.add.at(bb, ids, weight*normal[:, 1]**2)
        for t, speed in enumerate(velocities):
            np.add.at(bx[t], ids, weight*normal[:, 0]*speed[keep])
            np.add.at(by[t], ids, weight*normal[:, 1]*speed[keep])
    det = aa*bb-ab*ab
    if (det <= 0).any():
        raise ValueError('Degenerate cell normal reconstruction')
    return (bx*bb-by*ab)/det, (by*aa-bx*ab)/det


def cell_polygons(nodes, centres, faces, project):
    links = [set() for _ in centres]
    for left, right, u, v in faces:
        for cell in (left, right):
            if cell>=0:
                links[cell].update((int(u), int(v)))
    result = []
    for index, linked in enumerate(links):
        points = nodes[list(linked)]
        delta = points-centres[index]
        points = points[np.argsort(np.arctan2(delta[:, 1], delta[:, 0]))]
        xx, yy = project.transform(points[:, 0], points[:, 1])
        polygon = Polygon(np.column_stack((xx, yy)))
        if not polygon.is_valid:
            raise ValueError('Invalid hydraulic cell geometry')
        result.append((polygon, index+1))
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    record = json.loads((ROOT/'models/hec_ras_2d/muncie-inputs.json').read_text())
    for relative, expected in record['source_files_sha256'].items():
        if relative == 'Geometries/Base Geometry.h5':
            continue  # HEC-RAS prepare adds hydraulic property tables.
        if digest(RUN/relative) != expected:
            raise ValueError(f'Official copied model changed: {relative}')
    if digest(RUN/'Plans/Base Plan/Base Plan.dwe.r2r.h5') != record['ready_to_run_sha256']:
        raise ValueError('Prepared model changed')
    initialization=json.loads((HERE/'initialization.json').read_text())
    if digest(RESULT)!=initialization['initialized_flood_result_sha256']:
        raise ValueError('Wet-channel flood result does not match initialization record')
    with h5py.File(RESULT) as f:
        if int(f['Results/Compute Summary'].attrs['Success']) != 1:
            raise ValueError('Native HEC-RAS solve did not complete successfully')
        mesh = f['Geometry/2D Flow Areas/Mesh']
        nodes, centres, faces = [mesh[n][:] for n in ('Node Coordinates', 'Cell Coordinates', 'Face Data')]
        group = f['Results/Output Blocks/Base Output/2D Flow Areas/Mesh']
        native_depth = group['Cell Depth'][:]
        face_velocity = group['Face Velocity'][:]
        volumes = group['DEBUG/CellVolume'][:].sum(axis=1)*FT**3
        hours = f['Results/Output Blocks/Base Output/Time'][:]*24
        if not np.isfinite(native_depth).all() or native_depth.min() < -1e-5 or not np.isfinite(face_velocity).all():
            raise ValueError('Invalid native solver quantities')
        initial_wet_cells = int(np.count_nonzero(f['Results/Initial Conditions/2D Flow Areas/Mesh/Cell Depth'][:]>=.1/FT))
        if initial_wet_cells < 500:
            raise ValueError('River must already contain water at the start')
        vx, vy = reconstruct_velocity(nodes, centres, faces, face_velocity)
        # Transform the native local-axis velocity to true east/north metres per second.
        merc = Transformer.from_crs(2965, 3857, always_xy=True)
        geo = Transformer.from_crs(2965, 4326, always_xy=True)
        cx, cy = merc.transform(centres[:, 0], centres[:, 1])
        xdx, ydx = merc.transform(centres[:, 0]+1, centres[:, 1])
        xdy, ydy = merc.transform(centres[:, 0], centres[:, 1]+1)
        _, lat = geo.transform(centres[:, 0], centres[:, 1])
        scale = np.cos(np.deg2rad(lat))
        east_velocity = (vx*(xdx-cx)+vy*(xdy-cx))*scale
        south_velocity = -(vx*(ydx-cy)+vy*(ydy-cy))*scale
        # Dry native cells have no meaningful reconstructed velocity.
        east_velocity[native_depth*FT<.1] = 0
        south_velocity[native_depth*FT<.1] = 0
        payload = f['Boundary Conditions/BC Lines/Payloads']
        definitions, values = payload['Time Series Definitions'][:], payload['Values'][:]
        flow = definitions[0]
        hydro = values[int(flow['Start (Value)']):int(flow['Start (Value)']+flow['Count'])]*FT**3
        boundary_group = f['Boundary Conditions/BC Lines']
        lines = boundary_group['Polyline']
        boundaries = []
        for i, (start, count) in enumerate(zip(lines.attrs['Start'], lines.attrs['Count'])):
            points = lines[int(start):int(start+count)]
            lon, lat = geo.transform(points[:, 0], points[:, 1])
            boundaries.append({'kind': ['upstream', 'normal-depth', 'stage'][i],
                               'label': ['Upstream river inflow', 'Downstream normal-depth outlet', 'Downstream stage boundary'][i],
                               'coordinates': np.column_stack((lon, lat)).tolist()})
    metadata = json.loads((ROOT/'frontend/public/hec-ras-2d/muncie-results.json').read_text())
    w,n = metadata['bounds_lonlat'][0]
    e,s = metadata['bounds_lonlat'][2]
    to_merc = Transformer.from_crs(4326, 3857, always_xy=True)
    minx,miny = to_merc.transform(w,s)
    maxx,maxy = to_merc.transform(e,n)
    cols = 960
    rows = int(round(cols*(maxy-miny)/(maxx-minx)))
    transform = from_bounds(minx,miny,maxx,maxy,cols,rows)
    cell_ids = rasterize(cell_polygons(nodes, centres, faces, merc), out_shape=(rows,cols),transform=transform,fill=0,dtype='int32')-1
    grid_valid = cell_ids>=0
    scale = np.cos(np.deg2rad((n+s)/2))
    dx,dy = transform.a*scale,-transform.e*scale
    z = np.full((rows,cols), np.nan,dtype='float32')
    terrain_files = ['Terrain.TerrainWithChannel.muncie_clip.tif','Terrain.TerrainWithChannel.ChannelOnly.tif']
    for filename in terrain_files:
        path = RUN/'Terrains'/filename
        with rasterio.open(path) as raster:
            overlay = np.full(z.shape,np.nan,dtype='float32')
            reproject(rasterio.band(raster,1),overlay,src_transform=raster.transform,src_crs=raster.crs,src_nodata=raster.nodata,
                      dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.bilinear)
            z[np.isfinite(overlay)] = overlay[np.isfinite(overlay)]*FT
    terrain_valid = np.isfinite(z)
    slope_z = np.where(terrain_valid,z,np.nanmedian(z))
    gy,gx = np.gradient(slope_z,dy,dx)
    slope = np.rad2deg(np.arctan(np.hypot(gx,gy)))
    shade = np.clip(.65+(gx-gy)*.75,.2,1)
    rel = np.clip((slope_z-np.nanpercentile(z,2))/max(.1,np.nanpercentile(z,98)-np.nanpercentile(z,2)),0,1)
    rgb = np.stack(((65+rel*90)*shade,(95+rel*85)*shade,(84+rel*70)*shade),axis=-1).astype('uint8')
    rgba = np.concatenate([rgb,np.where(terrain_valid,255,0).astype('uint8')[...,None]],axis=-1)
    Image.fromarray(rgba).save(OUT/'terrain.png')
    frames, packed, initial_wet = [], [], None
    maps = HERE/'initialized-maps'
    maps.mkdir(exist_ok=True)
    for t,hour in enumerate(hours):
        path = maps/f'depth-{t:02d}.tif'
        command = [str(RAS),'result','map',str(RESULT),str(path),'--type','depth','--profile',str(t),
                   '--terrain',str(RUN/'Terrains/Terrain.h5'),'--projection','EPSG:2965','--cell-size','10','--force']
        result = subprocess.run(command,capture_output=True,text=True)
        if result.returncode or not path.exists():
            raise RuntimeError(f'Native terrain mapping failed: {result.stdout[-500:]} {result.stderr[-500:]}')
        depth = np.zeros((rows,cols),dtype='float32')
        with rasterio.open(path) as raster:
            reproject(rasterio.band(raster,1),depth,src_transform=raster.transform,src_crs=raster.crs,src_nodata=raster.nodata,
                      dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=0,resampling=Resampling.nearest)
        depth = np.maximum(depth*FT,0)
        depth[~grid_valid] = 0
        visible = depth>=.1
        if initial_wet is None:
            initial_wet = visible.copy()
        u,v = np.zeros_like(depth),np.zeros_like(depth)
        u[grid_valid] = east_velocity[t,cell_ids[grid_valid]]
        v[grid_valid] = south_velocity[t,cell_ids[grid_valid]]
        u[~visible]=0; v[~visible]=0
        speed = np.hypot(u,v)
        if depth.max()>=32.767 or np.abs(u).max()>=32.767 or np.abs(v).max()>=32.767:
            raise ValueError('Display packing range exceeded')
        packed.append(np.stack([np.rint(depth*1000),np.rint(u*1000),np.rint(v*1000)]).astype('<i2').tobytes())
        frames.append({'seconds':float(hour*3600),'inflow_m3s':float(hydro[t]),'volume_m3':float(volumes[t]),
                       'wet_area_km2':float(visible.sum()*dx*dy/1e6),'additional_wet_area_km2':float((visible&~initial_wet).sum()*dx*dy/1e6),
                       'max_depth_m':float(depth.max()),'max_speed_ms':float(speed.max())})
        print(f'Native profile {t+1}/{len(hours)}: wet {frames[-1]["wet_area_km2"]:.3f} km2',flush=True)
    raw = b''.join(packed)
    (OUT/'frames.bin.gz').write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))
    # A transparent model mask preserves NoData in inspection; these are never hydraulic inputs.
    elevation = np.where(terrain_valid,np.round(z.astype('float64'),3),-9999).ravel().tolist()
    slope_values = np.where(terrain_valid,np.round(slope.astype('float64'),3),-9999).ravel().tolist()
    meta = {'version':2,'sample':'White River · Muncie, Indiana, USA','study':'USACE Muncie 2025 example',
            'bounds':[w,s,e,n],'focus_bounds':[-85.401,40.190,-85.367,40.208], 'rows':rows,'cols':cols,
            'dx_m':dx,'dy_m':dy,'grid_crs':'EPSG:3857','duration_seconds':86400,'interval_seconds':3600,
            'depth_unit_m':.001,'velocity_unit_ms':.001,'wet_threshold_m':.1,'depth_color_max_m':4,
            'solver':'HEC-RAS 2025 Beta · CPU implicit diffusion-wave','hydraulic_cells':len(centres),
            'source_terrain_resolution_m':5*FT,'map_resolution_m':10*FT,
            'boundary_lines':boundaries,'boundaries':'Upstream flow hydrograph, downstream normal depth and stage; original USACE model inputs.',
            'hydrograph_seconds_m3s':[[float(h*3600),float(q)] for h,q in zip(hours,hydro)],
            'frames':frames,'elevation_m':elevation,'slope_degrees':slope_values,'terrain_nodata':-9999,
            'numerical_checks':{'solver_completed':True,'nonnegative_depth_passed':True,'source_verified':True,'initial_wet_cells':initial_wet_cells},
            'native_result_sha256':digest(RESULT),'frame_payload_sha256':hashlib.sha256(raw).hexdigest(),
            'initialization':initialization,
            'prepared_model_sha256':record['ready_to_run_sha256'],'source_manifest_url':record['source_manifest_url'],
            'method_url':'https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.4/viewing-2d-or-1d-2d-output-using-hec-ras-mapper/2d-output-file-hdf5-binary-file',
            'credit':'US Army Corps of Engineers, Hydrologic Engineering Center: official Muncie 2025 example model.',
            'limitations':['Demonstration in Indiana, USA; this is not Pakistan terrain or an NDMA flood forecast.',
                           'Sample boundary hydrographs are model inputs, not current river observations.',
                           'Detailed depth mapping uses the original channel terrain; map pixels do not increase hydraulic mesh resolution.',
                           'Particle vectors are reconstructed from signed native face velocities using weighted least squares and assigned by hydraulic cell.',
                           'Native hourly outputs are shown without interpolating new flood extents. Particle travel is accelerated for visibility.',
                           'Successful solver completion and finite output checks do not establish observed-event accuracy.']}
    (OUT/'results.json').write_text(json.dumps(meta,separators=(',',':'),allow_nan=False),encoding='utf-8')
    (HERE/'export-manifest.json').write_text(json.dumps({
        'solver_result':str(RESULT.relative_to(ROOT)),'solver_result_sha256':digest(RESULT),
        'source_record':'models/hec_ras_2d/muncie-inputs.json','prepared_model_sha256':record['ready_to_run_sha256'],
        'files':{p.name:digest(p) for p in OUT.iterdir() if p.is_file()},
        'native_depth_maps':{p.name:digest(p) for p in maps.glob('*.tif')},
        'checks':meta['numerical_checks']},indent=2),encoding='utf-8')
    print(json.dumps({'output':str(OUT),'grid':[rows,cols],'compressed_bytes':(OUT/'frames.bin.gz').stat().st_size,'initial_wet_cells':initial_wet_cells}))


if __name__=='__main__':
    main()
