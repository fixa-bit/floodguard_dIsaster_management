import { lazy, Suspense, useState } from "react";
import "../simulation-terrain-prototype.css";

const DistrictReplay = lazy(() => import("./SimulationStormReplay").then(module => ({ default: module.SimulationStormReplay })));
const TerrainPrototype = lazy(() => import("./SimulationJhangTerrainPrototype").then(module => ({ default: module.SimulationJhangTerrainPrototype })));
const HydraulicPilot = lazy(() => import("./SimulationHydraulicPilot").then(module => ({ default: module.SimulationHydraulicPilot })));
const HecRasReplay = lazy(() => import("./SimulationHecRasConfluence").then(module => ({ default: module.SimulationHecRasConfluence })));
const NdmaTerrainFlow = lazy(() => import("./SimulationNdmaTerrainFlow").then(module => ({ default: module.SimulationNdmaTerrainFlow })));

export function SimulationReplayWorkspace() {
  const [view, setView] = useState<"district" | "terrain" | "hydraulic" | "hec-ras" | "ndma-flow">("district");
  return <>
    <div className="replay-workspace-switch" role="group" aria-label="Replay study mode">
      <button type="button" data-tour-target="district-replay" aria-pressed={view === "district"} onClick={() => setView("district")}>District storm replay<small>Original example</small></button>
      <button type="button" data-tour-target="terrain-prototype" aria-pressed={view === "terrain"} onClick={() => setView("terrain")}>Jhang terrain prototype<small>Small area · experimental</small></button>
      <button type="button" aria-pressed={view === "hydraulic"} onClick={() => setView("hydraulic")}>2D hydraulic trial<small>ANUGA · hypothetical inflow</small></button>
      <button type="button" aria-pressed={view === "hec-ras"} onClick={() => setView("hec-ras")}>HEC-RAS 2D<small>USACE river confluence demo</small></button>
      <button type="button" aria-pressed={view === "ndma-flow"} onClick={() => setView("ndma-flow")}>River hydraulic flow<small>White River · HEC-RAS channel and floodplain</small></button>
    </div>
    <Suspense fallback={<p role="status" className="terrain-pilot-loading">Preparing study…</p>}>
      {view === "district" ? <DistrictReplay /> : view === "terrain" ? <TerrainPrototype /> : view === "hydraulic" ? <HydraulicPilot /> : view === "ndma-flow" ? <NdmaTerrainFlow /> : <HecRasReplay />}
    </Suspense>
  </>;
}
