// Product detail page.
const DESIGN_ID = window.LOOMWELL_DESIGN_ID;
const SIZES = ["S", "M", "L", "XL"];
let product = null, size = "M", qty = 1;

function showShot(url) { $("#main-img").src = url; $$(".thumb").forEach((t) => t.classList.toggle("active", t.dataset.url === url)); }

async function loadProduct() {
  const res = await fetch(`/api/public/products/${DESIGN_ID}`);
  if (!res.ok) {
    $("#d-title").textContent = "We couldn't find that piece";
    $("#d-desc").textContent = "It may have sold out of the catalogue or been removed.";
    return;
  }
  product = await res.json();
  document.title = `${product.title} — Loomwell`;
  $("#crumb-kind").textContent = product.garment_label || "Shop";
  $("#d-kicker").textContent = `${product.garment_label || ""}${product.color_label ? " · " + product.color_label : ""}`;
  $("#d-title").textContent = product.title;
  $("#d-price").textContent = inr(product.price_inr);
  $("#d-mrp").textContent = inr(product.mrp_inr);
  const off = Math.round(100 * (product.mrp_inr - product.price_inr) / product.mrp_inr);
  $("#d-off").textContent = off > 0 ? `${off}% off` : "";

  const st = product.stock;
  const stEl = $("#d-stock");
  stEl.textContent = st.state === "in" ? "In stock" : st.label;
  stEl.className = `stock-line ${st.state === "in" ? "" : st.state}`;
  if (st.state === "out") { $("#buy-btn").disabled = true; $("#buy-btn").textContent = "Sold out"; }

  const urls = Object.values(product.mockups);
  $("#thumbs").innerHTML = urls.map((u) => `<button class="thumb" data-url="${u}" aria-label="View photo"><img src="${u}" alt="" onerror="this.closest('.thumb').remove()" /></button>`).join("");
  $$(".thumb").forEach((t) => t.addEventListener("click", () => showShot(t.dataset.url)));
  $("#main-img").alt = product.title;
  showShot(urls[0]);

  $("#size-row").innerHTML = SIZES.map((s) => `<button type="button" class="size-btn${s === size ? " active" : ""}" data-size="${s}">${s}</button>`).join("");
  $$(".size-btn").forEach((b) => b.addEventListener("click", () => {
    size = b.dataset.size;
    $$(".size-btn").forEach((x) => x.classList.toggle("active", x === b));
  }));

  const desc = product.kind === "plain"
    ? `<p>${escapeHtml(product.trend_summary)}</p><p class="muted">Washed linen with a natural, slightly rumpled texture. Gentle cycle or hand wash, line dry.</p>`
    : `<p>${escapeHtml(product.trend_summary)}</p><p class="muted">Printed on a soft cotton-rich blend. Wash cold, inside out.</p>`;
  $("#d-desc").innerHTML = desc;
  $("#d-hash").textContent = product.hashtags || "";

  loadRelated();
}

async function loadRelated() {
  const res = await fetch("/api/public/products");
  if (!res.ok) return;
  const all = (await res.json()).filter((p) => p.id !== DESIGN_ID);
  const same = all.filter((p) => p.kind === product.kind);
  const list = (same.length >= 4 ? same : all).slice(0, 4);
  $("#related-grid").innerHTML = list.map(productCard).join("");
}

$("#qty-minus").addEventListener("click", () => { qty = Math.max(1, qty - 1); $("#qty-val").textContent = qty; });
$("#qty-plus").addEventListener("click", () => { qty = Math.min(10, qty + 1); $("#qty-val").textContent = qty; });
$("#buy-btn").addEventListener("click", () => {
  if (!product) return;
  location.href = `/checkout/design/${product.id}?size=${size}&qty=${qty}`;
});
$("#ask-btn").addEventListener("click", () => {
  openAssistant(product ? `Is #${product.id} ${product.title} in stock?` : undefined);
});

loadProduct();
