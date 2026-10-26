// "Print your own" studio.
const HEX = { white: "#f5f5f5", black: "#18181a", "heather-gray": "#969696", beige: "#d8c3a0", sage: "#a3b18a" };
let options = null, garment = "tshirt", color = "white", current = null, mode = "upload", view = "flat";

const err = (m) => { $("#studio-error").textContent = m || ""; };

async function api(url, form, method = "POST") {
  const res = await fetch(url, { method, body: form });
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong");
  return data;
}

function renderOptions() {
  const g = options.garments.find((x) => x.key === garment) || options.garments[0];
  garment = g.key;
  if (!g.colors.some((c) => c.key === color)) color = g.colors[0].key;
  $("#garment-opts").innerHTML = options.garments.map((x) =>
    `<button type="button" class="swatch${x.key === garment ? " active" : ""}" data-g="${x.key}">${escapeHtml(x.label)}</button>`).join("");
  $("#color-opts").innerHTML = g.colors.map((c) =>
    `<button type="button" class="swatch${c.key === color ? " active" : ""}" data-c="${c.key}"><i style="background:${HEX[c.key] || "#ccc"}"></i>${escapeHtml(c.label)}</button>`).join("");
  $$("#garment-opts .swatch").forEach((b) => b.addEventListener("click", () => { garment = b.dataset.g; renderOptions(); restyle(); }));
  $$("#color-opts .swatch").forEach((b) => b.addEventListener("click", () => { color = b.dataset.c; renderOptions(); restyle(); }));
}

function setLoading(text) {
  $("#preview-loading").classList.toggle("hidden", !text);
  if (text) $("#preview-loading-text").textContent = text;
}

function showCurrent() {
  const has = !!current;
  $("#preview-empty").hidden = has;
  $("#preview-img").hidden = !has;
  $("#preview-tabs").classList.toggle("hidden", !has);
  $("#order-btn").disabled = !has;
  $("#photo-btn").classList.toggle("hidden", !has);
  if (!has) return;
  $("#photo-btn").textContent = current.has_photo ? "Regenerate AI photo" : "Generate a realistic AI photo";
  $('[data-view="photo"]').classList.toggle("hidden", !current.has_photo);
  const bust = Date.now();
  const url = view === "photo" && current.photo_url ? current.photo_url
    : view === "model" ? `${current.preview_url}?slot=model&t=${bust}` : `${current.preview_url}?slot=front&t=${bust}`;
  setLoading("Rendering preview…");
  const img = $("#preview-img");
  img.onload = () => setLoading(null);
  img.onerror = () => { setLoading(null); err("Couldn't render the preview — your artwork is saved though."); };
  img.src = url;
  $("#preview-title").textContent = `Your custom ${current.garment_label}`;
  $("#preview-sub").textContent = `${current.color_label} · ${current.source === "ai" ? "AI artwork" : "your upload"}`;
  $("#preview-price").textContent = inr(current.price_inr);
  $$("#preview-tabs .fchip").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
}

async function restyle() {
  if (!current) return;
  const f = new FormData(); f.append("garment", garment); f.append("color", color);
  try { current = await api(`/api/studio/design/${current.id}/restyle`, f); view = "flat"; showCurrent(); loadMine(); }
  catch (e) { err(e.message); }
}

async function loadMine() {
  if (!currentUser) return;
  try {
    const rows = await (await fetch("/api/studio/mine")).json();
    $("#mine-panel").classList.toggle("hidden", !rows.length);
    $("#mine-grid").innerHTML = rows.map((r) =>
      `<button type="button" data-id="${r.id}" class="${current && current.id === r.id ? "active" : ""}" aria-label="Open design ${r.id}"><img src="${r.art_url}" alt="" loading="lazy" /></button>`).join("");
    $$("#mine-grid button").forEach((b) => b.addEventListener("click", () => {
      const row = rows.find((r) => r.id === Number(b.dataset.id));
      current = row; garment = row.garment; color = row.color; view = "flat";
      renderOptions(); showCurrent(); loadMine();
    }));
  } catch {}
}

// mode switch
function setMode(m) {
  mode = m;
  $("#mode-upload").classList.toggle("active", m === "upload");
  $("#mode-ai").classList.toggle("active", m === "ai");
  $("#upload-form").classList.toggle("hidden", m !== "upload");
  $("#ai-form").classList.toggle("hidden", m !== "ai");
  err("");
}
$("#mode-upload").addEventListener("click", () => setMode("upload"));
$("#mode-ai").addEventListener("click", () => setMode("ai"));

// upload
const artFile = $("#art-file");
artFile.addEventListener("change", () => {
  const f = artFile.files[0];
  $("#art-label").textContent = f ? f.name : "Drop your image here, or click to choose";
  $("#upload-btn").disabled = !f;
});
const dz = $("#art-dropzone");
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) { artFile.files = e.dataTransfer.files; artFile.dispatchEvent(new Event("change")); } });

$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  err("");
  if (!(await requireLogin())) return;
  const f = artFile.files[0]; if (!f) return;
  const form = new FormData(); form.append("garment", garment); form.append("color", color); form.append("file", f);
  $("#upload-btn").disabled = true;
  try { setLoading("Uploading…"); current = await api("/api/studio/upload", form); view = "flat"; showCurrent(); loadMine(); }
  catch (ex) { setLoading(null); err(ex.message); }
  finally { $("#upload-btn").disabled = false; }
});

$("#ai-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  err("");
  if (!(await requireLogin())) return;
  const prompt = $("#ai-prompt").value.trim();
  if (prompt.length < 4) { err("Describe your design in a few words."); return; }
  const form = new FormData(); form.append("garment", garment); form.append("color", color); form.append("prompt", prompt);
  $("#ai-btn").disabled = true;
  try { setLoading("Drawing your design… this takes about 30 seconds"); current = await api("/api/studio/generate", form); view = "flat"; showCurrent(); loadMine(); }
  catch (ex) { setLoading(null); err(ex.message); }
  finally { $("#ai-btn").disabled = false; }
});

// preview tabs, photo, order
$$("#preview-tabs .fchip").forEach((b) => b.addEventListener("click", () => { view = b.dataset.view; showCurrent(); }));
$("#photo-btn").addEventListener("click", async () => {
  if (!current) return;
  err("");
  $("#photo-btn").disabled = true;
  try { setLoading("Photographing it on a model… about 40 seconds"); current = await api(`/api/studio/design/${current.id}/photo`, new FormData()); view = "photo"; showCurrent(); }
  catch (ex) { setLoading(null); err(ex.message); }
  finally { $("#photo-btn").disabled = false; }
});
$("#order-btn").addEventListener("click", () => { if (current) location.href = `/checkout/custom/${current.id}?size=M&qty=1`; });

window.onAccountReady = () => loadMine();
window.onSignedOut = () => { $("#mine-panel").classList.add("hidden"); };

(async function init() {
  options = await (await fetch("/api/studio/options")).json();
  $("#ai-limit").textContent = options.ai_limit_per_day;
  renderOptions();
  showCurrent();
})();
