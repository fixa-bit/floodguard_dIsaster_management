import { useEffect, useMemo, useRef } from "react";
import { Popup, type GeoJSONSource, type Map as MapLibreMap, type MapLayerMouseEvent } from "maplibre-gl";
import { approximatePeople, type FloodExposurePreview } from "./outlookFloodExposureData";
import { cinematicPopulation } from "./simulationCinematicData";

const sceneLayers = ["simulation-scene-plinth", "simulation-scene-rim", "simulation-scene-river-glow", "simulation-scene-water", "simulation-scene-columns"];
const empty = { type: "FeatureCollection" as const, features: [] };

export function useSimulationCinematicScene({ maps, ready, active, data, level, layers, onInspect }: {
  maps: MapLibreMap[]; ready: boolean; active: boolean; data: FloodExposurePreview | null; level: number;
  layers: { water: boolean; population: boolean }; onInspect: () => void;
}) {
  const glyphs = useMemo(() => active && data ? cinematicPopulation(data) : null, [active, data]);
  const live = useRef({ data, level, layers, onInspect });
  live.current = { data, level, layers, onInspect };
  const popup = useRef<Popup | null>(null);

  useEffect(() => {
    const map = maps[1];
    if (!ready || !map?.getLayer("preview-selected")) return;
    if (active && !map.getSource("simulation-scene-glyphs")) {
      map.addSource("simulation-scene-glyphs", { type: "geojson", data: empty, tolerance: .2,
        attribution: 'Population: <a href="https://www.worldpop.org/">WorldPop</a> 2025 · CC BY 4.0',
      });
      map.setLight({ anchor: "viewport", color: "#e0f6ff", intensity: .6, position: [1.5, 175, 45] });
      map.addLayer({ id: sceneLayers[0], type: "fill-extrusion", source: "preview-districts", paint: { "fill-extrusion-color": "#153d49", "fill-extrusion-height": 2600, "fill-extrusion-opacity": 1, "fill-extrusion-vertical-gradient": true } }, "preview-selected");
      map.addLayer({ id: sceneLayers[1], type: "line", source: "preview-districts", paint: { "line-color": "#77ecd7", "line-width": 5, "line-blur": 4, "line-opacity": .5 } }, "preview-selected");
      map.addLayer({ id: sceneLayers[2], type: "line", source: "outlook-river-data", paint: { "line-color": "#78e9fa", "line-width": 8, "line-blur": 5, "line-opacity": .7 } }, "preview-selected");
      map.addLayer({ id: sceneLayers[3], type: "fill-extrusion", source: "outlook-water-data", paint: { "fill-extrusion-color": "#3b9fe9", "fill-extrusion-base": 2650, "fill-extrusion-height": 3510, "fill-extrusion-opacity": .8, "fill-extrusion-vertical-gradient": false } }, "preview-selected");
      map.addLayer({ id: sceneLayers[4], type: "fill-extrusion", source: "simulation-scene-glyphs", filter: [">", ["get", "population_2025"], 0], paint: {
        "fill-extrusion-color": ["case", ["boolean", ["feature-state", "exposed"], false], "#7ccfff", ["interpolate", ["linear"], ["get", "density_km2"], 0, "#47716a", 150, "#9cba88", 600, "#dfcd86", 2500, "#f0a574", 10000, "#f17d87"]],
        "fill-extrusion-base": 2700, "fill-extrusion-height": ["+", 2700, ["min", 34000, ["*", 420, ["sqrt", ["max", 0, ["get", "density_km2"]]]]]],
        "fill-extrusion-opacity": .95, "fill-extrusion-vertical-gradient": true,
      } }, "preview-selected");
    }
    if (!map.getSource("simulation-scene-glyphs")) return;
    popup.current?.remove();
    const container = map.getContainer();
    if (container.dataset.sceneArea !== (data?.id ?? "")) {
      map.removeFeatureState({ source: "simulation-scene-glyphs" });
      (map.getSource("simulation-scene-glyphs") as GeoJSONSource).setData(glyphs ?? empty);
      container.dataset.sceneArea = data?.id ?? "";
    } else if (active && glyphs && container.dataset.sceneColumnsPrepared !== "true") {
      (map.getSource("simulation-scene-glyphs") as GeoJSONSource).setData(glyphs);
    }
    container.dataset.sceneColumnsPrepared = String(Boolean(active && glyphs));
    const visible = (id: string, show: boolean) => map.setLayoutProperty(id, "visibility", show ? "visible" : "none");
    visible(sceneLayers[0], active && Boolean(data));
    visible(sceneLayers[1], active && Boolean(data));
    visible(sceneLayers[2], active && Boolean(data));
    visible(sceneLayers[3], Boolean(active && data?.supported && layers.water));
    visible(sceneLayers[4], Boolean(active && data && layers.population));
    [sceneLayers[0], sceneLayers[1]].forEach((id) => map.setFilter(id, ["==", ["get", "demo_id"], data?.id ?? ""]));
    map.setFilter(sceneLayers[3], ["<=", ["get", "min_level"], level]);
    map.setPaintProperty(sceneLayers[3], "fill-extrusion-height", 2850 + level * 220);
    visible("outlook-population", Boolean(!active && data && layers.population));
    visible("outlook-water-fill", Boolean(!active && data?.supported && layers.water));
    map.setPaintProperty("preview-outline", "line-opacity", active ? .25 : .5);
    map.setFilter("simulation-pins", active ? ["==", ["get", "demo_id"], data?.id ?? ""] : null);
    let exposedCells = 0;
    data?.population.features.forEach((feature) => {
      const exposed = Boolean(data.supported && layers.water && feature.properties.exposed_by_level[level] > 0);
      if (exposed) exposedCells++;
      map.setFeatureState({ source: "simulation-scene-glyphs", id: feature.id ?? feature.properties.id }, { exposed });
    });
    container.dataset.sceneColumns = String(map.getLayoutProperty(sceneLayers[4], "visibility"));
    container.dataset.sceneWater = String(map.getLayoutProperty(sceneLayers[3], "visibility"));
    container.dataset.sceneExposedCells = String(exposedCells);
    container.dataset.sceneFeatures = String(glyphs?.features.length ?? 0);
  }, [maps, ready, active, data, glyphs, level, layers]);

  useEffect(() => {
    const map = maps[1];
    if (!ready || !active || !map?.getLayer("simulation-scene-columns")) return;
    const renderInfo = () => {
      map.getContainer().dataset.sceneRenderedColumns = String(map.queryRenderedFeatures({ layers: ["simulation-scene-columns"] }).length);
      map.getContainer().dataset.sceneRenderedWater = String(map.queryRenderedFeatures({ layers: ["simulation-scene-water"] }).length);
    };
    const inspect = (event: MapLayerMouseEvent) => {
      const current = live.current;
      const hit = event.features?.[0];
      const feature = current.data?.population.features.find((item) => String(item.id ?? item.properties.id) === String(hit?.id));
      if (!feature || !current.data) return;
      current.onInspect();
      popup.current?.remove();
      const body = document.createElement("div");
      body.className = "simulation-scene-popup-body";
      const title = document.createElement("strong"); title.textContent = `${current.data.name} · population column`;
      const population = document.createElement("p"); population.textContent = `${approximatePeople(feature.properties.population_2025)} people · WorldPop 2025`;
      const density = document.createElement("p"); density.textContent = `${Math.round(feature.properties.density_km2).toLocaleString()} people/km²`;
      const exposed = document.createElement("p"); exposed.textContent = current.layers.water && current.data.supported ? `${approximatePeople(feature.properties.exposed_by_level[current.level])} within example footprint` : "No available flood footprint is enabled.";
      const note = document.createElement("small"); note.textContent = "Stylized column height; not a building or terrain height.";
      body.append(title, population, density, exposed, note);
      popup.current = new Popup({ className: "simulation-scene-popup", maxWidth: "290px" }).setLngLat(event.lngLat).setDOMContent(body).addTo(map);
    };
    map.on("idle", renderInfo);
    map.on("click", "simulation-scene-columns", inspect);
    return () => { map.off("idle", renderInfo); map.off("click", "simulation-scene-columns", inspect); popup.current?.remove(); popup.current = null; };
  }, [maps, ready, active]);
}
