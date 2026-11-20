/**
 * Standalone, shareable copy of the Riverine Forecast tab.
 *
 * The page carries a saved copy of the API responses (share/data/*.json, captured by
 * share/build.mjs) and answers the tab's requests from it, so it opens anywhere without
 * the FloodGuard backend. "Today" is frozen at the moment the data was captured.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RiverineForecastTab } from "../src/components/RiverineForecastTab";
import monitoring from "./data/monitoring.json";
import station from "./data/station.json";
import extended from "./data/extended.json";
import outlook from "./data/outlook.json";
import meta from "./data/meta.json";

const routes: Array<[RegExp, (match: RegExpMatchArray) => unknown]> = [
  [/\/river\/monitoring(\?|$)/, () => monitoring],
  [/\/predictive\/marala-station-forecast(\?|$)/, () => station],
  [/\/predictive\/riverine-extended-forecast(\?|$)/, () => extended],
  [/\/predictive\/riverine-outlook\/([^/?]+)/, (m) => decodeURIComponent(m[1]).toUpperCase() === "MARALA" ? outlook : {
    available: false, station: { id: decodeURIComponent(m[1]).toUpperCase() },
    reason: "No riverine outlook models have been trained for this station yet. Marala (Chenab) is the only station with trained models.",
  }],
];

const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  for (const [pattern, answer] of routes) {
    const match = url.match(pattern);
    if (match) return new Response(JSON.stringify(answer(match)), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  if (/\/api\/v1\//.test(url)) return new Response(JSON.stringify({ detail: "Not part of the saved copy" }), { status: 404, headers: { "Content-Type": "application/json" } });
  return realFetch(input, init);
};

const capturedAt = Date.parse(meta.captured_at);
const stamp = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Karachi" }).format(new Date(capturedAt));
const stampEl = document.getElementById("share-stamp");
if (stampEl) stampEl.textContent = `${stamp} PKT`;

createRoot(document.getElementById("root")!).render(<StrictMode><RiverineForecastTab snapshotAt={capturedAt} /></StrictMode>);
