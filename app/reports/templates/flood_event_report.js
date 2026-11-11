/* Flood Event Report body. Shared pieces: _base.html, _helpers.js, _tip.js (see app/reports/render.py).
   Data: app/reports/event_report.py. Spec: docs/reports/flood_event_report_spec.md */
const M = D.meta, E = D.event, S = D.summary;
const LVLC = l => l >= 4 ? "var(--crit)" : l === 3 ? "var(--serious)" : l === 2 ? "var(--warn)" : l === 1 ? "var(--s1)" : "var(--good)";
const reasonText = {"New event":"New flood event", "Escalated":"Escalation update", "Closed":"Event closed"}[M.reason] || M.reason;

/* ================= header ================= */
out += `<div class="sample">Flood Event Report · issued automatically when a flood is detected in real data, when it escalates, and when it ends. Every value is labeled with where it came from.</div>`;
if (D.has_simulated) out += `<div class="testbar">⚑ TEST ${M.is_test ? "EVENT" : "REPORT"}: contains simulated data<span>${M.is_test ? "This event was started by a simulated test signal, not by real data. The station reading marked SIMULATED, the flood extent and its impact are test values. Satellite images are real." : "Some items come from portal simulations or placeholder models and carry the striped SIMULATED label."} Do not use simulated figures for operational decisions.</span></div>`;
out += `<div class="inner"><header class="top" style="padding-bottom:20px"><div><div class="eyebrow">FloodGuard AI · Flood Event Report · ${esc(reasonText)}</div><h1>${esc(E.river)} flood event</h1>
  <div class="meta"><span>Event no.</span><b class="mono">${esc(M.event_no)}</b><span>Report</span><b class="mono">Version ${M.version} · ${esc(M.reason)}</b><span>Event opened</span><b>${esc(E.opened)} PKT</b>
  <span>Issued</span><b>${esc(M.generated)}</b>${E.closed ? `<span>Closed</span><b>${esc(E.closed)} PKT</b>` : ""}<span>Units</span><b>${esc(M.units)}</b></div></div>
  <div class="status-big"><div class="eyebrow">Event level</div><div class="lvl"><span class="dot" style="background:${LVLC(E.level)};width:14px;height:14px"></span>${esc(E.level_name)}</div><div class="note">Now: ${esc(E.current_level_name)} · status ${esc(E.status)}</div></div></header></div>`;

/* ================= 01 ================= */
const sigRows = E.signals.map(s => `<tr${s.sources.includes("sim")?' class="simrow"':""}><td>${src(s.sources)}</td><td>${esc(s.kind)}</td><td>${esc(s.station_name)}</td><td>${pill(s.label, LVLC(s.level))}</td><td class="n">${fmt(s.value_cumecs)}</td><td class="mono">${esc(s.at||"—")}</td><td>${esc(s.detail)}${s.stale ? ` ${pill("Stale reading: holds the event open, cannot raise it","var(--muted-bar)")}` : ""}</td></tr>`);
const verRows = E.versions.map(v => `<tr><td class="mono">v${v.version}</td><td>${esc(v.reason)}</td><td>${pill(v.level_name, LVLC(v.level))}</td><td class="mono">${esc(v.issued_at)}</td></tr>`)
  .concat([`<tr><td class="mono"><b>v${M.version}</b></td><td><b>${esc(M.reason)}</b> (this report)</td><td>${pill(E.level_name, LVLC(E.level))}</td><td class="mono">${esc(M.generated)}</td></tr>`]);
section("01", "Event Summary", [...new Set(E.signals.flatMap(s => s.sources))], `
  ${M.is_test ? `<div class="callout crit">⚑ Test event: started by a simulated signal. Real data shown alongside it is labeled as real.</div>` : ""}
  <p class="lead">${esc(S.headline)}</p>
  <div class="kpis">${S.kpis.map(k => `<div class="kpi"><span class="v" style="font-size:20px">${esc(k.value)}</span><span class="l">${esc(k.label)}</span></div>`).join("")}</div>
  <h3>What triggered this report</h3>${table(["Source","Type","Where","Level","#Cumecs","Time (PKT)","Detail"], sigRows)}
  <div class="grid2"><div><h3>Report versions for this event</h3>${table(["Version","Reason","Level","Issued (PKT)"], verRows)}</div>
  <div><h3>When this event gets a new report</h3><p class="note">Only when the level rises above the highest level already reported, or when the event closes after 24 h without a flood signal. Readings that stay at the same level, or dip and return, do not create new reports.</p></div></div>`);


/* ================= 02 ================= */
section("02", "Flagged Signals &amp; AI Analysis", ["obs","api"].concat(FLAGS && FLAGS.some(f => f.simulated) ? ["sim"] : []).concat(aiNotes() ? ["ai"] : []), aiSection());

/* ================= 03 ================= */
const ST = D.all_stations || D.stations, rivers = [...new Set(ST.map(s => s.river))];
const onRiver = new Set(D.stations.map(s => s.id));
const stRows = []; let cur = "";
ST.forEach(s => { if (s.river !== cur) { cur = s.river; stRows.push(`<tr class="river"><td colspan="10">${esc(cur)}${s.river === E.river || onRiver.has(s.id) ? " · this event" : ""}</td></tr>`); }
  stRows.push(`<tr${s.simulated?' class="simrow"':""}><td>${onRiver.has(s.id) ? "<b>" + esc(s.name) + "</b>" : esc(s.name)}</td><td>${src(s.sources) || "—"}</td><td class="n">${fmt(s.inflow,1)}</td><td class="n">${fmt(s.outflow,1)}</td><td class="n">${s.change_24h == null ? "—" : sgn(s.change_24h)}</td>
    <td class="note">Unavailable</td><td>${spark((s.history||[]).map(h => h.value))}</td><td class="n">${s.rising_days == null ? "—" : s.rising_days}</td><td>${cat(s.category)}${s.simulated ? `<div class="note">Real now: ${esc(s.real_category)}</div>` : ""}</td><td class="mono">${esc(s.observed_at||"—")}${s.stale ? ` <span class="tag" style="color:var(--crit);border-color:var(--crit)">${s.age_hours == null ? "No data" : "Stale " + Math.round(s.age_hours) + " h"}</span>` : ""}</td></tr>`); });
section("03", "Observed River Conditions", ["obs"].concat(ST.some(s => s.simulated) ? ["sim"] : []), `<p>All ${ST.length} FFD stations, upstream to downstream; stations on the ${esc(E.river)} event are in bold. Inflow and outflow are FFD gauge readings. The 24 h change compares with the previous stored FFD reading. "% of normal" needs station climatology, which the portal does not have yet.${ST.some(s => s.simulated) ? " A dashed ring marks the simulated test reading; its real category is shown under it." : ""}</p>
  <div class="fig"><h3>River network status</h3>${riverNetwork(rivers.map(r => ({label:r, stations:ST.filter(s => s.river === r)})))}</div>
  ${table(["Station","Source","#Inflow","#Outflow","#24 h change","% of normal","Recent trend","#Rising days","FFD category","Observed (PKT)"], stRows)}`);

/* ================= 04 ================= */
const A = D.arrival;
section("04", "Downstream Arrival", ["est"], A.available ? `<p>Expected arrival of the water from <b>${esc(A.origin)}</b> (reading of ${esc(A.base_time)} PKT) at each station downstream.</p>
  <div class="grid2"><div>${table(["Station","#Hours","Expected (PKT)","Category now"], A.rows.map(r => `<tr><td>${esc(r.station)}</td><td class="n">+${r.hours}</td><td class="mono">${esc(r.eta)}</td><td>${cat(r.category_now)}</td></tr>`))}</div>
  <div class="fig"><h3>Hours after ${esc(A.origin)}</h3>${hbars(A.rows.map(r => ({label:r.station, values:[r.hours]})), [{name:"Hours", color:"var(--s1)"}], {unit:" h", labels:true, aria:"Arrival hours"})}</div></div>
  ${A.tail ? `<p class="note">${esc(A.tail)}</p>` : ""}<p class="note">${esc(A.note)}</p>` : unavailable(A.reason));

/* ================= 05 ================= */
const IO = D.inout || [];
section("05", "Dams &amp; Barrages: Inflow vs Outflow", ["obs"], IO.length ? `<p>The difference between inflow and outflow at each site on this river shows whether water is being stored, released or withdrawn into canals. During a flood, outflow close to inflow means the barrage is passing the flood on downstream.</p>
  <div class="grid2"><div class="fig">${hbars(IO.map(r => ({label:r.name, values:[r.inflow, r.outflow]})), [{name:"Inflow",color:"var(--s1)"},{name:"Outflow",color:"var(--s2)"}], {unit:" cumecs", aria:"Inflow and outflow"})}</div>
  ${table(["Site","#Inflow","#Outflow","#Net (cumecs)","Reading"], IO.map(r => `<tr><td>${esc(r.name)}</td><td class="n">${fmt(r.inflow,1)}</td><td class="n">${fmt(r.outflow,1)}</td><td class="n">${fmt(r.net,1)}</td><td>${esc(r.reading)}</td></tr>`))}</div>
  <p class="note">Real FFD gauge readings. In a test event the simulated reading replaces the discharge only; inflow and outflow stay real.</p>` : unavailable("No inflow and outflow readings for stations on this river."));

/* ================= 06 ================= */
const U = D.upstream, provColor = {GloFAS:"var(--s2)", GEOGloWS:"var(--s3)", "Google Flood Hub":"var(--s1)"};
const simModels = D.models.rows.some(r => r.sources.includes("sim"));
const upBody = U.available && U.stations.length ? `<div class="gallery">${U.stations.map(u => `<div class="fig shot" style="padding:12px"><b style="font-family:var(--display)">${esc(u.name)}</b>${lines(u.providers.map(p => ({name:p.provider, color:provColor[p.provider]||"var(--ink-3)", points:p.series})), {aria:u.name})}
    <div class="legend">${u.providers.map(p => `<span><i class="sw" style="background:${provColor[p.provider]||"var(--ink-3)"}"></i>${esc(p.provider)}: peak ${fmt(p.peak,1)}</span>`).join("")}</div>
    <div>${u.agreement_pct == null ? "" : u.agree ? pill(`Sources agree (gap ${fmt(u.gap_cumecs)} cumecs)`, "var(--good)") : pill(`Sources disagree: ${u.agreement_pct}%, ${fmt(u.gap_cumecs)} cumecs`, "var(--warn)")}</div>
    <div class="note">${(u.signals||[]).map(s => `${esc(s.type)}: ${esc(s.severity)} ${s.probability}%`).join(" · ")}</div></div>`).join("")}</div>
  <p class="note">Flood-type signals are FloodGuard estimates from forecast rainfall and flow. A gap counts as disagreement only when it is over 25% and over 100 cumecs.</p>` : `<p class="note">${U.available ? "No upstream forecast point on this river." : esc(U.reason)}</p>`;
const fcRows = D.forecasts.map(f => `<tr><td>${esc(f.name)}</td><td>${src(f.sources)||"—"}</td><td class="n">${fmt(f.current,1)}</td><td class="n">${fmt(f.forecast,1)}</td><td class="mono">${esc(f.valid||"—")}</td><td class="n">${fmt(f.peak,1)}</td><td class="mono">${esc((f.peak_at||"—").slice(0,10))}</td><td>${f.mismatch ? pill("Check: forecast cell may not match station","var(--warn)") : esc(f.official_text||"—")}</td></tr>`);
const modelRows = D.models.rows.map(r => `<tr${r.sources.includes("sim")?' class="simrow"':""}><td>${esc(r.model)}</td><td>${esc(r.target)}</td><td>${src(r.sources)}</td><td class="n">${esc(r.value)}</td><td>${esc(r.risk_class)}</td><td>${esc(r.status)}</td></tr>`);
const sea = D.seasonal || {available:false, reason:"Not collected"};
const seaBody = sea.available ? `<div class="fig" style="max-width:560px">${hbars(sea.rows.map(r => ({label:r.month, values:[r.mean, r.observed_normal]})), [{name:"Provider outlook (mean)",color:"var(--s1)"},{name:"Observed same month",color:"var(--ink-3)"}], {unit:" cumecs", labels:true, aria:"Seasonal outlook", left:70})}
  ${table(["Month","#Mean","#p25","#p75","#Observed same month"], sea.rows.map(r => `<tr><td>${r.month}</td><td class="n">${fmt(r.mean,1)}</td><td class="n">${fmt(r.p25,1)}</td><td class="n">${fmt(r.p75,1)}</td><td class="n">${r.observed_normal == null ? "No record" : fmt(r.observed_normal,1)}</td></tr>`))}
  <p class="note">${esc(sea.source)}, issued ${esc(sea.issued)}. ${esc(sea.note)}</p></div>` : unavailable(sea.reason);
section("06", "Forecasts &amp; Model Outputs", ["api","ml"].concat(simModels ? ["sim"] : []), `<h3>6a. Station forecasts</h3>${table(["Station","Source","#Now","#Forecast","Valid","#Expected peak","Peak date","FFD text / check"], fcRows)}
  <h3>6b. Upstream forecasts (GloFAS and GEOGloWS)</h3>${upBody}
  <h3>6c. Model predictions</h3>${table(["Model","Target","Source","#Value","Risk class","Model status"], modelRows)}<p class="note">Placeholder model outputs are labeled SIMULATED and never trigger an event report.</p>
  <h3>6d. Seasonal outlook${sea.station ? ": " + esc(sea.station) : ""}</h3>${seaBody}`);

/* ================= 07 ================= */
const R = D.rainfall || {available:false, reason:"Not collected"}, CO = D.corridor || {districts:[]};
section("07", `Rainfall &amp; Weather along the ${esc(E.river)}`, ["api"], R.available ? `<p>${esc(R.verdict)}</p>
  <div class="grid2"><div class="fig"><h3>Rainfall by district (mm)</h3>${hbars(R.rows.slice(0,10).map(t => ({label:t.district, values:[t.observed, t.forecast]})), [{name:"Last 24 h",color:"var(--s1)"},{name:"Next 24 h",color:"var(--s2)"}], {unit:" mm", labels:true, aria:"Rainfall"})}</div>
  <div>${table(["District","#Last 24 h (mm)","#Next 24 h (mm)","#Temperature","#Screening risk"], R.rows.map(r => `<tr><td>${esc(r.district)}</td><td class="n">${fmt(r.observed,1)}</td><td class="n">${fmt(r.forecast,1)}</td><td class="n">${r.temp == null ? "—" : fmt(r.temp,1) + " °C"}</td><td class="n">${r.risk}%</td></tr>`))}</div></div>
  <p class="note">${esc(CO.rule)} Weather: Open-Meteo through the portal's district layer.</p>` : unavailable(R.reason));

/* ================= 08 ================= */
const SAT = D.satellite, IM = D.impact;
const satRows = SAT.checks.map(c => `<tr><td>${esc(c.location)}</td><td>${cat(c.category)}${c.simulated_category ? " (simulated)" : ""}</td><td class="mono">${esc((c.pre_date||"—").slice(0,10))}</td><td class="mono">${esc((c.during_date||"—").slice(0,10))}</td><td>${src(c.sources)}</td><td class="n">${c.potential_flood_area_km2 == null ? "—" : fmt(c.potential_flood_area_km2,1) + " km²"}</td><td>${c.error ? pill("Check failed: " + c.error, "var(--muted-bar)") : c.result === "potential_flooding_detected" ? pill("Possible flood water","var(--warn)") : pill(String(c.result).replace(/_/g," "),"var(--good)")}</td></tr>`);
const satFigs = SAT.checks.filter(c => c.during_radar_image_data_url).map(c => `<div class="fig"><h3>${esc(c.location)}: real radar, before and latest</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">${radar(c.pre_radar_image_data_url, [c.permanent_water_image_data_url], "Before · " + (c.pre_date||"").slice(0,10), c.coordinates)}${radar(c.during_radar_image_data_url, [c.permanent_water_image_data_url, c.image_data_url], "Latest · " + (c.during_date||"").slice(0,10), c.coordinates)}</div>
  <div class="legend"><span><i class="sw box" style="background:#4c73ff"></i>Permanent water (excluded)</span><span><i class="sw box" style="background:#00cae1"></i>Water outside the permanent-water reference</span></div>
  <p class="note">Water outside the permanent-water reference is potential flooding; seasonal water and reference gaps can remain. Source: Microsoft Planetary Computer Sentinel-1 RTC, Copernicus DEM, JRC GSW.</p></div>`).join("");
section("08", "Satellite Check", ["sat"], `<p>${esc(SAT.note)}</p>${table(["Location","Gauge category","Before pass","Latest pass","Source","#Possible flood water","Result"], satRows)}${satFigs}
  <p class="note">Satellite age is shown for every image; a pass older than the flood cannot show it.</p>`);

/* ================= 09 ================= */
let imBody;
if (IM.available) {
  const c = IM.counts || {}, pop = IM.population || {};
  const simSar = IM.kind === "simulated" && IM.sar && IM.sar.during_radar_image_data_url;
  imBody = `${IM.kind === "simulated" ? `<div class="callout crit">⚑ Simulated flood extent (synthetic test polygon near ${esc(IM.station)}), drawn hatched over the real radar image. Impact numbers below are test values.</div>` : `<div class="callout">Flood extent = water detected by Sentinel-1 near ${esc(IM.station)} (${esc(IM.label)}). It needs field confirmation.</div>`}
  <div class="kpis">${[[fmt(IM.people), "People in extent (lower bound)"], [fmt(IM.area_km2,1) + " km²", "Flood extent analysed"], [fmt((c.roads||{}).length_km,1) + " km", "Roads in extent"], [fmt((c.settlements||{}).count), "Settlements"], [fmt((c.schools||{}).count), "Schools"], [fmt((c.hospitals||{}).count), "Hospitals"]].map(([v,l]) => `<div class="kpi"><span class="v" style="font-size:20px">${v}</span><span class="l">${l}</span></div>`).join("")}</div>
  <div class="grid2">${simSar ? `<div class="fig"><h3>Simulated extent over the real radar image</h3>${radar(IM.sar.during_radar_image_data_url, [IM.sar.permanent_water_image_data_url, IM.sar.image_data_url], "Real pass · " + (IM.sar.during_date||"").slice(0,10), IM.sar.coordinates, IM.extent)}</div>` : ""}
  <div><h3>People by area</h3>${pop.rows && pop.rows.length ? `${hbars(pop.rows.map(r => ({label:r.name, values:[r.people]})), [{name:"People",color:"var(--s1)"}], {labels:true, aria:"People by area"})}${table(["Area","Level","#People"], pop.rows.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.level === "ADM3" ? "Tehsil" : "District")}</td><td class="n">${fmt(r.people)}</td></tr>`))}` : `<p class="note">${esc(IM.population_error || "No breakdown available")}</p>`}
  ${pop.known_area_fraction != null ? `<p class="note">Population data covers ${Math.round(pop.known_area_fraction*100)}% of the flood extent, so the total is a lower bound.${pop.adm3_available ? "" : " Tehsil boundaries are not available here, so totals are by district."}</p>` : ""}
  <h3 style="margin-top:12px">Exposed places and facilities</h3>${table(["Name","Type","Detail"], (IM.facilities||[]).map(f => `<tr><td>${esc(f.name)}</td><td>${esc(f.type)}</td><td>${esc(f.detail)}</td></tr>`))}</div></div>
  ${(IM.warnings||[]).length ? `<p class="note">${IM.warnings.map(esc).join(" ")}</p>` : ""}`;
} else imBody = unavailable(IM.reason);
const DR = D.districts, SC = D.screening || {available:false, reason:"Not collected"};
const yes = v => v ? `<span class="check">● Yes</span>` : `<span class="check" style="color:var(--ink-3)">○ No</span>`;
const scBody = SC.available ? `<div class="grid2"><div><h3 style="font-size:14px">Highest screening risk</h3>${table(["District","#Risk","Main factors"], SC.top_risk.map(d => `<tr><td>${esc(d.district)}</td><td class="n">${d.risk}%</td><td>${esc((d.factors||[]).join(", ")||"—")}</td></tr>`))}</div>
  <div><h3 style="font-size:14px">Warning signs</h3>${table(["District","High risk","Station rising","#Citizen reports","Open incident","#Signs"], SC.multi_signal.map(d => `<tr${d.signals.simulated_incident?' class="simrow"':""}><td>${esc(d.district)}</td><td>${yes(d.signals.high_risk)}</td><td>${yes(d.signals.station_rising)}</td><td class="n">${d.signals.citizen_reports}</td><td>${d.signals.open_incident.length ? "#" + d.signals.open_incident.join(", #") + (d.signals.simulated_incident ? " " + src(["sim"]) : "") : yes(false)}</td><td class="n"><b>${d.signal_count} / 4</b></td></tr>`))}</div></div>
  <p class="note">A weather-only screen that ranks districts for attention. It is not an inundation forecast.</p>` : unavailable(SC.reason);
section("09", "Impact &amp; Districts at Risk", (IM.sources||[]).concat(["api","est"]), `<h3>9a. Exposure in the flood extent</h3>${imBody}
  <h3>9b. Districts along the flood path</h3>${DR.available ? table(["District","Station","Why","Expected (PKT)","#Screening risk"], DR.rows.map(r => `<tr><td>${esc(r.district)}</td><td>${esc(r.station)}</td><td>${esc(r.why)}</td><td class="mono">${esc(r.eta)}</td><td class="n">${r.risk}%</td></tr>`)) : unavailable(DR.reason)}
  <h3>9c. District risk screening along the ${esc(E.river)} (${(CO.districts||[]).length} districts)</h3>${scBody}
  <p class="note">"In the extent" does not mean damaged or closed. Missing map features do not prove absence. Population is a modelled estimate, not an observed affected-person count.</p>`);

/* ================= 10 ================= */
const O = D.operations, OC = O.counts || {};
const simOps = [...O.alerts, ...O.incidents].some(x => x.sources.includes("sim"));
section("10", "Alerts, Incidents &amp; Citizen Reports", ["obs"].concat(simOps ? ["sim"] : []), `<p class="note">${esc(O.scope || "")}</p>
  ${O.counts ? `<div class="grid2">${table(["Item","#New in period","#Open","#Total"], [["Alerts awaiting approval",OC.alerts],["Incidents",OC.incidents],["Citizen reports",OC.reports]].map(([n,c]) => `<tr><td>${n}</td><td class="n">${c.new}</td><td class="n">${c.open}</td><td class="n">${c.total}</td></tr>`))}
  <div class="fig"><h3>Waiting times</h3>${table(["Item","#Waiting","#Target","Status"], O.waiting.map(w => `<tr><td>${esc(w.item)}</td><td class="n">${hrs(w.hours)}</td><td class="n">${hrs(w.target)}</td><td>${w.hours == null ? "Nothing waiting" : w.hours > w.target ? pill("Over target","var(--crit)") : pill("Within target","var(--good)")}</td></tr>`))}<p class="note">${esc(O.waiting_note)}</p></div></div>` : ""}
  <h3>Alerts</h3>${table(["#","Time","Location","Source","Severity","Approval","Message"], O.alerts.map(a => `<tr${a.sources.includes("sim")?' class="simrow"':""}><td class="mono">${a.id}</td><td class="mono">${esc(a.time)}</td><td>${esc(a.location)}</td><td>${src(a.sources)}</td><td>${esc(a.severity)}</td><td>${esc(a.approval)}</td><td>${esc(a.message)}</td></tr>`))}
  <h3>Incidents</h3>${table(["#","Type","Location","Source","Severity","Status","#Age","Description"], O.incidents.map(i => `<tr${i.sources.includes("sim")?' class="simrow"':""}><td class="mono">${i.id}</td><td>${esc(i.type)}</td><td>${esc(i.location)}</td><td>${src(i.sources)}</td><td>${esc(i.severity)}</td><td>${esc(i.status)}</td><td class="n">${hrs(i.age_hours)}</td><td>${esc(i.description)}</td></tr>`))}
  <h3>Citizen reports</h3>${table(["#","Location","Source","Verification","Status","#Water depth","#Age","Description"], O.reports.map(r => `<tr><td class="mono">${r.id}</td><td>${esc(r.location)}</td><td>${src(r.sources)}</td><td>${esc(r.verification)}</td><td>${esc(r.status)}</td><td class="n">${r.depth_cm == null ? "—" : fmt(r.depth_cm) + " cm"}</td><td class="n">${hrs(r.age_hours)}</td><td>${esc(r.description)}</td></tr>`))}`);

/* ================= 11 ================= */
const CL = D.checklist;
section("11", "Checks for Supervisors", [], `<p>For level: <b>${esc(CL.level)}</b>${M.reason === "Closed" ? " (event closed)" : ""}</p><ol class="concerns">${CL.items.map(i => `<li><span>${esc(i)}</span></li>`).join("")}</ol><p class="note">${esc(CL.note)}</p>`);

/* ================= 12 ================= */
const P = D.provenance, SR = D.simulation_runs || [], SN = D.snapshots;
section("12", "Data Sources, Quality &amp; System Health", SR.length ? ["sim"] : [], `<div class="grid2"><div class="fig"><h3>Report items by data source</h3>${stackbar(Object.keys(SRCN).map(k => ({label:SRCN[k], n:P[k]||0, color:SRCC[k]})))}</div>
  <div>${table(["Feed","Status","Note"], D.data_quality.map(q => `<tr><td>${esc(q.feed)}</td><td>${pill(q.status, q.status === "OK" ? "var(--good)" : ["Error","Unavailable"].includes(q.status) ? "var(--crit)" : "var(--warn)")}</td><td>${esc(q.note)}</td></tr>`).concat([aiQualityRow(3)].filter(Boolean)))}</div></div>
  <p class="note">Data mode: ${esc(M.data_mode)} · Simulation: ${M.simulation_enabled ? "On" : "Off"} · ML model: ${M.ml_model_enabled ? "On" : "Off (rule-based engine active)"}</p>
  <h3>Simulation runs on this river</h3>${SR.length ? table(["Run","Name","Station","Created (PKT)","In period","#Readings","#Max value","#Alerts","#Incidents"], SR.map(r => `<tr class="simrow"><td class="mono">${esc(r.run_id)}</td><td>${esc(r.name)}</td><td>${esc(r.station)}</td><td class="mono">${esc(r.created)}</td><td>${r.active_in_period ? "Yes" : "No"}</td><td class="n">${r.readings}</td><td class="n">${fmt(r.max_value)}</td><td class="n">${r.alerts}</td><td class="n">${r.incidents}</td></tr>`)) : `<p class="note">No portal simulation runs at stations on this river.</p>`}
  <h3>Portal visuals in this report</h3>${SN.captured ? table(["Visual","Section","Source","Status"], SN.shots.map(s => `<tr${(s.sources||[]).includes("sim")?' class="simrow"':""}><td>${esc(s.view)}</td><td class="mono">${esc(s.section)}</td><td>${src(s.sources)}</td><td>${s.image ? pill("Captured " + s.captured_at, "var(--good)") : pill("Unavailable: " + (s.error||""), "var(--muted-bar)")}</td></tr>`)) : `<p class="note">Snapshots unavailable. ${esc(SN.reason||"")}</p>`}`);

/* ================= 13 ================= */
section("13", "Annex", [], `<div class="grid2"><div><h3>FFD flood categories</h3><div class="legend" style="flex-direction:column;gap:6px">${Object.keys(CAT).map(k => `<span>${cat(k)} <span style="color:var(--ink-3)">${CAT_DEF[k]}</span></span>`).join("")}</div>
  <h3 style="margin-top:14px">Districts along this river</h3><p class="note">${esc((CO.districts||[]).join(", ") || "—")}. ${esc(CO.rule||"")}</p></div>
  <div><h3>Sources &amp; notes</h3><p class="note">River observations: PMD Flood Forecasting Division (FFD). Modeled discharge: GloFAS and GEOGloWS. Weather: Open-Meteo. Satellite: Sentinel-1 RTC via Microsoft Planetary Computer, with Copernicus DEM and JRC Global Surface Water. Exposure: WorldPop and OpenStreetMap. Modeled discharge is not measured water level. Travel times are indicative FloodGuard estimates. The data used for this report is stored next to it as report.json.</p></div></div>`);

out += `<footer><div class="inner" style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:12px;color:var(--ink-3)"><span>Prepared by: FloodGuard AI (automatic, event-triggered) · Reviewed by: ________</span><span class="mono">${esc(M.report_no)}</span></div></footer>`;
document.getElementById("report").innerHTML = out;
