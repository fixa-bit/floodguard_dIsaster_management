import { useEffect, useRef, type RefObject } from "react";
import type { LayerSpecification, Map, VisibilitySpecification } from "maplibre-gl";

export type MapBasemap = "satellite" | "vector";

const source = "vector-basemap";
const layers: LayerSpecification[] = [
  { id: "vector-land", type: "background", paint: { "background-color": "#efeee6" } },
  // Low-contrast relief gives mountain/basin context beneath the vector features.
  { id: "vector-relief", type: "raster", source: "vector-relief", paint: {
    "raster-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.38, 7, 0.24, 10, 0],
    "raster-saturation": -0.85, "raster-contrast": -0.15, "raster-fade-duration": 0,
  } },
  { id: "vector-landcover", type: "fill", source, "source-layer": "landcover", paint: {
    "fill-color": ["match", ["get", "class"], "wood", "#bdcdb4", "grass", "#d5ddbf", "sand", "#e6d9bc", "ice", "#f7faf8", "#dedfcf"],
    "fill-opacity": ["interpolate", ["linear"], ["zoom"], 3, 0.32, 9, 0.6],
  } },
  { id: "vector-parks", type: "fill", source, "source-layer": "park", paint: { "fill-color": "#c6d6b9", "fill-opacity": 0.4 } },
  { id: "vector-landuse", type: "fill", source, "source-layer": "landuse", minzoom: 5, paint: {
    "fill-color": ["match", ["get", "class"], "residential", "#d8d6cd", "industrial", "#d6d0ce", "farmland", "#e3e0c7", "#e2e0d4"],
    "fill-opacity": 0.45,
  } },
  { id: "vector-water", type: "fill", source, "source-layer": "water", paint: { "fill-color": "#afced9", "fill-outline-color": "#9bbfc9" } },
  { id: "vector-waterways", type: "line", source, "source-layer": "waterway", paint: {
    "line-color": "#78aebe", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.5, 7, 1, 12, 2.5],
  } },
  { id: "vector-neighbor-borders", type: "line", source, "source-layer": "boundary", filter: ["==", "admin_level", 2], paint: {
    "line-color": "#939b94", "line-opacity": 0.65, "line-dasharray": [3, 2],
    "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.7, 9, 1.4],
  } },
  { id: "vector-local-roads", type: "line", source, "source-layer": "transportation", minzoom: 9,
    filter: ["in", "class", "minor", "service", "tertiary", "secondary"], paint: {
      "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.5, 14, 2.5],
  } },
  { id: "vector-highways-casing", type: "line", source, "source-layer": "transportation", minzoom: 4,
    filter: ["in", "class", "motorway", "trunk", "primary"], layout: { "line-join": "round", "line-cap": "round" }, paint: {
      "line-color": "#c6b798", "line-opacity": 0.7,
      "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.7, 8, 2, 13, 5],
  } },
  { id: "vector-highways", type: "line", source, "source-layer": "transportation", minzoom: 4,
    filter: ["in", "class", "motorway", "trunk", "primary"], layout: { "line-join": "round", "line-cap": "round" }, paint: {
      "line-color": "#fff5d6", "line-opacity": 0.95,
      "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.3, 8, 1.1, 13, 3.5],
  } },
  { id: "vector-railways", type: "line", source, "source-layer": "transportation", minzoom: 7,
    filter: ["==", "class", "rail"], paint: { "line-color": "#969d99", "line-width": 0.7, "line-dasharray": [3, 3] },
  },
  { id: "vector-buildings", type: "fill", source, "source-layer": "building", minzoom: 13, paint: {
    "fill-color": "#d1cdc1", "fill-outline-color": "#c0bcae", "fill-opacity": 0.7,
  } },
  { id: "vector-river-names", type: "symbol", source, "source-layer": "waterway", minzoom: 6, layout: {
    "symbol-placement": "line", "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
    "text-font": ["Open Sans Italic"], "text-size": 11, "symbol-spacing": 350,
  }, paint: { "text-color": "#55879b", "text-halo-color": "#f4f5ef", "text-halo-width": 1.2 } },
  { id: "vector-countries", type: "symbol", source, "source-layer": "place", maxzoom: 7,
    filter: ["==", "class", "country"], layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-font": ["Open Sans Semibold"],
      "text-transform": "uppercase", "text-letter-spacing": 0.18,
      "text-size": ["interpolate", ["linear"], ["zoom"], 3, 11, 6, 16], "text-max-width": 10,
  }, paint: { "text-color": "#718078", "text-opacity": 0.75, "text-halo-color": "#f5f4ed", "text-halo-width": 1.5 } },
  { id: "vector-regions", type: "symbol", source, "source-layer": "place", minzoom: 5, maxzoom: 9,
    filter: ["in", "class", "state", "province"], layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-font": ["Open Sans Regular"],
      "text-transform": "uppercase", "text-letter-spacing": 0.12, "text-size": 10,
  }, paint: { "text-color": "#849086", "text-halo-color": "#f5f4ed", "text-halo-width": 1.2 } },
  { id: "vector-towns", type: "symbol", source, "source-layer": "place", minzoom: 7,
    filter: ["in", "class", "town", "village"], layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-font": ["Open Sans Regular"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 7, 10, 12, 12], "text-max-width": 8,
  }, paint: { "text-color": "#68716b", "text-halo-color": "#f8f7f0", "text-halo-width": 1.5 } },
  { id: "vector-city-dots", type: "circle", source, "source-layer": "place", filter: ["==", "class", "city"], paint: {
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1.5, 8, 3],
    "circle-color": "#62776d", "circle-stroke-color": "#fffdf5", "circle-stroke-width": 1,
  } },
  { id: "vector-places", type: "symbol", source, "source-layer": "place", filter: ["==", "class", "city"], layout: {
    "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
    "text-font": ["Open Sans Semibold"],
    "text-size": ["interpolate", ["linear"], ["zoom"], 3, 10, 6, 12, 10, 15],
    "text-max-width": 8, "text-anchor": "top", "text-offset": [0, 0.5],
  }, paint: { "text-color": "#394c45", "text-halo-color": "#fffdf5", "text-halo-width": 1.5 } },
];

export function useMapBasemap(mapRef: RefObject<Map | null>, basemap: MapBasemap) {
  const originalLayers = useRef<{ id: string; visibility: VisibilitySpecification }[] | null>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const update = () => {
      if (!map.getLayer("jammu-kashmir-context-fill")) return;
      if (!originalLayers.current) {
        const current = map.getStyle().layers;
        const firstOverlay = current.findIndex((layer) => layer.id === "jammu-kashmir-context-fill");
        originalLayers.current = current.slice(0, firstOverlay).map((layer) => ({
          id: layer.id, visibility: layer.layout?.visibility ?? "visible",
        }));
      }
      if (basemap === "vector" && !map.getSource(source)) {
        map.addSource("vector-relief", {
          type: "raster", tileSize: 256, maxzoom: 6,
          tiles: ["https://tiles.openfreemap.org/natural_earth/ne2sr/{z}/{x}/{y}.png"],
          attribution: '<a href="https://www.naturalearthdata.com/">Natural Earth</a>',
        });
        map.addSource(source, {
          type: "vector", url: "https://tiles.openfreemap.org/planet",
          attribution: '<a href="https://openfreemap.org/">OpenFreeMap</a> © <a href="https://openmaptiles.org/">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        });
        for (const layer of layers) map.addLayer(layer, "jammu-kashmir-context-fill");
      }
      for (const layer of originalLayers.current) {
        map.setLayoutProperty(layer.id, "visibility", basemap === "satellite" ? layer.visibility : "none");
      }
      for (const layer of layers) {
        if (map.getLayer(layer.id)) map.setLayoutProperty(layer.id, "visibility", basemap === "vector" ? "visible" : "none");
      }
      map.getContainer().dataset.basemap = basemap;
    };
    update();
    map.on("style.load", update);
    return () => { map.off("style.load", update); };
  }, [mapRef, basemap]);
}
