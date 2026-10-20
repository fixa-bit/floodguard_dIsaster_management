import { useState } from "react";
import { SimulationHecRasConfluence } from "./SimulationHecRasConfluence";
import { SimulationHecRasFloodplain } from "./SimulationHecRasFloodplain";
import "../simulation-hec-ras.css";

export function SimulationHecRasReplay() {
  const [model, setModel] = useState<"floodplain" | "confluence">("floodplain");
  return <>
    <div className="hec-model-tabs" role="tablist" aria-label="HEC-RAS demonstration model">
      <button type="button" role="tab" aria-selected={model === "floodplain"} onClick={() => setModel("floodplain")}>Floodplain close-up</button>
      <button type="button" role="tab" aria-selected={model === "confluence"} onClick={() => setModel("confluence")}>Tributary &amp; rain</button>
    </div>
    {model === "floodplain" ? <SimulationHecRasFloodplain /> : <SimulationHecRasConfluence />}
  </>;
}
