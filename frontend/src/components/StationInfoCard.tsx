import { ArrowDown, ArrowRight, ArrowUp, Gauge, Pin, X } from "lucide-react";
import { memo, useLayoutEffect } from "react";
import { sparklinePath, stationIsStale, withStationHistory, type InfoRow, type StationCardData, type StationHistory } from "./stationInfo";

interface Props {
  data: StationCardData; pinned: boolean; history?: StationHistory; historyState?: string;
  onClose: () => void; onPin: () => void; onInspect: () => void; onLayout: () => void;
}
export const StationInfoCard = memo(function StationInfoCard({ data: original, pinned, history, historyState, onClose, onPin, onInspect, onLayout }: Props) {
  useLayoutEffect(onLayout, [original, pinned, history, historyState, onLayout]);
  const data = withStationHistory(original, history);
  const stale = stationIsStale(data);
  const path = history ? sparklinePath(history.samples) : undefined;
  const Arrow = data.trendDirection === "up" ? ArrowUp : data.trendDirection === "down" ? ArrowDown : ArrowRight;
  const table = (rows: InfoRow[], label: string) => rows.length > 0 && <table aria-label={label}><tbody>{rows.map((row) => <tr key={row.label}><th scope="row">{row.label}</th><td>{row.value}{row.source && <small className="station-info-source">Source: {row.source}</small>}</td></tr>)}</tbody></table>;
  const metadata = <dl>{data.meta.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>;
  return <article className="station-info-card" role="dialog" aria-label={`${data.name} station information`} data-station-id={data.stationId ?? data.id} data-pinned={pinned}>
    <header><div><h3>{data.name}</h3><small>{data.latitude.toFixed(5)} N / {data.longitude.toFixed(5)} E</small></div>
      <button type="button" title="Pin station card" aria-label="Pin station card" aria-pressed={pinned} onClick={onPin}><Pin size={15} /></button>
      <button type="button" title="Close station card" aria-label="Close station card" onClick={onClose}><X size={16} /></button></header>
    <div className="station-info-scroll">
      {data.kind === "reference" ? <><p className="station-reference-note">Planning reference, not an active monitoring station</p>{metadata}</> : <>
        <div className="station-info-status"><span className={`station-status-chip status-${stale ? "unavailable" : data.status.toLowerCase()}`}>{stale ? "Unavailable" : data.status}</span>{stale && <span className="station-stale-badge">stale</span>}</div>
        {stale && <p className="station-no-data">No recent data</p>}
        {table(data.readings.map((row) => stale && /Current|Station discharge/.test(row.label) ? { ...row, label: "Last recorded discharge" } : row), "Station readings")}
        {metadata}
        {table(data.thresholds, "Station thresholds")}
        {data.dangerMessage && <p>{data.dangerMessage}</p>}
        {data.trendDirection && <div className="station-trend"><Arrow size={15} /><span>{data.trendDirection === "up" ? "Rising" : data.trendDirection === "down" ? "Falling" : "Steady"}{data.trendModeled ? " (modeled)" : ""}</span></div>}
        {table(data.trend, "Station trend")}
        {pinned && historyState && <small className="station-info-source">{historyState}</small>}
        {path && <figure className="station-sparkline"><svg viewBox="0 0 300 52" role="img" aria-label="Stored discharge observations over the last 48 hours"><path d={path} fill="none" stroke="currentColor" strokeWidth="2" /></svg><figcaption>{history?.source} / 48h / cumecs</figcaption></figure>}
      </>}
      {data.sourceUrl && <a href={data.sourceUrl} target="_blank" rel="noreferrer">Location reference</a>}
      {pinned && data.stationId && <button type="button" className="station-info-inspect" onClick={onInspect}><Gauge size={14} /> Open station details</button>}
    </div><i className="station-info-pointer" aria-hidden="true" />
  </article>;
});
