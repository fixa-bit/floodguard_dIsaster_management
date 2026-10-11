import { Download, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../services/api";
import type { RiverMonitoringStation } from "../types/api";
import { chartPath, chartTime } from "./SourceFloodForecastTab";
import { pakistanTime, type StationHistory } from "./stationInfo";
import { flowInUnit, formatFlow, type FlowUnit } from "./waterQuantities";
import { RiverDataSource } from "./RiverDataSource";
import { nearestDischargePoint, stationForecastSeries } from "./stationForecastData";

const historyCache = new Map<string, { time: number; data: StationHistory }>();
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const dateLabel = (time: number) => new Intl.DateTimeFormat("en-PK", { day: "numeric", month: "short", timeZone: "Asia/Karachi" }).format(time);
const readingTime = (time: string) => /^\d{4}-\d{2}-\d{2}$/.test(time) ? `${new Intl.DateTimeFormat("en-PK", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(chartTime(time))} (daily estimate)` : pakistanTime(time) ?? "Unavailable";

export default function StationForecastWindow({ station, intervalMinutes, flowUnit, onDetails, onClose }: {
  station: RiverMonitoringStation; intervalMinutes: number; flowUnit: FlowUnit; onDetails: () => void; onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [history, setHistory] = useState<StationHistory>();
  const [historyStatus, setHistoryStatus] = useState("Loading stored observations...");
  const [hover, setHover] = useState<number | null>(null);
  const [hiddenSeries, setHiddenSeries] = useState<string[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    const cached = historyCache.get(station.id);
    if (cached && Date.now() - cached.time < intervalMinutes * 60000) {
      setHistory(cached.data); setHistoryStatus(cached.data.samples.length ? "" : "No stored observations");
    } else {
      api.stationHistory(station.id, controller.signal).then((data) => {
        if (controller.signal.aborted) return;
        if (historyCache.size >= 100) historyCache.delete(historyCache.keys().next().value!);
        historyCache.set(station.id, { time: Date.now(), data }); setHistory(data);
        setHistoryStatus(data.samples.length ? "" : "No stored observations");
      }).catch(() => { if (!controller.signal.aborted) setHistoryStatus("Stored observations unavailable"); });
    }
    return () => controller.abort();
  }, [station.id, intervalMinutes]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const buttons = [...dialogRef.current!.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,[tabindex="0"]')];
      const first = buttons[0]; const last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener("keydown", handleKey); previous?.focus(); };
  }, [onClose]);
  const series = useMemo(() => stationForecastSeries(station, history), [station, history]);
  const thresholds = useMemo(() => {
    const stats = station.stats;
    if (typeof stats.threshold_source !== "string" || !stats.threshold_source.trim()) return [];
    return [{ label: "Danger discharge", value: stats.danger_discharge_cumecs, color: "#ff526d" },
      { label: "Highest recorded discharge", value: stats.highest_recorded_discharge_cumecs, color: "#4de2a3" }]
      .filter((item): item is { label: string; value: number; color: string } => finite(item.value) && item.value >= 0);
  }, [station.stats]);
  const allPoints = series.flatMap((item) => item.points.filter((point) => finite(point.value)));
  const start = Math.min(...allPoints.map((point) => chartTime(point.time)));
  const end = Math.max(...allPoints.map((point) => chartTime(point.time)), start + 86400000);
  const max = Math.max(1, ...allPoints.map((point) => point.value ?? 0), ...thresholds.map((item) => item.value)) * 1.1;
  const width = 900; const height = 260;
  const ticks = [0, .25, .5, .75, 1];
  const rows = series.flatMap((item) => item.points.filter((point) => finite(point.value)).map((point) => ({ ...point, label: item.label, source: item.source })))
    .sort((a, b) => chartTime(a.time) - chartTime(b.time));
  const exportCsv = () => {
    const quote = (value: string) => `"${value.replaceAll('"', '""')}"`;
    const csv = [["Station", "Time", "Series", "Discharge (cumecs)", "Source"], ...rows.map((row) => [station.name, row.time, row.label, String(row.value), row.source])]
      .map((row) => row.map(quote).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `${station.id}-discharge.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return createPortal(<div className="station-forecast-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialogRef} className="station-forecast-window" role="dialog" aria-modal="true" aria-labelledby="station-forecast-title">
      <header><div><small>{station.river} River / {station.id}</small><h2 id="station-forecast-title">{station.name}</h2></div><button type="button" aria-label="Close station forecast" title="Close station forecast" onClick={onClose}><X size={20} /></button></header>
      <div className="station-details-tabs" role="tablist" aria-label="Station views">
        <button role="tab" type="button" aria-selected="false" onClick={onDetails}>Station details</button>
        <button role="tab" type="button" id="station-forecast-tab" aria-selected="true" aria-controls="station-forecast-panel">Discharge forecast</button>
      </div>
      <section id="station-forecast-panel" role="tabpanel" aria-labelledby="station-forecast-tab">
        <div className="station-forecast-heading"><div><h3>Short-range discharge forecast / 5 days</h3><small>{station.latitude.toFixed(5)} N / {station.longitude.toFixed(5)} E</small></div><button type="button" title="Download discharge readings" aria-label="Download discharge readings" onClick={exportCsv} disabled={!rows.length}><Download size={18} /></button></div>
        <dl className="station-forecast-summary"><div><dt>Current discharge</dt><dd>{formatFlow(station.current_discharge_cumecs, flowUnit)}</dd><RiverDataSource source={station.current_source} station={station} />{station.observed_at && <small>{readingTime(station.observed_at)}{Date.now() - chartTime(station.observed_at) > intervalMinutes * 60000 ? " / stale" : ""}</small>}</div>
          <div><dt>Danger discharge</dt><dd>{thresholds.some((item) => item.label === "Danger discharge") ? formatFlow(thresholds.find((item) => item.label === "Danger discharge")!.value, flowUnit) : "Unavailable"}</dd><small>{thresholds.length ? String(station.stats.threshold_source) : "No verified station threshold"}</small></div>
          <div><dt>Highest recorded discharge</dt><dd>{thresholds.some((item) => item.label === "Highest recorded discharge") ? formatFlow(thresholds.find((item) => item.label === "Highest recorded discharge")!.value, flowUnit) : "Unavailable"}</dd><small>{typeof station.stats.highest_recorded_at === "string" ? readingTime(station.stats.highest_recorded_at) : "Record date unavailable"}</small></div></dl>
        {historyStatus && <p role="status">{historyStatus}</p>}
        {series.some((item) => !item.modeled) && series.some((item) => item.modeled) && <p className="station-forecast-data-note">FFD station readings and daily GloFAS grid estimates are not interchangeable; the model is not calibrated to this gauge.</p>}
        {allPoints.length ? <>
          <div className="station-forecast-chart" onPointerLeave={() => setHover(null)}>
            <div className="station-forecast-y-label">Discharge ({flowUnit === "cumecs" ? "m3/s" : "cusecs"})</div>
            <div className="station-forecast-plot" tabIndex={0} aria-label="Discharge chart; use arrow keys to inspect dates" onKeyDown={(event) => { if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); setHover((previous) => Math.max(0, Math.min(1, (previous ?? .5) + (event.key === "ArrowLeft" ? -.02 : .02)))); } }}
              onPointerMove={(event) => { const svg = event.currentTarget.querySelector("svg")!; const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY; const transform = svg.getScreenCTM(); if (transform) setHover(Math.max(0, Math.min(1, point.matrixTransform(transform.inverse()).x / width))); }}>
              <svg viewBox={`-70 -15 ${width + 80} ${height + 55}`} role="img" aria-label={`${station.name} observed and modeled discharge chart`}>
                {ticks.map((tick) => <g key={tick}><line x1={0} x2={width} y1={height * tick} y2={height * tick} stroke="#365150" /><text x={-10} y={height * tick + 4} textAnchor="end">{flowInUnit(max * (1 - tick), flowUnit).toLocaleString("en-PK", { maximumFractionDigits: 1 })}</text><text x={width * tick} y={height + 30} textAnchor={tick === 0 ? "start" : tick === 1 ? "end" : "middle"}>{dateLabel(start + tick * (end - start))}</text></g>)}
                {thresholds.map((item) => <line key={item.label} x1={0} x2={width} y1={height * (1 - item.value / max)} y2={height * (1 - item.value / max)} stroke={item.color} strokeWidth={2} />)}
                {series.filter((item) => !hiddenSeries.includes(item.id)).map((item) => <g key={item.id}><path d={chartPath(item.points, start, end, max, width, height)} fill="none" stroke={item.color} strokeWidth={2} strokeDasharray={item.id.endsWith("-past") ? "5 4" : undefined} />{item.points.filter((point) => finite(point.value)).map((point) => <circle key={point.time} cx={(chartTime(point.time) - start) / (end - start) * width} cy={height * (1 - point.value! / max)} r={3} fill={item.color} />)}</g>)}
                {hover !== null && <line x1={width * hover} x2={width * hover} y1={0} y2={height} stroke="#e5eeee" opacity={.5} />}
              </svg>
              {hover !== null && <div className="station-chart-tooltip" style={{ left: `${Math.min(65, hover * 100)}%` }}><strong>{dateLabel(start + hover * (end - start))}</strong>{series.filter((item) => !hiddenSeries.includes(item.id)).map((item) => {
                const point = nearestDischargePoint(item, start + hover * (end - start));
                return point && <div key={item.id}><span style={{ color: item.color }}>{item.label}</span><b>{formatFlow(point.value, flowUnit)}</b><small>{readingTime(point.time)}</small></div>;
              })}</div>}
            </div>
          </div>
          <div className="station-forecast-legend">{series.map((item) => <label key={item.id}><input type="checkbox" checked={!hiddenSeries.includes(item.id)} onChange={(event) => setHiddenSeries((previous) => event.target.checked ? previous.filter((id) => id !== item.id) : [...previous, item.id])} /><i style={{ background: item.color }} />{item.label}</label>)}{thresholds.map((item) => <span key={item.label}><i style={{ background: item.color }} />{item.label}</span>)}</div>
        </> : <p>No discharge series available for this station.</p>}
        <div className="station-forecast-table" tabIndex={0} aria-label="Station discharge readings"><table><thead><tr><th>Recorded / valid at</th><th>Series</th><th>Discharge ({flowUnit})</th><th>Source</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.label}:${row.time}:${index}`}><td>{readingTime(row.time)}</td><td>{row.label}</td><td>{formatFlow(row.value, flowUnit)}</td><td>{row.source}</td></tr>)}</tbody></table></div>
        <footer><RiverDataSource source="FFD observed" station={station} />{station.providers.map((provider) => <RiverDataSource key={provider.provider} source={`${provider.provider} modeled / ${provider.source}`} station={station} />)}</footer>
      </section>
    </div>
  </div>, document.body);
}
