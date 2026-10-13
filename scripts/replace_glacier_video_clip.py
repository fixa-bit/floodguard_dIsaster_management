from pathlib import Path
import json
import shutil
import subprocess

out=Path(__file__).resolve().parents[1]/'docs'/'portal-video'
shutil.copyfile(out/'glacier-clip.mp4',out/'clips'/'12.mp4')
path=out/'recording-manifest.json'
manifest=json.loads(path.read_text(encoding='utf-8'))
manifest['chapters'][11].update(source=str(out/'glacier-clip.mp4'),sourceStart=0,sourceEnd=12,caption="Inspect glacier coverage and upstream drainage, including glaciers that contribute to Pakistan's river basins.")
path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(out/'clips.txt'),'-c','copy',manifest['videoPath']],check=True)
print('Detailed glacier footage joined')
