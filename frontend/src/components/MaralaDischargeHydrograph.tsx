import { useState, type PointerEvent } from "react";
import type { MaralaMonthlyModelData } from "../types/api";
import { DAY_MS, dischargePoints, dischargeSegments, type DischargePoint, type HydrographMode } from "./maralaDischargeData";

const formatValue = (value: number) => value.toLocaleString("en-GB", { maximumFractionDigits: 1 });
const monthLabel = (time: number) => new Date(time).toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
const dateLabel = (time: number) => new Date(time).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Karachi" });
function pointLabel(point: DischargePoint) {
  if (point.resolution === "monthly") return `${monthLabel(point.time)}: ${formatValue(point.value)} m³/s - ${point.kind === "history" ? "observed monthly average" : "forecast monthly average"} (${point.days}/${point.calendarDays} days${point.days !== point.calendarDays ? "; partial" : ""})`;
  return point.kind === "history"
    ? `${dateLabel(point.time)}, 06:00 PKT: ${formatValue(point.value)} m³/s - measured inflow`
    : `${dateLabel(point.time)}: ${formatValue(point.value)} m³/s - forecast daily mean (UTC day; not a 06:00 prediction)`;
}

export function MaralaDischargeHydrograph({ data }: { data: MaralaMonthlyModelData }) {
  const [mode, setMode] = useState<HydrographMode>("daily");
  const [selected, setSelected] = useState<string | null>(null);
  const points = dischargePoints(data, mode);
  const history = points.filter(point => point.kind === "history");
  const forecast = points.filter(point => point.kind === "forecast");
  if (!points.length) return <p>No discharge data available.</p>;

  const width = 820, height = 390;
  const left = 78, right = 30, top = 30, bottom = 65;
  const chartWidth = width - left - right, chartHeight = height - top - bottom;
  const min = Math.min(...points.map(point => point.value));
  const max = Math.max(...points.map(point => point.value), 1);
  const step = 10 ** Math.floor(Math.log10(Math.max(max - min, 1))) / 2;
  const floor = Math.max(0, Math.floor(min * .85 / step) * step);
  const ceiling = Math.max(floor + step, Math.ceil(max * 1.1 / step) * step);
  const first = new Date(points[0].time);
  const last = new Date(points.at(-1)!.time);
  const firstForecast = points.find(point => point.kind === "forecast");
  const forecastStart = firstForecast ? Date.parse(`${firstForecast.date}${mode === "monthly" ? "-01" : ""}T00:00:00Z`) : null;
  const start = data.recent_history ? Date.parse(`${data.recent_history.period_start}T00:00:00Z`) : Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate() - 1);
  const end = mode === "monthly" ? Date.UTC(last.getUTCFullYear(), last.getUTCMonth() + 1, 1) : Math.max(Date.parse(`${data.current_provider_outlook.forecast_available_through}T00:00:00Z`) + DAY_MS, Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), last.getUTCDate() + 1));
  const requestedDays = Math.round((Date.parse(data.current_provider_outlook.forecast_available_through) - Date.parse(data.current_provider_outlook.forecast_issue_start)) / DAY_MS) + 1;
  const maxMonths = mode === "daily" ? Math.ceil(requestedDays / 30.4375) : forecast.length;
  const x = (time: number) => left + (time - start) / (end - start) * chartWidth;
  const y = (value: number) => top + (ceiling - value) / (ceiling - floor) * chartHeight;
  const highest = history.length ? history.reduce((best, point) => point.value > best.value ? point : best) : null;
  const active = points.find(point => point.key === selected) ?? history.at(-1) ?? firstForecast ?? points.at(-1)!;
  const ticks: number[] = [];
  const spanMonths = (last.getUTCFullYear() - first.getUTCFullYear()) * 12 + last.getUTCMonth() - first.getUTCMonth();
  const interval = spanMonths > 18 ? 6 : spanMonths > 8 ? 2 : 1;
  const showDailyTicks = mode === "daily" && end - start < 100 * DAY_MS;
  if (showDailyTicks) {
    const step = end - start > 45 * DAY_MS ? 14 : 7;
    for (let time = start; time < end; time += step * DAY_MS) ticks.push(time);
  } else {
    for (let month = first.getUTCMonth(); ; month += interval) {
      const time = Date.UTC(first.getUTCFullYear(), month, 1);
      if (time >= end) break;
      if (time >= start) ticks.push(time);
    }
  }
  if (ticks.every(time => time - start > 20 * DAY_MS)) ticks.unshift(start);
  const lastMonth = Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), 1);
  if (ticks.every(time => Math.abs(lastMonth - time) > 70 * DAY_MS)) ticks.push(lastMonth);

  function selectNearest(event: PointerEvent<SVGSVGElement>) {
    const svg = event.currentTarget;
    const transform = svg.getScreenCTM();
    if (!transform) return;
    const cursor = svg.createSVGPoint();
    cursor.x = event.clientX; cursor.y = event.clientY;
    const position = cursor.matrixTransform(transform.inverse());
    if (position.x < left || position.x > width - right || position.y < top || position.y > height - bottom) return;
    const time = start + (position.x - left) / chartWidth * (end - start);
    const nearest = points.reduce((best, point) => Math.abs(point.time - time) < Math.abs(best.time - time) ? point : best);
    setSelected(nearest.key);
  }
  const tooltipX = Math.max(left + 4, Math.min(x(active.time) + 12, width - right - 292));
  const tooltipY = Math.max(top + 8, Math.min(y(active.value) - 90, height - bottom - 95));

  function selectMode(next: HydrographMode) { setMode(next); setSelected(null); }
  return <figure className="marala-prediction-chart marala-hydrograph" data-mode={mode} data-max-months={maxMonths} data-history-start={data.recent_history?.period_start} data-history-end={data.recent_history?.period_end}>
    <div className="marala-resolution-tabs" role="tablist" aria-label="Discharge time resolution">
      {([["daily", "Daily"], ["monthly", "Monthly averages"]] as const).map(([id, text]) => <button type="button" role="tab" id={`marala-resolution-${id}`} aria-controls="marala-hydrograph-panel" aria-selected={mode === id} tabIndex={mode === id ? 0 : -1} key={id} onClick={() => selectMode(id)} onKeyDown={event => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          event.preventDefault(); const next = event.key === "Home" ? "daily" : event.key === "End" ? "monthly" : mode === "daily" ? "monthly" : "daily";
          selectMode(next); document.getElementById(`marala-resolution-${next}`)?.focus();
        }
      }}>{text}</button>)}
    </div>
    <div role="tabpanel" id="marala-hydrograph-panel" aria-labelledby={`marala-resolution-${mode}`}>
    <div className="marala-hydrograph-paper">
      <figcaption><strong>Marala · Chenab</strong><span>{mode === "daily" ? "Daily discharge" : "Monthly average discharge"} · m³/s</span><small>2-year history · {mode === "daily" ? `Maximum horizon: ~${maxMonths} months (${requestedDays} days)` : `Maximum complete-month horizon: ${maxMonths} months`}</small><small className="marala-forecast-horizon">{forecast.length ? mode === "daily" ? `${forecast.length} available daily forecasts · ${dateLabel(forecast[0].time)} – ${dateLabel(forecast.at(-1)!.time)}` : `${monthLabel(forecast[0].time)} – ${monthLabel(forecast.at(-1)!.time)}` : "Forecast unavailable"}</small></figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={`Marala ${mode} observed and forecast discharge hydrograph`} onPointerMove={selectNearest} onPointerLeave={() => setSelected(null)}>
        <title>Marala {mode} observed and forecast discharge</title>
        <desc>{mode === "daily" ? `Blue: measured inflow at 06:00 PKT over the full two-year window. Red: modeled daily means over the maximum ${requestedDays}-day forecast window, not instantaneous predictions.` : "Blue: average of available measured readings per month over the full two-year window. Red: average daily forecasts over all complete forecast months. Partial historical coverage is shown in the point label."} Missing dates break lines; sources are separate.</desc>
        {forecastStart !== null && <rect x={x(forecastStart)} y={top} width={width - right - x(forecastStart)} height={chartHeight} className="marala-forecast-region" />}
        {[0, 1, 2, 3, 4].map(index => {
          const value = floor + (ceiling - floor) * index / 4;
          return <g key={index}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} className="marala-prediction-grid" /><text x={left - 12} y={y(value) + 4} textAnchor="end">{formatValue(value)}</text></g>;
        })}
        <text transform={`translate(19 ${top + chartHeight / 2}) rotate(-90)`} textAnchor="middle">Discharge (m³/s)</text>
        {highest && <line x1={left} x2={width - right} y1={y(highest.value)} y2={y(highest.value)} className="marala-highest-line" />}
        {forecastStart !== null && <><line x1={x(forecastStart)} x2={x(forecastStart)} y1={top} y2={height - bottom} className="marala-forecast-boundary" /><text x={x(forecastStart) + 6} y={top + 15} className="marala-forecast-area-label">Forecast</text></>}
        {(["history", "forecast"] as const).flatMap(kind => dischargeSegments(points, kind).map((group, index) => <polyline key={`${kind}-${index}`} points={group.map(point => `${x(point.time)},${y(point.value)}`).join(" ")} className={`marala-prediction-line marala-${kind}-line`} />))}
        {points.map(point => {
          const handlers = { tabIndex: 0, "aria-label": pointLabel(point), onFocus: () => setSelected(point.key), onClick: () => setSelected(point.key), onPointerEnter: () => setSelected(point.key) };
          return point.kind === "history"
            ? <circle key={point.key} {...handlers} className="marala-history-point" cx={x(point.time)} cy={y(point.value)} r="3"><title>{pointLabel(point)}</title></circle>
            : <polygon key={point.key} {...handlers} className="marala-forecast-point" points={`${x(point.time)},${y(point.value) - 4} ${x(point.time) + 4},${y(point.value)} ${x(point.time)},${y(point.value) + 4} ${x(point.time) - 4},${y(point.value)}`}><title>{pointLabel(point)}</title></polygon>;
        })}
        {ticks.map(time => <text key={time} x={x(time)} y={height - bottom + 24} textAnchor="middle">{showDailyTicks ? new Date(time).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : monthLabel(time)}</text>)}
        <text x={left + chartWidth / 2} y={height - 8} textAnchor="middle">Date</text>
        {selected && <g className="marala-hydrograph-tooltip" pointerEvents="none">
          <line x1={x(active.time)} x2={x(active.time)} y1={top} y2={height - bottom} className="marala-date-cursor" />
          <circle cx={x(active.time)} cy={y(active.value)} r="6" className="marala-active-point" />
          <rect x={tooltipX} y={tooltipY} width="288" height={highest ? 89 : 70} rx="4" />
          <text x={tooltipX + 12} y={tooltipY + 23} className="marala-tooltip-date">{mode === "monthly" ? `${monthLabel(active.time)} · monthly average` : active.kind === "history" ? `${dateLabel(active.time)}, 06:00 PKT` : `${dateLabel(active.time)} · daily mean`}</text>
          <text x={tooltipX + 12} y={tooltipY + 46} className={`marala-tooltip-${active.kind}`}>{active.kind === "history" ? mode === "monthly" ? "Observed average" : "Observed inflow" : "Forecast mean"}: {formatValue(active.value)} m³/s</text>
          {highest && <text x={tooltipX + 12} y={tooltipY + 70} className="marala-tooltip-highest">Highest in view: {formatValue(highest.value)} m³/s</text>}
        </g>}
      </svg>
      <div className="marala-chart-legend"><span><i className="marala-history-key" />Observed · {mode === "daily" ? "06:00 PKT" : "monthly average"}</span><span><i className="marala-forecast-key" />Forecast · {mode === "daily" ? "daily mean" : "monthly average"}</span>{highest && <span><i className="marala-highest-key" />Highest observed in view</span>}</div>
      <p className="marala-chart-point-value" aria-live="polite">{pointLabel(active)}</p>
    </div>
    <p className="marala-prediction-caption">{mode === "daily" ? "Past readings are instantaneous at 06:00 PKT. The forecast source supplies daily means, not instantaneous predictions. All available forecast days are shown." : "Both series average daily values by month. Past averages use available 06:00 readings; future averages use complete months of daily forecasts. Partial future months are excluded."} Gaps remain blank.</p>
    </div>
  </figure>;
}
