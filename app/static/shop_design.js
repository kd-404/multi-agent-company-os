// Dedicated product-detail page. Self-contained (not sharing shop.js)
// because shop.js's loadProducts()/renderGrid() assume the collection
// grid IDs exist on the page, which this page doesn't have - only a
// "related" strip. The topbar/account/cart/cookie-banner behavior is
// duplicated here rather than refactored into a shared module, since
// this project has no build step and shop.html is already verified
// working - not worth the regression risk to extract it mid-session.

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const DESIGN_ID = window.LOOMWELL_DESIGN_ID;
const MOCKUP_SLOTS = ["front", "back", "model"];

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

function productCardHtml(p) {
  const meta = `${p.sources ? p.sources.length : 0} source${(p.sources || []).length === 1 ? "" : "s"} · ${formatDate(p.created_at)}`;
  return `
    <a class="product-card" href="/shop/design/${p.id}">
      <img src="${p.mockups.front}" alt="" loading="lazy" />
      <div class="product-body">
        <p class="product-summary">${escapeHtml(p.trend_summary)}</p>
        <p class="product-meta">${meta}</p>
      </div>
    </a>`;
}

// --- Load this design + related items ---
let activeDesign = null;

async function loadDesign() {
  const res = await fetch(`/api/public/products/${DESIGN_ID}`);
  if (!res.ok) {
    document.getElementById("detail-title").textContent = "Design not found";
    document.getElementById("detail-sources").textContent = "It may have been removed, or was never approved.";
    return;
  }
  activeDesign = await res.json();
  document.title = `Loomwell — ${activeDesign.trend_summary.slice(0, 60)}`;
  document.getElementById("detail-title").textContent = activeDesign.trend_summary;

  const sourcesEl = document.getElementById("detail-sources");
  sourcesEl.innerHTML = activeDesign.sources.length
    ? "Sourced from " + activeDesign.sources.slice(0, 5).map((s) => {
        let host; try { host = new URL(s).hostname.replace("www.", ""); } catch { host = s; }
        return `<a href="${s}" target="_blank" rel="noopener">${host}</a>`;
      }).join(", ")
    : "";

  if (activeDesign.caption) {
    document.getElementById("detail-caption").classList.remove("hidden");
    document.getElementById("detail-caption-text").textContent = activeDesign.caption;
    document.getElementById("detail-hashtags").textContent = activeDesign.hashtags || "";
  }

  const tabsEl = document.getElementById("detail-tabs");
  tabsEl.innerHTML = MOCKUP_SLOTS.map(
    (slot, i) => `<button data-slot="${slot}" class="${i === 0 ? "active" : ""}">${slot}</button>`
  ).join("");
  tabsEl.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => showSlot(btn.dataset.slot));
  });
  showSlot("front");

  loadRelated();
}

function showSlot(slot) {
  if (!activeDesign) return;
  document.getElementById("detail-image").src = activeDesign.mockups[slot];
  document.querySelectorAll("#detail-tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.slot === slot);
  });
}

async function loadRelated() {
  const res = await fetch("/api/public/products");
  if (!res.ok) return;
  const all = await res.json();
  const related = all.filter((p) => p.id !== DESIGN_ID).slice(0, 4);
  const section = document.getElementById("related");
  const grid = document.getElementById("related-grid");
  if (related.length === 0) {
    section.hidden = true;
    return;
  }
  grid.innerHTML = related.map(productCardHtml).join("");
}

loadDesign();

// --- Top-bar search: this page has no grid to filter, so send the
// shopper to the collection page with their query in mind. ---
document.getElementById("topbar-search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  window.location.href = "/shop#collection";
});

// --- Cookie consent (same behavior as shop.js) ---
(function setupCookieBanner() {
  const banner = document.getElementById("cookie-banner");
  let choice = null;
  try { choice = localStorage.getItem("loomwell_cookie_consent"); } catch {}
  if (!choice) banner.hidden = false;

  const setChoice = (value) => {
    try { localStorage.setItem("loomwell_cookie_consent", value); } catch {}
    banner.hidden = true;
  };
  document.getElementById("cookie-accept").addEventListener("click", () => setChoice("accepted"));
  document.getElementById("cookie-decline").addEventListener("click", () => setChoice("declined"));
})();

// --- Account (sign in / create account) - same endpoints as shop.js ---
async function refreshAccountState() {
  const line1 = document.getElementById("account-line-1");
  try {
    const res = await fetch("/api/me");
    if (res.ok) {
      const me = await res.json();
      line1.textContent = `Hello, ${me.email.split("@")[0]}`;
      document.getElementById("account-email").textContent = me.email;
      document.getElementById("account-signed-in").classList.remove("hidden");
      document.getElementById("account-signed-out").classList.add("hidden");
    } else {
      line1.textContent = "Hello, sign in";
      document.getElementById("account-signed-in").classList.add("hidden");
      document.getElementById("account-signed-out").classList.remove("hidden");
    }
  } catch {
    line1.textContent = "Hello, sign in";
  }
}

function openAccountModal() { document.getElementById("account-backdrop").hidden = false; }
function closeAccountModal() { document.getElementById("account-backdrop").hidden = true; }

document.getElementById("account-corner").addEventListener("click", openAccountModal);
document.getElementById("footer-account-btn").addEventListener("click", openAccountModal);
document.getElementById("account-modal-close").addEventListener("click", closeAccountModal);
document.getElementById("account-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "account-backdrop") closeAccountModal();
});

function switchAccountTab(which) {
  document.getElementById("account-tab-login").classList.toggle("active", which === "login");
  document.getElementById("account-tab-register").classList.toggle("active", which === "register");
  document.getElementById("account-login-form").classList.toggle("hidden", which !== "login");
  document.getElementById("account-register-form").classList.toggle("hidden", which !== "register");
}
document.getElementById("account-tab-login").addEventListener("click", () => switchAccountTab("login"));
document.getElementById("account-tab-register").addEventListener("click", () => switchAccountTab("register"));

document.getElementById("account-login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const res = await fetch("/api/login", { method: "POST", body: form });
  const data = await res.json();
  const errEl = document.getElementById("account-login-error");
  if (!res.ok) { errEl.textContent = data.detail || "Sign in failed"; return; }
  errEl.textContent = "";
  await refreshAccountState();
  closeAccountModal();
});

document.getElementById("account-register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const res = await fetch("/api/register", { method: "POST", body: form });
  const data = await res.json();
  const errEl = document.getElementById("account-register-error");
  if (!res.ok) { errEl.textContent = data.detail || "Couldn't create that account"; return; }
  errEl.textContent = "";
  switchAccountTab("login");
});

document.getElementById("account-sign-out").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  await refreshAccountState();
  closeAccountModal();
});

refreshAccountState();

// --- Cart (same honest "coming soon" popover as shop.js) ---
document.getElementById("cart-corner").addEventListener("click", (e) => {
  e.stopPropagation();
  const popover = document.getElementById("cart-popover");
  popover.hidden = !popover.hidden;
});
document.addEventListener("click", () => {
  document.getElementById("cart-popover").hidden = true;
});
