const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// --- Load products ---
let products = [];

async function loadProducts() {
  const res = await fetch("/api/public/products");
  if (!res.ok) return;
  products = await res.json();

  const grid = document.getElementById("product-grid");
  const emptyMsg = document.getElementById("grid-empty");
  const countEl = document.getElementById("collection-count");

  if (products.length === 0) {
    emptyMsg.hidden = false;
    countEl.textContent = "";
    return;
  }
  emptyMsg.hidden = true;
  countEl.textContent = `${products.length} piece${products.length === 1 ? "" : "s"}`;

  grid.innerHTML = products.map(productCardHtml).join("");
  grid.querySelectorAll(".product-card").forEach((card) => {
    card.addEventListener("click", () => openModal(Number(card.dataset.id)));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openModal(Number(card.dataset.id));
      }
    });
  });

  setupHero(products[0]);
}

function productCardHtml(p) {
  const badge = typeof p.similarity === "number"
    ? `<span class="search-match-badge">${p.similarity}% match</span>`
    : "";
  const meta = typeof p.similarity === "number"
    ? `${p.sources.length} source${p.sources.length === 1 ? "" : "s"}`
    : `${p.sources.length} source${p.sources.length === 1 ? "" : "s"} · ${formatDate(p.created_at)}`;
  return `
    <div class="product-card" data-id="${p.id}" tabindex="0" role="button" aria-label="View design">
      ${badge}
      <img src="${p.mockups.front}" alt="" loading="lazy" />
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

// --- Modal (front/back/side viewer) ---
let activeProduct = null;
const MOCKUP_SLOTS = ["front", "back", "side"];

function openModal(id) {
  const product = products.find((p) => p.id === id);
  if (!product) return;
  activeProduct = product;

  document.getElementById("modal-summary").textContent = product.trend_summary;
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

loadProducts();
