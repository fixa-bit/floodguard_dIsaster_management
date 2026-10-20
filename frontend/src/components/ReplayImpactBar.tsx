import { ScanLine, Users } from "lucide-react";

export function ReplayImpactBar({ kind, value, maximum, formattedValue, formattedMaximum, scaleLabel = "of level 5", maximumLabel = "Level 5", ariaScaleLabel = "of the level 5 example" }: {
  kind: "population" | "area"; value: number | null; maximum: number | null;
  formattedValue: string; formattedMaximum: string;
  scaleLabel?: string; maximumLabel?: string;
  ariaScaleLabel?: string;
}) {
  const label = kind === "population" ? "People in example footprint" : "Affected area in example footprint";
  const known = value !== null && Number.isFinite(value);
  const hasScale = known && maximum !== null && Number.isFinite(maximum) && maximum > 0;
  const percentage = hasScale ? Math.min(100, Math.max(0, value! / maximum! * 100)) : 0;
  const percentageLabel = `${percentage.toFixed(1).replace(/\.0$/, "")}%`;
  const Icon = kind === "population" ? Users : ScanLine;
  return <section className="storm-replay-impact" data-kind={kind} data-value={known ? value : ""} data-maximum={maximum ?? ""}>
    <div className="storm-replay-impact-heading"><Icon size={13} aria-hidden="true" /><span>{label}</span></div>
    <div className="storm-replay-impact-value"><strong data-testid={kind === "population" ? "replay-exposed-population" : "replay-affected-area"}>{formattedValue}</strong><span>{hasScale ? percentageLabel : "\u2014"}<small>{scaleLabel}</small></span></div>
    <div className="storm-replay-impact-track" role={hasScale ? "meter" : undefined} aria-label={hasScale ? label : undefined} aria-valuemin={hasScale ? 0 : undefined} aria-valuemax={hasScale ? maximum! : undefined} aria-valuenow={hasScale ? value! : undefined} aria-valuetext={hasScale ? `${formattedValue}; ${percentageLabel} ${ariaScaleLabel} (${formattedMaximum})` : undefined} aria-hidden={!hasScale || undefined}>
      <div className="storm-replay-impact-fill" style={{ width: `${percentage}%` }}><i className="storm-replay-impact-shimmer" aria-hidden="true" /></div>
      <i className="storm-replay-impact-ticks" aria-hidden="true" />
    </div>
    <div className="storm-replay-impact-caption"><span>{kind === "population" ? "WorldPop 2025 · approximate" : "Hypothetical flooded area"}</span><span>{hasScale ? `${maximumLabel}: ${formattedMaximum}` : known ? "No nonzero example to compare" : "No footprint data"}</span></div>
  </section>;
}
