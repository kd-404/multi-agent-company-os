// Agent Floor: workflow graph + globe + agent cards, driven by /api/admin/floor/*.
// Live status comes from the database (what agents actually logged). The
// "Simulate" mode is a scripted walkthrough that overlays the graph and is
// clearly labelled SIM - it never calls an API or writes anything.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (v) => { const d = document.createElement("div"); d.textContent = v == null ? "" : String(v); return d.innerHTML; };

const S = { reg: null, live: null, sel: null, tab: "workflow", dtab: "run", sim: null, lay: null, opened: Date.now(), pollMs: 2500, realRunning: false };
const KIND_LABEL = { ai: "AI model", tool: "API tool", rule: "Code", human: "Human" };
const STATUS_LABEL = { working: "Working", finished: "Just finished", ok: "Healthy", waiting: "Needs you", error: "Error", planned: "Planned", idle: "Idle" };

function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour12: false });
const ms = (n) => (n == null ? "" : n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n}ms`);

// ---------------- boot ----------------
(async function boot() {
  let me = null;
  try { const r = await fetch("/api/me"); if (r.ok) me = await r.json(); } catch {}
  if (!me || me.role !== "admin") { $("#gate").classList.remove("hidden"); return; }
  S.reg = await (await fetch("/api/admin/floor/registry")).json();
  buildLayout();
  renderGraph();
  renderCards();
  renderHops();
  bindUI();
  requestAnimationFrame(() => fitView());
  await poll();
  window.addEventListener("resize", () => { if (S.tab === "workflow") fitView(); });
})();

// ---------------- data polling ----------------
async function poll() {
  try {
    const r = await fetch("/api/admin/floor/state");
    if (r.ok) { S.live = await r.json(); $("#live-note").className = "note live"; $("#live-note").textContent = `live · updated ${new Date().toLocaleTimeString([], { hour12: false })}`; }
    else { $("#live-note").className = "note"; $("#live-note").textContent = `state error ${r.status}`; }
  } catch { $("#live-note").className = "note"; $("#live-note").textContent = "offline - retrying"; }
  paint();
  const busy = S.live && (S.live.stats.working > 0 || S.realRunning);
  setTimeout(poll, busy ? 1000 : S.pollMs);
}

// effective view of state (sim overlay wins while simulating)
function view() {
  if (S.sim) return S.sim.view;
  return S.live;
}

function paint() {
  const v = view();
  if (!v) return;
  paintChips(v);
  paintNodes(v);
  paintEdges(v);
  paintDrawer(v);
  if (S.tab === "agents") renderCards();
}

function paintChips(v) {
  const st = v.stats;
  const el = Math.floor((Date.now() - S.opened) / 1000);
  $("#chips").innerHTML = `
    <span><i class="dot ${st.working ? "w" : ""}"></i>Working<b>${st.working}</b></span>
    <span><i class="dot ${st.needs_you ? "n" : ""}"></i>Needs you<b>${st.needs_you}</b></span>
    <span>Model calls (24h)<b>${st.model_calls_24h}</b></span>
    <span><i class="dot ${st.errors_24h ? "e" : ""}"></i>Errors (24h)<b>${st.errors_24h}</b></span>
    <span>Runs (24h)<b>${st.runs_24h}</b></span>
    <span>Image model<b>${esc(st.image_model)}</b></span>
    <span>Open<b>${Math.floor(el / 60)}:${String(el % 60).padStart(2, "0")}</b></span>`;
}

// ---------------- layout ----------------
const NW = 132, NH = 78, DX = 160, X0 = 214, LANE_H = 150, LANE_GAP = 22;
function buildLayout() {
  const lay = { nodes: {}, lanes: [], w: 0, h: 0 };
  const byLane = {};
  S.reg.nodes.forEach((n) => (byLane[n.lane] = byLane[n.lane] || []).push(n));
  const maxN = Math.max(...Object.values(byLane).map((a) => a.length));
  lay.w = X0 + maxN * DX + 30;
  let y = 20;
  S.reg.lanes.forEach((l) => {
    const nodes = byLane[l.id] || [];
    lay.lanes.push({ ...l, y, h: LANE_H });
    nodes.forEach((n, i) => { lay.nodes[n.id] = { x: X0 + i * DX, y: y + 38, lane: l.id }; });
    y += LANE_H + LANE_GAP;
  });
  lay.h = y;
  S.lay = lay;
}

function renderGraph() {
  const stage = $("#stage");
  const { lay } = S;
  stage.style.width = lay.w + "px"; stage.style.height = lay.h + "px";
  let html = `<svg width="${lay.w}" height="${lay.h}" id="edges"><defs>
    <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#6b5a49"/></marker>
    <marker id="arr-live" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#5ab4ff"/></marker>
    <marker id="arr-hi" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#e9a15f"/></marker></defs>`;
  S.reg.edges.forEach((e, i) => { html += `<path class="edge ${e.loop ? "loop" : ""}" id="e${i}" d="${edgePath(e)}" marker-end="url(#arr)"/>`; });
  S.reg.edges.forEach((e, i) => { html += `<text class="edge-label" id="el${i}" visibility="hidden"><textPath href="#e${i}" startOffset="50%" text-anchor="middle">${esc(e.label)}</textPath></text>`; });
  html += `</svg>`;
  lay.lanes.forEach((l) => {
    html += `<div class="lane" style="--lc:${l.color};left:10px;top:${l.y}px;width:${lay.w - 20}px;height:${l.h}px"><div class="lane-label"><b>${esc(l.title)}</b><span>${esc(l.sub)}</span></div></div>`;
  });
  S.reg.nodes.forEach((n) => {
    const p = lay.nodes[n.id];
    const lane = S.reg.lanes.find((l) => l.id === n.lane);
    html += `<div class="node s-idle" data-id="${n.id}" style="left:${p.x}px;top:${p.y}px;--lc:${lane.color}" tabindex="0" role="button" aria-label="${esc(n.name)}">
      <span class="code">${esc(n.code)}</span><span class="kind">${KIND_LABEL[n.kind]}</span>
      <div class="nm">${esc(n.name)}</div><div class="st"></div><i class="pulse"></i></div>`;
  });
  stage.innerHTML = html;
  $$(".node", stage).forEach((el) => {
    el.addEventListener("click", (ev) => { ev.stopPropagation(); selectNode(el.dataset.id); });
    el.addEventListener("keydown", (ev) => { if (ev.key === "Enter") selectNode(el.dataset.id); });
    el.addEventListener("mouseenter", () => highlight(el.dataset.id));
    el.addEventListener("mouseleave", () => highlight(S.sel));
  });
}

function edgePath(e) {
  const a = S.lay.nodes[e.from], b = S.lay.nodes[e.to];
  const ax = a.x + NW, ay = a.y + NH / 2, bx = b.x, by = b.y + NH / 2;
  if (bx > ax + 10) {
    const dx = (bx - ax) * 0.5;
    return `M${ax},${ay} C${ax + dx},${ay} ${bx - dx},${by} ${bx},${by}`;
  }
  // backwards / same column: leave from top or bottom, arrive at top or bottom
  const down = b.y >= a.y;
  const sx = a.x + NW / 2, sy = down ? a.y + NH : a.y;
  const tx = b.x + NW / 2, ty = down ? b.y : b.y + NH;
  if (Math.abs(b.y - a.y) < 4) { // same lane loop: bow underneath
    return `M${sx},${a.y + NH} C${sx},${a.y + NH + 46} ${tx},${a.y + NH + 46} ${tx},${a.y + NH}`;
  }
  const mid = (sy + ty) / 2;
  return `M${sx},${sy} C${sx},${mid} ${tx},${mid} ${tx},${ty}`;
}

function paintNodes(v) {
  S.reg.nodes.forEach((n) => {
    const el = $(`.node[data-id="${n.id}"]`);
    if (!el) return;
    const d = v.nodes[n.id] || { status: n.built ? "idle" : "planned" };
    el.className = el.className.replace(/\bs-\w+\b/g, "").trim() + ` s-${d.status}`;
    let line;
    if (d.status === "planned") line = "Not built yet";
    else if (d.message) line = d.message;
    else line = n.does.split(". ")[0];
    $(".st", el).textContent = line;
    el.title = `${n.name} — ${STATUS_LABEL[d.status] || d.status}${d.at ? " · " + ago(d.at) : ""}`;
  });
}

function paintEdges(v) {
  S.reg.edges.forEach((e, i) => {
    const el = $(`#e${i}`); if (!el) return;
    const a = (v.nodes[e.from] || {}).status, b = (v.nodes[e.to] || {}).status;
    const live = (a === "working" || a === "finished") && (b === "working" || b === "finished" || b === "waiting");
    el.classList.toggle("live", live);
    el.setAttribute("marker-end", live ? "url(#arr-live)" : "url(#arr)");
  });
  highlight(S.sel);
}

function highlight(id) {
  const edges = S.reg.edges;
  const nodesLit = new Set();
  if (id) { nodesLit.add(id); edges.forEach((e) => { if (e.from === id) nodesLit.add(e.to); if (e.to === id) nodesLit.add(e.from); }); }
  edges.forEach((e, i) => {
    const el = $(`#e${i}`); if (!el) return;
    const on = id && (e.from === id || e.to === id);
    el.classList.toggle("hi", !!on && !el.classList.contains("live"));
    el.classList.toggle("dim", !!id && !on);
    if (on) el.setAttribute("marker-end", "url(#arr-hi)");
    const lab = $(`#el${i}`); if (lab) lab.setAttribute("visibility", on ? "visible" : "hidden");
  });
  $$(".node").forEach((n) => n.classList.toggle("dim", !!id && !nodesLit.has(n.dataset.id)));
}

function selectNode(id) {
  S.sel = id;
  $$(".node").forEach((n) => n.classList.toggle("sel", n.dataset.id === id));
  highlight(id);
  setDtab("agent");
  $("#drawer").classList.add("open");
}

// ---------------- pan / zoom ----------------
const T = { x: 0, y: 0, k: 1 };
function applyT() { $("#stage").style.transform = `translate(${T.x}px,${T.y}px) scale(${T.k})`; }
function fitView(all) {
  // default: fit the WIDTH (readable text, scroll down the lanes); "Fit all" fits everything
  const c = $("#canvas"); if (!c || !S.lay || !c.clientWidth) return;
  const k = all === true ? Math.min(c.clientWidth / S.lay.w, c.clientHeight / S.lay.h) : Math.min(c.clientWidth / S.lay.w, 1.1);
  T.k = Math.max(0.3, k); T.x = (c.clientWidth - S.lay.w * T.k) / 2; T.y = 8; applyT();
}
function focusLane(id) {
  const l = S.lay.lanes.find((x) => x.id === id); if (!l) return;
  const c = $("#canvas"); T.k = Math.min(1, c.clientWidth / S.lay.w * 1.15, 1); T.k = Math.max(T.k, 0.7);
  T.x = 12; T.y = 12 - l.y * T.k; applyT();
}
function zoomAt(f, px, py) {
  const nk = Math.min(2, Math.max(0.3, T.k * f));
  T.x = px - (px - T.x) * (nk / T.k); T.y = py - (py - T.y) * (nk / T.k); T.k = nk; applyT();
}

// ---------------- drawer ----------------
function setDtab(t) {
  S.dtab = t;
  $$(".dtabs button").forEach((b) => b.classList.toggle("on", b.dataset.d === t));
  paintDrawer(view());
}

function paintDrawer(v) {
  if (!v) return;
  const body = $("#dbody");
  const keep = body.scrollTop;
  if (S.dtab === "run") body.innerHTML = drawerRun(v);
  else if (S.dtab === "agent") body.innerHTML = drawerAgent(v);
  else body.innerHTML = drawerFeed(v);
  body.scrollTop = keep;
  $$("[data-node]", body).forEach((b) => b.addEventListener("click", () => selectNode(b.dataset.node)));
  const stop = $("#sim-stop"); if (stop) stop.onclick = stopSim;
  const back = $("#to-run"); if (back) back.onclick = () => setDtab("run");
}

function simBanner() {
  if (!S.sim) return "";
  return `<div class="sim-banner"><b>Simulation</b> — a scripted walkthrough of one drop from trend to doorstep. Nothing here calls an API or writes data. Step ${S.sim.i}/${S.sim.script.length}.<br><button class="btn ghost" id="sim-stop">Stop simulation</button></div>`;
}

function drawerRun(v) {
  const run = v.run;
  if (!run) return simBanner() + `<p class="empty">No pipeline runs yet. Click <b>⚡ Run a real design</b> to watch the Trend Scout, Design Generator and Vision Tagger work live — or <b>▶ Simulate a drop</b> for a free walkthrough.</p>`;
  const title = run.kind === "photo" ? "Photo Studio run" : run.kind === "sim" ? "Simulated drop" : "Design Studio run";
  const steps = run.steps.map((s, i) => `
    <div class="step ${s.status}"><i class="ic"></i><div>
      <b>${i + 1}. ${esc(s.name)} ${s.node ? `<a href="#" data-node="${s.node}" style="color:var(--accent);font-weight:500;font-size:11px">view</a>` : ""}</b>
      <p>${esc(s.label)}</p>
      <div class="ms">${s.status === "working" ? "working…" : ms(s.duration_ms)}</div></div></div>`).join("");
  const d = run.design;
  const result = d ? `<div class="result"><img src="${d.image_url}" alt="Design ${d.id}" onerror="this.style.visibility='hidden'" />
    <dl><dt>Design</dt><dd>#${d.id} · <span class="pill ${d.status === "approved" ? "finished" : d.status === "pending" ? "waiting" : "idle"}">${esc(d.status)}</span></dd>
    <dt>Garment</dt><dd>${esc(d.garment || "-")} · ${esc(d.color || "-")}</dd>
    <dt>Tags</dt><dd>${(d.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("") || "-"}</dd></dl></div>
    <p class="sub" style="margin-top:-4px">${esc(d.summary || "")}</p>` : "";
  return `${simBanner()}<h3>${title}</h3><p class="sub">${esc(run.title)} · <span class="pill ${run.running ? "working" : "finished"}">${run.running ? "running" : "finished"}</span></p>${result}${steps}`;
}

function drawerAgent(v) {
  const n = S.reg.nodes.find((x) => x.id === S.sel);
  if (!n) return `<p class="empty">Click any agent on the graph to see what it does, what it reads and writes, which service it calls, and how it behaves when something fails.</p>`;
  const d = v.nodes[n.id] || { status: "idle" };
  const lane = S.reg.lanes.find((l) => l.id === n.lane);
  const ins = S.reg.edges.filter((e) => e.to === n.id), outs = S.reg.edges.filter((e) => e.from === n.id);
  const nm = (id) => (S.reg.nodes.find((x) => x.id === id) || {}).name;
  const evs = v.events.filter((e) => e.node === n.id).slice(0, 8);
  return `<button class="back" id="to-run">← Latest run</button>
    <h3>${esc(n.name)}</h3>
    <p class="sub"><span class="pill ${d.status}">${STATUS_LABEL[d.status] || d.status}</span> &nbsp;${esc(lane.title)} · ${KIND_LABEL[n.kind]}${d.at ? " · active " + ago(d.at) : ""}</p>
    <p>${esc(n.does)}</p>
    ${n.built ? `<div class="statrow"><div><b>${d.runs_24h ?? 0}</b><span>runs 24h</span></div><div><b>${d.avg_ms ? ms(d.avg_ms) : "–"}</b><span>avg time</span></div><div><b>${d.errors_24h ?? 0}</b><span>errors</span></div></div>` : ""}
    <h4>How it works</h4>
    <dl class="kv"><dt>Service</dt><dd>${esc(n.service)}</dd><dt>Reads</dt><dd>${esc(n.reads)}</dd><dt>Writes</dt><dd>${esc(n.writes)}</dd><dt>If it fails</dt><dd>${esc(n.failure)}</dd></dl>
    <h4>Receives from</h4>${ins.map((e) => `<span class="tag" data-node="${e.from}" style="cursor:pointer">${esc(nm(e.from))} · ${esc(e.label)}</span>`).join("") || '<span class="tag">trigger</span>'}
    <h4>Hands off to</h4>${outs.map((e) => `<span class="tag" data-node="${e.to}" style="cursor:pointer">${esc(nm(e.to))} · ${esc(e.label)}</span>`).join("") || '<span class="tag">end of line</span>'}
    <h4>Recent activity</h4>${evs.length ? evs.map(evRow).join("") : '<p class="empty" style="padding:6px 0">Nothing logged in this window.</p>'}`;
}

function evRow(e) {
  return `<div class="ev ${e.status} ${e.sim ? "sim" : ""}"><time>${clock(e.at)}</time><div><b data-node="${e.node || ""}">${esc(e.name)}</b> <span>${esc(e.message)}</span> ${e.duration_ms ? `<span class="d">${ms(e.duration_ms)}</span>` : ""}</div></div>`;
}
function drawerFeed(v) {
  return `${simBanner()}<h4 style="margin-top:0">Live activity · ${v.events.length} events</h4>${v.events.map(evRow).join("") || '<p class="empty">No activity yet.</p>'}`;
}

// ---------------- all agents ----------------
function renderCards() {
  const v = view(); if (!v) return;
  const byLane = {};
  S.reg.nodes.forEach((n) => (byLane[n.lane] = byLane[n.lane] || []).push(n));
  $("#cards").innerHTML = S.reg.lanes.map((l) => `
    <h2 class="lane-h" style="--lc:${l.color}">${esc(l.title)}</h2><p class="lane-sub">${esc(l.sub)}</p>
    <div class="grid">${(byLane[l.id] || []).map((n) => {
      const d = v.nodes[n.id] || { status: n.built ? "idle" : "planned" };
      return `<div class="card ${n.built ? "" : "planned"}" style="--lc:${l.color}" data-id="${n.id}">
        <div class="top"><span class="cd">${esc(n.code)}</span><span class="cn">${esc(n.name)}</span><span class="pill ${d.status}">${STATUS_LABEL[d.status] || d.status}</span></div>
        <div class="svc">${KIND_LABEL[n.kind]} · ${esc(n.service)}</div><p>${esc(n.does)}</p>
        <div class="meta"><span>${d.at ? ago(d.at) : "no activity"}</span><span>${d.runs_24h ?? 0} runs/24h</span><span>${d.avg_ms ? ms(d.avg_ms) + " avg" : ""}</span></div></div>`;
    }).join("")}</div>`).join("");
  $$("#cards .card").forEach((c) => c.addEventListener("click", () => { switchTab("workflow"); selectNode(c.dataset.id); centerOn(c.dataset.id); }));
}

function centerOn(id) {
  const p = S.lay.nodes[id]; if (!p) return; const c = $("#canvas");
  T.k = Math.max(T.k, 0.8); T.x = c.clientWidth / 2 - (p.x + NW / 2) * T.k; T.y = c.clientHeight / 2 - (p.y + NH / 2) * T.k; applyT();
}

// ---------------- UI wiring ----------------
function switchTab(t) {
  S.tab = t;
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + t));
  $(".drawer").style.display = t === "globe" ? "none" : "";
  if (t === "workflow") fitView();
  if (t === "agents") renderCards();
  if (t === "globe") startGlobe(); else stopGlobe();
}

function bindUI() {
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $$(".dtabs button").forEach((b) => b.addEventListener("click", () => setDtab(b.dataset.d)));
  const c = $("#canvas");
  let drag = null;
  c.addEventListener("pointerdown", (e) => { if (e.target.closest(".node")) return; drag = { x: e.clientX, y: e.clientY, tx: T.x, ty: T.y }; c.classList.add("drag"); c.setPointerCapture(e.pointerId); });
  c.addEventListener("pointermove", (e) => { if (!drag) return; T.x = drag.tx + e.clientX - drag.x; T.y = drag.ty + e.clientY - drag.y; applyT(); });
  c.addEventListener("pointerup", (e) => { if (drag && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4) { S.sel = null; $$(".node").forEach((n) => n.classList.remove("sel")); highlight(null); } drag = null; c.classList.remove("drag"); });
  c.addEventListener("wheel", (e) => { e.preventDefault(); const r = c.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.12 : 0.89, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  $("#z-in").onclick = () => zoomAt(1.2, c.clientWidth / 2, c.clientHeight / 2);
  $("#z-out").onclick = () => zoomAt(0.83, c.clientWidth / 2, c.clientHeight / 2);
  $("#z-fit").onclick = () => fitView(true);
  $("#z-width").onclick = () => fitView();
  $("#z-lane").onclick = () => focusLane("design");
  $("#sim-btn").onclick = () => (S.sim ? stopSim() : startSim());
  $("#real-btn").onclick = runReal;
}

async function runReal() {
  if (S.sim) stopSim();
  if (!confirm("Run one real design now?\n\nThis calls Tavily, the image model and Azure Vision (a few cents) and takes about a minute. Watch the graph light up.")) return;
  const btn = $("#real-btn"); btn.disabled = true; btn.textContent = "⚡ Running…"; S.realRunning = true;
  setDtab("run"); $("#drawer").classList.add("open");
  try {
    const r = await fetch("/api/admin/design/generate", { method: "POST", body: new FormData() });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.status === "error") alert(`The run stopped at ${d.stage || "an early stage"}: ${d.detail || r.status}`);
  } catch (e) { alert("Couldn't reach the server: " + e.message); }
  S.realRunning = false; btn.disabled = false; btn.textContent = "⚡ Run a real design";
}

// ---------------- simulation ----------------
// One scripted drop, trend to doorstep and back. Each step: node, state, text, hold (ms).
const SCRIPT = [
  ["trend_radar", "work", "Scanning what's trending against the catalogue…", 1100],
  ["trend_radar", "done", "Gap found: 'retro Tamil cinema typography' isn't covered. Commissioning a design.", 900],
  ["trend_scout", "work", "Searching the live web (Tavily) for the trend…", 1500],
  ["trend_scout", "done", "Trend brief ready from 6 sources. One poisoned-looking page dropped.", 700],
  ["prompt_writer", "done", "Brief → image prompt, house style appended.", 700],
  ["image_gen", "work", "Drawing the artwork with the image model…", 1800],
  ["image_gen", "done", "Artwork generated (1024×1024).", 700],
  ["vision_tagger", "work", "Azure Vision reading the artwork…", 1100],
  ["vision_tagger", "done", "Tags: typography, retro, poster · dominant colour amber.", 700],
  ["relevance_critic", "done", "Relevance 78/100 — artwork matches the brief.", 800],
  ["garment_matcher", "done", "Amber art → black hoodie for contrast.", 800],
  ["human_approval", "wait", "Waiting for a human to approve…", 1600],
  ["human_approval", "done", "Approved by you. Photography and captions begin.", 800],
  ["photo_director", "done", "Photo brief: hoodie, print on chest, dark-on-dark contrast fix.", 800],
  ["photographer", "work", "Editing the design onto a hoodie photo…", 1800],
  ["photo_critic", "work", "Vision checking the photo…", 1000],
  ["photo_critic", "error", "It's a white tee, not a black hoodie. Sending back a correction.", 1300],
  ["photographer", "work", "Re-shooting with the critic's correction…", 1600],
  ["photo_critic", "done", "Verified: black hoodie, print legible.", 900],
  ["storefront", "done", "Photos stored in the database. Product live in the shop.", 900],
  ["caption_writer", "done", "Caption + hashtags drafted from the design's own research.", 800],
  ["instagram", "done", "Posted to Instagram.", 800],
  ["shop_assistant", "done", "Shopper: 'is the black hoodie in stock?' → 'In stock, 50 available.'", 1000],
  ["visual_search", "done", "Shopper uploaded a photo → matched this hoodie at 84%.", 900],
  ["checkout", "work", "Shopper moves through address → payment…", 1200],
  ["payment", "done", "Method chosen: UPI (demo, no money moves).", 800],
  ["checkout", "done", "Order placed. Funnel: opened → address → payment → paid.", 800],
  ["warehouse", "done", "Stock 50 → 49. Healthy.", 800],
  ["support_desk", "wait", "Shopper opened a ticket: 'wrong size'. Needs a human.", 1200],
  ["support_desk", "done", "Ticket resolved by support.", 800],
  ["ceo", "done", "CEO asked 'how is the new drop doing?' → answered from internal docs + live metrics.", 1000],
];

function simBase() {
  const nodes = {};
  S.reg.nodes.forEach((n) => (nodes[n.id] = { status: n.built ? "ok" : "planned", message: null, at: null, runs_24h: 0, errors_24h: 0, avg_ms: null }));
  return { nodes, events: [], run: { run_id: "sim-0", kind: "sim", title: "A new drop, from trend to doorstep (scripted)", running: true, steps: [], design: null },
    stats: { working: 0, needs_you: 0, model_calls_24h: 0, errors_24h: 0, runs_24h: 1, image_model: "simulated", pending_designs: 0, open_tickets: 0 } };
}

function startSim() {
  const view = simBase();
  S.sim = { view, i: 0, script: SCRIPT, timer: null };
  $("#sim-btn").textContent = "■ Stop simulation";
  setDtab("run"); $("#drawer").classList.add("open");
  fitView(); simStep();
}
function stopSim() {
  if (!S.sim) return; clearTimeout(S.sim.timer); S.sim = null;
  $("#sim-btn").textContent = "▶ Simulate a drop"; paint();
}
function simStep() {
  const sim = S.sim; if (!sim) return;
  const v = sim.view;
  if (sim.i >= sim.script.length) { v.run.running = false; Object.values(v.nodes).forEach((n) => { if (n.status === "working") n.status = "ok"; }); v.stats.working = 0; paint(); sim.timer = setTimeout(stopSim, 6000); return; }
  const [id, kind, text, hold] = sim.script[sim.i++];
  const n = v.nodes[id]; const reg = S.reg.nodes.find((x) => x.id === id);
  const now = new Date().toISOString();
  // previous "finished" glow -> healthy
  Object.values(v.nodes).forEach((x) => { if (x.status === "finished") x.status = "ok"; });
  n.message = text; n.at = now;
  n.status = kind === "work" ? "working" : kind === "wait" ? "waiting" : kind === "error" ? "error" : "finished";
  if (kind === "done" || kind === "error") { n.runs_24h++; if (kind === "error") n.errors_24h++; }
  if (kind === "done" && reg.kind === "ai") v.stats.model_calls_24h++;
  if (kind === "error") v.stats.errors_24h++;
  v.stats.working = Object.values(v.nodes).filter((x) => x.status === "working").length;
  v.stats.needs_you = Object.values(v.nodes).filter((x) => x.status === "waiting").length;
  // run steps: merge working→done of the same node
  const last = v.run.steps[v.run.steps.length - 1];
  const st = kind === "work" ? "working" : kind === "wait" ? "wait" : kind === "error" ? "error" : "done";
  if (last && last.node === id && (last.status === "working" || last.status === "wait")) Object.assign(last, { status: st, label: text, duration_ms: hold + 400 });
  else v.run.steps.push({ node: id, name: reg.name, label: text, status: st, duration_ms: kind === "work" ? null : hold + 300, at: now });
  if (id === "garment_matcher") v.run.design = { id: 0, status: "pending", garment: "hoodie", color: "black", tags: ["typography", "retro", "poster"], summary: "Retro Tamil cinema typography, amber on black.", image_url: "" };
  if (id === "human_approval" && kind === "done" && v.run.design) v.run.design.status = "approved";
  v.events.unshift({ id: sim.i, node: id, name: reg.name, status: kind === "work" ? "start" : kind === "error" ? "error" : "ok", message: text, at: now, duration_ms: null, sim: true });
  paint();
  centerOnIfFar(id);
  sim.timer = setTimeout(simStep, hold);
}
function centerOnIfFar(id) {
  const p = S.lay.nodes[id], c = $("#canvas"); if (!p) return;
  const sx = T.x + p.x * T.k, sy = T.y + p.y * T.k;
  if (sx < 60 || sx > c.clientWidth - 220 || sy < 20 || sy > c.clientHeight - 120) centerOn(id);
}

// ---------------- globe ----------------
const LAND = [
  [[-168,66],[-140,70],[-95,72],[-80,68],[-62,58],[-55,50],[-67,44],[-76,35],[-81,25],[-97,26],[-105,22],[-117,32],[-124,40],[-125,49],[-140,60]],
  [[-55,60],[-45,60],[-20,70],[-20,82],[-60,82],[-72,76]],
  [[-80,10],[-62,11],[-50,0],[-35,-6],[-40,-22],[-50,-30],[-58,-38],[-68,-52],[-74,-50],[-72,-30],[-76,-14],[-81,-4]],
  [[-10,36],[-9,43],[-1,48],[4,52],[10,57],[20,60],[30,70],[60,70],[100,77],[140,72],[180,68],[170,60],[142,52],[135,43],[122,40],[122,30],[110,20],[106,10],[100,2],[98,15],[92,22],[80,15],[77,8],[72,20],[66,25],[57,25],[50,30],[35,36],[27,36],[22,38],[12,38],[5,36]],
  [[35,30],[43,13],[52,16],[59,22],[56,26],[48,30]],
  [[-17,21],[-10,35],[10,37],[32,31],[43,12],[51,12],[40,-5],[40,-15],[33,-27],[20,-35],[12,-18],[9,-1],[-8,4],[-17,14]],
  [[114,-22],[130,-12],[142,-11],[153,-26],[147,-38],[135,-35],[115,-34]],
  [[95,5],[105,-6],[120,-8],[140,-5],[130,2],[110,2]],
  [[-5,50],[2,52],[-3,58],[-6,55]],
  [[130,32],[141,36],[142,44],[138,38]],
];
function inPoly(lon, lat, poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) c = !c;
  }
  return c;
}
const G = { zoom: 1, lon: 78, lat: 18, raf: null, dots: null, drag: null, hop: null, tour: null, t0: performance.now(), target: null };
function landDots() {
  if (G.dots) return G.dots;
  const d = [];
  for (let lat = -80; lat <= 84; lat += 1.7) {
    const step = 1.7 / Math.max(0.25, Math.cos(lat * Math.PI / 180));
    for (let lon = -180; lon < 180; lon += step) if (LAND.some((p) => inPoly(lon, lat, p))) d.push([lat, lon]);
  }
  return (G.dots = d);
}
const rad = (x) => x * Math.PI / 180;
function proj(lat, lon, R, cx, cy, lift = 1) {
  const p = rad(lat), l = rad(lon - G.lon), p0 = rad(G.lat);
  const cosc = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * Math.cos(p) * Math.cos(l);
  const x = Math.cos(p) * Math.sin(l), y = Math.cos(p0) * Math.sin(p) - Math.sin(p0) * Math.cos(p) * Math.cos(l);
  return { x: cx + R * lift * x, y: cy - R * lift * y, vis: cosc > 0.02 || (lift > 1 && cosc > -0.15 && false), cosc };
}
function arcPoints(a, b, n = 48) {
  const v = (la, lo) => [Math.cos(rad(la)) * Math.cos(rad(lo)), Math.cos(rad(la)) * Math.sin(rad(lo)), Math.sin(rad(la))];
  const A = v(a.lat, a.lon), B = v(b.lat, b.lon);
  const dot = Math.max(-1, Math.min(1, A[0] * B[0] + A[1] * B[1] + A[2] * B[2]));
  const om = Math.acos(dot) || 0.0001, out = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, s1 = Math.sin((1 - t) * om) / Math.sin(om), s2 = Math.sin(t * om) / Math.sin(om);
    const x = s1 * A[0] + s2 * B[0], y = s1 * A[1] + s2 * B[1], z = s1 * A[2] + s2 * B[2];
    out.push({ lat: Math.asin(z) * 180 / Math.PI, lon: Math.atan2(y, x) * 180 / Math.PI, lift: 1 + Math.sin(Math.PI * t) * Math.min(0.35, 0.08 + om * 0.16) });
  }
  return out;
}
function hopLive(h) {
  const v = S.live; if (!v || S.sim) { const sv = S.sim && S.sim.view; return !!sv && h.nodes.some((id) => sv.nodes[id] && sv.nodes[id].status === "working"); }
  return h.nodes.some((id) => v.nodes[id] && v.nodes[id].status === "working");
}
function drawGlobe(now) {
  const cv = $("#globe"); if (!cv) return;
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== w * dpr || cv.height !== h * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  const R = Math.min(w, h) * 0.36 * G.zoom, cx = w / 2, cy = h / 2 + 6;

  // glow + sphere
  const g = ctx.createRadialGradient(cx - R * .3, cy - R * .3, R * .1, cx, cy, R * 1.05);
  g.addColorStop(0, "#35271c"); g.addColorStop(1, "#171210");
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill();
  ctx.strokeStyle = "rgba(233,161,95,.35)"; ctx.lineWidth = 1.2; ctx.stroke();
  ctx.save(); ctx.shadowColor = "rgba(233,161,95,.35)"; ctx.shadowBlur = 40; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.strokeStyle = "rgba(233,161,95,.12)"; ctx.stroke(); ctx.restore();

  // graticule
  ctx.strokeStyle = "rgba(255,240,220,.05)"; ctx.lineWidth = 1;
  for (let lat = -60; lat <= 60; lat += 30) { ctx.beginPath(); let s = false; for (let lon = -180; lon <= 180; lon += 6) { const p = proj(lat, lon, R, cx, cy); if (p.vis) { s ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); s = true; } else s = false; } ctx.stroke(); }
  for (let lon = -180; lon < 180; lon += 30) { ctx.beginPath(); let s = false; for (let lat = -80; lat <= 80; lat += 5) { const p = proj(lat, lon, R, cx, cy); if (p.vis) { s ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); s = true; } else s = false; } ctx.stroke(); }

  // land dots
  landDots().forEach(([la, lo]) => { const p = proj(la, lo, R, cx, cy); if (!p.vis) return; ctx.fillStyle = `rgba(233,190,140,${0.18 + 0.5 * p.cosc})`; ctx.fillRect(p.x - 0.8, p.y - 0.8, 1.7, 1.7); });

  // arcs
  const P = S.reg.places, t = (now - G.t0) / 1000;
  S.reg.hops.forEach((h) => {
    const a = P[h.from], b = P[h.to]; if (!a || !b) return; const pts = arcPoints(a, b), active = G.hop === h.id, live = hopLive(h);
    ctx.lineWidth = active ? 2.4 : 1.1;
    ctx.strokeStyle = live ? "rgba(90,180,255,.95)" : active ? "rgba(233,161,95,.95)" : "rgba(233,161,95,.22)";
    ctx.shadowColor = live ? "#5ab4ff" : active ? "#e9a15f" : "transparent"; ctx.shadowBlur = active || live ? 12 : 0;
    ctx.beginPath(); let s = false;
    pts.forEach((q) => { const p = proj(q.lat, q.lon, R, cx, cy, q.lift); if (p.vis) { s ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); s = true; } else s = false; });
    ctx.stroke(); ctx.shadowBlur = 0;
    if (active || live) { // travelling packets
      for (let k = 0; k < 3; k++) { const f = ((t * 0.35 + k / 3) % 1), q = pts[Math.floor(f * (pts.length - 1))], p = proj(q.lat, q.lon, R, cx, cy, q.lift); if (!p.vis) continue; ctx.fillStyle = live ? "#bfe3ff" : "#ffe2bf"; ctx.beginPath(); ctx.arc(p.x, p.y, 3.2, 0, 7); ctx.fill(); }
    }
  });

  // pins
  const colors = { external: "#d98f7a", azure: "#5ab4ff", person: "#9bbf8a" };
  const activePlaces = new Set(); const ah = S.reg.hops.find((x) => x.id === G.hop); if (ah) { activePlaces.add(ah.from); activePlaces.add(ah.to); }
  Object.entries(P).forEach(([id, pl]) => {
    const p = proj(pl.lat, pl.lon, R, cx, cy); if (!p.vis) return;
    const on = activePlaces.has(id), pr = 4 + (on ? 2 + 1.5 * Math.sin(t * 4) : 0);
    ctx.fillStyle = colors[pl.kind]; ctx.shadowColor = colors[pl.kind]; ctx.shadowBlur = on ? 18 : 6; ctx.beginPath(); ctx.arc(p.x, p.y, pr, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    ctx.font = "600 11.5px Manrope, sans-serif"; ctx.fillStyle = on ? "#fff" : "rgba(241,232,220,.8)";
    pl.label.split("\n").forEach((line, i) => { ctx.textAlign = p.x > cx ? "left" : "right"; ctx.fillText(line, p.x + (p.x > cx ? 10 : -10), p.y + 4 + i * 13); });
  });
}
function globeLoop(now) {
  if (G.target) { G.lon += (G.target.lon - G.lon) * 0.05; G.lat += (G.target.lat - G.lat) * 0.05; }
  else if ($("#spin").checked && !G.drag && !G.tour) G.lon += 0.12;
  drawGlobe(now);
  G.raf = requestAnimationFrame(globeLoop);
}
function startGlobe() { if (!G.raf) { G.t0 = performance.now(); G.raf = requestAnimationFrame(globeLoop); } renderHops(); }
function stopGlobe() { if (G.raf) cancelAnimationFrame(G.raf); G.raf = null; stopTour(); }

function renderHops() {
  const box = $("#hops"); if (!box || !S.reg) return;
  const P = S.reg.places;
  box.innerHTML = `<p class="sub" style="color:var(--mute);margin:0 0 12px;line-height:1.5">How one design travels through the systems — from a web search to a doorstep. Click a hop (or play the tour) and the globe flies there. A hop glows <b style="color:var(--working)">blue</b> when one of its agents is working right now.</p>` +
    S.reg.hops.map((h) => `<div class="hop ${G.hop === h.id ? "on" : ""}" data-h="${h.id}"><span class="n">${String(h.id).padStart(2, "0")}</span>
      <b>${esc(h.title)}${hopLive(h) ? '<span class="livebadge">● LIVE</span>' : ""}</b>
      <div class="route">${esc(P[h.from].label.split("\n")[0])} → ${esc(P[h.to].label.split("\n")[0])}</div>
      <p>${esc(h.body)}</p>
      <div class="nodes">${h.nodes.map((id) => `<button data-n="${id}">${esc((S.reg.nodes.find((n) => n.id === id) || {}).name || id)}</button>`).join("")}</div></div>`).join("");
  $$(".hop", box).forEach((el) => el.addEventListener("click", (e) => {
    if (e.target.dataset.n) { switchTab("workflow"); selectNode(e.target.dataset.n); centerOn(e.target.dataset.n); return; }
    stopTour(); focusHop(Number(el.dataset.h));
  }));
}
function focusHop(id) {
  G.hop = id; const h = S.reg.hops.find((x) => x.id === id), P = S.reg.places;
  const a = P[h.from], b = P[h.to]; if (!a || !b) return;
  G.target = { lat: Math.max(-50, Math.min(55, (a.lat + b.lat) / 2)), lon: Math.abs(a.lon - b.lon) > 180 ? (a.lon + b.lon) / 2 + 180 : (a.lon + b.lon) / 2 };
  G.zoom = 1.05;
  $$(".hop").forEach((e) => e.classList.toggle("on", Number(e.dataset.h) === id));
  const el = $(`.hop[data-h="${id}"]`); if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  setTimeout(() => { if (G.hop === id && !G.tour) G.target = null; }, 2600);
}
function playTour() {
  stopTour(); let i = 0; G.tour = true; $("#tour-btn").textContent = "■ Stop the tour";
  const next = () => { if (!G.tour) return; if (i >= S.reg.hops.length) { stopTour(); return; } focusHop(S.reg.hops[i++].id); G.tour = setTimeout(next, 5200); G.tourOn = true; };
  G.tourOn = true; next();
}
function stopTour() { if (G.tour && G.tour !== true) clearTimeout(G.tour); G.tour = null; G.target = null; const b = $("#tour-btn"); if (b) b.textContent = "▶ Play the pipeline tour"; }
document.addEventListener("DOMContentLoaded", () => {
  const cv = $("#globe");
  cv.addEventListener("pointerdown", (e) => { G.drag = { x: e.clientX, y: e.clientY }; G.target = null; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => { if (!G.drag) return; G.lon -= (e.clientX - G.drag.x) * 0.35; G.lat = Math.max(-70, Math.min(70, G.lat + (e.clientY - G.drag.y) * 0.3)); G.drag = { x: e.clientX, y: e.clientY }; });
  cv.addEventListener("pointerup", () => { G.drag = null; });
  cv.addEventListener("wheel", (e) => { e.preventDefault(); G.zoom = Math.max(0.7, Math.min(2.6, G.zoom * (e.deltaY < 0 ? 1.08 : 0.93))); }, { passive: false });
  $("#tour-btn").addEventListener("click", () => (G.tour ? stopTour() : playTour()));
  setInterval(() => { if (S.tab === "globe" && S.reg) { const live = S.reg.hops.map(hopLive).join(); if (live !== G.liveKey) { G.liveKey = live; renderHops(); } } }, 1500);
});
