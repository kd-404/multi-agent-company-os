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
    document.getElementById("admin-panel").classList.remove("hidden");
    loadUsers();
  }

  loadChatHistory();
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
