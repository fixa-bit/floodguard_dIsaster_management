import assert from "node:assert/strict";
import { chartTime, nearestDischargePoint, stationForecastSeries } from "../src/components/stationForecastData.ts";

const station = {
  current_source: "FFD observed", observed_at: "2026-10-11T07:00:00Z", current_discharge_cumecs: 32.82,
  providers: [{ provider: "GloFAS", source: "Open-Meteo GloFAS 5 km grid", series: Array.from({ length: 28 }, (_, index) => ({
    time: new Date(Date.UTC(2026, 8, 27 + index)).toISOString().slice(0, 10), value: index === 15 ? 784.24 : 1126.2 - index * 20,
    phase: index <= 14 ? "past" : "forecast",
  })) }],
};
const history = { source: "FFD stored observations", samples: [
  { time: "2026-10-10T07:00:00Z", value: 32.82 }, { time: "2026-10-11T07:00:00Z", value: 999 },
  { time: "bad", value: 10 }, { time: "2026-10-11T01:00:00Z", value: NaN },
] };
const series = stationForecastSeries(station, history);
const observed = series.find((item) => item.id === "observed");
const past = series.find((item) => item.id === "GloFAS-past");
const forecast = series.find((item) => item.id === "GloFAS-forecast");
assert.equal(observed.points.length, 2);
assert.equal(observed.points.at(-1).value, 32.82, "Current reading overrides older cache at same timestamp");
assert.equal(past.points.length, 7, "Only seven days of model history");
assert.equal(past.points[0].time, "2026-10-05");
assert.equal(forecast.points.length, 5);
assert.equal(forecast.points[0].time, "2026-10-12");
assert.equal(forecast.points[0].value, 784.24, "No scaling or calibration of model values");
assert.equal(nearestDischargePoint(observed, chartTime("2026-10-12")), undefined, "Do not project an observation into the forecast period");
assert.equal(nearestDischargePoint(forecast, chartTime("2026-10-05")), undefined, "Do not project forecasts backward");
assert.equal(nearestDischargePoint(observed, chartTime("2026-10-11T07:00:00+00:00")).value, 32.82);
assert.equal(chartTime("2026-10-11T12:00:00+05:00"), chartTime("2026-10-11T07:00:00Z"), "PKT/UTC instants align");
assert.equal(chartTime("2026-10-12"), Date.UTC(2026, 9, 12), "Daily model dates retain UTC boundary");
assert.equal(stationForecastSeries({ ...station, current_source: "GloFAS modeled", providers: [] }).length, 0, "Modeled current reading never becomes an observation");
console.log("PASS: exact discharge values, UTC/PKT alignment, seven-day history, five-day forecast, cache reconciliation and date-bounded tooltip.");
