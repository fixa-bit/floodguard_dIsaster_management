import { ExternalLink, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useChartBox } from "../hooks/useChartBox";

import { api } from "../services/api";
import type { MaralaStationForecastData } from "../types/api";

type Data = MaralaStationForecastData;
type Lead = 1 | 3 | 7;
type Role = "champion" | "best_learned";

const DAY = 86_400_000;
const REFRESH_INTERVAL_MS = 15 * 60_000;
const HISTORY_SHOWN_DAYS = 21;
const pkDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Karachi" });
const pkDateYear = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Karachi" });

const flow = (value: number | null | undefined) => value === null || value === undefined ? "—" : Math.round(value).toLocaleString();
const day = (value: string) => pkDate.format(new Date(value));

export function candidateLabel(id: string) {
  if (id === "training_median") return "Training median (baseline)";
  if (id === "persistence") return "Persistence";
  const ridge = id.match(/^ridge_log_return_([\d.]+)$/);
  if (ridge) return `Ridge regression · log change · α ${Number(ridge[1]).toLocaleString()}`;
  if (id.startsWith("xgboost")) return `XGBoost · ${id.replace(/^xgboost_?/, "").replaceAll("_", " ")}`;
  if (id.startsWith("damped")) return `Damped trend · ${id.replace(/^damped_?trend_?/, "").replaceAll("_", " ")}`;
  return id.replaceAll("_", " ");
}

function forecastCandidates(item: Data["forecasts"][number]) {
  if (item.candidates?.length) return item.candidates.slice(0, 3);
  const unique = new Map([item.champion, item.best_learned].map((candidate) => [candidate.candidate, candidate]));
  return [...unique.values()];
}

function niceMax(value: number) {
  const step = 10 ** Math.floor(Math.log10(value)) / 2;
  return Math.ceil(value / step) * step;
}

function floodClass(value: number, thresholds: Record<string, number>) {
  const passed = Object.entries(thresholds).filter(([, limit]) => value >= limit);
  return passed.length ? `${passed[passed.length - 1][0]} flood` : "Below low flood";
}

function linePath(points: Array<[number, number | null]>, maxGapX: number) {
  let path = "";
  let previous: number | null = null;
  for (const [x, y] of points) {
    if (y === null) { previous = null; continue; }
    path += `${previous === null || x - previous > maxGapX ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)} `;
    previous = x;
  }
  return path.trim();
}

function ForecastChart({ data }: { data: Data }) {
  const box = useChartBox({ aspect: 0.36, minHeight: 230, maxHeight: 340 });
  const { width, height, narrow } = box;
  const hasTopThree = data.forecasts.every((item) => (item.candidates?.length ?? 0) >= 3);
  const left = 58, right = 18, top = 22, bottom = 36;
  const origin = Date.parse(data.origin.observed_at);
  const history = data.history.filter((row) => row.inflow_cumecs !== null && Date.parse(row.observed_at) >= origin - (narrow ? 10 : HISTORY_SHOWN_DAYS) * DAY);
  const start = Date.parse(history[0].observed_at);
  const end = Math.max(...data.forecasts.map((item) => Date.parse(item.target_at))) + DAY;
  const low = data.thresholds_cumecs.Low;
  const peakForecast = Math.max(...data.forecasts.flatMap((item) => forecastCandidates(item).map((candidate) => candidate.inflow_cumecs)));
  const maxValue = niceMax(Math.max(low * 1.12, peakForecast, ...history.map((row) => row.inflow_cumecs ?? 0)));
  const x = (time: number) => left + (time - start) / (end - start) * (width - left - right);
  const y = (value: number) => top + (1 - Math.max(value, 0) / maxValue) * (height - top - bottom);
  const ticks: number[] = [];
  for (let time = start; time <= end; time += (narrow ? 4 : 7) * DAY) ticks.push(time);
  const forecastPaths = [0, 1, 2].map((rank) => `M ${x(origin)} ${y(data.origin.inflow_cumecs)} ` + data.forecasts.map((item) => {
    const candidate = forecastCandidates(item)[rank];
    return candidate ? `L ${x(Date.parse(item.target_at))} ${y(candidate.inflow_cumecs)}` : "";
  }).filter(Boolean).join(" "));

  return (
    <figure className="station-chart">
      <ul className="station-legend" aria-label="Chart legend">
        <li><i className="key-measured" /> Measured inflow (FFD, 06:00 PKT)</li>
        <li><i className="key-model" /> {hasTopThree ? "Top 1 by validation RMSE" : "Saved model"}</li>
        <li><i className="key-model key-model-2" /> {hasTopThree ? "Top 2" : "Saved learned alternative"}</li>
        {hasTopThree && <li><i className="key-model key-model-3" /> Top 3</li>}
        <li><i className="key-persistence" /> Persistence (no change)</li>
        <li><i className="key-threshold" /> Low-flood limit</li>
      </ul>
      <div ref={box.ref}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Marala inflow: measured history and ${data.forecasts.map((item) => `+${item.horizon_days} day forecast ${flow(item.champion.inflow_cumecs)} cubic metres per second`).join(", ")}`}>
        <rect className="station-forecast-zone" x={x(origin)} y={top} width={x(end) - x(origin)} height={height - top - bottom} />
        <text className="station-zone-label" x={x(origin) + 6} y={top + 13}>{narrow ? "Forecast" : "Forecast window"}</text>
        {[0, 1, 2, 3, 4].map((step) => {
          const value = maxValue * step / 4;
          return <g key={step}><line className="station-grid" x1={left} x2={width - right} y1={y(value)} y2={y(value)} /><text className="station-axis" x={left - 8} y={y(value) + 4} textAnchor="end">{value.toLocaleString()}</text></g>;
        })}
        {ticks.map((time) => <text key={time} className="station-axis" x={x(time)} y={height - bottom + 18} textAnchor="middle">{pkDate.format(new Date(time))}</text>)}
        <text className="station-axis-title" x={8} y={12}>Inflow (m³/s)</text>
        <line className="station-threshold" x1={left} x2={width - right} y1={y(low)} y2={y(low)} />
        <text className="station-threshold-label" x={left + 6} y={y(low) - 6}>Low flood · {flow(low)} m³/s</text>
        <path className="station-measured" d={linePath(history.map((row) => [x(Date.parse(row.observed_at)), y(row.inflow_cumecs as number)]), x(start + 2.5 * DAY) - x(start))} />
        <line className="station-persistence" x1={x(origin)} x2={x(end - DAY)} y1={y(data.origin.inflow_cumecs)} y2={y(data.origin.inflow_cumecs)} />
        <line className="station-origin" x1={x(origin)} x2={x(origin)} y1={top} y2={height - bottom} />
        {forecastPaths.map((path, rank) => <path key={rank} className={`station-model-line candidate-${rank + 1}`} d={path} />)}
        {data.forecasts.map((item, index) => {
          const last = index === data.forecasts.length - 1;
          const cx = x(Date.parse(item.target_at));
          const candidates = forecastCandidates(item);
          const value = candidates[0]?.inflow_cumecs ?? item.champion.inflow_cumecs;
          return <g key={item.horizon_days}>
            {candidates.map((candidate, rank) => <circle key={candidate.candidate} className={`station-model-dot candidate-${rank + 1}`} cx={cx} cy={y(candidate.inflow_cumecs)} r={rank === 0 ? 5.5 : 4.5}><title>Top {rank + 1}, +{item.horizon_days} d ({candidateLabel(candidate.candidate)}): {flow(candidate.inflow_cumecs)} m³/s · validation RMSE {flow(candidate.validation_rmse_cumecs)} m³/s</title></circle>)}
            {!narrow && <text className="station-point-label" x={last ? cx - 9 : cx + 9} y={y(value) - 9} textAnchor={last ? "end" : "start"}>+{item.horizon_days}d · {flow(value)}</text>}
            <circle className="station-hit" cx={cx} cy={y(value)} r="14"><title>+{item.horizon_days} day ({day(item.target_at)} 06:00 PKT): {candidates.map((candidate, rank) => `Top ${rank + 1} ${flow(candidate.inflow_cumecs)} m³/s`).join(" · ")}</title></circle>
          </g>;
        })}
        <circle className="station-origin-dot" cx={x(origin)} cy={y(data.origin.inflow_cumecs)} r="4.5" />
        {history.map((row) => <circle key={row.observed_at} className="station-hit" cx={x(Date.parse(row.observed_at))} cy={y(row.inflow_cumecs as number)} r="7"><title>{day(row.observed_at)} 06:00 PKT measured: {flow(row.inflow_cumecs)} m³/s</title></circle>)}
      </svg>
      </div>
    </figure>
  );
}

function HindcastChart({ rows, low, role }: { rows: Data["holdout"]; low: number; role: Role }) {
  const box = useChartBox({ aspect: 0.3, minHeight: 200, maxHeight: 280, viewportShare: 0.35 });
  const { width, height } = box;
  const left = 58, right = 18, top = 18, bottom = 34;
  const times = rows.map((row) => Date.parse(row.target_at));
  const start = Math.min(...times), end = Math.max(...times);
  const maxValue = niceMax(Math.max(low * 1.1, ...rows.flatMap((row) => [row.actual ?? 0, row[role] ?? 0, row.persistence ?? 0])));
  const x = (time: number) => left + (time - start) / Math.max(end - start, DAY) * (width - left - right);
  const y = (value: number) => top + (1 - Math.max(value, 0) / maxValue) * (height - top - bottom);
  const gap = x(start + 2.5 * DAY) - x(start);
  const series = (key: "actual" | Role | "persistence") => linePath(rows.map((row) => [x(Date.parse(row.target_at)), row[key] === null ? null : y(row[key] as number)]), gap);
  const ticks: number[] = [];
  const first = new Date(start);
  for (let month = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1)).getTime(); month <= end; month = new Date(new Date(month).setUTCMonth(new Date(month).getUTCMonth() + 1)).getTime()) ticks.push(month);
  return (
    <div ref={box.ref}>
    <svg className="station-hindcast-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="2026 held-out season: measured inflow against model and persistence">
      {[0, 1, 2, 3, 4].map((step) => {
        const value = maxValue * step / 4;
        return <g key={step}><line className="station-grid" x1={left} x2={width - right} y1={y(value)} y2={y(value)} /><text className="station-axis" x={left - 8} y={y(value) + 4} textAnchor="end">{value.toLocaleString()}</text></g>;
      })}
      {ticks.map((time) => <text key={time} className="station-axis" x={x(time)} y={height - bottom + 18} textAnchor="middle">{pkDate.format(new Date(time))}</text>)}
      <line className="station-threshold" x1={left} x2={width - right} y1={y(low)} y2={y(low)} />
      <text className="station-threshold-label" x={width - right - 6} y={y(low) - 6} textAnchor="end">Low flood · {flow(low)} m³/s</text>
      <path className="station-persistence-line" d={series("persistence")} />
      <path className="station-measured" d={series("actual")} />
      <path className="station-model-hindcast" d={series(role)} />
      {rows.map((row) => <rect key={row.target_at} className="station-hit" x={x(Date.parse(row.target_at)) - 3} y={top} width="6" height={height - top - bottom}><title>{pkDateYear.format(new Date(row.target_at))} — measured {flow(row.actual)}, model {flow(row[role])}, persistence {flow(row.persistence)} m³/s</title></rect>)}
    </svg>
    </div>
  );
}

function SkillTiles({ skill }: { skill: Data["skill"][number] }) {
  const model = skill.test.champion;
  const persistence = skill.test.persistence;
  const change = (persistence.rmse_cumecs - model.rmse_cumecs) / persistence.rmse_cumecs * 100;
  const verdict = Math.abs(change) < 1 ? "Tie with persistence" : change > 0 ? `${change.toFixed(1)}% lower error` : `${Math.abs(change).toFixed(1)}% higher error`;
  const tone = Math.abs(change) < 1 ? "neutral" : change > 0 ? "good" : "bad";
  return (
    <div className="station-skill-tiles">
      <article className={`tone-${tone}`}><span>Error vs persistence</span><strong>{verdict}</strong><p>RMSE {flow(model.rmse_cumecs)} vs {flow(persistence.rmse_cumecs)} m³/s · {model.rows} days</p></article>
      <article><span>Fit (NSE, 1 = perfect)</span><strong>{model.nse.toFixed(2)}</strong><p>Persistence {persistence.nse.toFixed(2)} · MAE {flow(model.mae_cumecs)} m³/s</p></article>
      <article><span>Low-flood days caught</span><strong>{model.hits} of {model.flood_events_days}</strong><p>{model.false_alarms} false alarm{model.false_alarms === 1 ? "" : "s"} · persistence caught {persistence.hits}</p></article>
      <article><span>Season peak</span><strong>{flow(model.prediction_at_peak_cumecs)} <small>of {flow(model.peak_actual_cumecs)}</small></strong><p>{model.peak_error_percent.toFixed(0)}% on {day(model.peak_target_date)} · timing off {model.peak_timing_error_days} d</p></article>
    </div>
  );
}

export function MaralaStationForecast() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [packaged, setPackaged] = useState(false);
  const [lead, setLead] = useState<Lead>(1);
  const [role, setRole] = useState<Role>("champion");
  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.maralaStationForecast());
      setPackaged(false);
    } catch (cause) {
      try {
        const response = await fetch(`${import.meta.env.BASE_URL}data/marala-station-forecast.json`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setData(await response.json() as Data);
        setPackaged(true);
      } catch (fallback) {
        setError(`Backend: ${cause instanceof Error ? cause.message : "failed"}. Packaged copy: ${fallback instanceof Error ? fallback.message : "failed"}.`);
      }
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const holdoutRows = useMemo(() => (data?.holdout ?? []).filter((row) => row.horizon_days === lead).sort((a, b) => a.target_at.localeCompare(b.target_at)), [data, lead]);

  if (error) return <div className="station-state"><strong>Station forecast unavailable</strong><span>{error}</span><button type="button" onClick={() => void load()}>Retry</button></div>;
  if (!data) return <div className="station-state"><RefreshCw className="spinning" size={16} /><strong>Loading Marala station forecast</strong></div>;

  const now = Date.now();
  const originTime = Date.parse(data.origin.observed_at);
  const ageDays = Math.floor((now - originTime) / DAY);
  const lastTarget = Math.max(...data.forecasts.map((item) => Date.parse(item.target_at)));
  const expired = lastTarget < now;
  const selectedSkill = data.skill.find((item) => item.horizon_days === lead)!;
  const roleDiffers = selectedSkill.champion.candidate !== selectedSkill.best_learned.candidate;
  const activeRole: Role = roleDiffers ? role : "champion";
  const rollingForecast = data.forecast_mode === "rolling_live_origin";

  return (
    <section className="station-forecast" aria-label="Marala measured inflow forecast">
      <div className={`station-issue ${expired ? "stale" : ""}`}>
        <div>
          <span>Issued from</span>
          <strong>FFD reading {pkDateYear.format(new Date(originTime))}, 06:00 PKT · {flow(data.origin.inflow_cumecs)} m³/s</strong>
        </div>
        <p>{rollingForecast
          ? `Recomputed from the latest saved FFD reading (${ageDays} day${ageDays === 1 ? "" : "s"} old). Targets run to ${day(new Date(lastTarget).toISOString())}.`
          : expired
            ? `${ageDays} days old. All three target dates have passed — no fresh FFD origin was available, so this saved forecast was not re-run.`
            : `Saved forecast from ${ageDays} day${ageDays === 1 ? "" : "s"} ago. Targets run to ${day(new Date(lastTarget).toISOString())}.`}
          {packaged && " Showing the packaged copy; the backend route is unavailable."}</p>
      </div>

      <ForecastChart data={data} />

      <div className="station-table-wrap">
        <table className="station-table">
          <caption>{data.forecast_mode === "rolling_live_origin" ? "Top three models by validation RMSE · forecast by lead time" : "Saved forecast candidates · forecast by lead time"}</caption>
          <thead><tr><th scope="col">Lead</th><th scope="col">Target (06:00 PKT)</th><th scope="col">Rank</th><th scope="col">Model</th><th scope="col">Forecast (m³/s)</th><th scope="col">FFD class</th><th scope="col">Validation RMSE (m³/s)</th></tr></thead>
          <tbody>
            {data.forecasts.flatMap((item) => forecastCandidates(item).map((candidate, rank, candidates) => <tr key={`${item.horizon_days}:${candidate.candidate}`}>
              {rank === 0 && <th scope="rowgroup" rowSpan={candidates.length}>+{item.horizon_days} d</th>}
              {rank === 0 && <td rowSpan={candidates.length}>{day(item.target_at)}</td>}
              <td>#{rank + 1}</td>
              <td>{candidateLabel(candidate.candidate)}</td>
              <td className="num"><strong>{flow(candidate.inflow_cumecs)}</strong></td>
              <td>{floodClass(candidate.inflow_cumecs, data.thresholds_cumecs)}</td>
              <td className="num">{candidate.validation_rmse_cumecs == null ? "—" : flow(candidate.validation_rmse_cumecs)}</td>
            </tr>))}
          </tbody>
        </table>
      </div>

      <section className="station-hindcast" aria-label="Held-out 2026 season check">
        <header>
          <div><h3>How it did on the unseen 2026 season</h3><p>Each line point is a forecast made {lead} day{lead === 1 ? "" : "s"} earlier from measurements only, compared with the reading FFD later reported.</p></div>
          <div className="station-segmented" role="group" aria-label="Lead time">
            {([1, 3, 7] as Lead[]).map((value) => <button type="button" key={value} aria-pressed={lead === value} onClick={() => setLead(value)}>+{value} d</button>)}
          </div>
        </header>
        {roleDiffers && <div className="station-segmented station-role" role="group" aria-label="Model shown">
          <button type="button" aria-pressed={activeRole === "champion"} onClick={() => setRole("champion")}>Selected: {candidateLabel(selectedSkill.champion.candidate)}</button>
          <button type="button" aria-pressed={activeRole === "best_learned"} onClick={() => setRole("best_learned")}>Learned: {candidateLabel(selectedSkill.best_learned.candidate)}</button>
        </div>}
        <ul className="station-legend" aria-label="Held-out chart legend">
          <li><i className="key-measured" /> Measured</li>
          <li><i className="key-model" /> Model</li>
          <li><i className="key-persistence" /> Persistence</li>
          <li><i className="key-threshold" /> Low-flood limit</li>
        </ul>
        <HindcastChart rows={holdoutRows} low={data.thresholds_cumecs.Low} role={activeRole} />
        <SkillTiles skill={activeRole === "champion" ? selectedSkill : { ...selectedSkill, test: { ...selectedSkill.test, champion: selectedSkill.test.best_learned } }} />
      </section>

      <details className="station-details">
        <summary>Method, data and limits</summary>
        <dl>
          <div><dt>Target</dt><dd>{data.target}</dd></div>
          <div><dt>Data</dt><dd>{data.data.measured_days} measured FFD days, {data.data.first_day} to {data.data.last_day} ({Object.entries(data.data.years).map(([year, count]) => `${year}: ${count}`).join(", ")}). Missing days are never interpolated.</dd></div>
          <div><dt>Selection</dt><dd>{data.evaluation.selection}. {data.evaluation.test}.</dd></div>
          <div><dt>Final fit</dt><dd>{data.evaluation.production_refit}.</dd></div>
          <div><dt>Status</dt><dd>Research only · not deployment eligible · run {data.run_id}</dd></div>
        </dl>
        <ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        <a href={data.threshold_source} target="_blank" rel="noreferrer">FFD flood limits <ExternalLink size={11} /></a>
      </details>
    </section>
  );
}
