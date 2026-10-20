import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import type { SarValidationMetrics, SarWaterOverlay } from "../types/api";

const percent = (value: number | null) => value === null ? "N/A" : `${(100 * value).toFixed(1)}%`;

function MetricTable({ before, after }: { before: SarValidationMetrics; after: SarValidationMetrics }) {
  return <table><thead><tr><th>Metric</th><th>Original model</th><th>Current model</th></tr></thead><tbody>
    {(["iou", "dice", "precision", "recall"] as const).map(key => <tr key={key}><th>{key === "iou" ? "IoU" : key[0].toUpperCase() + key.slice(1)}</th><td>{percent(before[key])}</td><td>{percent(after[key])}</td></tr>)}
  </tbody></table>;
}

export function SarValidationView({ result, onClose }: { result: SarWaterOverlay; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const validation = result.validation;
  if (!validation) return null;
  const panels = [
    { title: "Event radar imagery", note: "The actual VV radar used for this prediction", overlay: undefined },
    { title: "Predicted water", note: "Cyan · all predicted water, including permanent water", overlay: result.all_water_image_data_url },
    { title: "Reference water labels", note: "Green · hand-labeled water from the same event", overlay: validation.reference_water_image_data_url },
    { title: "Correct detections & errors", note: "Cyan: correct water · Pink: missed water · Orange: false detection · Gray: excluded", overlay: validation.error_image_data_url },
    { title: "Permanent-water reference", note: "Blue · supplied historical reference, not a model prediction", overlay: result.permanent_water_image_data_url },
  ];
  return createPortal(<div className="sar-validation-backdrop"><section className="sar-validation-dialog" role="dialog" aria-modal="true" aria-labelledby="sar-validation-title">
    <header><div><small>HISTORICAL VALIDATION · NOT LIVE</small><h2 id="sar-validation-title">Compare prediction with event evidence</h2><p>{result.sample_id} · {result.during_date} · Official {validation.split} split</p></div><button autoFocus type="button" aria-label="Close satellite validation" onClick={onClose}><X size={23} /></button></header>
    <p>All panels use the same footprint and the actual event radar. Modern basemap imagery is not used for this comparison.</p>
    <div className="sar-validation-score-strip">
      <span>Water IoU: <strong>{percent(validation.baseline_metrics.iou)} → {percent(validation.metrics.iou)}</strong></span>
      <span>Water recall: <strong>{percent(validation.baseline_metrics.recall)} → {percent(validation.metrics.recall)}</strong></span>
      <span>Original model → current model · same supervised pixels</span>
    </div>
    <div className="sar-validation-panels">{panels.map(panel => <figure key={panel.title}><figcaption><strong>{panel.title}</strong><small>{panel.note}</small></figcaption><div className="sar-validation-image"><img src={validation.event_image_data_url} alt={`${panel.title}: event radar background`} />{panel.overlay && <img className="sar-validation-mask" src={panel.overlay} alt={panel.title} />}</div></figure>)}</div>
    {result.permanent_water_reference_pixels === 0 && <p className="sar-validation-warning">This chip's supplied reference marks zero permanent-water pixels. That does not establish that the river is temporary.</p>}
    <div className="sar-validation-metrics"><section><h3>Water-extent accuracy on this chip</h3><MetricTable before={validation.baseline_metrics} after={validation.metrics} /><p>{validation.metrics.evaluated_pixels.toLocaleString()} supervised pixels · {validation.metrics.fn.toLocaleString()} missed water pixels · {validation.metrics.fp.toLocaleString()} false water detections.</p></section>
    <section><h3>Water outside the permanent reference</h3><MetricTable before={validation.baseline_outside_permanent_metrics} after={validation.outside_permanent_metrics} /><p>This measures a flood-extent proxy. It does not validate newly flooded land.</p></section></div>
    <p>{validation.label_definition}</p><p>{validation.permanent_water_source}</p><p>{validation.imagery_description}</p>
    {result.evaluation && <><h3>Official test-set results</h3><p>These scores cover the full official test split, rather than this selected illustration.</p>
      <div className="sar-validation-metrics"><section><h3>All test chips · water extent</h3><MetricTable before={result.evaluation.baseline_test} after={result.evaluation.current_test} /></section>
      {result.evaluation.current_test.events.Pakistan && <section><h3>Pakistan test chips · water extent</h3><MetricTable before={result.evaluation.baseline_test_events.Pakistan} after={result.evaluation.current_test.events.Pakistan} /></section>}</div>
      <p>{result.evaluation.selection}</p>
      {result.evaluation.experiments && <section className="sar-validation-experiments"><h3>Accuracy experiments · original model retained</h3><p>Both candidates improved validation IoU but failed the Pakistan test release check. No reliable Pakistan accuracy gain was demonstrated.</p>
        <table><thead><tr><th>Candidate</th><th>Validation IoU</th><th>Test IoU</th><th>Pakistan test IoU</th><th>Default</th></tr></thead><tbody>{result.evaluation.experiments.map(experiment => <tr key={experiment.name}><th>{experiment.name}</th><td>{percent(experiment.validation_iou)}</td><td>{percent(experiment.test_iou)}</td><td>{percent(experiment.pakistan_test_iou)}</td><td>{experiment.accepted ? "Active" : "Rejected"}</td></tr>)}</tbody></table>
        <p>Further improvement needs more representative Pakistan event data and an independent event-level evaluation. Confirmed flood-only accuracy also requires newly flooded reference labels.</p>
      </section>}</>}
    <p>This example is illustrative. Model selection uses validation data; accuracy on unseen flood events still needs independent assessment.</p>
  </section></div>, document.body);
}
