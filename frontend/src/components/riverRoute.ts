import type { FeatureCollection, Position } from "geojson";

// The rivers as one connected network, so the monitoring tour can fly from one
// station to the next along the water. The river lines (OpenStreetMap
// waterways, one feature per river, often in many parts) are simplified, every
// part's ends are joined to the nearest river point close by (which links the
// parts of one river and each tributary to the river it flows into), and a
// route is the shortest way between two stations along that network.

/** A point in Web Mercator units (0 to 1 across the world). */
export type MercatorPoint = [number, number];
export const toMercator = (longitude: number, latitude: number): MercatorPoint =>
  [(longitude + 180) / 360, (1 - Math.asinh(Math.tan(latitude * Math.PI / 180)) / Math.PI) / 2];
export const fromMercator = ([x, y]: MercatorPoint): [number, number] =>
  [x * 360 - 180, Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI];

/** One kilometre in Mercator units around Pakistan's latitudes (about 30°N). */
const kilometre = 1 / (40_075 * Math.cos(30 * Math.PI / 180));
const simplifyTolerance = 0.08 * kilometre;   // finer bends than this do not show from the tour's height
const joinDistance = 6 * kilometre;   // a part's end this close to another river point is joined to it
const snapDistance = 12 * kilometre;  // a station this close to the network starts its route there

type Network = { points: MercatorPoint[]; links: Array<Array<[node: number, length: number]>>; grid: Map<string, number[]> };

const distance = (a: MercatorPoint, b: MercatorPoint) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** Douglas-Peucker, iterative. */
function simplify(points: MercatorPoint[], tolerance: number) {
  if (points.length < 3) return points;
  const keep = new Uint8Array(points.length);
  keep[0] = keep[points.length - 1] = 1;
  const stack: Array<[number, number]> = [[0, points.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop()!;
    const [ax, ay] = points[first], [bx, by] = points[last], length = Math.hypot(bx - ax, by - ay) || 1e-12;
    let farthest = -1, farthestDistance = tolerance;
    for (let index = first + 1; index < last; index++) {
      const [px, py] = points[index];
      const offset = Math.abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length;
      if (offset > farthestDistance) { farthest = index; farthestDistance = offset; }
    }
    if (farthest > 0) { keep[farthest] = 1; stack.push([first, farthest], [farthest, last]); }
  }
  return points.filter((_, index) => keep[index]);
}

const cellOf = ([x, y]: MercatorPoint) => `${Math.floor(x / joinDistance)}/${Math.floor(y / joinDistance)}`;

/** The nearest network point within `limit` of `point` (other than those `skip` rejects), or -1. */
function nearest(network: Network, point: MercatorPoint, limit: number, skip?: (node: number) => boolean) {
  const reach = Math.ceil(limit / joinDistance), cx = Math.floor(point[0] / joinDistance), cy = Math.floor(point[1] / joinDistance);
  let best = -1, bestDistance = limit;
  for (let dx = -reach; dx <= reach; dx++) for (let dy = -reach; dy <= reach; dy++) {
    for (const node of network.grid.get(`${cx + dx}/${cy + dy}`) ?? []) {
      if (skip?.(node)) continue;
      const gap = distance(point, network.points[node]);
      if (gap < bestDistance) { best = node; bestDistance = gap; }
    }
  }
  return best;
}

/** Builds the network from the river line features. */
export function riverNetwork(lines: FeatureCollection): Network {
  const network: Network = { points: [], links: [], grid: new Map() };
  const parts: Array<[first: number, last: number]> = [];
  for (const feature of lines.features) {
    const geometry = feature.geometry;
    const lineParts: Position[][] = geometry?.type === "LineString" ? [geometry.coordinates]
      : geometry?.type === "MultiLineString" ? geometry.coordinates : [];
    for (const line of lineParts) {
      const points = simplify(line.map(([longitude, latitude]) => toMercator(longitude, latitude)), simplifyTolerance);
      if (points.length < 2) continue;
      const first = network.points.length;
      points.forEach((point, index) => {
        const node = network.points.length;
        network.points.push(point);
        network.links.push([]);
        const cell = cellOf(point);
        network.grid.set(cell, [...(network.grid.get(cell) ?? []), node]);
        if (index) {
          const length = distance(points[index - 1], point);
          network.links[node - 1].push([node, length]);
          network.links[node].push([node - 1, length]);
        }
      });
      parts.push([first, network.points.length - 1]);
    }
  }
  // Join each part's ends to the nearest point of any other part close by.
  for (const [first, last] of parts) {
    for (const end of [first, last]) {
      const other = nearest(network, network.points[end], joinDistance, (node) => node >= first && node <= last);
      if (other < 0) continue;
      const length = distance(network.points[end], network.points[other]);
      network.links[end].push([other, length]);
      network.links[other].push([end, length]);
    }
  }
  return network;
}

/**
 * The river course from `from` to `to` (longitude, latitude), in Mercator units,
 * starting and ending at the two points themselves; null when either point is
 * not near the network or the network does not connect them.
 */
export function riverCourse(network: Network, from: [number, number], to: [number, number]) {
  const start = toMercator(...from), end = toMercator(...to);
  const source = nearest(network, start, snapDistance), target = nearest(network, end, snapDistance);
  if (source < 0 || target < 0) return null;
  // Dijkstra with a binary heap.
  const count = network.points.length, best = new Float64Array(count).fill(Infinity), previous = new Int32Array(count).fill(-1);
  const heap: Array<[number, number]> = [[0, source]];
  best[source] = 0;
  const push = (item: [number, number]) => {
    heap.push(item);
    for (let index = heap.length - 1; index > 0;) {
      const parent = (index - 1) >> 1;
      if (heap[parent][0] <= heap[index][0]) break;
      [heap[parent], heap[index]] = [heap[index], heap[parent]];
      index = parent;
    }
  };
  const pop = () => {
    const top = heap[0], last = heap.pop()!;
    if (heap.length) {
      heap[0] = last;
      for (let index = 0; ;) {
        const left = index * 2 + 1, right = left + 1;
        let smallest = index;
        if (left < heap.length && heap[left][0] < heap[smallest][0]) smallest = left;
        if (right < heap.length && heap[right][0] < heap[smallest][0]) smallest = right;
        if (smallest === index) break;
        [heap[smallest], heap[index]] = [heap[index], heap[smallest]];
        index = smallest;
      }
    }
    return top;
  };
  while (heap.length) {
    const [cost, node] = pop();
    if (node === target) break;
    if (cost > best[node]) continue;
    for (const [next, length] of network.links[node]) {
      if (cost + length < best[next]) { best[next] = cost + length; previous[next] = node; push([cost + length, next]); }
    }
  }
  if (!Number.isFinite(best[target])) return null;
  const course: MercatorPoint[] = [end];
  for (let node = target; node >= 0; node = previous[node]) course.push(network.points[node]);
  course.push(start);
  return course.reverse();
}

/** Total length of a polyline, in Mercator units. */
export function courseLength(points: MercatorPoint[]) {
  let length = 0;
  for (let index = 1; index < points.length; index++) length += distance(points[index - 1], points[index]);
  return length;
}

/**
 * The polyline resampled to `count` evenly spaced points and smoothed with a
 * Gaussian of `sigma` (Mercator units) that fades out towards the two ends, so
 * the smooth line still starts and ends exactly at the stations.
 */
export function smoothCourse(points: MercatorPoint[], count: number, sigma: number): MercatorPoint[] {
  const total = courseLength(points), step = total / (count - 1), even: MercatorPoint[] = [];
  let segment = 1, travelled = 0;
  for (let index = 0; index < count; index++) {
    const along = Math.min(total, index * step);
    while (segment < points.length - 1 && travelled + distance(points[segment - 1], points[segment]) < along) {
      travelled += distance(points[segment - 1], points[segment]);
      segment++;
    }
    const length = distance(points[segment - 1], points[segment]) || 1e-12, t = Math.min(1, Math.max(0, (along - travelled) / length));
    even.push([points[segment - 1][0] + (points[segment][0] - points[segment - 1][0]) * t, points[segment - 1][1] + (points[segment][1] - points[segment - 1][1]) * t]);
  }
  if (sigma <= 0 || total === 0) return even;
  const radius = Math.max(1, Math.round(sigma / step));
  return even.map((point, index) => {
    // Near the ends the window narrows, down to the end point itself.
    const reach = Math.min(radius * 3, index, count - 1 - index);
    if (!reach) return point;
    let x = 0, y = 0, weight = 0;
    for (let offset = -reach; offset <= reach; offset++) {
      const w = Math.exp(-(offset * offset) / (2 * radius * radius));
      x += even[index + offset][0] * w; y += even[index + offset][1] * w; weight += w;
    }
    return [x / weight, y / weight];
  });
}
