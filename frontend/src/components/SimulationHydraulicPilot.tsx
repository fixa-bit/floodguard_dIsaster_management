import { useEffect, useState } from "react";
import { Download, Pause, Play, RotateCcw } from "lucide-react";
import "../simulation-hydraulic.css";

type Frame = {
  elapsed_seconds: number; inflow_cumecs: number; water_volume_m3: number;
  wet_area_km2: number; maximum_depth_m: number; maximum_speed_m_s: number;
  relative_mass_error: number; image: string;
};
type Results = {
  run_id: string; solver: string; calibrated: false; triangle_count: number;
  mesh_spacing_m: number; source_dem_spacing_m: number; duration_seconds: number;
  max_relative_mass_error: number; bounds_utm43n: number[]; frames: Frame[];
  config: { manning_n: number; hydrograph_seconds_cumecs: number[][]; inlet_radius_m: number };
  limitations: string[]; dem_credit: string;
  numerical_checks: { passed: boolean };
};

const base = `${import.meta.env.BASE_URL}hydraulic-pilot/`;
const fixed = (value: number, digits = 2) => value.toLocaleString("en-GB", { maximumFractionDigits: digits });

export function SimulationHydraulicPilot() {
  const [data, setData] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [details, setDetails] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [imageError, setImageError] = useState(false);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => { setReducedMotion(preference.matches); if (preference.matches) setPlaying(false); };
    update(); preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetch(`${base}results.json`, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`Trial data returned HTTP ${response.status}`);
      const result = await response.json() as Results;
      if (!result.frames?.length || !result.numerical_checks?.passed || result.calibrated !== false ||
          result.frames.some(frame => !frame.image || !Number.isFinite(frame.wet_area_km2))) throw new Error("Trial data is incomplete");
      setData(result); setIndex(0); setImageError(false);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Trial data unavailable"); });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    if (!data || !playing || reducedMotion) return;
    const timer = window.setInterval(() => setIndex(value => {
      if (value >= data.frames.length - 1) { setPlaying(false); return value; }
      return value + 1;
    }), 700);
    return () => window.clearInterval(timer);
  }, [data, playing, reducedMotion]);
  useEffect(() => {
    const pause = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, []);

  if (error) return <section className="hydraulic-pilot" role="status"><p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Retry hydraulic trial</button></section>;
  if (!data) return <p role="status">Loading hydraulic trial…</p>;
  const frame = data.frames[index];
  const hours = frame.elapsed_seconds / 3600;
  const maxFlow = Math.max(...data.config.hydrograph_seconds_cumecs.map(point => point[1]), 1);
  const plotX = (seconds: number) => 42 + seconds / data.duration_seconds * 510;
  const plotY = (value: number) => 120 - value / maxFlow * 90;

  return <section className="hydraulic-pilot" aria-label="Jhang 2D hydraulic trial" data-frame={index} data-playing={playing}>
    <header className="hydraulic-heading"><div><span>JHANG / CHENAB · ANUGA 2D</span><h2>Water moving over real terrain</h2><p>Six-hour hydraulic trial · hypothetical inflow · uncalibrated</p></div><button type="button" aria-expanded={details} onClick={() => setDetails(value => !value)}>{details ? "Hide details" : "View details"}</button></header>
    <div className="hydraulic-layout">
      <figure className="hydraulic-map">
        <div className="hydraulic-images"><img src={`${base}terrain.png`} alt="Real Jhang surface terrain, shaded relief, north up" /><img key={frame.image} src={`${base}${frame.image}`} alt={`Computed water depth after ${fixed(hours)} scenario hours`} onError={() => { setImageError(true); setPlaying(false); }} /></div>
        <span className="hydraulic-north">N ↑</span>
        <figcaption><strong>{fixed(hours)} h</strong> elapsed scenario time <span>6 km × 6 km · UTM 43N</span></figcaption>
        <div className="hydraulic-depth-key"><span>Computed depth ≥0.1 m</span><i /><span>0.1 m</span><span>3 m+</span></div>
        {imageError && <p role="alert">A trial frame could not load. Playback is paused.</p>}
      </figure>
      <aside className="hydraulic-metrics" aria-label="Computed hydraulic results">
        <article><span>Wet area · depth ≥0.1 m</span><strong>{fixed(frame.wet_area_km2)} <small>km²</small></strong></article>
        <article><span>Maximum depth in this frame</span><strong>{fixed(frame.maximum_depth_m)} <small>m</small></strong></article>
        <article><span>Maximum speed · wet cells</span><strong>{fixed(frame.maximum_speed_m_s)} <small>m/s</small></strong></article>
        <article><span>Hypothetical inflow</span><strong>{fixed(frame.inflow_cumecs, 0)} <small>m³/s</small></strong></article>
        <p>Results describe this assumed scenario. They have not been validated against an observed Jhang flood.</p>
      </aside>
    </div>
    <div className="hydraulic-playback">
      <button type="button" disabled={reducedMotion || imageError} onClick={() => { if (index === data.frames.length - 1) setIndex(0); setPlaying(value => !value); }}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause hydraulic trial" : "Play hydraulic trial"}</button>
      <button type="button" aria-label="Reset hydraulic trial" onClick={() => { setPlaying(false); setIndex(0); }}><RotateCcw size={15} /></button>
      <label>Elapsed time <input type="range" aria-label="Hydraulic scenario time" min="0" max={data.frames.length - 1} step="1" value={index} onChange={event => { setPlaying(false); setIndex(Number(event.target.value)); }} /></label><output>{fixed(hours)} / {fixed(data.duration_seconds / 3600)} h</output>
    </div>
    {reducedMotion && <p className="hydraulic-note">Reduced motion is enabled. Use the time slider to inspect computed frames.</p>}
    {details && <div className="hydraulic-details">
      <p>{data.solver}. {fixed(data.triangle_count, 0)} computational triangles at {fixed(data.mesh_spacing_m, 0)} m spacing, using a {data.source_dem_spacing_m} m source DEM. Manning n = {data.config.manning_n}; initially dry, no rainfall or infiltration, open study edges. The inflow is applied over a {data.config.inlet_radius_m} m radius on the mapped river.</p>
      <figure className="hydraulic-hydrograph"><figcaption>Hypothetical inflow used by the simulation</figcaption><svg viewBox="0 0 580 160" role="img" aria-label="Hypothetical inflow hydrograph in cubic metres per second against elapsed scenario hours">
        {[0, .5, 1].map(fraction => <g key={fraction}><line x1="42" x2="552" y1={plotY(fraction * maxFlow)} y2={plotY(fraction * maxFlow)} stroke="#33515a" /><text x="36" y={plotY(fraction * maxFlow) + 4} textAnchor="end">{fixed(fraction * maxFlow, 0)}</text></g>)}
        <polyline points={data.config.hydrograph_seconds_cumecs.map(([t, q]) => `${plotX(t)},${plotY(q)}`).join(" ")} fill="none" stroke="#69dec5" strokeWidth="2" />
        {data.config.hydrograph_seconds_cumecs.map(([t]) => <text key={t} x={plotX(t)} y="138" textAnchor="middle">{fixed(t / 3600)} h</text>)}<text x="46" y="15">Discharge (m³/s)</text><line x1={plotX(frame.elapsed_seconds)} x2={plotX(frame.elapsed_seconds)} y1="25" y2="125" stroke="#e3be7a" />
      </svg></figure>
      <p>Still-water and analytical dam-break checks passed. Maximum relative volume-balance error: {data.max_relative_mass_error.toExponential(2)}. These checks verify the numerical setup, not local flood-prediction accuracy.</p>
      <ul>{data.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
      <div className="hydraulic-downloads"><a href={`${base}maximum-depth.tif`} download><Download size={14} /> Maximum sampled depth GeoTIFF</a><a href={`${base}timeseries.csv`} download>Result time series CSV</a><a href={`${base}results.json`} target="_blank" rel="noreferrer">Run details</a><a href={`${base}NOTICE.txt`} target="_blank" rel="noreferrer">Terrain credits and licence</a></div>
      <p>{data.dem_credit}. This hydraulic solver routes supplied water; it does not generate a year-ahead discharge forecast. Run: {data.run_id}.</p>
    </div>}
  </section>;
}
