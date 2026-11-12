import type { FeatureCollection, Position } from "geojson";
import type { ExpressionSpecification, LineLayerSpecification, Map as MapLibreMap, SymbolLayerSpecification } from "maplibre-gl";

// "Living water" rivers: each river is drawn as a soft glow, a water-coloured
// body sized by the river's importance, a bright core, and light pulses that
// travel downstream. River geometry comes from OpenStreetMap waterways, which
// are drawn in the direction of flow, so moving along a line means downstream.

/** Relative channel width: the Indus widest, then its major tributaries. */
const riverRank: ExpressionSpecification = ["match", ["get", "name"],
  "Indus River", 1.45, "Chenab River", 1.15, "Jhelum River", 1.1, "Sutlej River", 1.05, "Kabul River", 1, "Ravi River", 0.9, 0.85];
const riverWidth = (atZoom4: number, atZoom8: number, atZoom12: number): ExpressionSpecification =>
  ["interpolate", ["linear"], ["zoom"], 4, ["*", atZoom4, riverRank], 8, ["*", atZoom8, riverRank], 12, ["*", atZoom12, riverRank]];

export const riverGlowPaint: LineLayerSpecification["paint"] = {
  "line-color": "#0ea5e9", "line-width": riverWidth(8, 15, 22), "line-blur": riverWidth(6, 11, 16), "line-opacity": 0.36,
};
export const riverBodyPaint: LineLayerSpecification["paint"] = {
  "line-color": "#26b8e4", "line-width": riverWidth(2.1, 4, 6.8), "line-opacity": 0.9,
};
export const riverCorePaint: LineLayerSpecification["paint"] = {
  "line-color": "#c2f1ff", "line-width": riverWidth(0.6, 1.1, 1.9), "line-blur": 0.6, "line-opacity": 0.6,
};
export const riverFlowPaint: LineLayerSpecification["paint"] = {
  "line-color": "#ffffff", "line-width": riverWidth(1.8, 3.2, 5.2), "line-blur": riverWidth(1.2, 2, 3), "line-opacity": 0.95,
  "line-dasharray": [3.2, 8.8],
};
/** Soft halo under the live status colours (normal / rising / flood keep their meaning). */
export const riverStatusGlowBlur: ExpressionSpecification = riverWidth(5, 9, 14);
export const riverLabelLayer: Pick<SymbolLayerSpecification, "layout" | "paint" | "minzoom"> = {
  minzoom: 4.5,
  layout: {
    // A single font: the glyph server cannot combine font stacks.
    "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Open Sans Italic"],
    "text-size": ["interpolate", ["linear"], ["zoom"], 5, 10.5, 9, 13], "text-letter-spacing": 0.12, "symbol-spacing": 420,
    "text-max-angle": 45, "text-offset": [0, -1.05],
  },
  paint: { "text-color": "#c4f2ff", "text-halo-color": "#062530", "text-halo-width": 1.6, "text-opacity": 0.92 },
};

/**
 * River lines thinned to a vertex every ~4 km, used only for the names: the
 * detailed channel bends too sharply for a label to follow it.
 */
export function riverLabelLines(lines: FeatureCollection): FeatureCollection {
  const thin = (coordinates: Position[]) => {
    const kept = [coordinates[0]];
    for (const point of coordinates) {
      const last = kept[kept.length - 1];
      if (Math.hypot(point[0] - last[0], point[1] - last[1]) >= 0.04) kept.push(point);
    }
    if (kept[kept.length - 1] !== coordinates[coordinates.length - 1]) kept.push(coordinates[coordinates.length - 1]);
    return kept;
  };
  return { type: "FeatureCollection", features: lines.features.map((feature) => {
    const geometry = feature.geometry;
    if (geometry.type === "LineString") return { ...feature, geometry: { type: "LineString", coordinates: thin(geometry.coordinates) } };
    if (geometry.type === "MultiLineString") return { ...feature, geometry: { type: "MultiLineString", coordinates: geometry.coordinates.filter((part) => part.length > 1).map(thin) } };
    return feature;
  }) };
}

// The monitored station's river: the same treatment, brighter and in the app's mint.
const activeWidth = (atZoom5: number, atZoom9: number): ExpressionSpecification => ["interpolate", ["linear"], ["zoom"], 5, atZoom5, 9, atZoom9];
export const activeRiverGlowPaint: LineLayerSpecification["paint"] = {
  "line-color": "#3ff0cf", "line-width": activeWidth(16, 28), "line-blur": activeWidth(10, 16), "line-opacity": 0.4,
};
export const activeRiverBodyPaint: LineLayerSpecification["paint"] = {
  "line-color": "#63ffe0", "line-width": activeWidth(3.4, 6), "line-opacity": 1,
};
export const activeRiverCorePaint: LineLayerSpecification["paint"] = {
  "line-color": "#f0fffb", "line-width": activeWidth(1.1, 2), "line-blur": 0.5, "line-opacity": 0.9,
};
export const activeRiverFlowPaint: LineLayerSpecification["paint"] = {
  "line-color": "#ffffff", "line-width": activeWidth(3, 5.2), "line-blur": activeWidth(1.4, 2.2), "line-opacity": 0.95,
  "line-dasharray": [3.4, 7.6],
};

/** Flow layers and their pulse pattern (dash and gap in line widths) and speed (pattern periods per second). */
const flowLayers = [
  { id: "water-lines-flow", dash: 3.2, gap: 8.8, periodsPerSecond: 0.7 },
  { id: "active-monitoring-river-flow", dash: 3.4, gap: 7.6, periodsPerSecond: 1 },
];
const steps = 24;

/** Dash array for a pattern started `phase` units into it (dash first, then gap). */
function dashAt(phase: number, dash: number, gap: number): number[] {
  return phase < dash ? [dash - phase, gap, phase, 0] : [0, dash + gap - phase, dash, phase - dash];
}

/**
 * Moves the flow layers' light pulses downstream (along each line's drawing
 * direction), about 12 steps a second, pausing while the camera moves or tiles
 * load. The pattern cycles through a fixed set of steps so the map reuses the
 * same few dash textures. Off for viewers who prefer reduced motion. Returns a
 * function that stops the animation.
 */
export function startRiverFlow(map: MapLibreMap) {
  if (!riverFlowEnabled) return () => {};
  const shown = new Map<string, number>();
  let frame = 0, last = 0;
  const tick = (now: number) => {
    frame = requestAnimationFrame(tick);
    if (now - last < 80) return;
    last = now;
    try {
      // Each step redraws the map, so never compete with a camera move or with tiles still loading.
      if (map.isMoving() || !map.areTilesLoaded()) return;
      for (const layer of flowLayers) {
        if (!map.getLayer(layer.id) || map.getLayoutProperty(layer.id, "visibility") === "none") continue;
        const step = Math.floor(now / 1000 * layer.periodsPerSecond * steps) % steps;
        if (shown.get(layer.id) === step) continue;
        shown.set(layer.id, step);
        // Counting the phase down moves the pulses toward the end of each line: downstream.
        const period = layer.dash + layer.gap;
        map.setPaintProperty(layer.id, "line-dasharray", dashAt(period * ((steps - step) % steps) / steps, layer.dash, layer.gap));
      }
    } catch {
      cancelAnimationFrame(frame);   // the map was removed
    }
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}

/** Flowing light is decorative motion: off for viewers who prefer reduced motion. */
export const riverFlowEnabled = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
