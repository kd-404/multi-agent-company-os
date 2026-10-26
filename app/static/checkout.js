// Full-page demo checkout: Login -> Address -> Order summary -> Payment.
// Totals always come from the server; the page only displays them.
const KIND = window.CO_KIND, ITEM_ID = window.CO_ID;
const STATES = ["Andhra Pradesh","Assam","Bihar","Chandigarh","Chhattisgarh","Delhi","Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala","Madhya Pradesh","Maharashtra","Odisha","Punjab","Rajasthan","Tamil Nadu","Telangana","Uttar Pradesh","Uttarakhand","West Bengal","Other"];
const UPI_APPS = [["Google Pay", "#4c8bf5"], ["PhonePe", "#6f3fb5"], ["Paytm", "#1a9fe0"], ["BHIM", "#e07b2f"]];
const BANKS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Bank", "Other banks"];
const WALLETS = [["Mobikwik", "#2b73c9"], ["Quick wallet", "#d9962b"], ["Freecharge", "#e0562f"]];

const qs = new URLSearchParams(location.search);
let item = null, step = 1, size = SIZES_OK(qs.get("size")), qty = Math.min(10, Math.max(1, parseInt(qs.get("qty") || "1", 10) || 1));
let method = "upi", sub = null, coupon = "", addr = null, eta = "", sizes = ["S", "M", "L", "XL"];
function SIZES_OK(s) { return ["S", "M", "L", "XL"].includes(s) ? s : "M"; }

const card = (n) => $(`#card-${["login", "address", "summary", "payment"][n - 1]}`);

function setStep(n) {
  step = n;
  $$("#stepper .step").forEach((s, i) => {
    s.classList.toggle("done", i + 1 < n);
    s.classList.toggle("current", i + 1 === n);
  });
  [1, 2, 3, 4].forEach((i) => card(i).classList.toggle("locked", i > n));
  // bodies
  $("#address-body").classList.toggle("hidden", n !== 2);
  $("#address-summary").classList.toggle("hidden", !(n > 2));
  $("#address-change").classList.toggle("hidden", !(n > 2));
  $("#summary-body").classList.toggle("hidden", n !== 3);
  $("#summary-line").classList.toggle("hidden", !(n > 3));
  $("#summary-change").classList.toggle("hidden", !(n > 3));
  $("#payment-body").classList.toggle("hidden", n !== 4);
  $("#login-change").classList.toggle("hidden", n < 2 || !currentUser);
  renderMobileBar();
  card(n).scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth", block: "nearest" });
}

function renderLogin() {
  const body = $("#login-body");
  if (currentUser) {
    body.innerHTML = `<p><strong>${escapeHtml(currentUser.email)}</strong> <span class="muted">· signed in</span></p>`;
  } else {
    body.innerHTML = `<p class="muted" style="margin-bottom:12px">Sign in or create an account to place your order.</p><button type="button" class="btn btn-dark" id="login-go">Sign in / Create account</button>`;
    $("#login-go").addEventListener("click", async () => { if (await requireLogin()) boot(); });
  }
}

function renderPrice() {
  if (!sub) return;
  const t = sub;
  $("#price-body").innerHTML = `
    <h3>Price details (${t.quantity} item${t.quantity > 1 ? "s" : ""})</h3>
    <div class="price-line"><span>Price</span><span>${inr(t.mrp_total)}</span></div>
    <div class="price-line green"><span>Discount</span><span>− ${inr(t.discount_on_mrp)}</span></div>
    ${t.coupon_discount ? `<div class="price-line green"><span>Coupon (${escapeHtml(t.coupon)})</span><span>− ${inr(t.coupon_discount)}</span></div>` : ""}
    <div class="price-line"><span>Delivery charges</span><span>${t.delivery ? inr(t.delivery) : '<span style="color:var(--ok)">FREE</span>'}</span></div>
    <div class="price-line total"><span>Total payable</span><span>${inr(t.total)}</span></div>
    ${t.you_save ? `<div class="savings">You'll save ${inr(t.you_save)} on this order</div>` : ""}
    ${t.delivery ? `<p class="muted" style="font-size:13px;margin-top:10px">Add ${inr(t.free_delivery_over - (t.subtotal - t.coupon_discount))} more to get free delivery.</p>` : ""}
    <div class="coupon-row"><input type="text" id="coupon-input" placeholder="Coupon code" value="${escapeHtml(coupon)}" aria-label="Coupon code" /><button type="button" class="btn btn-ghost btn-sm" id="coupon-apply">Apply</button></div>
    <p class="coupon-msg" id="coupon-msg" style="color:${t.coupon ? "var(--ok)" : "var(--bad)"}">${escapeHtml(t.coupon_note || "")}</p>
    <p class="muted" style="font-size:12px">Inclusive of all taxes. Try <strong>WELCOME10</strong>.</p>`;
  $("#coupon-apply").addEventListener("click", async () => { coupon = $("#coupon-input").value.trim(); await requote(); });
  $("#coupon-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#coupon-apply").click(); } });
  $("#mb-total").textContent = inr(t.total);
  $("#place-order").textContent = `Place order · ${inr(t.total)}`;
}

async function requote() {
  const f = new FormData(); f.append("quantity", qty); f.append("coupon", coupon);
  const res = await fetch(`/api/checkout/quote/${KIND}/${ITEM_ID}`, { method: "POST", body: f });
  if (res.ok) { sub = await res.json(); if (!sub.coupon) coupon = ""; qty = sub.quantity; $("#q-val").textContent = qty; renderPrice(); renderSummaryLine(); }
}

function renderSummaryLine() {
  $("#summary-line").textContent = `${item.title} · size ${size} · qty ${qty}`;
}

function renderSizes() {
  $("#it-sizes").innerHTML = sizes.map((s) => `<button type="button" class="size-btn${s === size ? " active" : ""}" data-s="${s}">${s}</button>`).join("");
  $$("#it-sizes .size-btn").forEach((b) => b.addEventListener("click", () => { size = b.dataset.s; renderSizes(); renderSummaryLine(); }));
}

function tiles(list, name) {
  return `<div class="tile-row">${list.map(([n, c], i) => `<button type="button" class="tile${i === 0 ? " active" : ""}" data-t="${escapeHtml(n)}"><i style="background:${c || "#cbb89d"}"></i>${escapeHtml(n)}</button>`).join("")}</div>`;
}

function renderPayPane() {
  const pane = $("#pay-pane");
  if (method === "upi") pane.innerHTML = `<p><strong>Pay with a UPI app</strong></p><p class="muted" style="font-size:14px">Pick your app. In a live shop you'd be sent to it to approve the payment.</p>${tiles(UPI_APPS)}`;
  else if (method === "card") pane.innerHTML = `<p><strong>Credit / Debit card</strong></p><p class="muted" style="font-size:14px">In a live shop, a secure card form from the payment provider would appear here. This demo never asks for card details.</p>`;
  else if (method === "netbanking") pane.innerHTML = `<p><strong>Choose your bank</strong></p>${tiles(BANKS.map((b) => [b]))}`;
  else if (method === "wallet") pane.innerHTML = `<p><strong>Pay with a wallet</strong></p>${tiles(WALLETS)}`;
  else pane.innerHTML = `<p><strong>Pay on delivery</strong></p><p class="muted" style="font-size:14px">Pay in cash or by UPI when your order arrives. No extra fee.</p>`;
  $$("#pay-pane .tile").forEach((t) => t.addEventListener("click", () => { $$("#pay-pane .tile").forEach((x) => x.classList.toggle("active", x === t)); }));
}

function renderMobileBar() {
  const bar = $("#mobile-bar");
  const labels = { 1: "Sign in", 2: "Deliver here", 3: "Continue", 4: "Place order" };
  $("#mb-btn").textContent = labels[step];
  bar.style.visibility = item ? "visible" : "hidden";
}
$("#mb-btn").addEventListener("click", () => {
  const target = { 1: "#login-go", 2: "#address-submit", 3: "#summary-continue", 4: "#place-order" }[step];
  const el = $(target); if (el) el.click();
});

// ---------- address ----------
$("#f-state").insertAdjacentHTML("beforeend", STATES.map((s) => `<option>${s}</option>`).join(""));
function fieldErr(name, msg) {
  const input = $(`#address-form [name="${name}"]`);
  const field = input.closest(".field");
  field.classList.toggle("invalid", !!msg);
  field.querySelector(".err").textContent = msg || "";
}
function validateAddress(v) {
  const e = {};
  if (v.name.trim().length < 2) e.name = "Enter your full name";
  if (!/^[6-9]\d{9}$/.test(v.phone.replace(/[\s\-+]/g, "").replace(/^91(?=\d{10}$)/, ""))) e.phone = "Enter a valid 10-digit mobile number";
  if (!/^\d{6}$/.test(v.pincode.trim())) e.pincode = "Enter a 6-digit pincode";
  if (v.address.trim().length < 8) e.address = "Enter house no., building and street";
  if (v.city.trim().length < 2) e.city = "Enter your city";
  if (!v.state) e.state = "Select your state";
  return e;
}
$("#address-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = new FormData(ev.target);
  const v = Object.fromEntries(form.entries());
  const errs = validateAddress(v);
  ["name", "phone", "pincode", "address", "city", "state"].forEach((k) => fieldErr(k, errs[k]));
  if (Object.keys(errs).length) { $(`#address-form [name="${Object.keys(errs)[0]}"]`).focus(); return; }
  form.append("quantity", qty); form.append("coupon", coupon);
  $("#address-submit").disabled = true;
  try {
    const res = await fetch(`/api/checkout/address/${KIND}/${ITEM_ID}`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      const serverErrs = (data.detail && data.detail.errors) || {};
      Object.entries(serverErrs).forEach(([k, m]) => fieldErr(k, m));
      if (!Object.keys(serverErrs).length) toast(typeof data.detail === "string" ? data.detail : "Please check your details");
      return;
    }
    addr = v; eta = data.eta; sub = data.totals;
    $("#address-summary").innerHTML = `<strong>${escapeHtml(v.name)}</strong> · ${escapeHtml(v.address)}, ${escapeHtml(v.city)}, ${escapeHtml(v.state)} - ${escapeHtml(v.pincode)}`;
    $("#it-eta").textContent = `Delivery by ${eta}`;
    renderPrice();
    setStep(3);
  } finally { $("#address-submit").disabled = false; }
});
$("#address-change").addEventListener("click", () => setStep(2));
$("#summary-change").addEventListener("click", () => setStep(3));
$("#login-change").addEventListener("click", async () => { await fetch("/api/logout", { method: "POST" }); await refreshAccountState(); renderLogin(); setStep(1); });

// ---------- summary ----------
$("#q-minus").addEventListener("click", async () => { qty = Math.max(1, qty - 1); await requote(); });
$("#q-plus").addEventListener("click", async () => { qty = Math.min(10, qty + 1); await requote(); });
$("#summary-continue").addEventListener("click", async () => {
  const f = new FormData(); f.append("quantity", qty); f.append("coupon", coupon);
  const res = await fetch(`/api/checkout/payment/${KIND}/${ITEM_ID}`, { method: "POST", body: f });
  if (res.ok) { sub = (await res.json()).totals; renderPrice(); }
  renderSummaryLine();
  renderPayPane();
  setStep(4);
});

// ---------- payment ----------
$$("#pay-tabs .pay-tab").forEach((t) => t.addEventListener("click", () => {
  method = t.dataset.m;
  $$("#pay-tabs .pay-tab").forEach((x) => x.classList.toggle("active", x === t));
  renderPayPane();
}));

$("#place-order").addEventListener("click", async () => {
  const f = new FormData();
  Object.entries(addr).forEach(([k, v]) => f.append(k, v));
  f.append("size", size); f.append("quantity", qty); f.append("coupon", coupon); f.append("payment_method", method);
  const btn = $("#place-order"); btn.disabled = true; btn.textContent = "Placing your order…";
  $("#co-error").textContent = "";
  try {
    const res = await fetch(`/api/checkout/confirm/${KIND}/${ITEM_ID}`, { method: "POST", body: f });
    const data = await res.json();
    if (!res.ok) { $("#co-error").textContent = typeof data.detail === "string" ? data.detail : "Please check your details and try again."; return; }
    showSuccess(data);
  } catch { $("#co-error").textContent = "Network problem — please try again."; }
  finally { btn.disabled = false; renderPrice(); }
});

function showSuccess(o) {
  $("#co-root").classList.add("hidden");
  const root = $("#success-root");
  root.classList.remove("hidden");
  const t = o.totals;
  root.innerHTML = `
    <div class="tick">✓</div>
    <h1>Order placed</h1>
    <p class="muted" style="margin-top:6px">Thanks, ${escapeHtml(o.name)}. Your order <strong>${o.order_id}</strong> is confirmed (demo — nothing was charged).</p>
    <div class="co-card order-box"><div class="co-body">
      <div class="item-row"><img src="${o.image}" alt="" /><div><h4>${escapeHtml(o.title)}</h4><p class="muted">${escapeHtml(o.subtitle)} · size ${o.size} · qty ${o.quantity}</p><p class="delivery-eta">Arriving by ${escapeHtml(o.eta)}</p></div></div>
      <hr style="border:0;border-top:1px solid var(--line);margin:16px 0" />
      <div class="price-line"><span>Paid via</span><span>${escapeHtml(o.payment_method)} (demo)</span></div>
      <div class="price-line"><span>Ship to</span><span style="text-align:right;max-width:60%">${escapeHtml(o.address_line)}</span></div>
      <div class="price-line total"><span>Total</span><span>${inr(t.total)}</span></div>
    </div></div>
    <div class="stack" style="margin-top:20px;align-items:center"><a class="btn btn-dark" href="/shop">Continue shopping</a><button type="button" class="link-btn" data-open-assistant data-prompt="Where is my order?">Need help with this order?</button></div>`;
  $$("[data-open-assistant]", root).forEach((b) => b.addEventListener("click", () => openAssistant(b.dataset.prompt)));
  window.scrollTo({ top: 0 });
}

// ---------- boot ----------
async function boot() {
  renderLogin();
  if (!currentUser) { setStep(1); $("#price-body").innerHTML = `<p class="muted">Sign in to see your order.</p>`; return; }
  const res = await fetch(`/api/checkout/item/${KIND}/${ITEM_ID}`);
  if (!res.ok) {
    $("#co-root").innerHTML = `<div class="success"><h1>We couldn't find that item</h1><p class="muted" style="margin:10px 0 20px">It may have sold out or been removed.</p><a class="btn btn-dark" href="/shop">Back to the shop</a></div>`;
    return;
  }
  item = await res.json();
  sizes = item.sizes;
  if (item.stock.state === "out") {
    $("#co-root").innerHTML = `<div class="success"><h1>Sold out</h1><p class="muted" style="margin:10px 0 20px">${escapeHtml(item.title)} isn't available right now.</p><a class="btn btn-dark" href="/shop">Back to the shop</a></div>`;
    return;
  }
  $("#it-img").src = item.image; $("#it-title").textContent = item.title; $("#it-sub").textContent = item.subtitle;
  $("#q-val").textContent = qty;
  renderSizes();
  const f = new FormData(); f.append("quantity", qty); f.append("coupon", "");
  sub = await (await fetch(`/api/checkout/quote/${KIND}/${ITEM_ID}`, { method: "POST", body: f })).json();
  renderPrice();
  if (!$("#f-name").value) $("#f-name").value = "";
  setStep(2);
}

window.onAccountReady = () => boot();
window.onSignedOut = () => { renderLogin(); setStep(1); };
