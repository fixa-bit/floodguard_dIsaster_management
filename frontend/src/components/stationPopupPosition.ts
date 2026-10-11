export interface Rect { left: number; top: number; right: number; bottom: number }
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

// Search free vertical spans at each candidate x; this also handles narrow screens with tall overlays.
export function stationPopupPosition(point: { x: number; y: number }, bounds: Rect, obstacles: Rect[], width: number, wantedHeight: number) {
  const xs = [point.x - width / 2, point.x + 18, point.x - width - 18, bounds.left, bounds.right - width,
    ...obstacles.flatMap((rect) => [rect.right + 8, rect.left - width - 8])];
  let best: { left: number; top: number; maxHeight: number; score: number } | undefined;
  for (const candidate of xs) {
    const left = clamp(candidate, bounds.left, bounds.right - width);
    const blocked = obstacles.filter((rect) => rect.right + 8 > left && rect.left - 8 < left + width)
      .map((rect) => [Math.max(bounds.top, rect.top - 8), Math.min(bounds.bottom, rect.bottom + 8)])
      .filter(([top, bottom]) => bottom > top).sort((a, b) => a[0] - b[0]);
    let start = bounds.top;
    const spans: number[][] = [];
    for (const [top, bottom] of blocked) { if (top > start) spans.push([start, top]); start = Math.max(start, bottom); }
    if (start < bounds.bottom) spans.push([start, bounds.bottom]);
    for (const [top, bottom] of spans) {
      const heights = [Math.min(wantedHeight, bottom - top)];
      if (point.x >= left - 12 && point.x <= left + width + 12) heights.push(Math.min(wantedHeight, bottom - top, point.y - top - 18), Math.min(wantedHeight, bottom - top, bottom - point.y - 18));
      for (const maxHeight of heights) {
        if (maxHeight < 100) continue;
        for (const preferred of [point.y - maxHeight - 18, point.y + 18, point.y - maxHeight / 2]) {
          const y = clamp(preferred, top, bottom - maxHeight);
          const distance = Math.hypot(Math.max(left - point.x, 0, point.x - left - width), Math.max(y - point.y, 0, point.y - y - maxHeight));
          const coversPoint = point.x >= left - 12 && point.x <= left + width + 12 && point.y >= y - 12 && point.y <= y + maxHeight + 12;
          const score = distance + (wantedHeight - maxHeight) * 3 + (coversPoint ? 1000 : 0);
          if (!best || score < best.score) best = { left, top: y, maxHeight, score };
        }
      }
    }
  }
  return best;
}
