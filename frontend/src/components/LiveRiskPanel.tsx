import { ArrowDownRight, ArrowRight, ArrowUpRight, BrainCircuit, Gauge, Waves } from "lucide-react";

import type { RiskResponse } from "../types/api";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

const trendIcons = {
  FALLING: ArrowDownRight,
  STABLE: ArrowRight,
  RISING: ArrowUpRight,
  RAPIDLY_RISING: ArrowUpRight,
};

export function LiveRiskPanel({ risk }: { risk: RiskResponse | null }) {
  if (!risk) return <Panel title="Live Flood Risk" icon={Gauge}><div className="empty-state">Risk data is unavailable.</div></Panel>;
  const probability = Math.round(risk.flood_probability * 100);
  const TrendIcon = trendIcons[risk.trend];
  return (
    <Panel title="Live Flood Risk" icon={Gauge} action={<StatusBadge value={risk.severity} />} className="risk-panel">
      <div className="risk-summary">
        <div className={`risk-dial severity-${risk.severity.toLowerCase()}`}>
          <strong>{probability}%</strong><span>probability</span>
        </div>
        <div className="risk-details">
          <div className="risk-status-row"><StatusBadge value={risk.status} subtle /><span><TrendIcon size={16} /> {risk.trend.replaceAll("_", " ")} <b>{risk.probability_change >= 0 ? "+" : ""}{Math.round(risk.probability_change * 100)}%</b></span></div>
          <p>{risk.explanation}</p>
          <div className="probability-track"><span style={{ width: `${probability}%` }} /></div>
        </div>
      </div>
      <div className="risk-meta-grid">
        <div><Waves size={16} /><span>Monitoring</span><strong>{risk.monitoring_interval_minutes} min</strong></div>
        <div><BrainCircuit size={16} /><span>Decision model</span><strong>{risk.model}</strong><small>{risk.model_type.replaceAll("_", " ")}</small></div>
        <div className="source-cell"><span>Data sources</span><div>{Object.entries(risk.data_sources).map(([key, value]) => <span className="source-badge" key={key}>{key} = {value.toUpperCase()}</span>)}</div></div>
      </div>
      <div className="factor-list">
        <span>Top risk factors</span>
        <div>{risk.top_risk_factors.length ? risk.top_risk_factors.map((factor) => <span key={factor}>{factor}</span>) : <em>No elevated factors detected</em>}</div>
      </div>
    </Panel>
  );
}
