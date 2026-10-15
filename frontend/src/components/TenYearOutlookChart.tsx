import { ChartNoAxesCombined } from "lucide-react";
import { useId } from "react";
import { PREVIEW_BASE_YEAR, PREVIEW_END_YEAR, previewAreaName, type PreviewPoint, type PreviewSelection } from "./tenYearPreviewData";

export function TenYearOutlookChart({ points, selection, year, motion = false, playing = false }: { points: PreviewPoint[]; selection: PreviewSelection; year: number; motion?: boolean; playing?: boolean }) {
  const clipId = useId().replace(/:/g, "");
  const selected = points.find((point) => point.year === year)!;
  const x = (value: number) => 54 + (value - PREVIEW_BASE_YEAR) / (PREVIEW_END_YEAR - PREVIEW_BASE_YEAR) * 676;
  const y = (value: number) => 258 - value * 2.1;
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(point.year)},${y(point.value)}`).join(" ");
  const band = points.map((point, index) => `${index ? "L" : "M"}${x(point.year)},${y(point.upper)}`).join(" ")
    + [...points].reverse().map((point) => `L${x(point.year)},${y(point.lower)}`).join(" ") + " Z";
  const name = previewAreaName(selection);

  return <section className="outlook-chart-panel outlook-panel" aria-labelledby="outlook-chart-title" data-selected-year={year} data-selected-value={selected.value} data-animating={motion && playing}>
    <header className="outlook-panel-heading">
      <div><h3 id="outlook-chart-title"><ChartNoAxesCombined size={18} aria-hidden="true" /> Ten-year outlook</h3><p>{name} · Hypothetical index, 0–100</p></div>
      <span className="outlook-example-tag">{playing ? "Playing decade" : "Example curve"}</span>
    </header>
    <div className="outlook-chart-legend"><span><i className="outlook-legend-line" /> Scenario example</span><span><i className="outlook-legend-baseline" /> Current example</span><span><i className="outlook-legend-range" /> Illustrative range</span></div>
    <svg className="outlook-chart" viewBox="0 0 760 310" role="img" aria-labelledby="outlook-svg-title outlook-svg-description">
      <title id="outlook-svg-title">Hypothetical ten-year outlook for {name}</title>
      <desc id="outlook-svg-description">Constructed example values, not a trained forecast. Selected year {year}: index {selected.value.toFixed(1)}; illustrative range {selected.lower.toFixed(1)} to {selected.upper.toFixed(1)}. A table of all values follows the chart.</desc>
      <defs><linearGradient id={`${clipId}-fill`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#50d9bf" stopOpacity=".3" /><stop offset="100%" stopColor="#50d9bf" stopOpacity=".02" /></linearGradient><linearGradient id={`${clipId}-stroke`}><stop offset="0%" stopColor="#53d9c3" /><stop offset="100%" stopColor="#f2c67e" /></linearGradient><clipPath id={clipId}><rect x="54" y="30" width={x(year) - 54} height="230" className="outlook-chart-reveal" /></clipPath></defs>
      {[0, 25, 50, 75, 100].map((tick) => <g key={tick}><line x1="54" x2="730" y1={y(tick)} y2={y(tick)} className="outlook-chart-grid" /><text x="42" y={y(tick) + 4} textAnchor="end">{tick}</text></g>)}
      <path d={band} className="outlook-chart-band" fill={`url(#${clipId}-fill)`} />
      <line x1="54" x2="730" y1={y(selected.baseline)} y2={y(selected.baseline)} className="outlook-chart-baseline" />
      <path d={line} className="outlook-chart-future-line" />
      <g clipPath={`url(#${clipId})`}><path d={`${line} L730,258 L54,258 Z`} fill={`url(#${clipId}-fill)`} /><path d={line} pathLength="1" className="outlook-chart-line" style={{ stroke: `url(#${clipId}-stroke)` }} /></g>
      <g className="outlook-chart-playhead" style={{ transform: `translateX(${x(year)}px)` }}><line x1="0" x2="0" y1="38" y2="258" className="outlook-chart-selected" /></g>
      {points.map((point) => <circle key={point.year} cx={x(point.year)} cy={y(point.value)} r={point.year === year ? 5 : 2.7} className="outlook-chart-point"><title>{point.year}: {point.value.toFixed(1)} example index</title></circle>)}
      <g className="outlook-chart-head" style={{ transform: `translate(${x(year)}px, ${y(selected.value)}px)` }}><circle className="outlook-chart-head-halo" r="12" /><circle r="5" className="outlook-chart-head-core" /><text x={year >= 2034 ? -12 : 12} y="-15" textAnchor={year >= 2034 ? "end" : "start"}>{year} · {selected.value.toFixed(1)}</text></g>
      {[2026, 2028, 2030, 2032, 2034, 2036].map((tick) => <text key={tick} x={x(tick)} y="281" textAnchor="middle">{tick}</text>)}
      <text x="392" y="305" textAnchor="middle">Planning year · hypothetical values</text>
    </svg>
    <p className="outlook-chart-caption">The shaded range is illustrative. It is not a statistical confidence interval or a measured flood probability.</p>
    <details className="outlook-values"><summary>View example values</summary><div className="outlook-table-scroll"><table><caption>Hypothetical index for {name}</caption><thead><tr><th>Year</th><th>Current example</th><th>Scenario example</th><th>Illustrative range</th></tr></thead><tbody>{points.map((point) => <tr key={point.year} aria-current={point.year === year ? "true" : undefined}><th scope="row">{point.year}</th><td>{point.baseline.toFixed(1)}</td><td>{point.value.toFixed(1)}</td><td>{point.lower.toFixed(1)}–{point.upper.toFixed(1)}</td></tr>)}</tbody></table></div></details>
  </section>;
}
