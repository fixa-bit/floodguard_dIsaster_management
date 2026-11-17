// Sends dummy flood forecasts, in the FloodGuard portal's model-forecast format,
// to the n8n flood alarm webhook, and prints n8n's reply.
//
//   node automation/n8n/send-dummy-forecast.mjs [scenario] [--url http://localhost:5678/webhook/flood-forecast] [--key SECRET]
//
// --key sends the shared secret in the x-floodguard-key header (needed once webhookSecret is set in Alarm settings).
//
// Scenarios:
//   rising   (default) Watch, Warning, Danger and Extreme forecasts plus one normal one
//   worse    the Lahore and Balloki forecasts get worse: their alarms escalate at once
//   clear    Balloki and the hill torrents are back to normal: all-clear alerts, alarms resolved
//   invalid  a malformed forecast: n8n reports the problem and raises nothing (HTTP 400)
//   repeat   one forecast with a fixed portal id: run it twice and the second is a duplicate
const args = process.argv.slice(2);
const option = (name) => { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : undefined; };
const url = option("--url") ?? "http://localhost:5678/webhook/flood-forecast";
const key = option("--key");
const scenario = args.find((arg, index) => !arg.startsWith("--") && !["--url", "--key"].includes(args[index - 1])) ?? "rising";

const now = Date.now();
const at = (hours) => new Date(now + hours * 3600_000).toISOString();
const meta = { simulation_source: "dummy_flood_forecast_script", model_status: "dummy" };
const forecast = (model_case, target_id, target_name, risk_class, probability, value, value_unit, horizon_hours, model_name) => ({
  model_case, target_id, target_name, issued_at: at(0), valid_at: at(horizon_hours), horizon_hours,
  value, value_unit, probability, risk_class, model_name, point_metadata: meta,
});

const scenarios = {
  rising: [
    forecast("riverine", "balloki", "Balloki", "High", 0.72, 2950, "cumecs", 12, "xgboost_riverine_baseline_v1"),
    forecast("flash", "hill_torrents", "Hill torrents", "Extreme", 0.91, 91, "probability_percent", 3, "lightgbm_flash_flood_baseline_v1"),
    forecast("urban", "lahore_grid", "Lahore urban grid", "Moderate", 0.48, 48, "susceptibility_percent", 6, "urban_flood_susceptibility_v1"),
    forecast("riverine", "trimmu", "Trimmu", "Normal", 0.12, 610, "cumecs", 24, "xgboost_riverine_baseline_v1"),
    forecast("seasonal", "national_basin", "Indus national basin", "Extremely high", 0.81, 81, "risk_percent", 720, "seasonal_outlook_v1"),
  ],
  worse: [
    forecast("urban", "lahore_grid", "Lahore urban grid", "High", 0.88, 88, "susceptibility_percent", 4, "urban_flood_susceptibility_v1"),
    forecast("riverine", "balloki", "Balloki", "Extreme", 0.94, 4120, "cumecs", 8, "xgboost_riverine_baseline_v1"),
  ],
  clear: [
    forecast("riverine", "balloki", "Balloki", "Normal", 0.08, 780, "cumecs", 12, "xgboost_riverine_baseline_v1"),
    forecast("flash", "hill_torrents", "Hill torrents", "Low", 0.05, 5, "probability_percent", 3, "lightgbm_flash_flood_baseline_v1"),
  ],
  invalid: [
    { model_case: "riverine", target_name: "No station id", risk_class: "Catastrophic" },
  ],
  // Carries the portal's forecast id: send it twice and the second is ignored as a duplicate.
  repeat: [
    { ...forecast("riverine", "sulemanki", "Sulemanki", "High", 0.66, 1880, "cumecs", 18, "xgboost_riverine_baseline_v1"), id: 900001 },
  ],
};
if (!scenarios[scenario]) {
  console.error(`Unknown scenario "${scenario}". Use one of: ${Object.keys(scenarios).join(", ")}`);
  process.exit(1);
}

const response = await fetch(url, {
  method: "POST",
  headers: { "Content-Type": "application/json", ...(key ? { "x-floodguard-key": key } : {}) },
  body: JSON.stringify({ source: "floodguard-portal (dummy)", forecasts: scenarios[scenario] }),
});
const text = await response.text();
let body;
try { body = JSON.parse(text); } catch { body = text; }
console.log(`${scenario}: HTTP ${response.status}`);
console.log(typeof body === "string" ? body : JSON.stringify(body, null, 2));
if (!response.ok) process.exitCode = 1;
