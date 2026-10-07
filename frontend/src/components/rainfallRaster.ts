import { MercatorCoordinate } from "maplibre-gl";
import type { FeatureCollection, Geometry, Position } from "geojson";

export interface RainfallAnchor {
  longitude: number;
  latitude: number;
  value: number;
  weight: number;
}

const grid = { width: 169, height: 143, west: 60.55, east: 77.45, south: 23.15, north: 37.45 };
export const rainfallImageCoordinates: [[number, number], [number, number], [number, number], [number, number]] = [
  [grid.west, grid.north], [grid.east, grid.north], [grid.east, grid.south], [grid.west, grid.south],
];
const northwest = MercatorCoordinate.fromLngLat([grid.west, grid.north]);
const southeast = MercatorCoordinate.fromLngLat([grid.east, grid.south]);
const coverageMasks = new WeakMap<FeatureCollection, Uint8ClampedArray>();

function coverageMask(boundaries: FeatureCollection) {
  const cached = coverageMasks.get(boundaries);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = grid.width;
  canvas.height = grid.height;
  const context = canvas.getContext("2d")!;

  const drawPolygon = (rings: Position[][]) => {
    const path = new Path2D();
    for (const ring of rings) {
      ring.forEach(([longitude, latitude], index) => {
        const projected = MercatorCoordinate.fromLngLat([longitude, latitude]);
        const x = (projected.x - northwest.x) / (southeast.x - northwest.x) * grid.width;
        const y = (projected.y - northwest.y) / (southeast.y - northwest.y) * grid.height;
        if (index === 0) path.moveTo(x, y);
        else path.lineTo(x, y);
      });
      path.closePath();
    }
    context.fill(path, "evenodd");
  };
  const drawGeometry = (geometry: Geometry) => {
    if (geometry.type === "Polygon") drawPolygon(geometry.coordinates);
    else if (geometry.type === "MultiPolygon") geometry.coordinates.forEach(drawPolygon);
    else if (geometry.type === "GeometryCollection") geometry.geometries.forEach(drawGeometry);
  };
  boundaries.features.forEach((feature) => drawGeometry(feature.geometry));
  const mask = context.getImageData(0, 0, grid.width, grid.height).data;
  coverageMasks.set(boundaries, mask);
  return mask;
}

export function renderRainfallRaster(anchors: RainfallAnchor[], boundaries: FeatureCollection) {
  const validAnchors = anchors.filter((anchor) => [anchor.longitude, anchor.latitude, anchor.value, anchor.weight].every(Number.isFinite) && anchor.value >= 0 && anchor.weight > 0);
  const canvas = document.createElement("canvas");
  canvas.width = grid.width;
  canvas.height = grid.height;
  const context = canvas.getContext("2d")!;
  const pixels = context.createImageData(grid.width, grid.height);
  const mask = coverageMask(boundaries);
  const ramp = [
    { mm: 0, color: [34, 197, 94, 0] },
    { mm: 0.1, color: [34, 197, 94, 12] },
    { mm: 10, color: [253, 224, 71, 205] },
    { mm: 25, color: [249, 115, 22, 240] },
    { mm: 50, color: [239, 68, 68, 250] },
    { mm: 100, color: [127, 29, 29, 255] },
  ];
  let cellCount = 0;
  // Sample in Mercator space to keep the image aligned with MapLibre's raster projection.
  for (let row = 0; row < grid.height && validAnchors.length; row++) {
    const latitude = new MercatorCoordinate(northwest.x, northwest.y + (row + 0.5) / grid.height * (southeast.y - northwest.y)).toLngLat().lat;
    const longitudeScale = Math.cos(latitude * Math.PI / 180);
    for (let column = 0; column < grid.width; column++) {
      const offset = (row * grid.width + column) * 4;
      if (!mask[offset + 3]) continue;
      const longitude = grid.west + (column + 0.5) / grid.width * (grid.east - grid.west);
      let weighted = 0;
      let totalWeight = 0;
      let nearestDistance = Infinity;
      for (const anchor of validAnchors) {
        const distance = Math.hypot((longitude - anchor.longitude) * longitudeScale, latitude - anchor.latitude);
        if (distance >= 1.75) continue;
        nearestDistance = Math.min(nearestDistance, distance);
        const taper = (1 - distance / 1.75) ** 2;
        const weight = anchor.weight * taper / Math.max(distance, 0.18) ** 2;
        weighted += anchor.value * weight;
        totalWeight += weight;
      }
      if (!totalWeight) continue;
      const rainfall = weighted / totalWeight;
      if (rainfall < 0.05) continue;
      const upperIndex = ramp.findIndex((stop) => stop.mm >= rainfall);
      const upper = ramp[upperIndex < 0 ? ramp.length - 1 : upperIndex];
      const lower = ramp[Math.max(0, upperIndex < 0 ? ramp.length - 1 : upperIndex - 1)];
      const fraction = upper.mm === lower.mm ? 0 : (rainfall - lower.mm) / (upper.mm - lower.mm);
      for (let channel = 0; channel < 3; channel++) pixels.data[offset + channel] = Math.round(lower.color[channel] + (upper.color[channel] - lower.color[channel]) * fraction);
      const alpha = lower.color[3] + (upper.color[3] - lower.color[3]) * fraction;
      const support = Math.min(1, (1.75 - nearestDistance) / 0.35);
      pixels.data[offset + 3] = Math.round(alpha * support * mask[offset + 3] / 255);
      if (pixels.data[offset + 3]) cellCount++;
    }
  }
  context.putImageData(pixels, 0, 0);
  return { imageUrl: canvas.toDataURL("image/png"), cellCount };
}
