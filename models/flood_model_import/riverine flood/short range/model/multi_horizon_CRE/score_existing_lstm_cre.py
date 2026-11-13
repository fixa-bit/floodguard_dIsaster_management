"""Re-score the saved 30-day LSTM CRE and climatology on leads 7-30."""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "evaluation comparison" / "model_30_days" / "climatology_residual_ensemble" / "matched_predictions.csv"
OUT = (HERE / "../../evaluation comparison/multi_horizon_CRE").resolve()


def score(y: np.ndarray, p: np.ndarray) -> tuple[float, float, float]:
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    mae = float(np.mean(np.abs(p - y)))
    denom = float(np.sum((y - np.mean(y)) ** 2))
    nse = float(1 - np.sum((p - y) ** 2) / denom) if denom else float("nan")
    return nse, rmse, mae


def main() -> None:
    df = pd.read_csv(SOURCE)
    df = df[df["lead_day"].between(7, 30)]
    rows = []
    for lead, group in df.groupby("lead_day", sort=True):
        y = group["observed_cumecs"].to_numpy(float)
        for model, column in (("single_30day_LSTM_CRE", "Residual_ensemble"), ("seasonal_climatology", "Climatology")):
            nse, rmse, mae = score(y, group[column].to_numpy(float))
            rows.append({"lead_day": int(lead), "model": model, "observed_targets": len(y), "NSE": nse, "RMSE_cumecs": rmse, "MAE_cumecs": mae})
    scores = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    scores.to_csv(OUT / "existing_lstm_cre_leads_7_30.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    colors = {"single_30day_LSTM_CRE": "#128675", "seasonal_climatology": "#596963"}
    labels = {"single_30day_LSTM_CRE": "one 30-day CRE model", "seasonal_climatology": "training-only climatology"}
    for model, group in scores.groupby("model"):
        axes[0].plot(group.lead_day, group.NSE, marker="o", markersize=3, linewidth=2, color=colors[model], label=labels[model])
        axes[1].plot(group.lead_day, group.RMSE_cumecs, marker="o", markersize=3, linewidth=2, color=colors[model], label=labels[model])
    axes[0].set(xlabel="Lead day", ylabel="NSE (higher is better)", title="Flow skill")
    axes[0].axhline(0, color="#aaaaaa", linewidth=1)
    axes[1].set(xlabel="Lead day", ylabel="RMSE (m³/s; lower is better)", title="Flow error")
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle("Saved single-model CRE: lead-by-lead check, 2022–2024", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "existing_lstm_cre_leads_7_30.png", dpi=170)
    plt.close(fig)

    model_scores = scores[scores.model.eq("single_30day_LSTM_CRE")]
    climate_scores = scores[scores.model.eq("seasonal_climatology")].set_index("lead_day")
    beat_count = int(sum(row.RMSE_cumecs < climate_scores.loc[row.lead_day, "RMSE_cumecs"] for row in model_scores.itertuples()))
    text = ["## Existing trained LSTM CRE: all daily leads 7–30", "",
            f"The project's already-trained single 30-day LSTM CRE emits a forecast for every daily lead 1–30. Re-scoring its saved predictions shows it beat the matched training-only seasonal climatology by RMSE on **{beat_count}/24** leads from 7 through 30.", "",
            "| Lead | CRE NSE | Climatology NSE | CRE RMSE (m³/s) | Climatology RMSE (m³/s) | N |",
            "|---:|---:|---:|---:|---:|---:|"]
    for lead in [7, 14, 21, 30]:
        c = scores[(scores.lead_day.eq(lead)) & scores.model.eq("single_30day_LSTM_CRE")].iloc[0]
        b = scores[(scores.lead_day.eq(lead)) & scores.model.eq("seasonal_climatology")].iloc[0]
        text.append(f"| {lead} | {c.NSE:.3f} | {b.NSE:.3f} | {c.RMSE_cumecs:.1f} | {b.RMSE_cumecs:.1f} | {c.observed_targets} |")
    text += ["", "**Important:** this existing LSTM CRE is not the Ridge POC above. It has a 365-day encoder, future-weather sequence and observed-flow history. Its comparison uses noisy realized ERA5-Land weather, not archived forecasts available at issue time. The 2022–2024 comparison years have also been inspected in earlier project work. This confirms the model can produce useful hindcast scores across those leads under the proxy setup; it does not prove operational skill or prove one architecture is universally better.", ""]
    (OUT / "existing_lstm_cre_leads_7_30.md").write_text("\n".join(text), encoding="utf-8")
    report = OUT / "REPORT.md"
    if report.exists():
        with report.open("a", encoding="utf-8") as f:
            f.write("\n\n" + "\n".join(text) + "\n\n![Existing trained CRE versus climatology](existing_lstm_cre_leads_7_30.png)\n")
    print(f"CRE beat climatology RMSE at {beat_count}/24 leads")
    print("\n".join(text[:12]))


if __name__ == "__main__":
    main()
