import { ChevronDown, RefreshCw, Search, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import type { RiverMonitoringResponse } from "../types/api";
import { api } from "../services/api";
import { RiverDataSource, riverTimestamp } from "./RiverDataSource";
import { RiverStationInspector } from "./RiverStationInspector";
import { formatFlow, type FlowUnit } from "./waterQuantities";

export function RiverMonitoringView({ compact = false, onClose }: { compact?: boolean; onClose?: () => void }) {
  const [data, setData] = useState<RiverMonitoringResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [river, setRiver] = useState("All");
  const [unit, setUnit] = useState<FlowUnit>("cumecs");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const interval = data?.refreshing || !data?.stations.length ? 5000 : 60000;
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const response = await api.riverMonitoring(); if (active) { setData(response); setError(null); } }
      catch (err) { if (active) setError(err instanceof Error ? err.message : "Readings unavailable"); }
    };
    void load();
    const timer = window.setInterval(() => void load(), interval);
    return () => { active = false; window.clearInterval(timer); };
  }, [interval]);
  async function refresh() {
    setRefreshing(true);
    try { setData(await api.refreshRiverMonitoring()); setError(null); }
    catch (err) { setError(err instanceof Error ? err.message : "Refresh failed"); }
    finally { setRefreshing(false); }
  }
  const stations = (data?.stations ?? []).filter((station) => (river === "All" || data?.chains[river]?.includes(station.id)) && `${station.name} ${station.river}`.toLowerCase().includes(query.trim().toLowerCase()));
  const busy = refreshing || Boolean(data?.refreshing);
  return <section className={`river-monitoring-view ${compact ? "is-compact" : "is-detailed"}`} aria-label={compact ? "Monitoring summary" : "Detailed river monitoring"}>
    <header className="monitoring-view-head"><div><strong>River monitoring</strong><small>Updated {riverTimestamp(data?.cached_at)} / Every {data?.refresh_interval_minutes ?? 15} min</small></div><div><button type="button" title="Refresh monitoring" aria-label="Refresh monitoring" disabled={busy} onClick={() => void refresh()}><RefreshCw size={16} className={busy ? "spinning" : ""} /></button>{onClose && <button type="button" title="Hide monitoring" aria-label="Hide monitoring" onClick={onClose}><X size={16} /></button>}</div></header>
    <div className="monitoring-view-filters"><label>River<select aria-label="Monitoring view river" value={river} onChange={(event) => { setRiver(event.target.value); setSelected(null); }}><option value="All">All rivers</option>{Object.keys(data?.chains ?? {}).map((name) => <option key={name}>{name}</option>)}</select></label><label>Units<select aria-label="Monitoring view units" value={unit} onChange={(event) => setUnit(event.target.value as FlowUnit)}><option value="cumecs">m3/s</option><option value="cusecs">cusecs</option></select></label><label className="monitoring-view-search"><Search size={14} /><input aria-label="Search monitoring stations" type="search" placeholder="Search stations" value={query} onChange={(event) => setQuery(event.target.value)} /></label><small>{stations.length} stations</small></div>
    {(error || data?.refresh_error) && <p role="status">{error || data?.refresh_error}{data ? " / Stored readings shown" : ""}</p>}
    <div className="monitoring-view-table"><table className="data-table"><thead><tr><th>Station / river</th><th>Current flow</th><th>Forecast flow</th><th>Flood category</th>{!compact && <><th>24h change</th><th>Expected peak</th></>}</tr></thead><tbody>{stations.map((station) => <Fragment key={station.id}><tr className={selected === station.id ? "is-selected" : ""}>
      <td>{compact ? <strong>{station.name}</strong> : <button className="monitoring-station-toggle" type="button" aria-expanded={selected === station.id} onClick={() => setSelected(selected === station.id ? null : station.id)}>{station.name}<ChevronDown size={14} /></button>}<small>{station.river}</small></td>
      <td><strong>{formatFlow(station.current_discharge_cumecs, unit)}</strong><RiverDataSource source={station.current_source} station={station} /><small>{riverTimestamp(station.observed_at ?? station.providers.find((provider) => provider.provider === "GloFAS")?.series.filter((point) => point.phase === "past").slice(-1)[0]?.time)}</small></td>
      <td><strong>{formatFlow(station.forecast_discharge_cumecs, unit)}</strong><RiverDataSource source="GloFAS modeled" station={station} /><small>{riverTimestamp(station.forecast_valid_at)}</small></td>
      <td><span className={`monitoring-flood-status ${/below|normal/i.test(station.flood_category) ? "is-normal" : /unavailable/i.test(station.flood_category) ? "is-unknown" : "is-alert"}`}>{station.flood_category === "Below low" ? "Below flood level" : station.flood_category}</span><RiverDataSource source="FFD observed status" station={station} /></td>
      {!compact && <><td>{station.change_24h_cumecs != null && station.change_24h_cumecs > 0 ? "+" : ""}{formatFlow(station.change_24h_cumecs, unit)}<RiverDataSource source={station.change_source} station={station} /></td><td>{formatFlow(station.expected_peak_cumecs, unit)}<RiverDataSource source="GloFAS modeled peak" station={station} /><small>{riverTimestamp(station.expected_peak_at)}</small></td></>}
    </tr>{!compact && selected === station.id && <tr className="monitoring-detail-row"><td colSpan={6}><RiverStationInspector stationId={selected} data={data} error={error} refreshing={busy} onRefresh={() => void refresh()} onClose={() => setSelected(null)} onSelect={(id) => { setRiver("All"); setQuery(""); setSelected(id); }} flowUnit={unit} /></td></tr>}</Fragment>)}</tbody></table>{!stations.length && <p role="status">{data ? "No matching stations" : error ? "Readings unavailable" : "Loading monitoring readings..."}</p>}</div>
    <footer><span>Flow in {unit === "cumecs" ? "cubic metres per second" : "cubic feet per second"}. Measured water height unavailable.</span><RiverDataSource source="FFD observations" /><RiverDataSource source="GloFAS via Open-Meteo" /></footer>
  </section>;
}
