import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// Fail packaging if the independent JSON/CSV fallback is missing or inconsistent.
const dataRoot = new URL("../public/data/", import.meta.url);
const data = JSON.parse(await readFile(new URL("marala-monthly.json", dataRoot), "utf8"));
const csv = (await readFile(new URL("marala-monthly-dataset.csv", dataRoot), "utf8")).trim().split(/\r?\n/);
const header = csv.shift().split(",");
const monthIndex = header.indexOf("month");
assert.notEqual(monthIndex, -1, "Monthly CSV must contain the month column");
assert.equal(data.monthly_records, 264);
assert.equal(data.dataset.length, 264);
assert.equal(csv.length, 264);
assert.deepEqual(csv.map(row => row.split(",")[monthIndex]), data.dataset.map(row => row.month));
assert.equal(data.dataset[0].month, "2000-01");
assert.equal(data.dataset.at(-1).month, "2021-12");
const firstMonth = data.recent_history.period_start.slice(0, 7).split("-").map(Number);
const lastMonth = data.recent_history.period_end.slice(0, 7).split("-").map(Number);
assert.equal(data.recent_history.monthly.length, (lastMonth[0] - firstMonth[0]) * 12 + lastMonth[1] - firstMonth[1] + 1);
assert.equal(data.recent_history.monthly_records, data.recent_history.monthly.filter(row => row.flow_mean_cumecs !== null).length);
assert.equal(data.recent_history.station_observation, true);
assert.equal(data.recent_history.daily_records, data.recent_history.daily.length);
assert.equal(new Set(data.recent_history.daily.map(row => row.date)).size, data.recent_history.daily.length);
for (const row of data.recent_history.daily) {
  assert.equal(row.measurement_kind, "FFD_reported_observation");
  assert.ok(Number.isFinite(row.inflow_cumecs) && row.inflow_cumecs >= 0);
  assert.equal(row.observed_at, `${row.date}T06:00:00+05:00`);
}
assert.equal(data.recent_history.monthly[0].month, data.recent_history.period_start.slice(0, 7));
assert.equal(data.recent_history.monthly.at(-1).month, data.recent_history.period_end.slice(0, 7));
for (const row of data.recent_history.monthly) {
  if (row.days === 0) assert.equal(row.flow_mean_cumecs, null);
  else assert.ok(Number.isFinite(row.flow_mean_cumecs) && row.flow_mean_cumecs >= 0);
  assert.equal(row.source_urls.length, row.days);
}
assert.ok(data.recent_history.monthly.at(-1).month < data.current_provider_outlook.forecast[0].target_month);
assert.ok(data.current_provider_outlook.daily_forecast.length >= 30);
assert.match(data.current_provider_outlook.daily_time_basis, /not an instantaneous 06:00/);
for (const month of data.current_provider_outlook.forecast) {
  const rows = data.current_provider_outlook.daily_forecast.filter(row => row.date.startsWith(month.target_month));
  assert.equal(rows.length, month.days);
  const average = rows.reduce((sum, row) => sum + row.mean_cumecs, 0) / rows.length;
  assert.ok(Math.abs(average - month.monthly_mean_discharge_cumecs.mean) < 1e-8, "Monthly forecast must average the same saved daily forecasts");
}
console.log("Marala packaged JSON and CSV: 264 matching monthly records (2000–2021)");
console.log(`Chart history: ${data.recent_history.daily_records} measured daily snapshots; monthly summaries retained in details`);
