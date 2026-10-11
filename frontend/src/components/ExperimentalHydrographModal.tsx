import { RefreshCw, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../services/api";
import type { ExperimentalHydrograph, RiverMonitoringStation } from "../types/api";
import { pktTime } from "./experimentalHydrographData";
import "../experimental-hydrograph.css";

const Chart = lazy(() => import("./ExperimentalHydrographChart"));
const cache = new Map<string, { at: number; data: ExperimentalHydrograph }>();

export default function ExperimentalHydrographModal({ station, onDetails, onForecast, onClose }: {
  station: RiverMonitoringStation; onDetails: () => void; onForecast: () => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const [days, setDays] = useState<5 | 30>(5);
  const [data, setData] = useState<ExperimentalHydrograph>();
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); const key = `${station.id}:${days}`;
    setData(undefined); setError(false);
    const cached = cache.get(key);
    if (cached && Date.now() - cached.at < 4 * 3600000 && retry === 0) setData(cached.data);
    else api.experimentalHydrograph(station.id, days, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (cache.size >= 100) cache.delete(cache.keys().next().value!);
      if (!result.stale && !result.forecastUnavailable) cache.set(key, { at: Date.now(), data: result });
      setData(result);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [station.id, days, retry]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const items = [...dialog.current!.querySelectorAll<HTMLElement>('button:not(:disabled),input,a[href],[tabindex="0"]')];
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = overflow; previous?.focus(); };
  }, [onClose]);
  return createPortal(<div className="station-forecast-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="station-forecast-window experimental-hydrograph" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="experimental-title">
      <header><div><small>Station hydrograph / {station.id}</small><h2 id="experimental-title">{station.river} at {station.name} ({station.id}) <span>[Experimental Forecast]</span></h2></div><button type="button" onClick={onClose} aria-label="Close experimental hydrograph" title="Close experimental hydrograph"><X size={20} /></button></header>
      <div className="station-details-tabs" role="tablist" aria-label="Station views">
        <button type="button" role="tab" aria-selected="false" onClick={onDetails}>Station details</button>
        <button type="button" role="tab" aria-selected="false" onClick={onForecast}>Discharge forecast</button>
        <button type="button" id="experimental-tab" role="tab" aria-selected="true" aria-controls="experimental-panel">Experimental</button>
      </div>
      <section id="experimental-panel" role="tabpanel" aria-labelledby="experimental-tab">
        <div className="experimental-topline"><small>{data ? `As on ${pktTime(data.generatedAt)}` : "Experimental station hydrograph"}</small><div className="station-details-tabs" role="group" aria-label="Forecast horizon">{([5, 30] as const).map((value) => <button key={value} type="button" aria-pressed={days === value} onClick={() => { setRetry(0); setDays(value); }}>{value} Days</button>)}</div></div>
        {error ? <div className="experimental-empty" role="alert"><p>Hydrograph data is temporarily unavailable.</p><button type="button" onClick={() => setRetry((value) => value + 1)}><RefreshCw size={15} />Retry</button></div>
          : !data ? <div className="experimental-skeleton" role="status" aria-label="Loading hydrograph"><div /><div /><div /></div>
          : <><div className="experimental-provenance"><span>Observed: {data.sources.observed.length ? data.sources.observed.join("; ") : "No station observations"} / inflow</span><a href={data.sources.forecastUrl} target="_blank" rel="noreferrer">{data.sources.forecast}</a>
            <span>Model cell: {data.station.modelCell ? `${data.station.modelCell.lat.toFixed(5)}, ${data.station.modelCell.lon.toFixed(5)} (unverified)` : "Unavailable"}</span></div>
            {data.stale && <p className="experimental-notice">Stale forecast / last successful fetch {pktTime(data.generatedAt)}</p>}
            {data.forecastUnavailable && <p className="experimental-notice">Forecast unavailable; stored observations retained. <button type="button" onClick={() => setRetry((value) => value + 1)}><RefreshCw size={14} />Retry</button></p>}
            {!data.observed.length && data.forecast.length > 0 && <p className="experimental-notice">Forecast only / no observed station data available.</p>}
            <Suspense fallback={<div className="experimental-skeleton" role="status" aria-label="Loading chart"><div /></div>}><Chart data={data} days={days} /></Suspense>
          </>}
      </section>
    </div>
  </div>, document.body);
}
