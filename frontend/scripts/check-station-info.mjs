import assert from "node:assert/strict";
import { stationCardProperties, readStationCard, stationIsStale, pakistanTime, sparklinePath, withStationHistory } from "../src/components/stationInfo.ts";
import { stationPopupPosition } from "../src/components/stationPopupPosition.ts";
const now = Date.now();
const feature = { type: "Feature", id: "TAUNSA", geometry: { type: "Point", coordinates: [70.836721, 30.518528] }, properties: {
  name: "Taunsa Barrage", category: "barrages", stationId: "TAUNSA", warning_discharge_cumecs: 100, danger_discharge_cumecs: 200,
} };
const station = { current_source: "FFD observed", observed_at: new Date(now).toISOString(), current_discharge_cumecs: 130,
  change_24h_cumecs: 30, change_source: "FFD observed 24h change", flood_category: "Below low", river: "Indus" };
const card = readStationCard(stationCardProperties(feature, station, 60).properties);
assert.equal(card.kind, "barrage"); assert.equal(card.status, "Rising"); assert.ok(card.dangerMessage.includes("70 cumecs below"));
assert.equal(stationIsStale(card, now), false); assert.equal(stationIsStale(card, now + 61 * 60000), true);
assert.equal(card.readings.find((row) => row.label === "Current discharge").source, "FFD observed");
assert.deepEqual(card.readings.find((row) => row.label === "Water level"), { label: "Water level", value: "Unavailable", source: "Not provided by current feeds" });
const levelCard = readStationCard(stationCardProperties(feature, { ...station, observed_level_value: 0, observed_level_unit: "ft", level_source: "FFD Lahore observed", level_observed_at: station.observed_at }, 60).properties);
assert.deepEqual(levelCard.readings.find((row) => row.label === "Water level"), { label: "Water level", value: "0 ft", source: "FFD Lahore observed" });
const gisLevel = readStationCard(stationCardProperties({ ...feature, properties: { ...feature.properties, observed_level_m: 3.5, level_source: "Gauge telemetry" } }, station, 60).properties);
assert.equal(gisLevel.readings.find((row) => row.label === "Water level").value, "3.5 m");
assert.equal(gisLevel.readings.find((row) => row.label === "Water level").source, "Gauge telemetry");
assert.match(pakistanTime("2026-10-11T10:00:00Z"), /11 Oct 2026.*3:00 pm PKT/i);
assert.equal(pakistanTime("invalid"), undefined);
const reference = readStationCard(stationCardProperties({ ...feature, properties: { ...feature.properties, category: "confluences" } }, station, 60).properties);
assert.equal(reference.kind, "reference"); assert.deepEqual(reference.readings, []); assert.deepEqual(reference.thresholds, []); assert.deepEqual(reference.trend, []);
const dam = readStationCard(stationCardProperties({ ...feature, properties: { name: "Dam", category: "dams", percent_full: 0, inflow_cumecs: NaN, outflow_cumecs: null } }, undefined, 60).properties);
assert.deepEqual(dam.readings, [{ label: "Full", value: "0 %" },
  { label: "Current discharge", value: "Unavailable", source: "Not provided by current feeds" },
  { label: "Water level", value: "Unavailable", source: "Not provided by current feeds" }]);
const history = { station_id: "TAUNSA", source: "FFD stored observations", samples: [
  { time: new Date(now - 24 * 3600000).toISOString(), value: 100 }, { time: new Date(now - 3 * 3600000).toISOString(), value: 125 }, { time: station.observed_at, value: 130 },
] };
assert.ok(sparklinePath(history.samples)); assert.equal(sparklinePath([{ time: "bad", value: NaN }]), undefined);
assert.equal(withStationHistory(card, history).trend.find((row) => row.label === "3h change").value, "5 cumecs");
const bounds = { left: 240, top: 8, right: 1432, bottom: 992 };
const obstacles = [{ left: 240, top: 8, right: 1370, bottom: 182 }, { left: 244, top: 188, right: 460, bottom: 848 }, { left: 244, top: 896, right: 1428, bottom: 992 }];
for (const point of [{ x: 260, y: 190 }, { x: 1430, y: 980 }, { x: 700, y: 500 }]) {
  const placement = stationPopupPosition(point, bounds, obstacles, 326, 380);
  assert.ok(placement); assert.ok(placement.left >= bounds.left && placement.left + 326 <= bounds.right);
  assert.ok(placement.top >= bounds.top && placement.top + placement.maxHeight <= bounds.bottom);
  for (const obstacle of obstacles) assert.ok(placement.left + 326 <= obstacle.left || placement.left >= obstacle.right || placement.top + placement.maxHeight <= obstacle.top || placement.top >= obstacle.bottom);
}
const mobileBounds = { left: 8, top: 8, right: 382, bottom: 836 };
const mobileObstacles = [{ left: 94, top: 8, right: 380, bottom: 48 }, { left: 8, top: 55, right: 380, bottom: 185 },
  { left: 12, top: 220, right: 210, bottom: 268 }, { left: 8, top: 699, right: 382, bottom: 833 }];
const mobilePosition = stationPopupPosition({ x: 208, y: 520 }, mobileBounds, mobileObstacles, 326, 380);
assert.ok(mobilePosition);
for (const obstacle of mobileObstacles) assert.ok(mobilePosition.left + 326 <= obstacle.left || mobilePosition.left >= obstacle.right || mobilePosition.top + mobilePosition.maxHeight <= obstacle.top || mobilePosition.top >= obstacle.bottom);
console.log("Station templates, missing values, PKT times, staleness, observed changes and desktop/mobile obstacle-aware positioning passed.");
