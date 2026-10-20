import type { SarWaterOverlay } from "../types/api";

const area = (value: number) => value === 0 ? "0" : value < 0.01 ? "<0.01" : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
const date = (value: string) => new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

export function SarWaterSummary({ result }: { result: SarWaterOverlay }) {
  return <div className="sar-summary">
    {result.is_historical_example && <div className="sar-historical-notice"><strong>HISTORICAL EXAMPLE · NOT LIVE</strong><small>{result.example_title}</small></div>}
    <strong>{result.status === "potential_flooding_detected" ? "Potential flooding detected"
      : result.status === "permanent_water_only" ? "Only known permanent water detected" : "No water detected in usable imagery"}</strong>
    <div className="sar-area-highlight"><b>{area(result.potential_flood_area_km2)} <span>km²</span></b><small>Potential flooding · {result.potential_flood_percent}% of usable pixels</small></div>
    <dl>
      <div><dt>Area checked</dt><dd>{area(result.analysis_area_km2)} km²</dd></div>
      <div><dt>Usable imagery</dt><dd>{result.valid_coverage_percent}%</dd></div>
      <div><dt>All detected water</dt><dd>{area(result.water_area_km2)} km²</dd></div>
      <div><dt>Permanent water removed</dt><dd>{area(result.excluded_permanent_water_area_km2)} km²</dd></div>
      {result.permanent_water_reference_area_km2 !== undefined && <div><dt>Permanent-water reference</dt><dd>{area(result.permanent_water_reference_area_km2)} km²</dd></div>}
    </dl>
    {result.valid_coverage_percent < 90 && <small className="sar-result-warning">Incomplete coverage: unobserved pixels have not been assessed.</small>}
    {result.permanent_water_reference_pixels === 0 && <small className="sar-result-warning">The reference marks no permanent water here; river water may still remain in the potential-flooding layer.</small>}
    <small>The outlined box is the analysed area. Cyan shows potential flooding; a clear box means no potential flooding was detected in usable pixels.</small>
    {result.during_date && <small>Observed: {date(result.during_date)}{result.pre_date ? ` · Earlier radar: ${date(result.pre_date)}` : ""}</small>}
    <small>Satellite snapshot, not a live flood warning. An earlier radar pass is not necessarily a pre-flood baseline.</small>
    <details><summary>Interpretation & source</summary>{result.example_note && <small>{result.example_note}</small>}<small>{result.limitation}</small><small>Areas are approximate. Model scores are not calibrated flood probabilities.</small><small>{result.source}</small><small>Model: {result.model}</small></details>
  </div>;
}
