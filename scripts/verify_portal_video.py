from pathlib import Path
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

out=Path(__file__).resolve().parents[1]/'docs'/'portal-video'
video=out/'FloodGuard_Portal_Walkthrough.mp4'
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',str(video)]))
stream=next(s for s in probe['streams'] if s['codec_type']=='video')
assert stream['codec_name']=='h264'
assert (stream['width'],stream['height'])==(1920,1080)
assert stream['r_frame_rate']=='30/1'
assert abs(float(probe['format']['duration'])-345)<.1
assert len(probe['chapters'])==35
subtitles=(out/'FloodGuard_Portal_Walkthrough.srt').read_text(encoding='utf-8')
assert subtitles.count(' --> ')==35
print('Metadata passed: 5:45, 1080p, H.264, 30 fps, 35 chapters and captions',flush=True)
subprocess.run(['ffmpeg','-v','error','-i',str(video),'-map','0:v:0','-f','null','-'],check=True)
print('Full video decoded without errors',flush=True)
def preview(t):
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(video),'-frames:v','1',str(out/f'final-preview-{t}.png')],check=True)
with ThreadPoolExecutor(max_workers=2) as executor:list(executor.map(preview,[3,121,184,276,315]))
result={'duration_seconds':float(probe['format']['duration']),'width':stream['width'],'height':stream['height'],'fps':stream['r_frame_rate'],'codec':stream['codec_name'],'chapters':len(probe['chapters']),'caption_entries':35,'full_decode':'passed','file_size_bytes':video.stat().st_size}
(out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)
