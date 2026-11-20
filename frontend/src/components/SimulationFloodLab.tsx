import { ExternalLink, LoaderCircle, RefreshCw, Waves } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

/** The separate Flood Simulation app (Nowshera pilot: HEC-RAS 2D and LISFLOOD-FP cases on a 3D globe),
 * served by the portal at /flood-sim/ (frontend/build/floodSimApp.ts) and shown here in a same-origin frame. */
const APP_URL = "/flood-sim/";
type Status = "checking" | "ready" | "no-service" | "not-built";

export function SimulationFloodLab() {
  const [status, setStatus] = useState<Status>("checking");
  const check = useCallback(async () => {
    setStatus("checking");
    try {
      const page = await fetch(APP_URL, { method: "HEAD", cache: "no-store" });
      if (page.status === 503) { setStatus("not-built"); return; }
      const health = await fetch(`${APP_URL}api/health`, { cache: "no-store" });
      setStatus(health.ok ? "ready" : "no-service");
    } catch {
      setStatus("no-service");
    }
  }, []);
  useEffect(() => { void check(); }, [check]);

  return <div className="flood-lab">
    <div className="flood-lab-bar">
      <Waves size={18} aria-hidden />
      <div>
        <strong>Flood simulation lab</strong>
        <span>Nowshera pilot on the Kabul River: HEC-RAS 2D and LISFLOOD-FP flood cases, upstream inflows and exposure on a 3D globe.</span>
      </div>
      <span className={`flood-lab-state ${status}`}>
        {status === "checking" ? <><LoaderCircle size={13} className="spinning" aria-hidden />Connecting</> : status === "ready" ? "Model service connected" : status === "not-built" ? "App not built" : "Model service offline"}
      </span>
      <button type="button" className="secondary-button" onClick={() => void check()}><RefreshCw size={14} aria-hidden />Check</button>
      <a className="secondary-button" href={APP_URL} target="_blank" rel="noreferrer"><ExternalLink size={14} aria-hidden />Full screen</a>
    </div>
    {status === "not-built" && <p className="flood-lab-note">Build the simulation app for the portal once: <code>node scripts/build-flood-sim.mjs</code>, then press Check.</p>}
    {status === "no-service" && <p className="flood-lab-note">The map loads, but cases and results need the simulation’s data service on port 8010. <code>npm run dev</code> starts it automatically when <code>D:\projects\flood sim cursor\flood sim cursor</code> is set up; otherwise run <code>.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8010</code> in that folder, then press Check.</p>}
    {status !== "not-built" && <iframe className="flood-lab-frame" src={APP_URL} title="Flood simulation lab" allow="fullscreen" />}
  </div>;
}
