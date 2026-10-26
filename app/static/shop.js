// Storefront home: hero + brand imagery, linen edit, printed pieces with
// type filters, and the photo search.
applyBrandImage($("#hero"), "hero");
applyBrandImage($("#banner-shirts"), "shirts-banner");
applyBrandImage($("#banner-tees"), "tees-banner");
applyBrandImage($("#banner-studio"), "studio-banner");
["farm-1", "farm-2", "farm-3"].forEach((k) => applyBrandImage(document.getElementById(k), k));

let products = [];
let typeFilter = "all";

function renderLinen() {
  const list = products.filter((p) => p.kind === "plain");
  $("#linen-grid").innerHTML = list.length
    ? list.map(productCard).join("")
    : `<p class="grid-empty">The linen shirts are being photographed — check back very soon.</p>`;
}

function renderTees() {
  let list = products.filter((p) => p.kind !== "plain");
  if (typeFilter !== "all") list = list.filter((p) => p.garment_label === typeFilter);
  $("#tees-grid").innerHTML = list.length
    ? list.map(productCard).join("")
    : `<p class="grid-empty">${products.some((p) => p.kind !== "plain") ? "Nothing in that category yet." : "The next drop is still in design."}</p>`;
}

async function loadProducts() {
  try {
    const res = await fetch("/api/public/products");
    products = res.ok ? await res.json() : [];
  } catch { products = []; }
  renderLinen();
  renderTees();
}

$$("#type-filters .fchip").forEach((b) => b.addEventListener("click", () => {
  $$("#type-filters .fchip").forEach((x) => x.classList.toggle("active", x === b));
  typeFilter = b.dataset.type;
  renderTees();
}));

// ---------- photo search ----------
const sFile = $("#search-file"), sBtn = $("#search-submit"), sRes = $("#search-results"), sLabel = $("#search-dropzone-label");
sFile.addEventListener("change", () => {
  const f = sFile.files[0];
  sLabel.textContent = f ? f.name : "Drop a photo here, or click to choose";
  sBtn.disabled = !f;
});
const dz = $("#search-dropzone");
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", (e) => {
  if (e.dataTransfer.files[0]) { sFile.files = e.dataTransfer.files; sFile.dispatchEvent(new Event("change")); }
});

$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = sFile.files[0];
  if (!f) return;
  sBtn.disabled = true; sBtn.textContent = "Searching…";
  try {
    const form = new FormData(); form.append("file", f);
    const res = await fetch("/api/public/visual-search", { method: "POST", body: form });
    sRes.hidden = false;
    if (!res.ok) { sRes.innerHTML = `<p class="grid-empty">Couldn't read that image — try a different photo.</p>`; return; }
    const matches = await res.json();
    sRes.innerHTML = matches.length ? matches.map(productCard).join("") : `<p class="grid-empty">No close matches yet.</p>`;
    sRes.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth", block: "nearest" });
  } finally {
    sBtn.disabled = false; sBtn.textContent = "Find matches";
  }
});

loadProducts();
