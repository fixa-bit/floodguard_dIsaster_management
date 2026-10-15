import { lazy, Suspense, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ArrowUpRight, BookOpen, Compass, FlaskConical, Pause, Play, RotateCcw, Sparkles } from "lucide-react";
import { TenYearOutlookChart } from "./TenYearOutlookChart";
import { TenYearInputsMethod } from "./TenYearInputsMethod";
import { useOutlookMotion } from "./useOutlookMotion";
import { PREVIEW_BASE_YEAR, PREVIEW_END_YEAR, formatPreviewChange, previewAreaName, previewAreas, previewBand, previewHazards, previewPoint, previewScenarios, previewSeries, type PreviewHazard, type PreviewScenario, type PreviewSelection } from "./tenYearPreviewData";

const ComparisonMaps = lazy(() => import("./TenYearComparisonMaps").then((module) => ({ default: module.TenYearComparisonMaps })));

export function TenYearRiskOutlook({ active = true }: { active?: boolean }) {
  const [selection, setSelection] = useState<PreviewSelection>("all");
  const [hazard, setHazard] = useState<PreviewHazard>("riverine");
  const [scenario, setScenario] = useState<PreviewScenario>("moderate");
  const [year, setYear] = useState(PREVIEW_END_YEAR);
  const [methodOpen, setMethodOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [touring, setTouring] = useState(false);
  const { canAnimate, reducedMotion, enabled, setEnabled } = useOutlookMotion(active);
  const methodPanel = useRef<HTMLDetailsElement>(null);
  const points = useMemo(() => previewSeries(selection, hazard, scenario), [selection, hazard, scenario]);
  const selected = points.find((point) => point.year === year)!;
  const change = selected.value - selected.baseline;
  const areas = previewAreas.map((area) => {
    const point = previewPoint(area.id, hazard, scenario, year);
    return { ...area, ...point, change: point.value - point.baseline };
  }).sort((a, b) => b.change - a.change);
  const progress = (year - PREVIEW_BASE_YEAR) / (PREVIEW_END_YEAR - PREVIEW_BASE_YEAR);
  const scenarioConfig = previewScenarios.find((item) => item.id === scenario)!;

  useEffect(() => {
    if (!canAnimate) { setPlaying(false); setTouring(false); }
  }, [canAnimate]);

  useEffect(() => {
    if (!playing || !canAnimate) return;
    const timer = window.setInterval(() => setYear((current) => Math.min(PREVIEW_END_YEAR, current + 1)), 1500);
    return () => window.clearInterval(timer);
  }, [playing, canAnimate]);

  useEffect(() => { if (year === PREVIEW_END_YEAR) setPlaying(false); }, [year]);

  useEffect(() => {
    if (!touring || !canAnimate) return;
    let index = Math.max(0, previewAreas.findIndex((area) => area.id === selection));
    const timer = window.setInterval(() => {
      index = (index + 1) % previewAreas.length;
      setSelection(previewAreas[index].id);
    }, 6500);
    return () => window.clearInterval(timer);
    // Selection changes are the tour's output; manual changes explicitly stop it.
  }, [touring, canAnimate]);

  function stopPlayback() { setPlaying(false); setTouring(false); }
  function selectArea(next: PreviewSelection) { stopPlayback(); setSelection(next); }
  function selectYear(next: number) { stopPlayback(); setYear(next); }
  function toggleTour() {
    if (touring) { setTouring(false); return; }
    if (selection === "all") setSelection(previewAreas[0].id);
    setTouring(true);
  }
  function togglePlayback() {
    if (playing) { setPlaying(false); return; }
    if (year === PREVIEW_END_YEAR) setYear(PREVIEW_BASE_YEAR);
    setPlaying(true);
  }

  function showMethod() {
    stopPlayback();
    setMethodOpen(true);
    requestAnimationFrame(() => methodPanel.current?.scrollIntoView({ block: "start", behavior: "instant" }));
  }

  return (
    <section className="ten-year-outlook" aria-labelledby="ten-year-outlook-title" data-is-hypothetical="true" data-motion={canAnimate ? "on" : "off"}>
      <header className="ten-year-outlook-header">
        <div>
          <span className="ten-year-outlook-eyebrow"><Compass size={15} aria-hidden="true" /> Long-range planning</span>
          <h2 id="ten-year-outlook-title">10-Year Flood-Risk Outlook</h2>
          <p>A picture of the planning experience we aim to build: compare locations, explore scenarios, and understand what drives change.</p>
        </div>
        <div className="outlook-header-actions"><button className="outlook-quiet-button" type="button" aria-pressed={canAnimate} disabled={reducedMotion} title={reducedMotion ? "Your browser prefers reduced motion" : "Enable or disable visual motion"} onClick={() => { stopPlayback(); setEnabled(!enabled); }}><Sparkles size={15} aria-hidden="true" /> Motion {canAnimate ? "on" : "off"}</button><button className="outlook-method-button" type="button" onClick={showMethod} aria-controls="outlook-inputs-method" aria-expanded={methodOpen}><BookOpen size={16} aria-hidden="true" /> Inputs &amp; Method</button></div>
      </header>

      <div className="outlook-demo-notice"><FlaskConical size={22} aria-hidden="true" /><div><strong>Hypothetical preview</strong><p>All scores, scenario changes, ranges, and flood-spread levels below are examples, not validated predictions. Geography and the optional WorldPop 2025 population layer use real datasets; population exposure is an approximate what-if calculation.</p></div></div>

      <div className="outlook-controls" aria-label="Hypothetical outlook controls">
        <label>Example area<select aria-label="Example area" value={selection} onChange={(event) => selectArea(event.target.value as PreviewSelection)}><option value="all">All 8 example areas</option>{previewAreas.map((area) => <option value={area.id} key={area.id}>{area.name} · {area.province}</option>)}</select></label>
        <label>Flood type<select aria-label="Flood type" value={hazard} onChange={(event) => { stopPlayback(); setHazard(event.target.value as PreviewHazard); }}>{previewHazards.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
        <label>Example scenario<select aria-label="Example scenario" aria-describedby="outlook-scenario-description" value={scenario} onChange={(event) => { stopPlayback(); setScenario(event.target.value as PreviewScenario); }}>{previewScenarios.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
        <label>Planning year<select aria-label="Planning year" value={year} onChange={(event) => selectYear(Number(event.target.value))}>{Array.from({ length: 11 }, (_, index) => PREVIEW_BASE_YEAR + index).map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
      </div>

      <p className="outlook-scenario-description" id="outlook-scenario-description"><strong>{scenarioConfig.label}:</strong> {scenarioConfig.description}</p>

      <section className="outlook-timeline" aria-label="Outlook animation controls" data-playing={playing} data-touring={touring}>
        <div className="outlook-timeline-intro"><span className="outlook-motion-eyebrow"><i aria-hidden="true" /> DECADE EXPLORER</span><h3>See the outlook evolve.</h3><p>Play the years. Follow the change.</p></div>
        <div className="outlook-timeline-player">
          <div className="outlook-playback-actions"><button type="button" className="outlook-play-button" onClick={togglePlayback} disabled={!canAnimate} aria-pressed={playing}>{playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />} {playing ? "Pause timeline" : "Play decade"}</button><button type="button" className="outlook-restart-button" aria-label="Restart timeline" title="Return to the current example year" onClick={() => selectYear(PREVIEW_BASE_YEAR)}><RotateCcw size={16} aria-hidden="true" /></button><span className="outlook-playback-state">{playing ? "Playing example years" : "Drag to explore"}</span></div>
          <input type="range" min={PREVIEW_BASE_YEAR} max={PREVIEW_END_YEAR} step="1" value={year} aria-label="Timeline year" aria-valuetext={`${year}, hypothetical planning year`} onChange={(event) => selectYear(Number(event.target.value))} style={{ "--outlook-progress": `${progress * 100}%` } as CSSProperties} />
          <div className="outlook-timeline-ticks"><span>{PREVIEW_BASE_YEAR}<small>Current example</small></span><span>2031</span><span>{PREVIEW_END_YEAR}<small>Future example</small></span></div>
        </div>
        <div className="outlook-year-dial" aria-hidden="true"><svg viewBox="0 0 108 108"><circle className="outlook-dial-track" cx="54" cy="54" r="47" /><circle className="outlook-dial-progress" cx="54" cy="54" r="47" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - progress} /></svg><span><strong>{year}</strong><small>PLANNING YEAR</small></span></div>
      </section>

      <div className="outlook-selection-heading"><strong>{previewAreaName(selection)}</strong><span>{selection === "all" ? "Unweighted mean of the eight examples · not a national estimate" : "Selected district example"}</span></div>
      <div className="outlook-summary-grid" aria-label="Hypothetical change summary" aria-live={playing || touring ? "off" : "polite"}>
        <article><span>Current example · {PREVIEW_BASE_YEAR}</span><strong data-testid="outlook-baseline">{selected.baseline.toFixed(1)}<small>/100</small></strong><p>Constructed baseline index</p></article>
        <article><span>Future example · {year}</span><strong data-testid="outlook-future"><span className="outlook-value-enter" key={selected.value}>{selected.value.toFixed(1)}</span><small>/100</small></strong><p>{previewBand(selected.value)} example band · range {selected.lower.toFixed(1)}–{selected.upper.toFixed(1)}</p><span className="outlook-card-meter" aria-hidden="true"><i style={{ width: `${selected.value}%` }} /></span></article>
        <article><span>Change by {year}</span><strong data-testid="outlook-change"><span className="outlook-value-enter" key={change}>{formatPreviewChange(change)}</span><small>points</small></strong><p>{change === 0 ? "Stable-condition illustration" : "Change from the current example"}</p><span className="outlook-card-meter" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(0, change) * 2)}%` }} /></span></article>
      </div>

      {active && <Suspense fallback={<div className="outlook-panel outlook-map-message" role="status">Loading the comparison maps…</div>}><ComparisonMaps selection={selection} hazard={hazard} scenario={scenario} year={year} onSelectionChange={selectArea} motion={canAnimate} touring={touring} onToggleTour={toggleTour} onInteract={stopPlayback} /></Suspense>}

      <div className="outlook-analysis-grid">
        <TenYearOutlookChart points={points} selection={selection} year={year} motion={canAnimate} playing={playing} />
        <aside className="outlook-change-panel outlook-panel" aria-labelledby="outlook-change-title"><header className="outlook-panel-heading"><div><h3 id="outlook-change-title"><ArrowUpRight size={18} aria-hidden="true" /> Example changes</h3><p>Across the eight areas · {year}</p></div></header><p className="outlook-change-intro">Explore the largest constructed changes. This is not a ranking of actual flood risk.</p><ol>{areas.slice(0, 4).map((area) => <li key={area.id}><button type="button" onClick={() => selectArea(area.id)} aria-label={`Explore ${area.name} example`}><span>{area.name}<small>{area.baseline.toFixed(1)} → {area.value.toFixed(1)}</small></span><strong>{formatPreviewChange(area.change)}<small>index points</small></strong></button><span className="outlook-change-meter" aria-hidden="true"><i style={{ width: `${area.value}%` }} /></span></li>)}</ol><p className="outlook-change-footnote">Changing the flood type or scenario updates the maps, curve, and summaries together.</p></aside>
      </div>

      <TenYearInputsMethod open={methodOpen} onToggle={setMethodOpen} panelRef={methodPanel} hazard={hazard} scenario={scenario} />
      <p className="ten-year-outlook-note">Hypothetical planning demonstration · {PREVIEW_BASE_YEAR}–{PREVIEW_END_YEAR}. This view does not create operational alerts or incidents.</p>
    </section>
  );
}
