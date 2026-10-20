import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/components/maralaDischargeData.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { dischargePoints, dischargeSegments, DAY_MS } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const data = JSON.parse(await readFile(new URL("../public/data/marala-monthly.json", import.meta.url), "utf8"));
const points = dischargePoints(data);
const daily = points.filter(point => point.kind === "history");
assert.equal(daily.length, data.recent_history.daily.length);
assert.deepEqual(daily.map(point => point.value), data.recent_history.daily.map(row => row.inflow_cumecs));
assert.deepEqual(daily.map(point => point.time), data.recent_history.daily.map(row => Date.parse(row.observed_at)));
const groups = dischargeSegments(points, "history");
assert.equal(groups.flat().length, daily.length);
for (const group of groups) {
  for (let i = 1; i < group.length; i++) assert.equal(Date.parse(group[i].date) - Date.parse(group[i - 1].date), DAY_MS);
}
// A missing day must break the line even when both readings are in the same month.
const fixture = [{ date: "2025-07-01", kind: "history" }, { date: "2025-07-02", kind: "history" }, { date: "2025-07-04", kind: "history" }];
assert.deepEqual(dischargeSegments(fixture, "history").map(group => group.length), [2, 1]);
assert.ok(dischargeSegments(points, "forecast").flat().every(point => point.kind === "forecast"));
const forecast = points.filter(point => point.kind === "forecast");
const issue = Date.parse(data.current_provider_outlook.forecast_issue_start);
const expectedDays = data.current_provider_outlook.daily_forecast.filter(row => Date.parse(row.date) >= issue && row.date <= data.current_provider_outlook.forecast_available_through);
assert.deepEqual(forecast.map(point => point.value), expectedDays.map(row => row.mean_cumecs));
assert.equal(forecast.length, data.current_provider_outlook.daily_forecast.length, "Maximum horizon must not truncate daily forecasts");
assert.ok(forecast.every(point => point.resolution === "daily" && point.date.length === 10));
assert.deepEqual(dischargeSegments(fixture.map(point => ({ ...point, kind: "forecast" })), "forecast").map(group => group.length), [2, 1]);
const monthly = dischargePoints(data, "monthly");
const measuredMonths = data.recent_history.monthly.filter(row => row.flow_mean_cumecs !== null);
assert.deepEqual(monthly.filter(point => point.kind === "history").map(point => point.value), measuredMonths.map(row => row.flow_mean_cumecs));
assert.deepEqual(monthly.filter(point => point.kind === "forecast").map(point => point.value), data.current_provider_outlook.forecast.map(row => row.monthly_mean_discharge_cumecs.mean));
assert.ok(monthly.every(point => point.resolution === "monthly" && point.date.length === 7));
assert.deepEqual(monthly.filter(point => point.kind === "history").map(point => point.days), measuredMonths.map(row => row.days));
console.log(`Daily chart verified: ${daily.length} unaveraged measured values on actual timestamps; ${groups.length} segments with missing-day gaps; forecast separate`);
console.log(`Resolution tabs verified: ${forecast.length} daily forecasts; ${measuredMonths.length} observed monthly averages and ${data.current_provider_outlook.forecast.length} forecast monthly averages`);
