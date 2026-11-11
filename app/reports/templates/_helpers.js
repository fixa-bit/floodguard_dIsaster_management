/* Shared report helpers: labels, tables, charts, radar figure, portal snapshots. Expects D (report data). */
const D = JSON.parse(document.getElementById("report-data").textContent);
const CAT = {"Below low":"var(--good)","Low flood":"var(--warn)","Medium flood":"var(--serious)","High flood":"var(--crit)","Very high flood":"var(--crit)","Exceptionally high flood":"var(--crit)","Unavailable":"var(--muted-bar)"};
const CAT_DEF = {"Below low":"Normal flow","Low flood":"Water in active floodplain","Medium flood":"Floodplain partly inundated","High flood":"Embankments under pressure","Very high flood":"Breach risk, evacuation likely","Exceptionally high flood":"Record-scale flows","Unavailable":"No reading in the period"};
const SRCN = {obs:"Observed",off:"Official forecast",api:"Flood API",ml:"Model prediction",sat:"Satellite",est:"Estimate",sim:"Simulated",ai:"AI analysis"};
const SRCC = {obs:"var(--good)",off:"var(--accent)",api:"var(--s1)",ml:"var(--ink-3)",sat:"var(--s3)",est:"var(--muted-bar)",sim:"var(--crit)",ai:"var(--ai)"};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (n, d=0) => n == null ? "—" : Number(n).toLocaleString("en-US", {maximumFractionDigits:d, minimumFractionDigits:0});
const sgn = n => n == null ? "—" : (n > 0 ? "▲ +" : n < 0 ? "▼ −" : "± ") + fmt(Math.abs(n), 1);
const src = keys => (keys||[]).filter((k,i,a)=>a.indexOf(k)===i).map(k => `<span class="src ${k}">${SRCN[k]}</span>`).join(" ");
const pill = (label, color) => `<span class="pill"><i class="dot" style="background:${color}"></i>${esc(label)}</span>`;
const cat = c => pill(c, CAT[c] || "var(--muted-bar)");
const unavailable = reason => `<div class="callout"><b>Unavailable.</b> ${esc(reason)}</div>`;
const table = (head, rows, cls="") => `<div class="tbl"><table class="${cls}"><thead><tr>${head.map(h => `<th${h.startsWith("#")?' class="n"':""}>${h.replace("#","")}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${head.length}">None in this period.</td></tr>`}</tbody></table></div>`;
const hrs = h => h == null ? "—" : h >= 48 ? `${Math.round(h/24)} d` : `${Math.round(h)} h`;
let out = "";
const section = (no, title, sources, body) => { out += `<section><div class="inner"><h2><span class="no">${no}</span>${title}<span class="srcs">${src(sources)}</span></h2>${body}${inapp(no)}</div></section>`; };

/* ---------- chart helpers (drawn to scale, colors from theme tokens) ---------- */
function hbars(rows, series, opts={}) { // rows: [{label, values:[...], tips:[...]}]
  const W = 520, l = opts.left || 110, r = 50, barH = 12, gap = 3, groupH = series.length*(barH+gap) + 10;
  const max = opts.max || Math.max(1, ...rows.flatMap(x => x.values.filter(v => v != null)));
  const sx = v => v / max * (W - l - r), H = rows.length * groupH + 22;
  const ticks = [0, .25, .5, .75, 1].map(t => t * max);
  let g = ticks.map(t => `<line x1="${l+sx(t)}" x2="${l+sx(t)}" y1="0" y2="${H-22}" stroke="var(--rule)"/><text x="${l+sx(t)}" y="${H-6}" text-anchor="middle" class="t-mute">${fmt(t, max < 10 ? 1 : 0)}</text>`).join("");
  rows.forEach((row, i) => { const y = i * groupH + 4;
    g += `<text x="${l-8}" y="${y + series.length*(barH+gap)/2 + 3}" text-anchor="end" class="t-ink">${esc(row.label)}</text>`;
    row.values.forEach((v, j) => { if (v == null) return; const yy = y + j*(barH+gap);
      g += `<rect class="bar" x="${l}" y="${yy}" width="${Math.max(sx(v),1)}" height="${barH}" rx="3" fill="${series[j].color}" data-tip="${esc(row.label)}: ${esc(series[j].name)} ${fmt(v,1)}${opts.unit||""}"/>`;
      if (opts.labels) g += `<text x="${l+sx(v)+5}" y="${yy+10}" class="mono t-mute" style="font-size:10px">${fmt(v, v<10?1:0)}</text>`; }); });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria||"bar chart")}">${g}</svg>` + (series.length > 1 ? `<div class="legend">${series.map(s => `<span><i class="sw box" style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : "");
}
function stackbar(parts) { // [{label,n,color}]
  const W = 600, H = 30, tot = parts.reduce((a,b) => a+b.n, 0) || 1; let x = 0, g = "";
  parts.filter(p => p.n).forEach(p => { const w = W*p.n/tot; g += `<rect x="${x}" y="0" width="${Math.max(w-2,1)}" height="${H}" rx="4" fill="${p.color}" data-tip="${esc(p.label)}: ${p.n}"/>`;
    if (w > 70) g += `<text x="${x+8}" y="19" class="t-ink" style="font-weight:600">${p.n} ${esc(p.label)}</text>`; x += w; });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Proportions">${g}</svg><div class="legend">${parts.map(p => `<span><i class="sw box" style="background:${p.color}"></i>${esc(p.label)}: <b class="mono">${p.n}</b></span>`).join("")}</div>`;
}
function spark(values) {
  if (values.length < 3) return `<span class="note">${values.length} reading${values.length===1?"":"s"}, need 3</span>`;
  const W = 90, H = 22, mn = Math.min(...values), mx = Math.max(...values), sx = i => i*(W-4)/(values.length-1)+2, sy = v => H-3-(v-mn)/((mx-mn)||1)*(H-6);
  return `<svg viewBox="0 0 ${W} ${H}" style="width:90px"><path d="${values.map((v,i) => (i?"L":"M")+sx(i).toFixed(1)+" "+sy(v).toFixed(1)).join("")}" fill="none" stroke="var(--s1)" stroke-width="1.75"/><circle cx="${sx(values.length-1)}" cy="${sy(values[values.length-1])}" r="2.5" fill="var(--s1)"/></svg>`;
}
function lines(seriesList, opts={}) { // [{name,color,points:[{time,value,phase}]}]
  const all = seriesList.flatMap(s => s.points.filter(p => p.value != null));
  if (!all.length) return `<p class="note">No series data.</p>`;
  const times = [...new Set(all.map(p => p.time))].sort(), W = 300, H = 150, l = 40, r = 8, t = 8, b = 22;
  const max = Math.max(...all.map(p => p.value)) * 1.1 || 1, sx = tm => l + times.indexOf(tm)/(Math.max(times.length-1,1))*(W-l-r), sy = v => t + (1 - v/max)*(H-t-b);
  let g = [0, .5, 1].map(f => `<line x1="${l}" x2="${W-r}" y1="${sy(f*max)}" y2="${sy(f*max)}" stroke="var(--rule)"/><text x="${l-5}" y="${sy(f*max)+4}" text-anchor="end" class="t-mute" style="font-size:9px">${fmt(f*max, max<10?1:0)}</text>`).join("");
  const today = opts.today && times.find(tm => tm >= opts.today); if (today) g += `<line x1="${sx(today)}" x2="${sx(today)}" y1="${t}" y2="${H-b}" stroke="var(--ink-3)" stroke-dasharray="3 3"/>`;
  [times[0], times[times.length-1]].forEach((tm,i) => g += `<text x="${sx(tm)}" y="${H-6}" text-anchor="${i?"end":"start"}" class="t-mute" style="font-size:9px">${tm.slice(5)}</text>`);
  seriesList.forEach(s => { const pts = s.points.filter(p => p.value != null);
    g += `<path d="${pts.map((p,i) => (i?"L":"M")+sx(p.time).toFixed(1)+" "+sy(p.value).toFixed(1)).join("")}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/>`;
    pts.forEach(p => g += `<circle class="hit" cx="${sx(p.time)}" cy="${sy(p.value)}" r="6" data-tip="${esc(s.name)} ${p.time}: ${fmt(p.value,1)} cumecs (${p.phase})"/>`); });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria||"line chart")}">${g}</svg>`;
}
// Satellite figure: real radar image + overlays + optional simulated polygon (hatched)
function radar(image, overlays, label, coords, polygon) {
  if (!image) return `<div class="callout">Radar image unavailable.</div>`;
  const S = 256; let poly = "";
  if (polygon && coords) { const [ul, ur, , ll] = coords;
    const px = ([lon, lat]) => [((lon-ul[0])/(ur[0]-ul[0])*S).toFixed(1), ((lat-ul[1])/(ll[1]-ul[1])*S).toFixed(1)];
    poly = `<polygon points="${polygon.map(p => px(p).join(",")).join(" ")}" fill="url(#hatch-${label.replace(/\W/g,"")})" stroke="#2bc4dd" stroke-width="2"/>`; }
  const id = "hatch-" + label.replace(/\W/g,"");
  return `<svg viewBox="0 0 ${S} ${S+18}" role="img" aria-label="${esc(label)}"><defs><pattern id="${id}" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="7" fill="#2bc4dd" opacity=".9"/></pattern><clipPath id="c-${id}"><rect width="${S}" height="${S}"/></clipPath></defs>
    <image href="${image}" width="${S}" height="${S}" preserveAspectRatio="none"/>${(overlays||[]).filter(Boolean).map(o => `<image href="${o}" width="${S}" height="${S}" preserveAspectRatio="none"/>`).join("")}<g clip-path="url(#c-${id})">${poly}</g>
    <rect x="6" y="6" width="${label.length*6.2+14}" height="18" rx="3" fill="#000000" opacity=".6"/><text x="13" y="19" style="fill:#ffffff;font-size:10.5px;font-weight:600">${esc(label)}</text>
    ${polygon ? `<rect x="${S-128}" y="${S-24}" width="122" height="18" rx="3" fill="#d03b3b"/><text x="${S-121}" y="${S-11}" style="fill:#ffffff;font-size:10px;font-weight:700">⚑ SIMULATED EXTENT</text>` : ""}
    <line x1="4" x2="70" y1="${S+11}" y2="${S+11}" stroke="var(--ink-3)" stroke-width="2"/><text x="76" y="${S+15}" class="t-mute" style="font-size:9.5px">≈ 2 km</text></svg>`;
}
/* ---------- in-portal snapshots ---------- */
function inapp(no) {
  const shots = (D.snapshots.shots || []).filter(s => s.section === no); if (!shots.length) return "";
  const body = shots.map(s => s.image ? `<figure class="shot" style="margin:0"><img src="${s.image}" alt="${esc(s.view)}"><figcaption class="cap"><b>${esc(s.view)}</b><span>${src(s.sources)}</span>${s.caption ? `<span class="note">${esc(s.caption)}</span>` : ""}<span class="from">Captured from the portal ${esc(s.captured_at)} PKT</span></figcaption></figure>`
    : `<div class="note">Snapshot unavailable: ${esc(s.view)}. ${esc(s.error || D.snapshots.reason || "")}</div>`).join("");
  return `<div class="inapp"><div class="eyebrow">In the portal</div><div class="row">${body}</div></div>`;
}

/* River network diagram: rows = [{label, stations:[{name, category, discharge, change_24h, simulated|sources}]}], upstream to downstream. */
function riverNetwork(rows) {
  const W = 980, rowH = 46, left = 80, H = rows.length*rowH + 10, step = (W-left-40)/6;
  let net = "", anySim = false;
  rows.forEach((row, i) => { const y = 20 + i*rowH, list = row.stations;
    net += `<text x="0" y="${y+4}" class="t-ink" style="font-family:var(--display);font-weight:600;font-size:13px">${esc(row.label)}</text><line x1="${left}" x2="${left+Math.max(list.length-1,0.02)*step}" y1="${y}" y2="${y}" stroke="var(--s1)" stroke-width="3" stroke-linecap="round" opacity=".35"/>`;
    list.forEach((s, j) => { const x = left + j*step, sim = s.simulated || (s.sources||[]).includes("sim"); anySim = anySim || sim;
      net += `<circle cx="${x}" cy="${y}" r="7" fill="${CAT[s.category]||"var(--muted-bar)"}" stroke="var(--paper)" stroke-width="2"/>${sim ? `<circle cx="${x}" cy="${y}" r="11" fill="none" stroke="var(--ink)" stroke-width="1.5" stroke-dasharray="3 2"/>` : ""}${(s.change_24h||0) > 0 ? `<path d="M${x-5} ${y-13} L${x} ${y-19} L${x+5} ${y-13}Z" fill="var(--ink)"/>` : ""}
        <text x="${x}" y="${y+21}" text-anchor="middle">${esc(s.name.replace("Ganda Singh Wala","G.S. Wala"))}</text><circle class="hit" cx="${x}" cy="${y}" r="16" data-tip="<b>${esc(s.name)}</b><br>${fmt(s.discharge,1)} cumecs<br>${esc(s.category)}${sim ? "<br>SIMULATED" : ""}"/>`; }); });
  const cats = ["Below low","Low flood","Medium flood","High flood"].concat(rows.some(r => r.stations.some(s => /Very high|Exceptionally/.test(s.category||""))) ? ["Very high flood"] : []);
  return `<div style="overflow-x:auto"><svg viewBox="-4 0 ${W} ${H}" style="min-width:640px" role="img" aria-label="River network">${net}</svg></div>
    <div class="legend">${cats.map(c => `<span>${cat(c)}</span>`).join("")}<span>▲ Higher than the previous reading</span>${anySim ? `<span>◌ Dashed ring: simulated reading</span>` : ""}</div>`;
}


/* ---------- Flagged signals and AI analysis (section 02 of both reports) ----------
   Code owns the measured value and the risk category; the AI explanation is a separate, labelled draft. */
const AI = D.ai_analysis || null, FLAGS = D.flags || null, REVIEW = (D.review && D.review.flags) || {};
const AI_STATUS = {complete:["Complete","var(--good)"], partial:["Partly complete","var(--warn)"], pending:["Not finished","var(--warn)"],
  running:["Not finished","var(--warn)"], unavailable:["Not run","var(--muted-bar)"], failed:["Failed","var(--crit)"], off:["Switched off","var(--muted-bar)"],
  no_flags:["Nothing to analyse","var(--good)"], skipped:["Skipped","var(--muted-bar)"]};
const aiNotes = () => AI ? Object.values(AI.flags || {}).filter(e => (e.explanation||{}).status === "complete" || ["complete","incomplete"].includes((e.agent||{}).status)).length : 0;
const dateText = iso => { try { return new Date(iso).toLocaleString("en-GB", {day:"numeric", month:"short", year:"numeric", hour:"2-digit", minute:"2-digit", timeZone:"Asia/Karachi"}) + " PKT"; } catch (e) { return iso || ""; } };

function aiStamp(flagId, hasContent) {
  if (!AI || !hasContent) return "";
  const r = REVIEW[flagId];
  if (r && r.decision === "accepted") return `<div class="stamp ok">✓ Accepted by ${esc(r.reviewer)}, ${esc(dateText(r.at))}${r.note ? ": " + esc(r.note) : ""}</div>`;
  if (r && r.decision === "rejected") return `<div class="stamp bad">✗ Rejected by ${esc(r.reviewer)}, ${esc(dateText(r.at))}: do not use this AI note${r.note ? ". " + esc(r.note) : ""}</div>`;
  if (AI.review_mode === "portal") return `<div class="stamp wait">Awaiting review in the portal</div>`;
  if (AI.review_mode === "none") return `<div class="stamp auto">Automatic report: published without human review</div>`;
  return `<div class="stamp wait">Draft, not reviewed</div>`;
}

function aiExplanation(ex) {
  if (!AI) return `<p class="note">This report was generated before AI analysis was added.</p>`;
  if (!ex) {
    if (["pending","running"].includes(AI.status)) return `<p class="note">AI analysis did not finish for this report.</p>`;
    if (["off","unavailable","failed","skipped"].includes(AI.status)) return `<p class="note">AI analysis was not run for this report (reason above).</p>`;
    return `<p class="note">Not analysed: lower priority than the flags above (limit ${esc((AI.limits||{}).explanations ?? "")}).</p>`;
  }
  if (ex.status !== "complete") return `<p class="note">${esc(ex.note || "No explanation.")}</p>`;
  const tip = s => `${esc(s.title)}${s.published ? " (" + esc(s.published) + ")" : ""}: “${esc(s.cited_text)}”`;
  const bySrc = Object.fromEntries((ex.sources || []).map(s => [s.n, s]));
  const text = ex.segments.map(seg => esc(seg.text) + seg.cites.map(n => `<sup class="cite" data-tip="${tip(bySrc[n] || {})}">[${n}]</sup>`).join("")).join("");
  const list = (ex.sources || []).map(s => `<li>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title)}<span class="note"> · ${esc(s.kind_name || "")}${s.published ? " · " + esc(s.published) : ""}</span></li>`).join("");
  return `<p class="aitext">${text}</p>${list ? `<ol class="aisrc">${list}</ol>` : ""}${ex.uncited ? `<p class="note">${ex.uncited} sentence(s) carry no citation; treat them with care.</p>` : ""}`;
}

function aiRefChips(refs, references) {
  return (refs || []).map(r => { const info = (references || {})[r] || {};
    const label = info.kind === "data" ? `${r} · ${info.label || ""}` : (info.kind === "web" ? `Web · ${info.domain || info.label || r}` : (info.label || r));
    return info.url ? `<a class="refchip" href="${esc(info.url)}" target="_blank" rel="noopener" data-tip="${esc(info.label || r)}">${esc(label)}</a>`
                    : `<span class="refchip" data-tip="${esc(info.label || r)}">${esc(label)}</span>`; }).join("");
}

function aiAgent(ag) {
  if (!ag) return "";
  const relC = {supports:"var(--crit)", weakens:"var(--good)", context:"var(--muted-bar)"};
  const relT = {supports:"Supports the flag", weakens:"Weakens the flag", context:"Context"};
  const likeC = {"more likely":"var(--ai)", "possible":"var(--muted-bar)", "less likely":"var(--rule)"};
  const unc = ag.uncertainty || {};
  const head = `<div class="eyebrow">${src(["ai"])} Deeper analysis · agent · draft</div>`;
  if (!["complete","incomplete"].includes(ag.status) || !ag.summary) return `<div class="aiagent">${head}<p class="note">${esc(ag.note || "The deeper analysis did not produce findings.")}</p></div>`;
  return `<div class="aiagent">${head}
    <p>${esc(ag.summary)}</p>
    ${(ag.evidence||[]).length ? table(["Finding","Relation","Sources"], ag.evidence.map(e => `<tr><td>${esc(e.finding)}</td><td>${pill(relT[e.relation] || e.relation, relC[e.relation] || "var(--muted-bar)")}</td><td>${aiRefChips(e.refs, ag.references)}</td></tr>`)) : ""}
    ${(ag.possible_explanations||[]).length ? `<h4>Possible explanations</h4><ul class="aiexp">${ag.possible_explanations.map(x => `<li>${pill(x.likelihood, likeC[x.likelihood] || "var(--muted-bar)")} ${esc(x.explanation)} ${aiRefChips(x.refs, ag.references)}</li>`).join("")}</ul>` : ""}
    <div class="grid2"><div><h4>Uncertainty: ${esc(unc.level || "—")}</h4>${(unc.reasons||[]).length ? `<ul class="aiexp">${unc.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</div>
    <div>${(ag.reviewer_checks||[]).length ? `<h4>Checks for the reviewer</h4><ol class="aiexp">${ag.reviewer_checks.map(r => `<li>${esc(r)}</li>`).join("")}</ol>` : ""}</div></div>
    <p class="note">${ag.status === "incomplete" ? esc(ag.note || "Incomplete.") + " " : ""}${fmt(ag.tool_calls)} read-only data queries · ${fmt(ag.web_searches || 0)} web searches (web search ${esc(ag.web_search)}) · ${fmt(ag.turns)} turns · ${fmt(ag.seconds, 0)} s${ag.dropped_statements ? ` · ${ag.dropped_statements} statement(s) dropped because they had no valid source` : ""}. Only statements citing data, documents or pages actually returned to the agent are shown.</p>
  </div>`;
}

function aiFlagCard(f) {
  const entry = (AI && AI.flags && AI.flags[f.id]) || {}, ex = entry.explanation, ag = entry.agent;
  const has = (ex && ex.status === "complete") || (ag && ["complete","incomplete"].includes(ag.status));
  const rejected = (REVIEW[f.id] || {}).decision === "rejected";
  const m = f.measured, c = f.category;
  return `<article class="aiflag${rejected ? " rejected" : ""}" id="flag-${esc(f.id)}">
    <header><span class="mono">${esc(f.id)}</span><b>${esc(f.title)}</b><span class="kind">${esc(f.kind_label)}</span>${f.simulated ? src(["sim"]) : ""}</header>
    <div class="aigrid">
      <div class="box code"><div class="eyebrow">Measured value · code</div><div class="big">${esc(m.value)}</div>
        <div class="note">${esc(m.label)}${m.detail ? " · " + esc(m.detail) : ""}${m.time ? " · " + esc(m.time) + " PKT" : ""}</div><div>${src(m.sources)}</div></div>
      <div class="box code"><div class="eyebrow">Risk category · FloodGuard rule</div><div class="big">${esc(c.label)}</div>
        <div class="note">Rule: ${esc(c.rule)}</div><div class="note"><b>Effect:</b> ${esc(c.status_effect)}</div></div>
      <div class="box ai"><div class="eyebrow">${src(["ai"])} AI explanation · draft</div>${aiExplanation(ex)}${aiStamp(f.id, has)}</div>
    </div>
    ${aiAgent(ag)}
  </article>`;
}

function aiSection() {
  const intro = `<p>Values that a FloodGuard rule flagged in this report. For each one, the <b>measured value</b> and the <b>risk category</b> come from FloodGuard's code and rules, exactly as elsewhere in this report. The <b>AI explanation</b> is written afterwards by Claude from cited documents and read-only data. It is a draft: it cannot change any value, category or status.</p>`;
  if (!FLAGS) return intro + `<div class="callout">This report was generated before flagged signals were added.</div>`;
  const st = AI ? (AI_STATUS[AI.status] || [AI.status, "var(--muted-bar)"]) : null;
  const review = !AI ? "" : AI.review_mode === "none" ? "Automatic report: AI notes are published without human review." :
    AI.review_mode === "portal" ? "AI notes need review in the portal (Situation Reports)." : "AI notes are drafts; no review was requested.";
  const line = AI ? `<p class="note">AI analysis: ${pill(st[0], st[1])} ${AI.model ? "· " + esc(AI.model) + " " : ""}· ${esc(review)}${AI.integrity && AI.integrity.unchanged ? " · Code-computed values unchanged (checksum verified)." : ""}${AI.reason && AI.status !== "off" ? " · " + esc(AI.reason) : ""}${AI.note ? " · " + esc(AI.note) : ""}</p>` : "";
  if (!FLAGS.length) return intro + line + `<div class="callout">No rule flagged a current or forecast value in this report, so no AI analysis was run.</div>`;
  return intro + line + FLAGS.map(aiFlagCard).join("");
}

function aiQualityRow(cols) {
  if (!AI) return "";
  const st = AI_STATUS[AI.status] || [AI.status, "var(--muted-bar)"];
  const reviewed = Object.keys(REVIEW).length;
  const note = [AI.integrity ? AI.integrity.note : "", AI.reason || "", AI.review_mode === "portal" ? `${reviewed} of ${aiNotes()} AI note(s) reviewed.` : ""].filter(Boolean).join(" ");
  const cells = cols === 5
    ? `<td>AI analysis (${esc(AI.model || "Claude")})</td><td>${pill(st[0], st[1])}</td><td class="mono">${esc(AI.finished_at ? dateText(AI.finished_at) : "—")}</td><td class="n">${aiNotes()} / ${(FLAGS||[]).length} flags</td><td>${esc(note)}</td>`
    : `<td>AI analysis (${esc(AI.model || "Claude")})</td><td>${pill(st[0], st[1])}</td><td>${esc(note)}</td>`;
  return `<tr>${cells}</tr>`;
}
