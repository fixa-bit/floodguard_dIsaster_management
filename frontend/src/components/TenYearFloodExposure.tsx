import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Droplets, Info, Layers, Users } from "lucide-react";
import { Popup, type GeoJSONSource, type Map as MapLibreMap, type MapLayerMouseEvent } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import { loadMapAsset } from "./mapAssets";
import { approximatePeople, exposureAssetUrl, type FloodExposurePreview } from "./outlookFloodExposureData";
import type { PreviewAreaId, PreviewSelection } from "./tenYearPreviewData";

const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
const sourceIds = ["outlook-population-data", "outlook-water-data", "outlook-river-data"];

export function TenYearFloodExposure({ maps, ready, selection, onSelectionChange, onInteract, children,
  context = "outlook", initialLayers = false, level: controlledLevel, onLevelChange, onAvailabilityChange,
  onDataChange, onLayerVisibilityChange, cinematic = false,
}: {
  maps: MapLibreMap[]; ready: boolean; selection: PreviewSelection;
  onSelectionChange: (id: PreviewSelection) => void; onInteract: () => void; children: ReactNode;
  context?: "outlook" | "simulation"; initialLayers?: boolean;
  level?: number; onLevelChange?: (level: number) => void; onAvailabilityChange?: (available: boolean) => void;
  onDataChange?: (data: FloodExposurePreview | null) => void;
  onLayerVisibilityChange?: (layers: { water: boolean; population: boolean }) => void;
  cinematic?: boolean;
}) {
  const [water, setWater] = useState(initialLayers);
  const [population, setPopulation] = useState(initialLayers);
  const [localLevel, setLocalLevel] = useState(2);
  const level = controlledLevel ?? localLevel;
  const sliderId = `${context === "simulation" ? "simulation" : "outlook"}-flood-level`;
  const [loaded, setLoaded] = useState<FloodExposurePreview | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const active = water || population;
  // A newly selected area must never display the previous district's estimates.
  const data = loaded?.id === selection ? loaded : null;
  const selected = data?.levels[level];
  const live = useRef({ level, water, data });
  live.current = { level, water, data };
  const popups = useRef<Popup[]>([]);

  useEffect(() => { onAvailabilityChange?.(Boolean(ready && water && data?.supported)); }, [ready, water, data, onAvailabilityChange]);
  useEffect(() => { onDataChange?.(data); }, [data, onDataChange]);
  useEffect(() => { onLayerVisibilityChange?.({ water, population }); }, [water, population, onLayerVisibilityChange]);

  useEffect(() => {
    if (!active || selection === "all") return;
    let disposed = false;
    setError(false);
    loadMapAsset<FloodExposurePreview>(exposureAssetUrl(selection)).then((result) => {
      if (!disposed) setLoaded(result);
    }).catch(() => { if (!disposed) setError(true); });
    return () => { disposed = true; };
  }, [active, selection, attempt]);

  useEffect(() => {
    if (!ready) return;
    const cleanups: (() => void)[] = [];
    maps.forEach((map, index) => {
      sourceIds.forEach((id, i) => { if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: empty, tolerance: .2,
        attribution: i === 0 ? 'Population: <a href="https://www.worldpop.org/">WorldPop</a> 2025 · CC BY 4.0' : 'River references: <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> · Hypothetical spread',
      }); });
      if (!map.getLayer("outlook-population")) {
        map.addLayer({ id: "outlook-population", type: "fill", source: sourceIds[0], layout: { visibility: "none" }, paint: {
          "fill-color": ["interpolate", ["linear"], ["get", "density_km2"], 0, "#3b5555", 100, "#788d60", 500, "#d4be69", 2000, "#ec985e", 10000, "#e5677d"],
          "fill-opacity": .86,
        } }, "preview-outline");
        map.addLayer({ id: "outlook-water-fill", type: "fill", source: sourceIds[1], layout: { visibility: "none" }, paint: { "fill-color": "#428fee", "fill-opacity": .65 } }, "preview-outline");
        map.addLayer({ id: "outlook-water-edge", type: "line", source: sourceIds[1], layout: { visibility: "none" }, paint: { "line-color": "#9ad8ff", "line-width": .7, "line-opacity": .8 } }, "preview-outline");
        map.addLayer({ id: "outlook-rivers", type: "line", source: sourceIds[2], layout: { visibility: "none" }, paint: { "line-color": "#91e0ef", "line-width": 1.4 } }, "preview-selected");
      }
      const click = (event: MapLayerMouseEvent) => {
        const hit = event.features?.[0];
        if (!hit || !live.current.data) return;
        const values = typeof hit.properties.exposed_by_level === "string" ? JSON.parse(hit.properties.exposed_by_level) as number[] : hit.properties.exposed_by_level as number[];
        const title = document.createElement("strong");
        title.textContent = `${live.current.data.name} · population cell`;
        const count = document.createElement("p");
        count.textContent = `${approximatePeople(Number(hit.properties.population_2025))} people · WorldPop 2025`;
        const exposure = document.createElement("p");
        exposure.textContent = index === 1 && live.current.water && live.current.data.supported
          ? `${approximatePeople(values[live.current.level])} within example level ${live.current.level} footprint`
          : "Population context; no example flooding on this map.";
        const note = document.createElement("small");
        note.textContent = "Approximate 2 km display cell. NoData excluded.";
        const body = document.createElement("div");
        body.className = "outlook-population-popup";
        body.append(title, count, exposure, note);
        popups.current.forEach((popup) => popup.remove());
        popups.current = [new Popup({ maxWidth: "280px" }).setLngLat(event.lngLat).setDOMContent(body).addTo(map)];
      };
      map.on("click", "outlook-population", click);
      cleanups.push(() => map.off("click", "outlook-population", click));
    });
    return () => { cleanups.forEach((cleanup) => cleanup()); popups.current.forEach((popup) => popup.remove()); popups.current = []; };
  }, [ready, maps]);

  useEffect(() => {
    if (!ready) return;
    popups.current.forEach((popup) => popup.remove());
    popups.current = [];
    maps.forEach((map, index) => {
      if (!map.getLayer("outlook-population")) return;
      const container = map.getContainer();
      if (container.dataset.exposureArea !== (data?.id ?? "")) {
        [data?.population, data?.water, data?.river_lines].forEach((collection, i) => (map.getSource(sourceIds[i]) as GeoJSONSource).setData(collection ?? empty));
        container.dataset.exposureArea = data?.id ?? "";
      }
      const showWater = Boolean(active && water && data?.supported && index === 1);
      const showPopulation = Boolean(active && population && data);
      map.setLayoutProperty("outlook-population", "visibility", showPopulation ? "visible" : "none");
      ["outlook-water-fill", "outlook-water-edge"].forEach((id) => {
        map.setLayoutProperty(id, "visibility", showWater ? "visible" : "none");
        map.setFilter(id, ["<=", ["get", "min_level"], level]);
      });
      map.setLayoutProperty("outlook-rivers", "visibility", active && data ? "visible" : "none");
      map.setPaintProperty("preview-fill", "fill-opacity-transition", { duration: 0 });
      map.setPaintProperty("preview-fill", "fill-opacity", active ? .18 : .85);
      container.dataset.populationVisible = String(map.getLayoutProperty("outlook-population", "visibility"));
      container.dataset.waterVisible = String(map.getLayoutProperty("outlook-water-fill", "visibility"));
      container.dataset.floodLevel = String(showWater ? level : 0);
      container.dataset.exposedPeople = showWater ? String(data?.levels[level].exposed_population) : "0";
    });
  }, [ready, maps, active, water, population, level, data]);

  function toggleLayer(kind: "water" | "population") {
    onInteract();
    if (selection === "all") onSelectionChange("jhang");
    if (kind === "water") setWater((value) => !value);
    else setPopulation((value) => !value);
  }
  function chooseLevel(value: number) { onInteract(); if (onLevelChange) onLevelChange(value); else setLocalLevel(value); }
  const percentage = selected?.exposed_population != null && data?.known_population_2025 ? selected.exposed_population / data.known_population_2025 * 100 : null;
  const maxPeople = Math.max(1, ...(data?.levels.map((item) => item.exposed_population ?? 0) ?? []));

  return <div className="outlook-exposure" data-exposure-active={active} data-exposure-level={level} data-exposure-area={data?.id ?? ""}>
    <div className="outlook-layer-toolbar">
      <div><span className="outlook-layer-eyebrow"><Layers size={14} aria-hidden="true" /> MAP LAYERS</span><h4>Water spread &amp; population</h4><p>Explore who could be inside an example river-flood footprint.</p></div>
      <div className="outlook-layer-buttons" data-tour-target="simulation-spread-layers"><button className="outlook-quiet-button" type="button" aria-pressed={water} onClick={() => toggleLayer("water")}><Droplets size={16} aria-hidden="true" /> Flood spread</button><button className="outlook-quiet-button" type="button" aria-pressed={population} onClick={() => toggleLayer("population")}><Users size={16} aria-hidden="true" /> Population map</button></div>
    </div>
    {active && <div className="outlook-flood-settings">
      <p className="outlook-exposure-notice"><Info size={16} aria-hidden="true" /><span><strong>What-if experiment.</strong> {context === "simulation" ? "Water spread is a hypothetical district example. Population uses a fixed WorldPop 2025 baseline. Monitoring readings and warning/danger thresholds are not calibrated to these footprints." : "Water spread is hypothetical. Population uses a fixed WorldPop 2025 baseline, independent of planning year, scenario, and flood-type index."} No terrain or hydraulic simulation is used.</span></p>
      {selection === "all" ? <p className="outlook-exposure-status" role="status">Choose one example district to see its population and flood-spread layers. <button className="outlook-quiet-button" type="button" onClick={() => onSelectionChange("jhang")}>Explore Jhang</button></p>
        : error ? <p className="outlook-exposure-status" role="status">Population and spread data could not be loaded. <button className="outlook-quiet-button" type="button" onClick={() => { setError(false); setAttempt((value) => value + 1); }}>Retry layers</button></p>
          : !data ? <p className="outlook-exposure-status" role="status">Loading district population and spread examples…</p>
            : !data.supported ? <p className="outlook-exposure-status" role="status"><strong>{data.name}: population available; water spread unavailable.</strong> The local river-reference dataset has no usable river alignment here. A flood footprint and affected population cannot be estimated from these inputs.</p> : null}
      {water && <div className="outlook-flood-slider">
        <label htmlFor={sliderId}>Example flood level <output htmlFor={sliderId}>{data?.supported ? `${level} / 5` : "Unavailable"}</output></label>
        <input id={sliderId} aria-label="Example flood level" type="range" min="0" max="5" step="1" value={level} disabled={!ready || !data?.supported} aria-valuetext={`Example level ${level} of 5, ${level === 0 ? "no example flooding" : "hypothetical river spread"}; not a water height`} onChange={(event) => chooseLevel(Number(event.target.value))} />
        <div><span>0 · No example flooding</span><span>5 · Widest example</span></div>
        <div className="outlook-flood-presets" role="group" aria-label="Flood scenario presets"><button type="button" className="outlook-quiet-button" disabled={!ready || !data?.supported} aria-pressed={level === 0} onClick={() => chooseLevel(0)}>Lowest flood scenario <small>Level 0</small></button><button type="button" className="outlook-quiet-button" disabled={!ready || !data?.supported} aria-pressed={level === 5} onClick={() => chooseLevel(5)}>Highest flood scenario <small>Level 5</small></button></div>
        <p>Ordinal levels, not metres or official warning categories. Larger levels widen the example river corridor on the right map.</p>
      </div>}
      {data && <div className="outlook-overlay-context">{cinematic ? <><span>Stylized population columns · fixed 2025 baseline</span><span>{water && data.supported ? `Example flood level ${level}` : "Population / district context"}</span></> : <><span>Left: {population ? "2025 population context" : "district context"} · no example flooding</span><span>Right: {water && data.supported ? `example flood level ${level}` : "population / district context"}</span></>}</div>}
    </div>}
    {children}
    {active && <>
      <div className="outlook-map-legend outlook-exposure-legend" aria-label="Flood spread and population legend">
        {water && <span><i style={{ background: "#428fee" }} /> Hypothetical water spread{cinematic ? "" : " · right map"}</span>}
        {population && <><span><i className="outlook-density-key" /> Population {cinematic ? "columns" : "density"}: sparse → dense</span><span>People/km²: 0 · 100 · 500 · 2,000 · 10,000+</span></>}
        <span><i style={{ background: "#91e0ef" }} /> Reference river alignment</span>
      </div>
      {data && <div className="outlook-exposure-impact" aria-live="polite" data-estimated-people={water && data.supported ? selected?.exposed_population : "unavailable"}>
        <div className="outlook-exposure-metrics">
          <article className="outlook-exposed-count"><span><Users size={15} aria-hidden="true" /> People inside example footprint</span><strong data-testid="outlook-exposed-population">{water ? approximatePeople(selected?.exposed_population ?? null) : "Enable flood spread"}</strong><p>{water && percentage !== null ? `~${percentage.toFixed(1)}% of known 2025 population in ${data.name}` : "Needs an available water footprint"}</p></article>
          <article><span>Example flooded area</span><strong>{water && selected?.flood_area_km2 != null ? `${selected.flood_area_km2.toFixed(1)} km²` : "Unavailable"}</strong><p>Clipped to the selected district</p></article>
          <article><span>Known population · {data.name}</span><strong>{approximatePeople(data.known_population_2025)}</strong><p>WorldPop 2025 · 2 km display grid</p></article>
        </div>
        {water && data.supported && <div className="outlook-exposure-levels"><div><h4>Population by example flood level</h4><p>Click a bar or drag the slider to compare.</p></div><div className="outlook-exposure-bars" role="group" aria-label="Population exposed by flood level">{data.levels.map((item) => <button type="button" key={item.level} aria-label={`Use flood level ${item.level}: ${approximatePeople(item.exposed_population)} people`} aria-pressed={level === item.level} onClick={() => chooseLevel(item.level)}><span>{approximatePeople(item.exposed_population)}</span><i style={{ "--exposure-bar-height": `${(item.exposed_population ?? 0) / maxPeople * 100}%` } as CSSProperties}><b /></i><small>L{item.level}</small></button>)}</div></div>}
        <p className="outlook-exposure-footnote">Approximate exposure, not confirmed affected people: population is assumed uniform within each 2 km cell and intersected by footprint area. NoData is excluded; no population growth is projected. District outlines and reference rivers are approximate. <a href="https://doi.org/10.5258/SOTON/WP00839" target="_blank" rel="noreferrer">WorldPop R2025A v1</a> · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>. River references: <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>. See Inputs &amp; Method for assumptions.</p>
      </div>}
    </>}
  </div>;
}
