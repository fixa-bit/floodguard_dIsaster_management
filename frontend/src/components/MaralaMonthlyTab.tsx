import { Activity, Database, Download, RefreshCw, Waves } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../services/api";
import type { MaralaMonthlyModelData } from "../types/api";
import "../marala-monthly.css";
import { MaralaDischargeHydrograph } from "./MaralaDischargeHydrograph";

function number(value: number, digits = 0) {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function MaralaMonthlyTab() {
  const [data, setData] = useState<MaralaMonthlyModelData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceNotice, setSourceNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDetails, setShowDetails] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.maralaMonthlyModelData());
      setSourceNotice(null);
    } catch (cause) {
      try {
        const response = await fetch(`${import.meta.env.BASE_URL}data/marala-monthly.json`);
        if (!response.ok) throw new Error(`Packaged dataset returned HTTP ${response.status}`);
        const packaged = await response.json() as MaralaMonthlyModelData;
        if (!Array.isArray(packaged.dataset) || !packaged.dataset.length || packaged.dataset.length !== packaged.monthly_records) {
          throw new Error("Packaged monthly dataset is incomplete");
        }
        setData(packaged);
        setSourceNotice("Showing packaged dataset; the live backend route is unavailable.");
      } catch (fallbackCause) {
        const backendError = cause instanceof Error ? cause.message : "Request failed";
        const packagedError = fallbackCause instanceof Error ? fallbackCause.message : "Request failed";
        setError(`Backend: ${backendError}. Packaged dataset: ${packagedError}.`);
      }
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const maxMonthlyFlow = useMemo(() => data ? Math.max(...data.dataset.map((row) => row.flow_mean_cumecs)) : 0, [data]);

  if (loading && !data) return <div className="marala-monthly-state"><RefreshCw className="spinning" /><strong>Loading Marala monthly dataset</strong></div>;
  if (error && !data) return <div className="marala-monthly-state marala-monthly-error"><strong>Monthly dataset unavailable</strong><span>{error}</span><button type="button" onClick={() => void refresh()}>Retry</button></div>;
  if (!data) return null;

  return (
    <section className="marala-monthly" aria-label="Marala monthly river flow dataset and outlook">
      <header className="marala-monthly-heading">
        <div><span className="marala-monthly-eyebrow"><Waves size={14} /> Monthly station outlook · Chenab</span><h2>Marala discharge prediction</h2>

        </div>
        <div className="marala-monthly-actions">
          <button type="button" aria-expanded={showDetails} aria-controls="marala-monthly-details" onClick={() => setShowDetails(value => !value)}>{showDetails ? "Hide details" : "View details"}</button>
        </div>
      </header>
      <MaralaDischargeHydrograph data={data} />
      {showDetails && <div id="marala-monthly-details" className="marala-monthly-details">
        {data.recent_history?.station_observation && <><p className="marala-panel-footnote">Chart history: {data.recent_history.period_start} to {data.recent_history.period_end}. {data.recent_history.aggregation}. {data.recent_history.limitations} The measured Marala inflows and the modeled nearby-reach forecast are separate data products.</p><div className="marala-table-scroll"><table><thead><tr><th>Month</th><th>Measured inflow average (m³/s)</th><th>Reading days</th></tr></thead><tbody>{data.recent_history.monthly.map(row => <tr key={row.month}><td>{row.month}</td><td>{row.flow_mean_cumecs === null ? "Unavailable" : number(row.flow_mean_cumecs, 1)}</td><td>{row.days}/{row.calendar_days}{row.coverage === "partial" ? " · partial" : ""}</td></tr>)}</tbody></table></div></>}
        <div className="marala-monthly-actions">
          <a href={`${import.meta.env.BASE_URL}data/marala-monthly-dataset.csv`} download><Download size={15} /> Download CSV</a>
          <button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spinning" : ""} /> Reload saved data</button>
        </div>
      <div className="marala-data-notice"><Database size={17} /><p><strong>Research data, not gauge readings.</strong> The 2000–2021 target is GloFAS modeled discharge at a nearby river grid cell. Monthly means do not predict flood peaks or inundation. Model training and configuration remain in the repository.</p></div>

      <div className="marala-monthly-stats">
        <article><span>Dataset</span><strong>{data.monthly_records} <small>months</small></strong><p>{data.input_period}</p></article>
        <article><span>Peak monthly mean in dataset</span><strong>{number(maxMonthlyFlow)} <small>m³/s</small></strong><p>Historical modeled flow</p></article>
        <article><span>Saved provider forecast</span><strong>GloFAS</strong><p>Retrieved {new Date(data.current_provider_outlook.retrieved_at).toLocaleString()}</p></article>
      </div>

      <section className="marala-panel">
        <header><div><h3><Activity size={16} /> Historical monthly dataset</h3><p>Monthly mean discharge, {data.input_period}. Rainfall and weather inputs are also available below.</p></div><span>{data.dataset.length} rows</span></header>
        <details className="marala-dataset-details"><summary>Browse monthly input dataset</summary>
          <div className="marala-table-scroll"><table><thead><tr><th>Month</th><th>Mean flow (m³/s)</th><th>Max daily mean (m³/s)</th><th>Rain (mm)</th><th>Temp (°C)</th><th>Snow (cm)</th></tr></thead>
            <tbody>{data.dataset.map((row) => <tr key={row.month}><td>{row.month}</td><td>{number(row.flow_mean_cumecs, 1)}</td><td>{number(row.flow_max_daily_mean_cumecs, 1)}</td><td>{number(row.rainfall_mm, 1)}</td><td>{number(row.temperature_c, 1)}</td><td>{number(row.snowfall_cm, 1)}</td></tr>)}</tbody>
          </table></div>
        </details>
      </section>

      <div className="marala-forecast-grid">
        <section className="marala-panel">
          <header><div><h3>Saved provider outlook</h3><p>{data.current_provider_outlook.forecast_source} · Monthly mean of daily modeled flow</p></div><span>Retrieved {new Date(data.current_provider_outlook.retrieved_at).toLocaleDateString()}</span></header>
          <div className="marala-table-scroll marala-forecast-table"><table><thead><tr><th>Target month</th><th>Mean (m³/s)</th><th>Daily p25–p75 avg.</th></tr></thead><tbody>
            {data.current_provider_outlook.forecast.map((row) => <tr key={row.target_month}><td>{row.target_month}</td><td>{number(row.monthly_mean_discharge_cumecs.mean, 1)}</td><td>{number(row.monthly_mean_discharge_cumecs.p25, 1)} – {number(row.monthly_mean_discharge_cumecs.p75, 1)}</td></tr>)}
          </tbody></table></div>
          <p className="marala-panel-footnote">The p25–p75 values average daily ensemble statistics; they are not calibrated monthly prediction intervals.</p>
        </section>

        <section className="marala-panel">
          <header><div><h3>Local model validation</h3><p>Selected using 2014–2017 validation; scores below are on the held-out 2018–2021 period.</p></div><span>Ridge / XGBoost</span></header>
          <div className="marala-table-scroll"><table><thead><tr><th>Lead</th><th>Selected candidate</th><th>Test RMSE (m³/s)</th><th>Best Ridge / XGB RMSE</th></tr></thead>
            <tbody>{Object.entries(data.leads).map(([lead, result]) => <tr key={lead}><td>+{lead} month</td><td>{result.selected_candidate}</td><td>{number(result.test.rmse_cumecs, 1)}</td><td>{number(result.ridge_vs_xgboost_test.ridge_alpha?.rmse_cumecs ?? 0, 1)} / {number(result.ridge_vs_xgboost_test.xgboost?.rmse_cumecs ?? 0, 1)}</td></tr>)}</tbody>
          </table></div>
          <p className="marala-panel-footnote">Saved local model example: input through {data.historical_model_hindcast.input_through_month}; this is a historical hindcast, not a current model forecast.</p>
          <div className="marala-hindcast-cards">{data.historical_model_hindcast.outlook.map((point) => <article key={point.horizon_months}><span>{point.target_month} · +{point.horizon_months}m</span><strong>{number(point.predicted_monthly_mean_discharge_cumecs)} <small>m³/s</small></strong><small>{point.model_type.replaceAll("_", " ")}</small></article>)}</div>
        </section>
      </div>
      <footer className="marala-sources"><strong>Data sources</strong> {data.sources.attribution}. Weather: {data.sources.weather_definition}. <a href={data.sources.documentation[0]} target="_blank" rel="noreferrer">GloFAS documentation</a> · <a href={data.sources.documentation[1]} target="_blank" rel="noreferrer">ERA5 weather documentation</a>.</footer>
      {sourceNotice && <p className="marala-refresh-error" role="status">{sourceNotice}</p>}
      {error && <p className="marala-refresh-error" role="status">Refresh failed; showing the last loaded data. {error}</p>}
      </div>}
    </section>
  );
}
