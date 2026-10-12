import { useEffect, useRef, useState } from 'react';
import type { PopulationOverlay, PopulationSummary, FloodSource } from '../services/population';
import { populationApi } from '../services/population';
import '../population-analysis.css';

const number = (value: number | null | undefined, suffix = '') => value == null ? 'Unknown' : value.toLocaleString(undefined, { maximumFractionDigits: suffix ? 1 : 0 }) + suffix;

export function PopulationAnalysisPanel({ onChange }: { onChange: (value: PopulationOverlay | null) => void }) {
  const [region, setRegion] = useState('trimmu_jhang');
  const [regions, setRegions] = useState(['trimmu_jhang']);
  const [source, setSource] = useState<FloodSource>('historical_reference');
  const [summary, setSummary] = useState<PopulationSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [extent, setExtent] = useState<object>();
  const [adminLevel, setAdminLevel] = useState('ADM2');
  const [visible, setVisible] = useState<Record<string, boolean>>({ flood_extent: true, population_grid: true, settlements: true, administrative_exposure: true });
  const pending = useRef<AbortController | null>(null);
  useEffect(() => { populationApi.regions().then(r => setRegions(r.regions.map(x => x.region))).catch(() => {}); }, []);
  useEffect(() => {
    const controller = new AbortController();
    pending.current?.abort(); setSummary(null); setError(''); setBusy(false);
    populationApi.latest(region, controller.signal).then(setSummary).catch(e => { if (!controller.signal.aborted) setError(String(e.message)); });
    return () => { controller.abort(); pending.current?.abort(); };
  }, [region]);
  useEffect(() => { onChange(summary ? {summary, visible, adminLevel} : null); }, [summary, visible, adminLevel, onChange]);
  async function calculate() {
    setBusy(true); setError('');
    const controller = new AbortController(); pending.current = controller;
    try {
      const job = await populationApi.start(region, source, source === 'provided' ? extent : undefined);
      let state = job;
      while (!controller.signal.aborted && !['COMPLETED','FAILED'].includes(state.status)) {
        await new Promise<void>(resolve => {
          const done = () => { window.clearTimeout(timeout); controller.signal.removeEventListener('abort',done); resolve(); };
          const timeout = window.setTimeout(done, 1500);
          controller.signal.addEventListener('abort',done,{once:true});
        });
        if (controller.signal.aborted) return;
        state = await populationApi.status(region, job.analysis_id, controller.signal);
      }
      if (controller.signal.aborted) return;
      if (state.status === 'FAILED') throw new Error(state.error?.message ?? 'Analysis failed');
      setSummary(await populationApi.summary(region, job.analysis_id, controller.signal));
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  const rows = summary?.administrative[adminLevel] ?? [];
  const max = Math.max(1, ...rows.map(r => r.estimated_exposed_population ?? 0));
  return <section className="population-analysis" aria-label="Flood-affected population analysis">
    <div className="population-heading"><div><h2>Flood-affected population</h2><p>WorldPop estimates · fractional flooded cells · Trimmu / Jhang pilot</p></div>
      <div className="population-controls"><label>Study region<select aria-label="Population study region" value={region} disabled={busy} onChange={e => setRegion(e.target.value)}>{regions.map(r => <option key={r} value={r}>{r.replaceAll('_',' ')}</option>)}</select></label>
      <label>Flood extent<select aria-label="Population flood source" value={source} disabled={busy} onChange={e => setSource(e.target.value as FloodSource)}><option value="historical_reference">Historical satellite water reference</option><option value="segmentation">Configured segmentation output</option><option value="provided">Upload flood polygons (WGS84)</option><option value="sample">Synthetic test scenario</option></select></label>
      <button type="button" disabled={busy || (source === 'provided' && !extent)} onClick={() => void calculate()}>{busy ? 'Calculating…' : 'Calculate population'}</button></div></div>
    {source === 'provided' && <label className="population-upload">Flood GeoJSON in EPSG:4326<input type="file" accept=".json,.geojson" aria-label="Flood polygon GeoJSON" onChange={async e => { try { const file=e.target.files?.[0]; if (file) { if(file.size>15_000_000) throw new Error('Use a GeoJSON smaller than 15 MB'); setExtent(JSON.parse(await file.text())); setError(''); } } catch(err) { setExtent(undefined); setError(String(err)); } }} /></label>}
    {error && <p role="alert" className="population-warning">{error}</p>}
    {!summary && !busy && <p>Choose an available flood source and calculate. Missing segmentation or boundaries produce an explicit error.</p>}
    {summary && <>
      <p className={summary.flood.is_sample ? 'population-warning' : 'population-provenance'}><strong>{summary.flood.is_sample ? 'SYNTHETIC TEST — ' : ''}{summary.flood.label}</strong>{summary.flood.observation_period && ` · ${summary.flood.observation_period}`}</p>
      <div className="population-cards">
        <div><span>Estimated exposed people</span><strong>{number(summary.population.estimated_exposed_population)}</strong><small>Known population cells only</small></div>
        <div><span>Known population exposed</span><strong>{number(summary.population.percentage_exposed_of_known_population,'%')}</strong><small>Denominator: {number(summary.population.known_population_total)}</small></div>
        <div><span>Water area with population data</span><strong>{number(summary.population.flood_area_with_known_population_fraction == null ? null : 100*summary.population.flood_area_with_known_population_fraction,'%')}</strong><small>Nodata is unknown, never zero</small></div>
        <div><span>Mapped settlements exposed</span><strong>{number(summary.settlements.affected_count)}</strong><small>OSM coverage may be incomplete</small></div>
      </div>
      {summary.population.status !== 'ESTIMATED' && <p className="population-warning">Partial or unknown coverage: this estimate is not a complete affected-person count.</p>}
      <div className="population-details"><div><label>Administrative statistics<select aria-label="Population administrative level" value={adminLevel} onChange={e => setAdminLevel(e.target.value)}><option value="ADM2">Districts</option><option value="ADM3">Tehsils</option></select></label>
        {rows.length ? <div className="population-chart" role="img" aria-label="Administrative population exposure chart">{rows.map(r => <div className="population-chart-row" key={r.id}><span>{r.name}</span><div><i style={{width:`${100*(r.estimated_exposed_population ?? 0)/max}%`}} /></div><strong>{number(r.estimated_exposed_population)} · {number(r.percentage_exposed_of_known_population,'%')}</strong></div>)}</div> : <p>{adminLevel === 'ADM3' ? 'Tehsil boundaries unavailable. No tehsil totals have been invented.' : 'District statistics unavailable.'}</p>}
      </div><div><strong>Interactive map layers</strong><div className="population-layer-controls">{Object.entries({flood_extent:'Flooded areas · blue',population_grid:'Population density · yellow to red',administrative_exposure:'Administrative exposure',settlements:'Affected settlements · pink'}).map(([key,label]) => <label key={key}><input type="checkbox" checked={visible[key]} onChange={e => setVisible(v => ({...v,[key]:e.target.checked}))} />{label}</label>)}</div><small>Click a region, population cell or settlement on the map. Density is people/km²; the display grid groups native cell centres.</small></div></div>
      <details><summary>Population distribution across flooded areas</summary>{summary.density_distribution.map(r => <p key={r.density_min_people_km2}>{r.density_min_people_km2}–{r.density_max_people_km2 ?? '∞'} people/km²: {number(r.exposed_population)} estimated exposed</p>)}{summary.notes.map(note => <p key={note}>{note}</p>)}</details>
    </>}
  </section>;
}
