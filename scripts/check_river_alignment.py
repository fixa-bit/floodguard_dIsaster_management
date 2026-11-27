"""How far are the app's river lines from real water? (Checks app/gis/data/pakistan_osm_waterways.geojson.)

Reference: JRC Global Surface Water occurrence 1984-2021 (Pekel et al. 2016, free tiles), zoom 12
(~32 m pixels). A point every 500 m along each river line (Pakistan + Kashmir window) is measured
to the nearest pixel that is water at least `--threshold` % of the time.

    python scripts/check_river_alignment.py                   # water seen at least 1% of the time (any flooding since 1984)
    python scripts/check_river_alignment.py --threshold 25    # regularly wet channels only

Lines that follow the real channel measure ~15-20 m (half a pixel). Stretches more than 500 m off are
listed; "[straight jump in the data]" marks a gap in the geometry (as the Indus had south of Taunsa).
Dry riverbeds (lower Ravi/Sutlej) only show as water with a low threshold; thin mountain streams
(< 30 m wide) can be missed by the reference. Tiles are cached in .local-cache/jrc-occurrence.
"""
import argparse
import io
import json
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

Z = 12
N = 2 ** Z
URL = "https://storage.googleapis.com/global-surface-water/tiles2021/occurrence/{z}/{x}/{y}.png"
WINDOW = 110  # pixels each side (~3.5 km)
REGION = (66.0, 23.5, 75.8, 36.4)  # lon/lat box: Pakistan and Kashmir


def km(a, b):
    r = math.pi / 180
    h = math.sin((b[1] - a[1]) * r / 2) ** 2 + math.cos(a[1] * r) * math.cos(b[1] * r) * math.sin((b[0] - a[0]) * r / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def global_pixel(lon, lat):
    x = (lon + 180) / 360 * N * 256
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * N * 256
    return x, y


def densify(line, step_km=0.5):
    out = [line[0]]
    for a, b in zip(line, line[1:]):
        d = km(a, b)
        n = max(1, int(d / step_km))
        for i in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, d > 2.5))
    return [(p[0], p[1], p[2] if len(p) > 2 else False) for p in out]


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("waterways", nargs="?", default=str(root / "app" / "gis" / "data" / "pakistan_osm_waterways.geojson"))
    ap.add_argument("cache", nargs="?", default=str(root / ".local-cache" / "jrc-occurrence"))
    ap.add_argument("--threshold", type=float, default=1)
    ap.add_argument("--json")
    args = ap.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    alpha_min = args.threshold / 100 * 255

    rivers = json.load(open(args.waterways, encoding="utf-8"))["features"]
    samples = {}
    for f in rivers:
        g = f["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        pts = []
        for part_index, part in enumerate(parts):
            for lon, lat, straight in densify(part):
                if REGION[0] <= lon <= REGION[2] and REGION[1] <= lat <= REGION[3]:
                    pts.append((lon, lat, straight, part_index))
        samples[f["properties"]["name"]] = pts

    tiles = set()
    for pts in samples.values():
        for lon, lat, *_ in pts:
            gx, gy = global_pixel(lon, lat)
            for dx in (-WINDOW, WINDOW):
                for dy in (-WINDOW, WINDOW):
                    tiles.add((int((gx + dx) // 256), int((gy + dy) // 256)))
            tiles.add((int(gx // 256), int(gy // 256)))

    def fetch(t):
        path = cache / f"{Z}_{t[0]}_{t[1]}.png"
        if path.exists():
            return
        for attempt in range(3):
            try:
                data = urllib.request.urlopen(urllib.request.Request(URL.format(z=Z, x=t[0], y=t[1]), headers={"User-Agent": "floodguard-river-check"}), timeout=60).read()
                path.write_bytes(data)
                return
            except Exception as error:
                if "404" in str(error):
                    path.write_bytes(b"")  # no water data: an empty (all-dry) tile
                    return
        print("failed", t, file=sys.stderr)

    print(f"{sum(len(p) for p in samples.values())} sample points, {len(tiles)} tiles", flush=True)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fetch, sorted(tiles)))

    masks = {}

    def mask(t):
        if t not in masks:
            path = cache / f"{Z}_{t[0]}_{t[1]}.png"
            if not path.exists() or path.stat().st_size == 0:
                masks[t] = np.zeros((256, 256), bool)
            else:
                masks[t] = np.asarray(Image.open(path).convert("RGBA"))[:, :, 3] >= alpha_min
        return masks[t]

    report = {}
    for name, pts in samples.items():
        dists = []
        for lon, lat, straight, part in pts:
            gx, gy = global_pixel(lon, lat)
            x0, y0 = int(gx) - WINDOW, int(gy) - WINDOW
            size = 2 * WINDOW + 1
            win = np.zeros((size, size), bool)
            for ty in range(y0 // 256, (y0 + size) // 256 + 1):
                for tx in range(x0 // 256, (x0 + size) // 256 + 1):
                    m = mask((tx, ty))
                    ax0, ay0 = max(x0, tx * 256), max(y0, ty * 256)
                    ax1, ay1 = min(x0 + size, tx * 256 + 256), min(y0 + size, ty * 256 + 256)
                    win[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = m[ay0 - ty * 256:ay1 - ty * 256, ax0 - tx * 256:ax1 - tx * 256]
            ys, xs = np.nonzero(win)
            meters_per_px = 156543.03392 * math.cos(math.radians(lat)) / N
            if len(xs):
                d = np.sqrt((xs - (gx - x0)) ** 2 + (ys - (gy - y0)) ** 2).min() * meters_per_px
            else:
                d = float("inf")
            dists.append((lon, lat, d, straight))
        arr = np.array([d for _, _, d, _ in dists])
        finite = np.where(np.isinf(arr), 9999, arr)
        # Stretches more than 500 m from water, at least 1.5 km long
        stretches, run = [], []
        for item in dists + [(0, 0, 0, False)]:
            if item[2] > 500:
                run.append(item)
            else:
                if len(run) >= 3:
                    stretches.append({"from": [round(run[0][1], 4), round(run[0][0], 4)], "to": [round(run[-1][1], 4), round(run[-1][0], 4)],
                                      "length_km": round(len(run) * 0.5, 1), "max_m": round(max(r[2] for r in run)) if all(math.isfinite(r[2]) for r in run) else ">3500",
                                      "on_straight_jump": any(r[3] for r in run)})
                run = []
        report[name] = {
            "points": len(arr), "median_m": round(float(np.median(finite))), "p90_m": round(float(np.percentile(finite, 90))),
            "p95_m": round(float(np.percentile(finite, 95))),
            "over_250m_pct": round(float((arr > 250).mean() * 100), 1), "over_500m_pct": round(float((arr > 500).mean() * 100), 1),
            "over_1km_pct": round(float((arr > 1000).mean() * 100), 1),
            "stretches": sorted(stretches, key=lambda s: -s["length_km"]),
        }
    for name, r in report.items():
        print(f"\n{name}: {r['points']} pts  median {r['median_m']} m  p90 {r['p90_m']} m  p95 {r['p95_m']} m  >250m {r['over_250m_pct']}%  >500m {r['over_500m_pct']}%  >1km {r['over_1km_pct']}%")
        for s in r["stretches"][:8]:
            print(f"   {s['length_km']:5.1f} km off (max {s['max_m']} m) from {s['from']} to {s['to']}{'  [straight jump in the data]' if s['on_straight_jump'] else ''}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
