/* Daily Flood Situation Report body. Shared pieces: _base.html, _helpers.js, _tip.js (see app/reports/render.py). */

/* ================= header ================= */
const M = D.meta, S = D.summary;
const simRuns = D.simulation_runs || [];
out += `<div class="sample">Generated automatically from the FloodGuard portal. Every value is real portal data, labeled with where it came from.</div>`;
if (D.has_simulated) out += `<div class="testbar">⚑ TEST REPORT: contains simulated data<span>This report includes items from portal simulation runs (${simRuns.map(r => esc(r.name) + " · " + r.run_id).join(", ") || "see section 11"}) and placeholder model outputs. Every simulated item carries a striped SIMULATED label. Do not use simulated figures for operational decisions.</span></div>`;
const statusColor = {Normal:"var(--good)",Watch:"var(--warn)",Warning:"var(--serious)",Emergency:"var(--crit)"}[S.status];
out += `<div class="inner"><header class="top" style="padding-bottom:20px"><div><div class="eyebrow">FloodGuard AI · National Flood Monitoring</div><h1>Daily Flood Situation Report</h1>
  <div class="meta"><span>Report no.</span><b class="mono">${esc(M.report_no)}</b><span>Reporting period</span><b>${esc(M.period)}</b><span>Generated</span><b>${esc(M.generated)}</b>
  <span>Data mode</span><b>${esc(M.data_mode)}${M.simulation_enabled ? " + simulation on" : ""}</b><span>Units</span><b>${esc(M.units)}</b></div></div>
  <div class="status-big"><div class="eyebrow">National status</div><div class="lvl"><span class="dot" style="background:${statusColor};width:14px;height:14px"></span>${S.status}</div><div class="note">${esc(S.status_note)}</div></div></header></div>`;

/* ================= 00 ================= */
const P = D.provenance, ptot = Object.values(P).reduce((a,b) => a+b, 0);
section("00", "Where This Report's Data Comes From", [], `<p>Every section, row and figure carries a label naming where its data came from. Simulated data always has the striped label.</p>
  ${table(["Label","Meaning","#Items"], [
    ["obs","Measured by a real gauge, or a real citizen report or incident"],["off","Forecast issued by the PMD Flood Forecasting Division"],
    ["api","Modeled data from an external flood or weather service (GloFAS, GEOGloWS, Open-Meteo)"],["ml","Output of a FloodGuard model"],
    ["sat","Real Sentinel-1 radar image from a real satellite pass"],["est","Calculated by FloodGuard from other data (travel time, exposure, signals)"],
    ["sim","Test data from a portal simulation run, or a placeholder model. Not real conditions"],
    ["ai","Written by AI (Claude) to explain a flagged value, from cited documents and data. A draft: it never changes a value, category or status"]].map(([k,m]) => `<tr><td>${src([k])}</td><td>${m}</td><td class="n">${k === "ai" ? aiNotes() : P[k]||0}</td></tr>`))}
  <div class="fig"><h3>Share of report items by data source</h3>${stackbar(Object.keys(SRCN).map(k => ({label:SRCN[k], n:P[k]||0, color:SRCC[k]})))}</div>`);

/* ================= 01 ================= */
const simItems = [];
const simAlerts = D.operations.alerts.filter(a => a.sources.includes("sim")).length, simInc = D.operations.incidents.filter(i => i.sources.includes("sim")).length;
const simModels = D.models.rows.filter(r => r.sources.includes("sim")).length;
if (simAlerts) simItems.push(`${simAlerts} alert(s)`); if (simInc) simItems.push(`${simInc} incident(s)`); if (simModels) simItems.push(`${simModels} model outputs from placeholder models`);
if (D.satellite.test_flood) simItems.push(`the test flood in ${esc(D.satellite.test_flood.region)} (section 11)`);
section("01", "Executive Summary", ["obs","api","sat"].concat(D.has_simulated ? ["sim"] : []), `
  ${simItems.length ? `<div class="callout crit">⚑ Simulated items in this report: ${simItems.join(", ")}. They are labeled and do not affect the national status.</div>` : ""}
  <p class="lead">${esc(S.headline)}</p>
  <div class="kpis">${S.kpis.map(k => `<div class="kpi"><span class="v">${esc(k.value)}</span><span class="l">${esc(k.label)}</span><span class="d">${esc(k.delta||"")}</span></div>`).join("")}</div>
  <div class="grid2"><div><h3>Top concerns</h3>${S.concerns.length ? `<ol class="concerns">${S.concerns.map(c => `<li><span>${src(c.sources)} ${esc(c.text)}</span></li>`).join("")}</ol>` : `<p>No concerns raised by today's data.</p>`}</div>
  <div class="fig"><h3>Stations by FFD flood category</h3>${stackbar(Object.entries(S.categories).map(([k,n]) => ({label:k, n, color:CAT[k]||"var(--muted-bar)"})))}<p class="note">All 22 stations appear every day. A station with no reading counts as "Unavailable".</p></div></div>`);

/* ================= 02 ================= */
section("02", "Flagged Signals &amp; AI Analysis", ["obs","api"].concat(FLAGS && FLAGS.some(f => f.simulated) ? ["sim"] : []).concat(aiNotes() ? ["ai"] : []), aiSection());

/* ================= 03 ================= */
const ST = D.stations, rivers = [...new Set(ST.map(s => s.river))];
const net = riverNetwork(rivers.map(r => ({label:r, stations:ST.filter(s => s.river === r)})));
const stRows = []; let cur = "";
ST.forEach(s => { if (s.river !== cur) { cur = s.river; stRows.push(`<tr class="river"><td colspan="10">${esc(cur)}</td></tr>`); }
  stRows.push(`<tr${s.sources.includes("sim")?' class="simrow"':""}><td>${esc(s.name)}</td><td>${src(s.sources) || "—"}</td><td class="n">${fmt(s.inflow,1)}</td><td class="n">${fmt(s.outflow,1)}</td><td class="n">${s.change_24h == null ? "—" : sgn(s.change_24h)}</td>
    <td class="note">Unavailable</td><td>${spark(s.history.map(h => h.value))}</td><td class="n">${s.rising_days == null ? "—" : s.rising_days}</td><td>${cat(s.category)}</td><td class="mono">${esc(s.observed_at||"—")}${s.stale ? ` <span class="tag" style="color:var(--crit);border-color:var(--crit)">${s.age_hours == null ? "No data" : "Stale " + Math.round(s.age_hours) + " h"}</span>` : ""}</td></tr>`); });
section("03", "Observed River Conditions", ["obs"], `<p>All 22 FFD stations, upstream to downstream. Inflow and outflow are FFD gauge readings. The 24 h change compares with the previous stored FFD reading. "% of normal" needs station climatology, which the portal does not have yet.</p>
  <div class="fig"><h3>River network status</h3>${net}</div>
  ${table(["Station","Source","#Inflow","#Outflow","#24 h change","% of normal","Recent trend","#Rising days","FFD category","Observed (PKT)"], stRows)}`);

/* ================= 04 ================= */
section("04", "Flood Wave Travel", ["est"], D.wave.waves.length ? D.wave.waves.map(w => `<div class="fig"><h3>${esc(w.river)}: expected arrival of the ${esc(w.origin)} rise</h3>${table(["Station","#Hours after origin"], w.path.map(p => `<tr><td>${esc(p.name)}</td><td class="n">${p.hours ? "+" + p.hours : "Origin"}</td></tr>`))}</div>`).join("") + `<p class="note">Travel times are indicative FloodGuard estimates, to be calibrated against FFD peak timings.</p>`
  : `<p>No station is rising fast enough to track a flood wave. ${esc(D.wave.rule)}</p>`);

/* ================= 05 ================= */
const IO = D.inout.slice().sort((a,b) => Math.max(b.inflow,b.outflow) - Math.max(a.inflow,a.outflow));
section("05", "Dams &amp; Barrages: Inflow vs Outflow", ["obs"], `<p>The difference between inflow and outflow shows whether water is being stored, released or withdrawn into canals.</p>
  <div class="grid2"><div class="fig">${hbars(IO.slice(0,10).map(r => ({label:r.name, values:[r.inflow, r.outflow]})), [{name:"Inflow",color:"var(--s1)"},{name:"Outflow",color:"var(--s2)"}], {unit:" cumecs", aria:"Inflow and outflow"})}</div>
  ${table(["Site","#Net (cumecs)","Reading"], IO.map(r => `<tr><td>${esc(r.name)}</td><td class="n">${fmt(r.net,1)}</td><td>${esc(r.reading)}</td></tr>`))}</div>`);

/* ================= 06 ================= */
const U = D.upstream, provColor = {GloFAS:"var(--s2)", GEOGloWS:"var(--s3)", "Google Flood Hub":"var(--s1)"};
const fcRows = D.forecasts.map(f => `<tr><td>${esc(f.name)}</td><td>${src(f.sources) || "—"}</td><td class="n">${fmt(f.current,1)}</td><td class="n">${fmt(f.forecast,1)}</td><td class="mono">${esc(f.valid||"—")}</td><td class="n">${fmt(f.peak,1)}</td><td class="mono">${esc(f.peak_at||"—")}</td><td>${f.mismatch ? pill("Check: forecast cell may not match station","var(--warn)") : esc(f.official_text || "—")}</td></tr>`);
const upBody = U.available ? `<div class="gallery">${U.stations.map(u => `<div class="fig shot" style="padding:12px"><b style="font-family:var(--display)">${esc(u.name)}</b>${lines(u.providers.map(p => ({name:p.provider, color:provColor[p.provider]||"var(--ink-3)", points:p.series})), {aria:u.name})}
    <div class="legend">${u.providers.map(p => `<span><i class="sw" style="background:${provColor[p.provider]||"var(--ink-3)"}"></i>${esc(p.provider)}: peak ${fmt(p.peak,1)}</span>`).join("")}</div>
    <div>${u.agreement_pct == null ? "" : u.agree ? pill(`Sources agree (gap ${fmt(u.gap_cumecs)} cumecs)`, "var(--good)") : pill(`Sources disagree: ${u.agreement_pct}%, ${fmt(u.gap_cumecs)} cumecs`, "var(--warn)")}</div>
    <div class="note">${u.signals.map(s => `${esc(s.type)}: ${esc(s.severity)} ${s.probability}%`).join(" · ")}</div></div>`).join("")}</div>
  <p class="note">Flood-type signals are FloodGuard estimates from forecast rainfall and flow. A gap counts as disagreement only when it is over 25% and over 100 cumecs.</p>` : unavailable(U.reason);
const sea = D.seasonal;
const seaBody = sea.available ? `<div class="fig" style="max-width:560px">${hbars(sea.rows.map(r => ({label:r.month, values:[r.mean, r.observed_normal]})), [{name:"Provider outlook (mean)",color:"var(--s1)"},{name:"Observed same month",color:"var(--ink-3)"}], {unit:" cumecs", labels:true, aria:"Seasonal outlook", left:70})}
  ${table(["Month","#Mean","#p25","#p75","#Observed same month"], sea.rows.map(r => `<tr><td>${r.month}</td><td class="n">${fmt(r.mean,1)}</td><td class="n">${fmt(r.p25,1)}</td><td class="n">${fmt(r.p75,1)}</td><td class="n">${r.observed_normal == null ? "No record" : fmt(r.observed_normal,1)}</td></tr>`))}
  <p class="note">${esc(sea.source)}, issued ${esc(sea.issued)}. ${esc(sea.note)}</p></div>` : unavailable(sea.reason);
section("06", "Hydrological Forecast &amp; Outlook", ["api","ml"].concat(simModels ? ["sim"] : []), `<h3>6a. Station forecasts</h3>${table(["Station","Source","#Now","#Forecast","Valid","#Expected peak","Peak date","FFD text / check"], fcRows)}
  <h3>6b. Upstream Source Flood Watch</h3>${upBody}
  <h3>6c. Model predictions</h3>${table(["Model","Target","Source","#Value","Risk class","Model status"], D.models.rows.map(r => `<tr${r.sources.includes("sim")?' class="simrow"':""}><td>${esc(r.model)}</td><td>${esc(r.target)}</td><td>${src(r.sources)}</td><td class="n">${esc(r.value)}</td><td>${esc(r.risk_class)}</td><td>${esc(r.status)}</td></tr>`))}
  <h3>6d. Seasonal outlook: ${esc(sea.station || "Marala")}</h3>${seaBody}`);

/* ================= 07 ================= */
section("07", "Forecast Accuracy", [], unavailable(D.accuracy.reason));

/* ================= 08 ================= */
const R = D.rainfall;
section("08", "Rainfall &amp; Weather", ["api"], R.available ? `<div class="grid2"><div class="fig"><h3>Wettest districts (mm)</h3>${hbars(R.top.map(t => ({label:t.district, values:[t.observed, t.forecast]})), [{name:"Last 24 h",color:"var(--s1)"},{name:"Next 24 h",color:"var(--s2)"}], {unit:" mm", labels:true, aria:"Rainfall"})}</div>
  <div class="fig"><h3>Heat &amp; snowmelt watch</h3>${table(["District","#Temperature","vs normal","Signal"], R.melt.map(m => `<tr><td>${esc(m.district)}</td><td class="n">${fmt(m.temp,1)} °C</td><td class="note">Unavailable</td><td class="note">Cannot assess</td></tr>`))}<p class="note">${esc(R.melt_note)}</p></div></div>` : unavailable(R.reason));

/* ================= 09 ================= */
const DI = D.districts, yes = v => v ? `<span class="check">● Yes</span>` : `<span class="check" style="color:var(--ink-3)">○ No</span>`;
section("09", "District Risk Screening", ["api","est"], DI.available ? `<div class="fig"><h3>${DI.total} districts by risk band</h3>${stackbar([["High","var(--crit)"],["Medium","var(--serious)"],["Low","var(--good)"]].map(([k,c]) => ({label:k, n:DI.bands[k]||0, color:c})))}</div>
  <div class="grid2"><div><h3>Highest risk</h3>${table(["District","#Risk","Main factors"], DI.top_risk.map(d => `<tr><td>${esc(d.district)}</td><td class="n">${d.risk}%</td><td>${esc(d.factors.join(", ")||"—")}</td></tr>`))}</div>
  <div><h3>Districts with warning signs</h3>${table(["District","High risk","Station rising","#Citizen reports","Open incident","#Signs"], DI.multi_signal.map(d => `<tr${d.signals.simulated_incident?' class="simrow"':""}><td>${esc(d.district)}</td><td>${yes(d.signals.high_risk)}</td><td>${yes(d.signals.station_rising)}</td><td class="n">${d.signals.citizen_reports}</td><td>${d.signals.open_incident.length ? "#" + d.signals.open_incident.join(", #") + (d.signals.simulated_incident ? " " + src(["sim"]) : "") : yes(false)}</td><td class="n"><b>${d.signal_count} / 4</b></td></tr>`))}</div></div>
  <p class="note">A weather-only screen that ranks districts for attention. It is not an inundation forecast.</p>` : unavailable(DI.reason));

/* ================= 10 ================= */
const O = D.operations, C = O.counts;
section("10", "Alerts, Incidents &amp; Citizen Reports", ["obs"].concat(simAlerts||simInc ? ["sim"] : []), `<div class="grid2">${table(["Item","#New in period","#Open","#Total"], [["Alerts awaiting approval",C.alerts],["Incidents",C.incidents],["Citizen reports",C.reports]].map(([n,c]) => `<tr><td>${n}</td><td class="n">${c.new}</td><td class="n">${c.open}</td><td class="n">${c.total}</td></tr>`))}
  <div class="fig"><h3>Waiting times</h3>${table(["Item","#Waiting","#Target","Status"], O.waiting.map(w => `<tr><td>${esc(w.item)}</td><td class="n">${hrs(w.hours)}</td><td class="n">${hrs(w.target)}</td><td>${w.hours == null ? "Nothing waiting" : w.hours > w.target ? pill("Over target","var(--crit)") : pill("Within target","var(--good)")}</td></tr>`))}<p class="note">${esc(O.waiting_note)}</p></div></div>
  <h3>Alerts</h3>${table(["#","Time","Location","Source","Severity","Approval","Message"], O.alerts.map(a => `<tr${a.sources.includes("sim")?' class="simrow"':""}><td class="mono">${a.id}</td><td class="mono">${esc(a.time)}</td><td>${esc(a.location)}</td><td>${src(a.sources)}</td><td>${esc(a.severity)}</td><td>${esc(a.approval)}</td><td>${esc(a.message)}</td></tr>`))}
  <h3>Incidents</h3>${table(["#","Type","Location","Source","Severity","Status","#Age","Description"], O.incidents.map(i => `<tr${i.sources.includes("sim")?' class="simrow"':""}><td class="mono">${i.id}</td><td>${esc(i.type)}</td><td>${esc(i.location)}</td><td>${src(i.sources)}</td><td>${esc(i.severity)}</td><td>${esc(i.status)}</td><td class="n">${hrs(i.age_hours)}</td><td>${esc(i.description)}</td></tr>`))}
  <h3>Citizen reports</h3>${table(["#","Location","Source","Verification","Status","#Water depth","#Age","Description"], O.reports.map(r => `<tr><td class="mono">${r.id}</td><td>${esc(r.location)}</td><td>${src(r.sources)}</td><td>${esc(r.verification)}</td><td>${esc(r.status)}</td><td class="n">${r.depth_cm == null ? "—" : fmt(r.depth_cm) + " cm"}</td><td class="n">${hrs(r.age_hours)}</td><td>${esc(r.description)}</td></tr>`))}`);

/* ================= 11 ================= */
const SAT = D.satellite, TF = SAT.test_flood;
const checkRows = SAT.checks.map(c => `<tr${c.triggered_by_simulation?' class="simrow"':""}><td>${esc(c.location)}</td><td>${esc(c.why)}</td><td class="mono">${esc((c.pre_date||"—").slice(0,10))}</td><td class="mono">${esc((c.during_date||"—").slice(0,10))}</td><td>${src(c.sources)}</td><td class="n">${c.potential_flood_area_km2 == null ? "—" : fmt(c.potential_flood_area_km2,1) + " km²"}</td><td>${c.error ? pill("Check failed: " + c.error, "var(--muted-bar)") : c.result === "potential_flooding_detected" ? pill("Possible flood water, needs review","var(--warn)") : pill(String(c.result).replace(/_/g," "),"var(--good)")}</td></tr>`);
const checkFigs = SAT.checks.filter(c => c.during_radar_image_data_url).map(c => `<div class="fig"><h3>${esc(c.location)}: real radar, before and latest</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">${radar(c.pre_radar_image_data_url, [c.permanent_water_image_data_url], "Before · " + (c.pre_date||"").slice(0,10), c.coordinates)}${radar(c.during_radar_image_data_url, [c.permanent_water_image_data_url, c.image_data_url], "Latest · " + (c.during_date||"").slice(0,10), c.coordinates)}</div>
  <div class="legend"><span><i class="sw box" style="background:#00cae1"></i>Water outside permanent-water reference</span><span><i class="sw box" style="background:#4c73ff"></i>Permanent water (excluded)</span></div>
  <p class="note">${esc(c.limitation)} Source: ${esc(c.source)}.</p></div>`).join("");
let tfBody = "";
if (TF) {
  if (TF.exposure_error) tfBody = unavailable("Test flood could not run: " + TF.exposure_error);
  else { const sar = TF.sar || {}, pop = TF.population || {}, cnt = TF.counts || {};
    const known = pop.known_area_fraction == null ? null : Math.round(pop.known_area_fraction*100);
    tfBody = `<div class="callout crit">${src(["sim"])} <b>Test flood: ${esc(TF.label)}</b>. A ${fmt(TF.area_km2,1)} km² synthetic flood polygon in ${esc(TF.region)}, drawn over the real Sentinel-1 image and run through the portal's exposure and population analysis. This tests the full chain. It is not a real flood.</div>
    <div class="grid2"><div class="fig"><h3>Real radar with simulated extent</h3>${sar.during_radar_image_data_url ? radar(sar.during_radar_image_data_url, [sar.permanent_water_image_data_url, sar.image_data_url], "Latest · " + (sar.during_date||"").slice(0,10), sar.coordinates, TF.extent) : unavailable(TF.sar_error || "No radar image")}
      <div class="legend"><span><i class="sw box" style="background:repeating-linear-gradient(135deg,#2bc4dd 0 2px,transparent 2px 4px);outline:1px solid #2bc4dd"></i>Simulated flood extent</span><span><i class="sw box" style="background:#00cae1"></i>Real detected water</span><span><i class="sw box" style="background:#4c73ff"></i>Permanent water</span></div>
      <p class="note">${src(["sat"])} image from the pass of ${esc((sar.during_date||"").slice(0,10))}. The hatched area extends past the image edge where the test polygon is larger than the 7.7 km radar window.</p></div>
    <div class="fig"><h3>Estimated impact inside the simulated extent</h3><div>${src(["sim","est"])}</div>
      <div class="kpis" style="grid-template-columns:repeat(2,1fr)">${[[fmt(TF.people), "People (modeled)"], [fmt(cnt.settlements?.count), "Settlements"], [fmt(cnt.buildings?.count), "Buildings (OSM)"], [fmt(cnt.roads?.length_km,1) + " km", `Roads (${fmt(cnt.roads?.count)} segments)`], [fmt(cnt.schools?.count), "Schools"], [fmt(cnt.hospitals?.count), "Health facilities"]].map(([v,l]) => `<div class="kpi"><span class="v">${v}</span><span class="l">${l}</span></div>`).join("")}</div>
      ${known != null ? `<div class="callout">Population data covers only ${known}% of the test area (${esc(pop.status||"")}), so the people figure is a lower bound.</div>` : ""}</div></div>
    <div class="grid2"><div class="fig"><h3>Exposed population by area</h3>${pop.rows && pop.rows.length ? hbars(pop.rows.map(r => ({label:r.name, values:[r.people]})), [{name:"People",color:"var(--s1)"}], {labels:true, aria:"Population by area"}) + `<p class="note">${pop.adm3_available ? "" : "Tehsil (ADM3) boundaries are not available for this region, so district totals are shown."}</p>` : unavailable(TF.population_error || "No breakdown")}</div>
      <div><h3>Exposed places and facilities</h3>${table(["Name","Type","Detail"], (TF.facilities||[]).map(f => `<tr><td>${esc(f.name)}</td><td>${esc(f.type)}</td><td>${esc(f.detail)}</td></tr>`))}</div></div>
    <p class="note">${(TF.warnings||[]).map(esc).join(" ")}</p>`; }
}
section("11", "Satellite Flood Detection &amp; Impact", ["sat","est"].concat(TF || SAT.checks.some(c => c.triggered_by_simulation) ? ["sim"] : []), `<p>${esc(SAT.rule)} Each check compares the latest Sentinel-1 radar pass with an earlier pass from the same orbit, and removes permanent water.</p>
  <h3>11a. Satellite checks</h3>${table(["Location","Why checked","Before pass","Latest pass","Source","#Water outside reference","Result"], checkRows)}
  ${SAT.checks.length ? "" : `<p>No watch location qualified, so no real-time satellite checks ran.</p>`}
  ${checkFigs}<h3>11b. Simulated flood test on real imagery</h3>${TF ? tfBody : `<p class="note">No test flood configured for this run.</p>`}`);

/* ================= 12 ================= */
const SN = D.snapshots;
section("12", "App &amp; Simulation Snapshots", ["sim"].filter(() => simRuns.length), `<h3>12a. Simulation runs</h3>${table(["Run","Name","Station","Created (PKT)","In period","#Readings","#Max value","#Alerts","#Incidents"], simRuns.map(r => `<tr class="simrow"><td class="mono">${esc(r.run_id)}</td><td>${esc(r.name)}</td><td>${esc(r.station)}</td><td class="mono">${esc(r.created)}</td><td>${r.active_in_period ? "Yes" : "No"}</td><td class="n">${r.readings}</td><td class="n">${fmt(r.max_value)}</td><td class="n">${r.alerts}</td><td class="n">${r.incidents}</td></tr>`))}
  <h3>12b. Portal visuals in this report</h3><p class="note">Only flood-relevant visuals are captured: model prediction graphs, upstream forecast graphs for selected stations, flood extent and population impact, and the simulated flood spread (2D and 3D). Each appears in its section.</p>
  ${SN.captured ? table(["Visual","Section","Source","Status"], SN.shots.map(s => `<tr${(s.sources||[]).includes("sim")?' class="simrow"':""}><td>${esc(s.view)}</td><td class="mono">${esc(s.section)}</td><td>${src(s.sources)}</td><td>${s.image ? pill("Captured " + s.captured_at, "var(--good)") : pill("Unavailable: " + (s.error||""), "var(--muted-bar)")}</td></tr>`))
    : `<div class="callout"><b>Snapshots unavailable.</b> ${esc(SN.reason)}. Visuals that will be captured: ${SN.shots.map(s => esc(s.view)).join(", ")}.</div>`}`);

/* ================= 13 ================= */
section("13", "Data Quality &amp; System Health", [], `${table(["Feed","Status","Last update","#Coverage","Note"], D.data_quality.map(q => `<tr><td>${esc(q.feed)}</td><td>${pill(q.status, q.status === "OK" ? "var(--good)" : ["Error","Unavailable"].includes(q.status) ? "var(--crit)" : "var(--warn)")}</td><td class="mono">${esc(q.last)}</td><td class="n">${esc(q.coverage)}</td><td>${esc(q.note)}</td></tr>`).concat([aiQualityRow(5)].filter(Boolean)))}
  <p class="note">Data mode: ${esc(M.data_mode)} · Simulation: ${M.simulation_enabled ? "On" : "Off"} · ML model: ${M.ml_model_enabled ? "On" : "Off (rule-based engine active)"}</p>`);

/* ================= 14 ================= */
section("14", "Annex", [], `<div class="grid2"><div><h3>FFD flood categories</h3><div class="legend" style="flex-direction:column;gap:6px">${Object.keys(CAT).map(k => `<span>${cat(k)} <span style="color:var(--ink-3)">${CAT_DEF[k]}</span></span>`).join("")}</div></div>
  <div><h3>Sources &amp; notes</h3><p class="note">River observations: PMD Flood Forecasting Division (FFD). Modeled discharge: GloFAS and GEOGloWS. Weather: Open-Meteo. Satellite: Sentinel-1 RTC via Microsoft Planetary Computer, with Copernicus DEM and JRC Global Surface Water. Exposure: gridded population and OpenStreetMap. Modeled discharge is not measured water level. The data used for this report is stored next to it as report.json.</p></div></div>`);

out += `<footer><div class="inner" style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:12px;color:var(--ink-3)"><span>Prepared by: FloodGuard AI (automatic) · Reviewed by: ________</span><span class="mono">${esc(M.report_no)}</span></div></footer>`;
document.getElementById("report").innerHTML = out;
