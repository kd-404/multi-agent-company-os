const authScreen = document.getElementById("auth-screen");
const dashboardScreen = document.getElementById("dashboard-screen");

// --- Tabs ---
document.getElementById("tab-login").onclick = () => switchTab("login");
document.getElementById("tab-register").onclick = () => switchTab("register");
function switchTab(which) {
  document.getElementById("tab-login").classList.toggle("active", which === "login");
  document.getElementById("tab-register").classList.toggle("active", which === "register");
  document.getElementById("login-form").classList.toggle("hidden", which !== "login");
  document.getElementById("register-form").classList.toggle("hidden", which !== "register");
}

// --- Register ---
document.getElementById("register-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const res = await fetch("/api/register", { method: "POST", body: form });
  const data = await res.json();
  const errEl = document.getElementById("register-error");
  if (!res.ok) { errEl.textContent = data.detail || "Registration failed"; return; }
  errEl.textContent = "";
  switchTab("login");
};

// --- Login ---
document.getElementById("login-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const res = await fetch("/api/login", { method: "POST", body: form });
  const data = await res.json();
  const errEl = document.getElementById("login-error");
  if (!res.ok) { errEl.textContent = data.detail || "Login failed"; return; }
  errEl.textContent = "";
  await enterDashboard();
};

// --- Logout ---
document.getElementById("logout-btn").onclick = async () => {
  await fetch("/api/logout", { method: "POST" });
  dashboardScreen.classList.add("hidden");
  authScreen.classList.remove("hidden");
};

// --- On load, check if already logged in ---
(async function init() {
  const res = await fetch("/api/me");
  if (res.ok) await enterDashboard();
})();

async function enterDashboard() {
  const me = await (await fetch("/api/me")).json();
  document.getElementById("user-email").textContent = me.email;
  document.getElementById("role-badge").textContent = me.role;
  authScreen.classList.add("hidden");
  dashboardScreen.classList.remove("hidden");

  if (me.role === "admin") {
    ["admin-panel", "design-panel", "interest-panel", "agents-panel", "marketing-panel", "warehouse-panel"].forEach((id) => {
      document.getElementById(id).classList.remove("hidden");
    });
    document.querySelectorAll(".sidebar-link[data-target]").forEach((a) => a.classList.remove("hidden"));
    loadUsers();
    await checkMockupTemplates();
    loadDesigns();
    loadSearchTrends();
    loadAgentStatus();
    loadAgentFeed();
    loadMarketingFeed();
    loadWarehouseStatus();
    loadStatRow();
  }

  loadChatHistory();
  setupSidebarScrollspy();
}

// --- Sidebar: scrollspy (highlight the section currently in view) ---
function setupSidebarScrollspy() {
  const links = Array.from(document.querySelectorAll(".sidebar-link[data-target]"));
  if (!links.length) return;

  const setActive = (id) => {
    links.forEach((a) => a.classList.toggle("active", a.dataset.target === id));
  };

  links.forEach((a) => {
    a.addEventListener("click", () => setActive(a.dataset.target));
  });

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries.filter((e) => e.isIntersecting);
      if (visible.length) setActive(visible[0].target.id);
    },
    { rootMargin: "-20% 0px -70% 0px" }
  );
  links.forEach((a) => {
    const section = document.getElementById(a.dataset.target);
    if (section) observer.observe(section);
  });
}

// --- Stat row: dashboard-home summary cards, built from data already loaded ---
async function loadStatRow() {
  const el = document.getElementById("stat-row");
  try {
    const [designs, users, warehouse, feed] = await Promise.all([
      fetch("/api/admin/design/list").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/admin/users").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/admin/warehouse/status").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/admin/agents/feed").then((r) => (r.ok ? r.json() : [])),
    ]);

    const approved = designs.filter((d) => d.status === "approved").length;
    const pending = designs.filter((d) => d.status === "pending").length;
    const customers = users.filter((u) => u.role === "user").length;
    const reprintFlags = warehouse.filter((w) => w.recommend_reprint).length;
    const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
    const alerts24h = feed.filter((f) => (f.status === "alert" || f.status === "error") && new Date(f.created_at).getTime() >= dayAgo).length;

    const cards = [
      { label: "Designs", value: designs.length, sub: `${approved} approved · ${pending} pending` },
      { label: "Customers", value: customers, sub: "registered accounts" },
      { label: "Agent alerts (24h)", value: alerts24h, sub: "across all agents", cls: alerts24h ? "stat-alert" : "stat-ok" },
      { label: "Reprint recommended", value: reprintFlags, sub: "low stock + high interest", cls: reprintFlags ? "stat-alert" : "stat-ok" },
    ];

    el.innerHTML = cards.map((c) => `
      <div class="stat-card ${c.cls || ""}">
        <p class="stat-label">${c.label}</p>
        <p class="stat-value">${c.value}</p>
        <p class="stat-sub">${c.sub}</p>
      </div>`).join("");
  } catch (e) {
    el.innerHTML = "";
  }
}

// --- Chat ---
const chatLog = document.getElementById("chat-log");
function appendChat(role, content) {
  const div = document.createElement("div");
  div.className = "chat-msg " + role;
  div.textContent = content;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function loadChatHistory() {
  const res = await fetch("/api/chat/history");
  if (!res.ok) return;
  const history = await res.json();
  chatLog.innerHTML = "";
  history.forEach((m) => appendChat(m.role, m.content));
}

document.getElementById("chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;
  appendChat("user", message);
  input.value = "";

  const form = new FormData();
  form.append("message", message);
  const res = await fetch("/api/chat", { method: "POST", body: form });
  const data = await res.json();
  appendChat("assistant", data.reply || "(no reply)");
};

// --- Vision ---
document.getElementById("vision-form").onsubmit = async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("vision-file");
  const mode = document.querySelector('input[name="mode"]:checked').value;
  if (!fileInput.files[0]) return;

  const form = new FormData();
  form.append("file", fileInput.files[0]);
  form.append("mode", mode);

  const resultEl = document.getElementById("vision-result");
  resultEl.textContent = "Analyzing...";

  const res = await fetch("/api/vision/analyze", { method: "POST", body: form });
  const data = await res.json();
  resultEl.textContent = JSON.stringify(data, null, 2);
};

// --- Admin: list users / create admin ---
async function loadUsers() {
  const res = await fetch("/api/admin/users");
  if (!res.ok) return;
  const users = await res.json();
  const el = document.getElementById("user-list");
  el.innerHTML = users.map(u => `<div>${u.email} &mdash; <strong>${u.role}</strong></div>`).join("");
}

document.getElementById("create-admin-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const res = await fetch("/api/admin/create-admin", { method: "POST", body: form });
  if (res.ok) { e.target.reset(); loadUsers(); }
};

// --- Design agent ---
const designGallery = document.getElementById("design-gallery");
const designStatusEl = document.getElementById("design-generate-status");
const MOCKUP_SLOTS = ["front", "back", "model"];
let mockupTemplatesReady = false; // true once the DEFAULT (tshirt/white) combo exists - enough to show any design

async function checkMockupTemplates() {
  const hint = document.getElementById("mockup-setup-hint");
  const btn = document.getElementById("mockup-setup-btn");
  const res = await fetch("/api/admin/mockup-templates");
  if (!res.ok) return;
  const status = await res.json();
  mockupTemplatesReady = status.default_ready;

  if (status.generated_count === status.total_count) {
    hint.textContent = `All ${status.total_count} garment/color/angle combos are photographed. Each approved design previews on its assigned garment below.`;
    btn.textContent = "Regenerate all mockup templates";
    btn.classList.remove("hidden");
  } else if (status.generated_count > 0) {
    hint.textContent = `${status.generated_count} of ${status.total_count} garment/color/angle combos photographed so far — finish the set so every design has its own garment+color to land on.`;
    btn.textContent = "Finish generating mockup templates";
    btn.classList.remove("hidden");
  } else {
    hint.textContent = "Photograph the garment matrix once (T-shirt, hoodie and full-sleeve, each in a few colors), so every design previews on a mixed, varied product shot instead of the same white tee.";
    btn.classList.remove("hidden");
  }
}

document.getElementById("mockup-setup-btn").onclick = async (e) => {
  const btn = e.target;
  const hint = document.getElementById("mockup-setup-hint");
  btn.disabled = true;
  btn.textContent = "Photographing the garment matrix (several minutes)...";
  try {
    const res = await fetch("/api/admin/mockup-templates/generate", { method: "POST" });
    const data = await res.json();
    const failed = Object.entries(data.results || {}).filter(([, v]) => v.status !== "ok");
    await checkMockupTemplates();
    if (failed.length) {
      hint.textContent = `${data.succeeded}/${data.total} combos generated. Failed: ${failed.map(([combo, v]) => `${combo} (${v.detail})`).join(", ")}`;
    }
    loadDesigns();
  } finally {
    btn.disabled = false;
    if (btn.textContent.startsWith("Photographing")) btn.textContent = "Regenerate all mockup templates";
  }
};

async function loadDesigns() {
  const res = await fetch("/api/admin/design/list");
  if (!res.ok) return;
  const designs = await res.json();
  if (designs.length === 0) {
    designGallery.innerHTML = '<p class="hint">No designs generated yet.</p>';
    return;
  }
  designGallery.innerHTML = designs.map(designCardHtml).join("");

  designs.forEach((d) => {
    if (d.status === "pending") {
      const approveBtn = document.getElementById(`approve-${d.id}`);
      const rejectBtn = document.getElementById(`reject-${d.id}`);
      if (approveBtn) approveBtn.onclick = () => reviewDesign(d.id, "approve");
      if (rejectBtn) rejectBtn.onclick = () => reviewDesign(d.id, "reject");
    }
    const reassignBtn = document.getElementById(`reassign-btn-${d.id}`);
    if (reassignBtn) reassignBtn.onclick = () => reassignDesign(d.id);
  });
}

async function reassignDesign(id) {
  const btn = document.getElementById(`reassign-btn-${id}`);
  const garment = document.getElementById(`reassign-garment-${id}`).value;
  const color = document.getElementById(`reassign-color-${id}`).value;
  btn.disabled = true;
  btn.textContent = "Saving...";
  try {
    const form = new FormData();
    form.append("garment", garment);
    form.append("color", color);
    await fetch(`/api/admin/design/${id}/reassign`, { method: "POST", body: form });
    loadDesigns();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Change garment/color";
  }
}

function designCardHtml(d) {
  const sourcesHtml = d.sources
    .slice(0, 3)
    .map((s) => `<a href="${s}" target="_blank" rel="noopener">${new URL(s).hostname}</a>`)
    .join(", ");
  const actions =
    d.status === "pending"
      ? `<div class="design-actions">
           <button id="approve-${d.id}" class="approve-btn">Approve</button>
           <button id="reject-${d.id}" class="reject-btn">Reject</button>
         </div>`
      : "";
  const mockupsHtml = mockupTemplatesReady
    ? `<div class="mockup-row">
         ${MOCKUP_SLOTS.map(
           (slot) => `<img src="/api/admin/design/${d.id}/mockup/${slot}" alt="${slot} mockup" loading="lazy" title="${slot}" />`
         ).join("")}
       </div>`
    : `<p class="design-sources">Generate mockup templates above to preview this on a shirt.</p>`;
  const reassignHtml = `
    <div class="reassign-row">
      <select id="reassign-garment-${d.id}">
        <option value="tshirt" ${d.garment === "tshirt" || !d.garment ? "selected" : ""}>T-Shirt</option>
        <option value="long-sleeve" ${d.garment === "long-sleeve" ? "selected" : ""}>Full-Sleeve</option>
        <option value="hoodie" ${d.garment === "hoodie" ? "selected" : ""}>Hoodie</option>
      </select>
      <select id="reassign-color-${d.id}">
        <option value="white" ${d.color === "white" || !d.color ? "selected" : ""}>White</option>
        <option value="black" ${d.color === "black" ? "selected" : ""}>Black</option>
        <option value="heather-gray" ${d.color === "heather-gray" ? "selected" : ""}>Heather Gray</option>
      </select>
      <button type="button" id="reassign-btn-${d.id}" class="reassign-btn">Change garment/color</button>
    </div>`;
  return `
    <div class="design-card">
      <img src="${d.image_url}" alt="Generated design ${d.id}" loading="lazy" />
      <div class="design-body">
        <span class="status-badge status-${d.status}">${d.status}</span>
        <span class="garment-badge">${d.garment_label || "T-Shirt"} · ${d.color_label || "White"}</span>
        <p class="design-summary">${d.trend_summary}</p>
        <p class="design-sources">Sources: ${sourcesHtml || "none"}</p>
        ${actions}
        ${mockupsHtml}
        ${reassignHtml}
      </div>
    </div>`;
}

async function reviewDesign(id, action) {
  await fetch(`/api/admin/design/${id}/${action}`, { method: "POST" });
  loadDesigns();
}

// --- Batch generation (varied styles) ---
document.getElementById("batch-generate-btn").addEventListener("click", async () => {
  const btn = document.getElementById("batch-generate-btn");
  const statusEl = document.getElementById("batch-generate-status");
  btn.disabled = true;
  btn.textContent = "Generating batch (this takes a few minutes)...";
  statusEl.textContent = "";

  try {
    const form = new FormData();
    form.append("count", "8");
    form.append("garment", document.getElementById("design-garment").value);
    form.append("color", document.getElementById("design-color").value);
    const res = await fetch("/api/admin/design/generate-batch", { method: "POST", body: form });
    const data = await res.json();
    const failed = (data.results || []).filter((r) => r.status !== "ok");
    statusEl.textContent = failed.length
      ? `${data.succeeded} of ${data.results.length} generated. ${failed.length} failed (${failed.map((f) => f.stage).join(", ")}).`
      : `${data.succeeded} designs generated.`;
    loadDesigns();
  } catch (e) {
    statusEl.textContent = "Batch generation failed - check Log Stream.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate a batch of 8 (varied styles)";
  }
});

// --- Customer interest (visual-search trend alerts) ---
async function loadSearchTrends() {
  const el = document.getElementById("interest-list");
  const res = await fetch("/api/admin/search-trends");
  if (!res.ok) return;
  const trends = await res.json();

  if (trends.length === 0) {
    el.innerHTML = '<p class="hint">No repeated search interest in the last 7 days yet.</p>';
    return;
  }

  el.innerHTML = trends.map((t) => `
    <div class="interest-row">
      <img src="${t.image_url}" alt="" loading="lazy" />
      <div>
        <p class="interest-count">${t.search_count} searches matched this design (last 7 days)</p>
        <p class="interest-summary">${t.trend_summary}</p>
      </div>
    </div>
  `).join("");
}

document.getElementById("design-generate-form").onsubmit = async (e) => {
  e.preventDefault();
  const btn = document.getElementById("design-generate-btn");
  const focus = document.getElementById("design-focus").value.trim();

  btn.disabled = true;
  btn.textContent = "Researching trends & generating...";
  designStatusEl.textContent = "";

  // Always append "focus", even empty - an entirely empty multipart body
  // (zero fields) trips Starlette's form parser ("There was an error
  // parsing the body"), which is what was happening whenever this box
  // was left blank. The backend already treats "" the same as omitted.
  const form = new FormData();
  form.append("focus", focus);
  form.append("garment", document.getElementById("design-garment").value);
  form.append("color", document.getElementById("design-color").value);

  try {
    const res = await fetch("/api/admin/design/generate", { method: "POST", body: form });
    const data = await res.json();
    if (data.status !== "ok") {
      designStatusEl.textContent = `Failed (${data.stage}): ${data.detail}`;
    } else {
      designStatusEl.textContent = "";
      document.getElementById("design-focus").value = "";
      loadDesigns();
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate new design";
  }
};

// --- Agent status + full pipeline demo ---
const AGENT_LABELS = {
  design: "Design",
  marketing: "Marketing",
  warehouse: "Warehouse",
  payment: "Payment",
  ceo: "CEO",
};

function timeAgo(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function agentCardHtml(entry) {
  const label = AGENT_LABELS[entry.agent] || entry.agent;
  if (!entry.latest) {
    return `<div class="agent-card status-idle"><h4>${label}</h4><p class="agent-status-badge">idle</p><p class="agent-msg">No activity yet.</p></div>`;
  }
  const a = entry.latest;
  return `
    <div class="agent-card status-${a.status}">
      <h4>${label}</h4>
      <p class="agent-status-badge">${a.status}</p>
      <p class="agent-msg">${escapeHtmlAdmin(a.message)}</p>
      <p class="agent-time">${timeAgo(a.created_at)}</p>
    </div>`;
}

function escapeHtmlAdmin(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

async function loadAgentStatus() {
  const res = await fetch("/api/admin/agents/status");
  if (!res.ok) return;
  const data = await res.json();
  document.getElementById("agent-cards").innerHTML = data.map(agentCardHtml).join("");
}

async function loadAgentFeed() {
  const res = await fetch("/api/admin/agents/feed");
  if (!res.ok) return;
  const rows = await res.json();
  const el = document.getElementById("agent-feed");
  if (rows.length === 0) {
    el.innerHTML = '<p class="hint">No agent activity yet.</p>';
    return;
  }
  el.innerHTML = rows.map((a) => `
    <div class="feed-row status-${a.status}">
      <span class="feed-agent">${AGENT_LABELS[a.agent] || a.agent}</span>
      <span class="feed-msg">${escapeHtmlAdmin(a.message)}</span>
      <span class="feed-time">${timeAgo(a.created_at)}</span>
    </div>`).join("");
}

document.getElementById("run-demo-btn").addEventListener("click", async () => {
  const btn = document.getElementById("run-demo-btn");
  const statusEl = document.getElementById("run-demo-status");
  btn.disabled = true;
  btn.textContent = "Running pipeline...";
  statusEl.textContent = "Kicking off CEO → Design → Marketing → Payment → Warehouse...";
  try {
    const res = await fetch("/api/admin/agents/run-demo", { method: "POST" });
    const data = await res.json();
    statusEl.textContent = data.ok
      ? `Pipeline run complete (${data.steps.length} steps) — design #${data.design_id} went through the full flow.`
      : "Pipeline run stopped early - see the feed below.";
    await Promise.all([loadAgentStatus(), loadAgentFeed(), loadDesigns(), loadMarketingFeed(), loadWarehouseStatus()]);
  } catch (e) {
    statusEl.textContent = "Pipeline run failed - check Log Stream.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Run full pipeline demo";
  }
});

// --- Marketing agent ---
async function loadMarketingFeed() {
  const res = await fetch("/api/admin/marketing/feed");
  if (!res.ok) return;
  const designs = await res.json();
  const el = document.getElementById("marketing-list");
  if (designs.length === 0) {
    el.innerHTML = '<p class="hint">No approved designs yet - approve one in the Design Agent panel first.</p>';
    return;
  }
  el.innerHTML = designs.map((d) => `
    <div class="marketing-row">
      <img src="${d.image_url}" alt="" loading="lazy" />
      <div class="marketing-body">
        <p class="marketing-summary">${escapeHtmlAdmin(d.trend_summary)}</p>
        ${d.caption
          ? `<p class="marketing-caption">${escapeHtmlAdmin(d.caption)}</p><p class="marketing-hashtags">${escapeHtmlAdmin(d.hashtags || "")}</p>`
          : `<button type="button" class="draft-caption-btn" data-id="${d.id}">Draft caption</button>`}
        <button type="button" class="schedule-post-btn" data-id="${d.id}">Post to Instagram</button>
        <p class="schedule-post-status" id="schedule-post-status-${d.id}"></p>
      </div>
    </div>`).join("");
  el.querySelectorAll(".draft-caption-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      b.disabled = true;
      b.textContent = "Drafting...";
      await fetch(`/api/admin/marketing/draft/${b.dataset.id}`, { method: "POST" });
      loadMarketingFeed();
      loadAgentStatus();
      loadAgentFeed();
    });
  });
  el.querySelectorAll(".schedule-post-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      const statusEl = document.getElementById(`schedule-post-status-${b.dataset.id}`);
      b.disabled = true;
      b.textContent = "Posting...";
      try {
        const res = await fetch(`/api/admin/marketing/schedule-post/${b.dataset.id}`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        statusEl.textContent = res.ok
          ? (data.mode === "live" ? `Posted to Instagram (media ${data.media_id}).` : data.message)
          : (data.detail || "Post failed - check Log Stream.");
      } finally {
        b.disabled = false;
        b.textContent = "Post to Instagram";
        loadAgentStatus();
        loadAgentFeed();
      }
    });
  });
}

document.getElementById("scan-trends-btn").addEventListener("click", async () => {
  const btn = document.getElementById("scan-trends-btn");
  const statusEl = document.getElementById("scan-trends-status");
  btn.disabled = true;
  btn.textContent = "Scanning...";
  try {
    const res = await fetch("/api/admin/marketing/scan-trends", { method: "POST" });
    const data = await res.json();
    if (data.flagged && data.generated_design_id) {
      statusEl.textContent = `New trend found - commissioned design #${data.generated_design_id} to cover it (pending review in the Design Agent panel below).`;
    } else if (data.flagged) {
      statusEl.textContent = `New trend found (best overlap ${Math.round(data.best_overlap * 100)}%), but the Design agent couldn't generate for it - check Log Stream.`;
    } else {
      statusEl.textContent = `Catalog already covers current trends (best overlap ${Math.round(data.best_overlap * 100)}%).`;
    }
    loadAgentStatus();
    loadAgentFeed();
    if (data.generated_design_id) loadDesigns();
  } catch (e) {
    statusEl.textContent = "Trend scan failed - check Log Stream.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Scan for new trends";
  }
});

// --- Warehouse agent ---
async function loadWarehouseStatus() {
  const res = await fetch("/api/admin/warehouse/status");
  if (!res.ok) return;
  const rows = await res.json();
  const el = document.getElementById("warehouse-list");
  if (rows.length === 0) {
    el.innerHTML = '<p class="hint">No approved designs yet.</p>';
    return;
  }
  el.innerHTML = rows.map((r) => `
    <div class="warehouse-row ${r.recommend_reprint ? "recommend" : ""}">
      <img src="${r.image_url}" alt="" loading="lazy" />
      <div class="warehouse-body">
        <p class="warehouse-summary">${escapeHtmlAdmin(r.trend_summary)}</p>
        <p class="warehouse-stats">${r.virtual_stock} in stock &middot; ${r.interest_7d} searches (7d)${r.recommend_reprint ? " &middot; <strong>recommend reprint</strong>" : ""}</p>
      </div>
      <button type="button" class="restock-btn" data-id="${r.id}">Restock +50</button>
    </div>`).join("");
  el.querySelectorAll(".restock-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      b.disabled = true;
      const form = new FormData();
      form.append("qty", "50");
      await fetch(`/api/admin/warehouse/restock/${b.dataset.id}`, { method: "POST", body: form });
      loadWarehouseStatus();
      loadAgentStatus();
      loadAgentFeed();
    });
  });
}

document.getElementById("warehouse-scan-btn").addEventListener("click", async () => {
  const btn = document.getElementById("warehouse-scan-btn");
  const statusEl = document.getElementById("warehouse-scan-status");
  btn.disabled = true;
  btn.textContent = "Checking...";
  try {
    const res = await fetch("/api/admin/warehouse/scan", { method: "POST" });
    const data = await res.json();
    statusEl.textContent = data.flagged.length
      ? `${data.flagged.length} design(s) recommended for reprint.`
      : `Checked ${data.checked} design(s) - stock healthy.`;
    loadAgentStatus();
    loadAgentFeed();
  } catch (e) {
    statusEl.textContent = "Stock check failed - check Log Stream.";
  } finally {
    btn.disabled = false;
    btn.textContent = "Run stock check";
  }
});
