"""Cache real Terrarium elevation tiles around four station viewpoints.

Source tiles are copied without modification. The manifest retains hashes and
the original public source; this is display terrain, not hydraulic input.
"""
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'frontend/public/station-terrain'
SOURCE='https://elevation-tiles-prod.s3.amazonaws.com/terrarium/'
STATIONS={'TARBELA':(72.7338,34.1059),'MANGLA':(73.645,33.142),'MARALA':(74.41125,32.660583),'TAUNSA':(70.836721,30.518528)}


def main():
    keys=set()
    for lon,lat in STATIONS.values():
        for zoom in range(14):
            n=2**zoom
            x=int((lon+180)/360*n)
            y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    if 0<=y+dy<n:keys.add((zoom,(x+dx)%n,y+dy))
    def fetch(key):
        z,x,y=key
        relative=f'{z}/{x}/{y}.png'
        path=OUT/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():raw=path.read_bytes()
        else:
            with urlopen(SOURCE+relative,timeout=45) as response:raw=response.read()
            Image.open(BytesIO(raw)).verify()
            path.write_bytes(raw)
        pixels=np.asarray(Image.open(BytesIO(raw)).convert('RGB'),dtype='float32')
        if pixels.shape!=(256,256,3):raise ValueError('Unexpected terrain tile')
        height=pixels[...,0]*256+pixels[...,1]+pixels[...,2]/256-32768
        return relative,{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                         'min_m':round(float(height.min()),2),'max_m':round(float(height.max()),2)}
    with ThreadPoolExecutor(max_workers=6) as pool:tiles=dict(pool.map(fetch,sorted(keys)))
    station_elevations={}
    for name,(lon,lat) in STATIONS.items():
        n=2**13
        x=(lon+180)/360*n
        y=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
        tile=Image.open(OUT/f'13/{int(x)}/{int(y)}.png').convert('RGB')
        r,g,b=tile.getpixel((int((x%1)*256),int((y%1)*256)))
        station_elevations[name]=round(r*256+g+b/256-32768,3)
    meta={'source':SOURCE+'{z}/{x}/{y}.png','source_url':'https://registry.opendata.aws/terrain-tiles/',
          'encoding':'terrarium','tile_size':256,'stations':STATIONS,'tiles':tiles,
          'station_elevations_m':station_elevations,
          'credit':'Terrain Tiles / Mapzen and contributing elevation providers; distributed through AWS Open Data.',
          'purpose':'Terrain visualization only; no change to flood-model elevations or monitoring readings.'}
    (OUT/'manifest.json').write_text(json.dumps(meta,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'tiles':len(tiles),'bytes':sum(v['bytes'] for v in tiles.values()),'stations':list(STATIONS)}))


if __name__=='__main__':main()
