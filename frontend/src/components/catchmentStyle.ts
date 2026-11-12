import { bbox } from "@turf/bbox";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import type { Feature, FeatureCollection, MultiPolygon, Polygon, Position } from "geojson";
import type { ExpressionSpecification, FillLayerSpecification, LineLayerSpecification, SymbolLayerSpecification } from "maplibre-gl";

// Catchment styling. The selected station's catchment is spotlit (the map
// outside it dims), outlined with a glowing edge and named inside like a map
// region. The all-basins layer outlines each basin with a glow in its own colour.

const signedArea = (ring: Position[]) => ring.reduce((sum, [x, y], index) => {
  const [nextX, nextY] = ring[(index + 1) % ring.length];
  return sum + (x * nextY - nextX * y);
}, 0) / 2;

/** A world-sized polygon with the catchment cut out, used to dim everything outside it. */
export function catchmentSpotlight(catchment: Feature<Polygon | MultiPolygon>): FeatureCollection {
  const world: Position[] = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];   // counter-clockwise
  const outlines = catchment.geometry.type === "Polygon"
    ? [catchment.geometry.coordinates[0]]
    : catchment.geometry.coordinates.map((polygon) => polygon[0]);
  // Holes must wind the opposite way to the outer ring.
  const holes = outlines.map((ring) => signedArea(ring) > 0 ? [...ring].reverse() : ring);
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [world, ...holes] } }] };
}

/**
 * Where to write the catchment's name: the middle of its bounding box, or the
 * point inside the catchment nearest that middle when the shape is irregular.
 */
export function catchmentLabelPoint(catchment: Feature<Polygon | MultiPolygon>): FeatureCollection {
  const [west, south, east, north] = bbox(catchment);
  const middle: [number, number] = [(west + east) / 2, (south + north) / 2];
  let point = middle;
  if (!booleanPointInPolygon(middle, catchment)) {
    let nearest = Infinity;
    for (let i = 1; i < 12; i++) for (let j = 1; j < 12; j++) {
      const candidate: [number, number] = [west + (east - west) * i / 12, south + (north - south) * j / 12];
      const distance = Math.hypot(candidate[0] - middle[0], candidate[1] - middle[1]);
      if (distance < nearest && booleanPointInPolygon(candidate, catchment)) { point = candidate; nearest = distance; }
    }
  }
  return { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: point },
    properties: { name: catchment.properties?.name, area_km2: catchment.properties?.area_km2 } }] };
}

const byZoom = (atZoom5: number, atZoom9: number): ExpressionSpecification => ["interpolate", ["linear"], ["zoom"], 5, atZoom5, 9, atZoom9];

// The selected station's catchment.
export const catchmentSpotlightPaint: FillLayerSpecification["paint"] = { "fill-color": "#01090b", "fill-opacity": 0.34, "fill-antialias": false };
export const activeCatchmentFillPaint: FillLayerSpecification["paint"] = { "fill-color": "#22d3b5", "fill-opacity": 0.06 };
export const activeCatchmentGlowPaint: LineLayerSpecification["paint"] = {
  "line-color": "#46f2cf", "line-width": byZoom(12, 22), "line-blur": byZoom(9, 15), "line-opacity": 0.5,
};
export const activeCatchmentCasingPaint: LineLayerSpecification["paint"] = { "line-color": "#03191d", "line-width": byZoom(4, 6.5), "line-opacity": 0.75 };
export const activeCatchmentLinePaint: LineLayerSpecification["paint"] = { "line-color": "#a6ffe9", "line-width": byZoom(1.8, 3), "line-opacity": 1 };
/** "SUB-BASIN 1734" with "69,087 km² catchment" beneath, written inside the catchment like a region name. */
export const activeCatchmentLabel: Pick<SymbolLayerSpecification, "layout" | "paint"> = {
  layout: {
    "text-field": ["format",
      ["upcase", ["get", "name"]], { "font-scale": 1 }, "\n", {},
      ["concat", ["number-format", ["get", "area_km2"], { "max-fraction-digits": 0 }], " km² catchment"], { "font-scale": 0.7 }],
    "text-font": ["Open Sans Semibold"], "text-size": byZoom(13, 17), "text-letter-spacing": 0.24, "text-line-height": 1.5,
    "text-max-width": 16, "text-padding": 6,
  },
  paint: { "text-color": "#c4fff1", "text-opacity": 0.85, "text-halo-color": "#03191d", "text-halo-width": 1.8, "text-halo-blur": 0.6 },
};

// The "Catchment areas" layer: every basin in its own colour.
const basinZoom = (atZoom3: number, atZoom7: number, atZoom10: number): ExpressionSpecification =>
  ["interpolate", ["linear"], ["zoom"], 3, atZoom3, 7, atZoom7, 10, atZoom10];
export const catchmentAreaFillPaint: FillLayerSpecification["paint"] = { "fill-color": ["get", "map_color"], "fill-opacity": 0.2 };
export const catchmentAreaGlowPaint: LineLayerSpecification["paint"] = {
  "line-color": ["get", "map_color"], "line-width": basinZoom(5, 10, 16), "line-blur": basinZoom(4, 8, 12), "line-opacity": 0.55,
};
export const catchmentAreaLinePaint: LineLayerSpecification["paint"] = {
  "line-color": "#eafcff", "line-width": basinZoom(0.9, 1.6, 2.4), "line-opacity": 0.8,
};
export const catchmentAreaLabel: Pick<SymbolLayerSpecification, "layout" | "paint"> = {
  layout: {
    "text-field": ["upcase", ["get", "name"]], "text-font": ["Open Sans Semibold"], "text-size": basinZoom(9, 11.5, 13),
    "text-letter-spacing": 0.18, "text-max-width": 8, "text-allow-overlap": false, "text-padding": 4,
  },
  paint: { "text-color": "#eafcff", "text-halo-color": "#04161b", "text-halo-width": 1.5, "text-opacity": 0.92 },
};
