const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// --- Load products ---
let products = [];

async function loadProducts() {
  const res = await fetch("/api/public/products");
  if (!res.ok) return;
  products = await res.json();
  renderGrid(products);
  if (products.length) setupHero(products[0]);
}

function renderGrid(list) {
  const grid = document.getElementById("product-grid");
  const countEl = document.getElementById("collection-count");

  if (list.length === 0) {
    const message = products.length === 0
      ? "Nothing's gone to print yet — the design agent is still working on the next drop."
      : "No designs match that search.";
    grid.innerHTML = `<p class="grid-empty">${message}</p>`;
    countEl.textContent = "";
    return;
  }
  countEl.textContent = `${list.length} piece${list.length === 1 ? "" : "s"}`;

  grid.innerHTML = list.map(productCardHtml).join("");
  grid.querySelectorAll(".product-card").forEach((card) => {
    card.addEventListener("click", () => openModal(Number(card.dataset.id)));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openModal(Number(card.dataset.id));
      }
    });
  });
}

// --- Top-bar keyword search (filters the loaded collection client-side;
// separate from the photo-based "Find something like it" visual search) ---
document.getElementById("topbar-search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("topbar-search-input").value.trim().toLowerCase();
  if (!q) {
    renderGrid(products);
  } else {
    renderGrid(products.filter((p) => p.trend_summary.toLowerCase().includes(q)));
  }
  document.getElementById("collection").scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth" });
});

function productCardHtml(p) {
  const badge = typeof p.similarity === "number"
    ? `<span class="search-match-badge">${p.similarity}% match</span>`
    : "";
  const garmentTag = p.garment_label && p.color_label ? `${p.garment_label} · ${p.color_label}` : "";
  const meta = typeof p.similarity === "number"
    ? `${p.sources.length} source${p.sources.length === 1 ? "" : "s"}`
    : `${p.sources.length} source${p.sources.length === 1 ? "" : "s"} · ${formatDate(p.created_at)}`;
  return `
    <div class="product-card" data-id="${p.id}" tabindex="0" role="button" aria-label="View design">
      <div class="product-media">
        ${badge}
        ${garmentTag ? `<span class="garment-tag">${garmentTag}</span>` : ""}
        <img src="${p.mockups.front}" alt="" loading="lazy" />
        <div class="product-overlay">Quick view</div>
      </div>
      <div class="product-body">
        <p class="product-summary">${escapeHtml(p.trend_summary)}</p>
        <p class="product-meta">${meta}</p>
      </div>
    </div>`;
}

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

// --- Visual search ("find similar") ---
const searchFile = document.getElementById("search-file");
const searchDropzone = document.getElementById("search-dropzone");
const searchDropzoneLabel = document.getElementById("search-dropzone-label");
const searchSubmit = document.getElementById("search-submit");
const searchResults = document.getElementById("search-results");

searchFile.addEventListener("change", () => {
  const file = searchFile.files[0];
  searchDropzoneLabel.textContent = file ? file.name : "Choose a photo";
  searchSubmit.disabled = !file;
});

document.getElementById("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = searchFile.files[0];
  if (!file) return;

  searchSubmit.disabled = true;
  searchSubmit.textContent = "Searching…";

  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/public/visual-search", { method: "POST", body: form });
    if (!res.ok) {
      searchResults.hidden = false;
      searchResults.innerHTML = `<p class="grid-empty">Couldn't search that image — try a different photo.</p>`;
      return;
    }
    const matches = await res.json();
    searchResults.hidden = false;
    if (matches.length === 0) {
      searchResults.innerHTML = `<p class="grid-empty">No matches yet — the collection is still small.</p>`;
      return;
    }
    searchResults.innerHTML = matches.map(productCardHtml).join("");
    searchResults.querySelectorAll(".product-card").forEach((card) => {
      card.addEventListener("click", () => openModal(Number(card.dataset.id)));
    });
    searchResults.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth", block: "start" });
  } finally {
    searchSubmit.disabled = false;
    searchSubmit.textContent = "Find matches";
  }
});

// --- Hero: featured piece + mousemove 3D tilt ---
function setupHero(product) {
  const heroImage = document.getElementById("hero-image");
  const heroStatus = document.getElementById("hero-status");
  heroImage.src = product.mockups.front;

  const sourceHost = (url) => {
    try { return new URL(url).hostname.replace("www.", ""); } catch { return url; }
  };
  const hosts = product.sources.slice(0, 3).map(sourceHost).join(", ");
  heroStatus.textContent = hosts
    ? `Latest drop sourced from ${hosts} · ${formatDate(product.created_at)}`
    : `Latest drop · ${formatDate(product.created_at)}`;

  if (prefersReducedMotion) return;

  const stage = document.getElementById("hero-tilt");
  const bounds = () => stage.getBoundingClientRect();

  window.addEventListener("mousemove", (e) => {
    const b = bounds();
    if (e.clientY < b.top - 200 || e.clientY > b.bottom + 200) return; // only react when roughly near the hero
    const relX = (e.clientX - (b.left + b.width / 2)) / b.width;
    const relY = (e.clientY - (b.top + b.height / 2)) / b.height;
    const rotY = Math.max(-14, Math.min(14, relX * 22));
    const rotX = Math.max(-14, Math.min(14, -relY * 22));
    stage.style.transform = `rotateX(${rotX}deg) rotateY(${rotY}deg)`;
  });
}

// --- Modal (front/back/model viewer) ---
let activeProduct = null;
const MOCKUP_SLOTS = ["front", "back", "model"];

function openModal(id) {
  const product = products.find((p) => p.id === id);
  if (!product) return;
  activeProduct = product;

  document.getElementById("modal-title").textContent =
    product.garment_label && product.color_label ? `${product.garment_label} · ${product.color_label}` : "Design";
  document.getElementById("modal-summary").textContent = product.trend_summary;
  document.getElementById("modal-detail-link").href = `/shop/design/${product.id}`;
  const sourcesEl = document.getElementById("modal-sources");
  sourcesEl.innerHTML = product.sources.length
    ? "Sourced from " + product.sources.slice(0, 4).map((s) => {
        let host; try { host = new URL(s).hostname.replace("www.", ""); } catch { host = s; }
        return `<a href="${s}" target="_blank" rel="noopener">${host}</a>`;
      }).join(", ")
    : "";

  const tabsEl = document.getElementById("modal-tabs");
  tabsEl.innerHTML = MOCKUP_SLOTS.map(
    (slot, i) => `<button data-slot="${slot}" class="${i === 0 ? "active" : ""}">${slot}</button>`
  ).join("");
  tabsEl.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => showModalSlot(btn.dataset.slot));
  });

  showModalSlot("front");

  const backdrop = document.getElementById("modal-backdrop");
  backdrop.hidden = false;
  document.getElementById("modal-close").focus();
}

function showModalSlot(slot) {
  if (!activeProduct) return;
  document.getElementById("modal-image").src = activeProduct.mockups[slot];
  document.querySelectorAll(".modal-tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.slot === slot);
  });
}

function closeModal() {
  document.getElementById("modal-backdrop").hidden = true;
  activeProduct = null;
}

document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "modal-backdrop") closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

// --- Cookie consent ---
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

// --- Account (sign in / create account) ---
// Reuses the exact same /api/login, /api/register, /api/logout, /api/me
// endpoints the admin dashboard uses - a storefront visitor is just a
// "user"-role account on the same system, nothing new on the backend.
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

function openAccountModal() {
  document.getElementById("account-backdrop").hidden = false;
}
function closeAccountModal() {
  document.getElementById("account-backdrop").hidden = true;
}

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

// --- Cart (not wired up yet - honest "coming soon" popover, not a dead button) ---
document.getElementById("cart-corner").addEventListener("click", (e) => {
  e.stopPropagation();
  const popover = document.getElementById("cart-popover");
  popover.hidden = !popover.hidden;
});
document.addEventListener("click", () => {
  document.getElementById("cart-popover").hidden = true;
});

loadProducts();
