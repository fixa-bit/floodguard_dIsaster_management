"""Package the real Playwright browser recording as an MP4 with captions and chapters."""
from pathlib import Path
import json
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "portal-video"


def ass_time(seconds):
    centiseconds = round(seconds * 100)
    return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02}:{centiseconds // 100 % 60:02}.{centiseconds % 100:02}"


def srt_time(seconds):
    milliseconds = round(seconds * 1000)
    return f"{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}"


def timestamp(seconds):
    return f"{int(seconds) // 60:02}:{int(seconds) % 60:02}"


def main():
    manifest = json.loads((OUT / "recording-manifest.json").read_text(encoding="utf-8"))
    captured_duration = manifest["durationSeconds"]
    # Shorten loading/action periods while retaining the final three seconds of each view.
    desired = [min(16.0, max(8.0, chapter["end"] - chapter["start"])) for chapter in manifest["chapters"]]
    factor = min(1.0, 345.0 / sum(desired))
    if sum(desired) * factor < 270.0:
        factor = 270.0 / sum(desired)
    chapters, timing = [], []
    duration = 0.0
    for original, length in zip(manifest["chapters"], desired):
        target = length * factor
        raw = original["end"] - original["start"]
        keep = min(3.0, raw / 2, target / 2)
        rate = (raw - keep) / (target - keep)
        boundary = original["end"] - keep
        expression = f"if(lt(T,{boundary:.6f}),{duration:.6f}+(T-{original['start']:.6f})/{rate:.8f},{duration+target-keep:.6f}+T-{boundary:.6f})"
        timing.append((original["end"], expression))
        chapters.append({**original, "start": duration, "end": duration + target})
        duration += target
    pts = timing[-1][1]
    for end, expression in reversed(timing[:-1]):
        pts = f"if(lt(T,{end:.6f}),{expression},{pts})"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1600
PlayResY: 900
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chapter,Segoe UI,17,&H00E9FFFF,&H00FFFFFF,&H00221D07,&H00221D07,-1,0,0,0,100,100,0,0,1,0,0,7,18,18,9,1
Style: Demo,Segoe UI,13,&H009EDDFF,&H00FFFFFF,&H00221D07,&H00221D07,0,0,0,0,100,100,0,0,1,0,0,9,18,18,12,1
Style: Caption,Segoe UI,20,&H00F4FFF6,&H00FFFFFF,&H00221D07,&H00221D07,0,0,0,0,100,100,0,0,1,0,0,2,28,28,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [f"Dialogue: 0,0:00:00.00,{ass_time(duration)},Demo,,0,0,0,,ILLUSTRATIVE DEMO  |  Small-dataset model assumption"]
    srt = []
    ffmetadata = [";FFMETADATA1", "title=FloodGuard AI - Portal Feature Walkthrough", "comment=Actual browser recording. Illustrative feeds; models assumed trained on small datasets. No new model training or validation is claimed."]
    lines = []
    for index, chapter in enumerate(chapters, 1):
        start, end = chapter["start"], chapter["end"]
        title = chapter["title"].split(" / ", 1)[-1]
        caption = chapter["caption"]
        wrapped = "\\N".join(textwrap.wrap(caption, width=145))
        events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Chapter,,0,0,0,,FLOODGUARD AI  /  {title}")
        events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{wrapped}")
        srt.append(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n" + "\n".join(textwrap.wrap(caption, width=85)) + "\n")
        ffmetadata.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(start*1000)}", f"END={round(end*1000)}", f"title={title}"])
        lines.append(f"- {timestamp(start)} — {title}")
    (OUT / "captions.ass").write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    (OUT / "FloodGuard_Portal_Walkthrough.srt").write_text("\n".join(srt), encoding="utf-8")
    (OUT / "chapters.ffmetadata").write_text("\n".join(ffmetadata) + "\n", encoding="utf-8")
    destination = OUT / "FloodGuard_Portal_Walkthrough.mp4"
    filters = f"setpts=PTS-STARTPTS,setpts='{pts}/TB',fps=30,pad=1600:900:0:40:color=0x071d22,subtitles=captions.ass,scale=1920:1080:flags=lanczos"
    command = ["ffmpeg", "-hide_banner", "-y", "-ss", str(manifest["trimStartSeconds"]), "-i", manifest["videoPath"], "-i", "chapters.ffmetadata", "-map", "0:v:0", "-map_metadata", "1", "-map_chapters", "1", "-t", str(duration), "-vf", filters, "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(destination)]
    print("Rendering captured portal browser frames into 1080p MP4...", flush=True)
    subprocess.run(command, cwd=OUT, check=True)
    notes = f"""# FloodGuard portal walkthrough

Deliverable: `FloodGuard_Portal_Walkthrough.mp4` — 1920 × 1080, 30 fps, {timestamp(duration)}, English on-screen captions, silent.
The video is a real browser recording of the existing React portal, with pointer movement, clicks, scrolling, form entry, and chart interaction. It is not a slideshow or an AI-generated video.
Loading and action periods are retimed per chapter to fit the requested 4–6 minute runtime; every section retains its final three seconds at normal speed for readability.

## Demo assumptions and data

The requested assumption is that the displayed models have been trained on small datasets. This project does not train additional models or claim validated accuracy. The existing forecast cards use the portal's bundled dummy forecast series. The visible operational risk engine remains the configured rule-based engine.

- Backend weather, city river values, national screening, and water geometry use the isolated backend's simulation mode.
- River geometry is generalized to 0.001 degrees in the browser-only demo feed to keep catchment clipping responsive; the portal's static district and boundary assets and station coordinates are unchanged.
- River monitoring/provider series, rainfall heatmap samples, Google integration markers, and the satellite water mask are explicitly illustrative browser fixtures. The satellite segment demonstrates the existing U-Net control using an illustrative mask; it does not execute the Sentinel-1 inference pipeline.
- Reports, priority flags, closure actions, monitoring simulation, saved alerts, linked incidents, and events run against a separate `demo.db`, using the portal's real backend endpoints.
- Population exposure displays the existing stored historical-reference analysis with its coverage limitations. The video inspects its controls and overlays without recomputing or replacing that analysis.
- This video does not assert access to an official Google Flood API, operational thresholds, successful training of planned models, or measured model accuracy.

## Chapters

{chr(10).join(lines)}

## Reproduction

1. Start the backend with `DATA_MODE=simulation`, `ENABLE_SIMULATION=true`, `ALLOW_RULE_BASED_FALLBACK=true`, `DATABASE_URL=sqlite:///D:/Projects/disaster_management/docs/portal-video/demo.db`, and `CORS_ORIGINS=http://127.0.0.1:3025`, on port 8025.
2. Start Vite on port 3025 with `VITE_API_BASE_URL=http://127.0.0.1:8025/api/v1`.
3. Existing `feed-*.json` files retain the recording session's base GIS geometry. From `frontend`, run `node scripts/record-portal-video.mjs`. Set `VIDEO_PREFLIGHT=1` for an abbreviated interaction check.
4. From the repository root, run `.venv/Scripts/python.exe scripts/render_portal_video.py`.

`recording-manifest.json` contains capture timing, chapter spans, downloads, and browser-error results. `demo-feed-provenance.json` describes demo feed sources. A separate SRT file is included for editable captions; the MP4 includes burned-in captions and embedded chapter markers.
"""
    (OUT / "README.md").write_text(notes, encoding="utf-8")
    print(f"Saved {destination} ({destination.stat().st_size / 1024**2:.1f} MiB)", flush=True)


if __name__ == "__main__":
    main()
