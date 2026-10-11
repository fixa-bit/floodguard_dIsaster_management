import { Download, ImageDown, Menu } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { ExperimentalHydrograph } from "../types/api";
import { chartData, CUSECS_PER_CUMEC, hydrographCsv, pktTime, pointTime, validFlow } from "./experimentalHydrographData";

const thresholdColors: Record<string, string> = { low: "#4de2a3", medium: "#ffc857", high: "#fb923c", veryHigh: "#ef476f", exceptional: "#c084fc" };
const thresholdLabels: Record<string, string> = { low: "Low", medium: "Medium", high: "High", veryHigh: "Very high", exceptional: "Exceptional" };
const dayLabel = (t: number) => new Intl.DateTimeFormat("en-PK", { day: "numeric", month: "short", timeZone: "Asia/Karachi" }).format(t);
function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob); const link = document.createElement("a");
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ExperimentalHydrographChart({ data, days }: { data: ExperimentalHydrograph; days: 5 | 30 }) {
  const [unit, setUnit] = useState<"cusecs" | "cumecs">("cusecs");
  const [align, setAlign] = useState(false);
  const [showThresholds, setShowThresholds] = useState(true);
  const [hidden, setHidden] = useState<string[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const [menu, setMenu] = useState(false);
  const [exportError, setExportError] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const plot = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const frame = useRef<number | null>(null);
  useEffect(() => () => { if (frame.current !== null) cancelAnimationFrame(frame.current); }, []);
  useEffect(() => {
    const element = plot.current;
    if (!element) return;
    const resize = () => setWidth(Math.max(220, Math.min(900, element.clientWidth - 110)));
    resize();
    const observer = new ResizeObserver(resize); observer.observe(element);
    return () => observer.disconnect();
  }, [data]);
  const { observed, forecast, offset } = useMemo(() => chartData(data, align), [data, align]);
  const convert = (v: number) => unit === "cumecs" ? v / CUSECS_PER_CUMEC : v;
  const number = (v: unknown) => validFlow(v) ? convert(v).toLocaleString("en-PK", { maximumFractionDigits: unit === "cusecs" ? 0 : 1 }) : "Unavailable";
  const unitLabel = unit === "cumecs" ? "m3/s" : "cusecs";
  const shown = (id: string) => !hidden.includes(id);
  const now = useMemo(() => Date.now(), [data]);
  const start = new Date(now).setUTCHours(0, 0, 0, 0) - 7 * 86400000;
  const end = Math.max(new Date(now).setUTCHours(0, 0, 0, 0) + (days - 1) * 86400000, ...forecast.map((p) => pointTime(p.t)), now + 86400000);
  const references = [...Object.entries(data.thresholds).filter(([, v]) => validFlow(v)).map(([id, v]) => ({ id, value: v!, label: `${thresholdLabels[id]} threshold`, color: thresholdColors[id] })),
    ...(validFlow(data.highestRecorded.value) ? [{ id: "highest", value: data.highestRecorded.value, label: `Highest recorded flow${data.highestRecorded.date ? ` / ${data.highestRecorded.date}` : ""}`, color: "#83dfaf" }] : [])];
  const activeRefs = showThresholds ? references.filter((item) => shown(item.id)) : [];
  const values = [...(shown("observed") ? observed.map((p) => p.v) : []), ...(shown("forecast") ? forecast.map((p) => p.v) : []),
    ...(shown("band") ? forecast.flatMap((p) => [p.p25, p.p75]) : []), ...activeRefs.map((item) => item.value)].filter(validFlow);
  const max = Math.max(1, ...values) * 1.12;
  const height = 180;
  const x = (t: string | number) => ((typeof t === "string" ? pointTime(t) : t) - start) / (end - start) * width;
  const y = (v: number) => height * (1 - v / max);
  const path = (points: Array<{ t: string; v: number | null }>) => {
    let connected = false;
    return points.map((p) => {
      if (!validFlow(p.v)) { connected = false; return ""; }
      const result = `${connected ? "L" : "M"}${x(p.t).toFixed(2)},${y(p.v).toFixed(2)}`;
      connected = true; return result;
    }).join(" ");
  };
  const bands: Array<typeof forecast> = [];
  let segment: typeof forecast = [];
  for (const p of forecast) {
    if (validFlow(p.p25) && validFlow(p.p75) && p.p25 <= p.p75) segment.push(p);
    else if (segment.length) { bands.push(segment); segment = []; }
  }
  if (segment.length) bands.push(segment);
  const nearest = (points: Array<{ t: string; v: number | null }>, t: number, tolerance: number) => {
    const best = points.filter((p) => validFlow(p.v)).reduce<{ t: string; v: number | null } | undefined>((best, p) => !best || Math.abs(pointTime(p.t) - t) < Math.abs(pointTime(best.t) - t) ? p : best, undefined);
    return best && Math.abs(pointTime(best.t) - t) <= tolerance ? best : undefined;
  };
  const observedHover = hover === null || !shown("observed") ? undefined : nearest(observed, hover, 3 * 3600000);
  const forecastHover = hover === null || !shown("forecast") ? undefined : nearest(forecast, hover, 12 * 3600000);
  const tableRows = [...observed.map((p) => ({ ...p, type: "Observed" })), ...forecast.map((p) => ({ ...p, type: "Forecast" }))].sort((a, b) => pointTime(a.t) - pointTime(b.t));
  const exportPng = async () => {
    setExportError(false); setMenu(false);
    let url: string | undefined;
    try {
      const cloned = svg.current!.cloneNode(true) as SVGSVGElement;
      cloned.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(cloned)], { type: "image/svg+xml;charset=utf-8" }));
      const image = new Image();
      await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = reject; image.src = url!; });
      const canvas = document.createElement("canvas"); canvas.width = 1800; canvas.height = 800;
      const context = canvas.getContext("2d")!; context.fillStyle = "#0a2428"; context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#e2f1ef"; context.font = "24px Arial";
      context.fillText(`${data.station.river} at ${data.station.name} / Experimental Forecast`, 24, 34);
      context.font = "16px Arial"; context.fillText(`Discharge (${unitLabel}) / ${align ? "display-only alignment applied" : "raw model values"}`, 24, 60);
      context.drawImage(image, 0, 72, 1800, 650);
      context.fillStyle = "#e2f1ef"; context.fillText("Blue: observed inflow / Red: experimental forecast / Shading: p25 - p75", 24, 746);
      context.fillStyle = "#ff7686"; context.fillText("Experimental GloFAS simulation. Use caution when interpreting.", 24, 778);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("PNG export unavailable");
      download(blob, `${data.station.station_id}-experimental-hydrograph.png`);
    } catch { setExportError(true); }
    finally { if (url) URL.revokeObjectURL(url); }
  };
  return <div className="experimental-chart-surface">
    <div className="experimental-chart-toolbar">
      <div className="station-details-tabs" role="group" aria-label="Hydrograph unit">{(["cusecs", "cumecs"] as const).map((value) => <button type="button" key={value} aria-pressed={unit === value} onClick={() => setUnit(value)}>{value === "cumecs" ? "m3/s" : "Cusecs"}</button>)}</div>
      <label><input type="checkbox" checked={showThresholds} onChange={(e) => setShowThresholds(e.target.checked)} />Show thresholds</label>
      <div className="experimental-export"><button type="button" aria-label="Export hydrograph" title="Export hydrograph" aria-expanded={menu} onClick={() => setMenu(!menu)}><Menu size={18} /></button>
        {menu && <div role="group" aria-label="Export formats"><button type="button" onClick={exportPng}><ImageDown size={15} />PNG</button><button type="button" onClick={() => { download(new Blob([hydrographCsv(data, align)], { type: "text/csv;charset=utf-8" }), `${data.station.station_id}-experimental-hydrograph.csv`); setMenu(false); }}><Download size={15} />CSV</button></div>}
      </div>
    </div>
    <label className="experimental-align"><input type="checkbox" checked={align} disabled={!observed.length || !forecast.length} onChange={(e) => setAlign(e.target.checked)} />Align forecast to last observed value</label>
    {align && <p className="experimental-notice">Display-only alignment applied: {offset >= 0 ? "+" : ""}{offset.toLocaleString("en-PK", { maximumFractionDigits: 1 })} cusecs. This is not calibration; negative shifted values are omitted.</p>}
    {exportError && <p role="alert">PNG export failed. Please try again.</p>}
    {observed.length || forecast.length ? <div className="station-forecast-chart" onPointerLeave={() => { if (frame.current !== null) { cancelAnimationFrame(frame.current); frame.current = null; } setHover(null); }}>
      <div className="station-forecast-y-label">Discharge ({unitLabel})</div>
      <div ref={plot} className="station-forecast-plot" tabIndex={0} aria-label="Experimental discharge chart" onKeyDown={(e) => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); setHover((v) => Math.max(start, Math.min(end, (v ?? now) + (e.key === "ArrowLeft" ? -1 : 1) * 86400000))); } }}
        onPointerMove={(e) => {
          const point = svg.current!.createSVGPoint(); point.x = e.clientX; point.y = e.clientY;
          const transform = svg.current!.getScreenCTM(); if (!transform) return;
          const t = start + Math.max(0, Math.min(1, point.matrixTransform(transform.inverse()).x / width)) * (end - start);
          if (frame.current !== null) cancelAnimationFrame(frame.current);
          frame.current = requestAnimationFrame(() => { setHover(t); frame.current = null; });
        }}>
        <svg ref={svg} viewBox={`-90 -24 ${width + 110} ${height + 70}`} role="img" aria-label={`${data.station.name} experimental hydrograph`} fontFamily="Arial, sans-serif" fontSize="12" fill="#b3ceca">
          {[0, .25, .5, .75, 1].map((tick) => <g key={tick}><line x1={0} x2={width} y1={height * tick} y2={height * tick} stroke="#355150" /><text x={-12} y={height * tick + 4} textAnchor="end">{number(max * (1 - tick))}</text><text x={width * tick} y={height + 30} textAnchor={tick === 0 ? "start" : tick === 1 ? "end" : "middle"}>{dayLabel(start + tick * (end - start))}</text></g>)}
          {shown("band") && bands.map((points, i) => <path key={i} d={`${path(points.map((p) => ({ t: p.t, v: p.p75 })))} ${path([...points].reverse().map((p) => ({ t: p.t, v: p.p25 }))).replace(/^M/, "L")} Z`} fill="#ff7686" opacity={.16} />)}
          {activeRefs.map((line) => <g key={line.id}><line x1={0} x2={width} y1={y(line.value)} y2={y(line.value)} stroke={line.color} strokeWidth={1.5} strokeDasharray="6 3" /><text x={width - 4} y={y(line.value) - 4} textAnchor="end" fill={line.color}>{width < 500 ? line.id === "highest" ? "Record" : thresholdLabels[line.id] : line.label}: {number(line.value)}</text></g>)}
          {shown("observed") && <g><path d={path(observed)} stroke="#6baeff" strokeWidth={2} fill="none" />{observed.map((p) => <circle key={p.t} cx={x(p.t)} cy={y(p.v)} r={3} fill="#6baeff" />)}</g>}
          {shown("forecast") && <g>{shown("observed") && observed.at(-1) && forecast[0] && validFlow(forecast[0].v) && <path d={path([observed.at(-1)!, forecast[0]])} stroke="#ff7686" strokeDasharray="4 4" fill="none"><title>Observed-to-model connector; not a measurement or calibration</title></path>}<path d={path(forecast)} stroke="#ff7686" strokeWidth={2} fill="none" />{forecast.filter((p) => validFlow(p.v)).map((p) => <circle key={p.t} cx={x(p.t)} cy={y(p.v!)} r={3} fill="#ff7686" />)}</g>}
          <line x1={x(now)} x2={x(now)} y1={0} y2={height} stroke="#dce9e5" strokeDasharray="3 4" /><text x={x(now) + 4} y={-10}>Now</text>
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="#dce9e5" opacity={.65} />}
        </svg>
        {hover !== null && <div className="station-chart-tooltip" style={{ left: `${Math.max(0, Math.min(60, (hover - start) / (end - start) * 100))}%` }}><strong>{pktTime(hover)}</strong>
          {observedHover && <div><span>Observed inflow</span><b>{number(observedHover.v)} {unitLabel}</b><small>{pktTime(observedHover.t)}</small></div>}
          {forecastHover && <div><span>Forecast / Experimental{align ? " / shifted" : ""}</span><b>{number(forecastHover.v)} {unitLabel}</b><small>{pktTime(forecastHover.t)} / daily model value</small></div>}
        </div>}
      </div>
    </div> : <p>No data available.</p>}
    <div className="station-forecast-legend">
      {[{ id: "observed", name: "Observed inflow", color: "#6baeff" }, { id: "forecast", name: "Forecast / Experimental", color: "#ff7686" }, { id: "band", name: "p25 - p75", color: "#ff7686" }, ...references.map((line) => ({ id: line.id, name: line.label, color: line.color }))].map((item) => <label key={item.id}><input type="checkbox" checked={shown(item.id)} onChange={(e) => setHidden((previous) => e.target.checked ? previous.filter((id) => id !== item.id) : [...previous, item.id])} /><i style={{ background: item.color }} />{item.name}</label>)}
    </div>
    <div className="station-forecast-table experimental-data-table" tabIndex={0} aria-label="Experimental hydrograph values"><table><thead><tr><th>River</th><th>Location</th><th>Highest Recorded Flow</th>{tableRows.map((p) => <th key={`${p.type}:${p.t}`}>{dayLabel(pointTime(p.t))}<small>{p.type}</small></th>)}</tr></thead><tbody><tr><td>{data.station.river}</td><td>{data.station.name}</td><td>{number(data.highestRecorded.value)}{data.highestRecorded.date && <small>{data.highestRecorded.date}</small>}</td>{tableRows.map((p) => <td key={`${p.type}:${p.t}`} className={p.type === "Forecast" ? "experimental-forecast-cell" : undefined} title={`${pktTime(p.t)} / ${p.type}`}>{number(p.v)}</td>)}</tr></tbody></table></div>
    <p className="experimental-disclaimer">Experimental forecast based on GloFAS model output. It may be less accurate than observed data. Use caution when interpreting.</p>
  </div>;
}

export default memo(ExperimentalHydrographChart);
