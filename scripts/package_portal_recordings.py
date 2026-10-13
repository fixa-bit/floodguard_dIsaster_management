"""Locate completed browser views in captured footage and join concise recorded clips."""
from pathlib import Path
import json
import subprocess
import sys
import shutil
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs'/'portal-video'
WIDTH,HEIGHT=160,80


def match_frames(source, folder, count):
    print(f'Finding {count} captured views in {source.name}',flush=True)
    command=['ffmpeg','-v','error','-threads','2','-i',str(source),'-vf',f'fps=1,scale={WIDTH}:{HEIGHT},format=gray','-f','rawvideo','pipe:1']
    result=subprocess.run(command,stdout=subprocess.PIPE,check=True)
    frames=np.frombuffer(result.stdout,dtype=np.uint8).reshape(-1,WIDTH*HEIGHT)
    matches=[]
    previous=-1
    for index in range(1,count+1):
        target=np.asarray(Image.open(folder/f'{index:02}.png').resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR).convert('L')).reshape(-1).astype(np.float32)
        scores=np.full(len(frames),np.inf)
        # Small batches keep memory use low even for long stalled captures.
        for start in range(previous+1,len(frames),100):
            batch=frames[start:start+100].astype(np.float32)
            scores[start:start+len(batch)]=np.square(batch-target).mean(axis=1)
        best=int(np.argmin(scores))
        if not np.isfinite(scores[best]):raise RuntimeError(f'No ordered frame match for {folder.name}/{index:02}')
        matches.append(float(best));previous=best
        print(f'  {index:02}: {best}s, image difference {scores[best]:.2f}',flush=True)
    return matches


def main():
    preflight=json.loads((OUT/'preflight-manifest.json').read_text(encoding='utf-8'))
    first=OUT/'raw'/'completed-first-sections.mkv'
    cache=OUT/'first-frame-matches.json'
    first_times=json.loads(cache.read_text()) if cache.exists() else match_frames(first,OUT/'frames',12)
    cache.write_text(json.dumps(first_times),encoding='utf-8')
    if '--first-only' in sys.argv:return
    rest=json.loads((OUT/'recording-rest-manifest.json').read_text(encoding='utf-8'))
    rest_source=Path(rest['videoPath'])
    rest_times=match_frames(rest_source,OUT/'frames-rest',len(rest['chapters']))
    scenes=[]
    for source,times,originals,lead in [(first,first_times,preflight['chapters'][:12],6),(rest_source,rest_times,rest['chapters'],14)]:
        previous=max(0,times[0]-lead)
        for match,chapter in zip(times,originals):
            end=match+0.8
            start=previous
            # Retain a browser-recorded action/view excerpt; omit long processing stalls.
            if end-start>18:start=end-14
            scenes.append({**chapter,'source':str(source),'sourceStart':max(0,start),'sourceEnd':end})
            previous=end
    clips=OUT/'clips';clips.mkdir(exist_ok=True)
    cumulative=0
    chapters=[]
    for index,scene in enumerate(scenes):
        source_length=scene['sourceEnd']-scene['sourceStart']
        target=min(12.0,max(8.0,source_length))
        rate=source_length/target
        destination=clips/f'{index+1:02}.mp4'
        if index==11 and (OUT/'glacier-clip.mp4').exists():
            shutil.copyfile(OUT/'glacier-clip.mp4',destination)
            scene.update(source=str(OUT/'glacier-clip.mp4'),sourceStart=0,sourceEnd=12,caption="Inspect glacier coverage and upstream drainage, including glaciers that contribute to Pakistan's river basins.")
            target=12
            chapters.append({**scene,'start':cumulative,'end':cumulative+target});cumulative+=target
            continue
        command=['ffmpeg','-v','error','-y','-ss',str(scene['sourceStart']),'-i',scene['source'],'-t',str(source_length),'-vf',f'setpts=(PTS-STARTPTS)/{rate:.8f},fps=30','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','4','-an',str(destination)]
        # Duration is measured after the retime filter, so use target for the output limit.
        command[command.index('-t')+1]=str(target)
        print(f'Packaging scene {index+1}/{len(scenes)}: {scene["title"]}',flush=True)
        subprocess.run(command,check=True)
        chapters.append({**scene,'start':cumulative,'end':cumulative+target})
        cumulative+=target
    (OUT/'clips.txt').write_text(''.join(f"file 'clips/{i+1:02}.mp4'\n" for i in range(len(scenes))),encoding='utf-8')
    combined=OUT/'raw'/'joined-browser-capture.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(OUT/'clips.txt'),'-c','copy',str(combined)],check=True)
    manifest={**rest,'videoPath':str(combined),'trimStartSeconds':0,'durationSeconds':cumulative,'chapters':chapters,'captureMethod':'Joined excerpts from actual browser recordings; processing stalls omitted','validation':{'fullPreflightBrowserErrors':preflight['browserErrors'],'resumedRecordingBrowserErrors':rest['browserErrors'],'firstFootage':'Completed views recovered and visually checked after the recording controller stalled'},'frameMatches':{'first':first_times,'rest':rest_times}}
    (OUT/'recording-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Joined recording: {cumulative:.1f}s, {len(chapters)} sections',flush=True)


if __name__=='__main__':main()
