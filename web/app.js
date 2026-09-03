const cfg = window.BLINQ_CONFIG || {};
const state = { predictions: [], ui: null, user: null, adminUser: null };
const $ = (id) => document.getElementById(id);
const api = (path) => `${String(cfg.apiBase || "").replace(/\/$/, "")}${path}`;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
}

function confidenceBand(probabilityPct) {
  const p = Number(probabilityPct || 0);
  if (p >= 80) return "elite";
  if (p >= 70) return "high";
  if (p >= 60) return "medium";
  return "low";
}

function fmtPct(value) { return `${Number(value || 0).toFixed(1)}%`; }
function fmtTime(value) {
  if (!value) return "TBA";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "TBA";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(d);
}
function fmtToday() {
  return new Intl.DateTimeFormat(undefined, { weekday: "long", day: "2-digit", month: "short", year: "numeric" }).format(new Date());
}
function initials(name) {
  return String(name || "?").trim().split(/\s+/).slice(0, 2).map((x) => x[0] || "").join("").toUpperCase();
}

async function getJSON(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

async function loadUiConfig() {
  try {
    state.ui = await getJSON(cfg.uiConfigPath || "ui-config.json");
  } catch {
    state.ui = { navigation: { main: [], learn: [] }, panels: {}, banners: {} };
  }
  renderNavigation();
  applyPanelConfig();
  renderBanners();
}

function renderNavigationGroup(items, containerId) {
  const host = $(containerId);
  host.innerHTML = "";
  [...(items || [])]
    .filter((item) => item.enabled !== false && (!item.admin_only || isAdminSession()))
    .sort((a, b) => Number(a.order || 0) - Number(b.order || 0))
    .forEach((item, index) => {
      const a = document.createElement("a");
      a.href = item.href || "#";
      a.className = `nav-link${containerId === "mainNavigation" && index === 0 ? " active" : ""}`;
      a.dataset.route = item.id || "";
      a.innerHTML = `<span class="nav-icon">${escapeHtml(item.icon || "•")}</span><span>${escapeHtml(item.label || item.id)}</span>`;
      host.appendChild(a);
    });
}

function renderNavigation() {
  renderNavigationGroup(state.ui?.navigation?.main, "mainNavigation");
  renderNavigationGroup(state.ui?.navigation?.learn, "learnNavigation");
}

function applyPanelConfig() {
  const panels = state.ui?.panels || {};
  Object.entries(panels).forEach(([id, panel]) => {
    const node = $(id);
    if (node) node.hidden = panel?.enabled === false;
  });
}

function renderBanners() {
  const banners = state.ui?.banners || {};
  Object.values(banners).forEach((banner) => {
    const host = $(banner.target);
    if (!host) return;
    if (banner.enabled === false) { host.hidden = true; host.innerHTML = ""; return; }
    host.hidden = false;
    const hasImage = Boolean(String(banner.image || "").trim());
    host.innerHTML = `
      <a class="promo-banner${hasImage ? " has-image" : ""}" href="${escapeHtml(banner.link || "#")}" target="${escapeHtml(banner.link_target || "_self")}" ${banner.link_target === "_blank" ? 'rel="noopener noreferrer"' : ""}>
        ${hasImage ? `<img src="${escapeHtml(banner.image)}" alt="${escapeHtml(banner.headline || "BlinQ banner")}" />` : ""}
        <div class="promo-overlay"></div>
        <div class="promo-copy">
          <span class="promo-eyebrow">${escapeHtml(banner.sponsored ? "Sponsored" : (banner.eyebrow || "BlinQ"))}</span>
          <strong>${escapeHtml(banner.headline || "")}</strong>
          <p>${escapeHtml(banner.text || "")}</p>
        </div>
        <span class="promo-cta">${escapeHtml(banner.button_text || "Open")} →</span>
      </a>`;
  });
}

function loadPreviewSession() {
  try { return JSON.parse(localStorage.getItem("blinq_preview_session") || "null"); } catch { return null; }
}
function savePreviewSession(user) { localStorage.setItem("blinq_preview_session", JSON.stringify(user)); }

function setAuthView(view) {
  const map = { signin: "signInView", register: "registerView", forgot: "forgotView" };

  // Keep the email the user already typed when switching between auth screens.
  const email = String(
    $("emailInput")?.value || $("registerEmailInput")?.value || $("forgotEmailInput")?.value || ""
  ).trim();

  Object.values(map).forEach((id) => {
    const node = $(id);
    if (node) node.hidden = id !== map[view];
  });

  if (email) {
    if ($("emailInput")) $("emailInput").value = email;
    if ($("registerEmailInput")) $("registerEmailInput").value = email;
    if ($("forgotEmailInput")) $("forgotEmailInput").value = email;
  }

  const msg = $("authMessage");
  if (msg) {
    msg.hidden = true;
    msg.textContent = "";
    msg.classList.remove("error", "success");
  }
}
function authMessage(message, type = "success") {
  const node = $("authMessage");
  if (!node) return;
  node.textContent = message;
  node.className = `auth-message ${type}`;
  node.hidden = false;
}
function normalizeTelegram(value) {
  const clean = String(value || "").trim().replace(/^@+/, "");
  return clean ? `@${clean}` : "";
}

function startSession(user) {
  state.user = { ...user, role: user.role || (cfg.authMode === "preview" && cfg.previewAdmin ? "admin" : "user") };
  seedPreviewAdminUser();
  renderNavigation();
  $("loginScreen").hidden = true;
  $("appShell").hidden = false;
  $("profileName").textContent = user.name || user.email || "BlinQ User";
  $("profilePlan").textContent = "Free Trial";
  $("avatar").textContent = initials(user.name || user.email || "BlinQ");
  $("todayLabel").textContent = fmtToday();
  updateTrialTimer();
  loadPredictions();
}

function updateTrialTimer() {
  const started = Number(state.user?.startedAt || Date.now());
  const remainingMs = Math.max(0, (24 * 60 * 60 * 1000) - (Date.now() - started));
  const hours = Math.floor(remainingMs / 3600000);
  const minutes = Math.floor((remainingMs % 3600000) / 60000);
  $("trialRemaining").textContent = `${hours}h ${String(minutes).padStart(2, "0")}m left`;
}

function normalizePrediction(raw) {
  if (raw?.prediction && raw?.player1 && raw?.player2) {
    const pickPct = Number(raw.prediction.probability_pct ?? Math.max(raw.player1.win_probability_pct || 0, raw.player2.win_probability_pct || 0));
    return {
      id: raw.id || raw.match_id,
      date: raw.scheduled_at,
      tour: String(raw.tour || "").toUpperCase(),
      tournament: raw.tournament || "Tournament",
      surface: raw.surface || "unknown",
      round: raw.round || "",
      p1: raw.player1.name,
      p2: raw.player2.name,
      p1Id: raw.player1.id,
      p2Id: raw.player2.id,
      p1Rank: raw.player1.rank,
      p2Rank: raw.player2.rank,
      p1Prob: Number(raw.player1.win_probability_pct || 0),
      p2Prob: Number(raw.player2.win_probability_pct || 0),
      pick: raw.prediction.winner_name,
      pickId: raw.prediction.winner_id,
      probability: pickPct,
      confidence: confidenceBand(pickPct),
      signals: raw.prediction.signals || [],
      model: raw.model_version || ""
    };
  }

  const p1Prob = Number(raw.p1_prob || 0);
  const p2Prob = Number(raw.p2_prob || 0);
  const probability = Number(raw.probability || Math.max(p1Prob, p2Prob));
  return {
    id: raw.id || raw.match_id,
    date: raw.date || raw.scheduled_at,
    tour: String(raw.tour || "").toUpperCase(),
    tournament: raw.tournament || "Tournament",
    surface: raw.surface || "unknown",
    round: raw.round || "",
    p1: raw.p1 || raw.player1_name || "Player 1",
    p2: raw.p2 || raw.player2_name || "Player 2",
    p1Id: raw.p1_id,
    p2Id: raw.p2_id,
    p1Rank: raw.p1_rank,
    p2Rank: raw.p2_rank,
    p1Prob,
    p2Prob,
    pick: raw.pick || (p1Prob >= p2Prob ? raw.p1 : raw.p2),
    pickId: raw.pick_id,
    probability,
    confidence: confidenceBand(probability),
    signals: raw.signals || [],
    model: raw.model || raw.model_version || ""
  };
}

async function fetchPredictions() {
  const days = Number(cfg.predictionsDays || 3);
  try {
    const v = await getJSON(api(`/api/blinq/predictions?days=${days}`));
    const rows = Array.isArray(v?.data) ? v.data : Array.isArray(v?.matches) ? v.matches : [];
    if (rows.length) return { rows, updatedAt: v.updated_at || v.generated_at || null };
  } catch (_) {}

  const v = await getJSON(api(`/api/v1/predictions/upcoming?days=${days}`));
  return { rows: Array.isArray(v?.matches) ? v.matches : [], updatedAt: v.updated_at || v.generated_at || null };
}

async function loadPredictions() {
  const grid = $("predictionGrid");
  grid.innerHTML = '<div class="state-card">Loading current model predictions…</div>';
  try {
    const result = await fetchPredictions();
    state.predictions = result.rows.map(normalizePrediction);
    populateFilterOptions();
    renderPredictions();
    $("updatedAt").textContent = result.updatedAt ? fmtTime(result.updatedAt) : new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
  } catch (error) {
    state.predictions = [];
    grid.innerHTML = `<div class="state-card error">Predictions API is unavailable.<small>${escapeHtml(error.message)}</small></div>`;
    $("matchCount").textContent = "0";
  }
}

function populateSelect(id, values, firstLabel) {
  const select = $(id);
  const selected = select.value;
  select.innerHTML = `<option value="">${firstLabel}</option>`;
  [...values].filter(Boolean).sort().forEach((value) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value.replaceAll("_", " ");
    select.appendChild(opt);
  });
  if ([...select.options].some((o) => o.value === selected)) select.value = selected;
}
function populateFilterOptions() {
  populateSelect("tournamentFilter", new Set(state.predictions.map((x) => x.tournament)), "All Tournaments");
  populateSelect("surfaceFilter", new Set(state.predictions.map((x) => x.surface)), "All Surfaces");
}

function currentFilteredPredictions() {
  const tour = $("tourFilter").value;
  const tournament = $("tournamentFilter").value;
  const surface = $("surfaceFilter").value;
  const confidence = $("confidenceFilter").value;
  const q = $("searchInput").value.trim().toLowerCase();
  return state.predictions.filter((m) => {
    if (tour && m.tour !== tour) return false;
    if (tournament && m.tournament !== tournament) return false;
    if (surface && m.surface !== surface) return false;
    if (confidence && m.confidence !== confidence) return false;
    if (q && !`${m.p1} ${m.p2} ${m.tournament}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderSignal(signal, pickId) {
  const favoursPick = String(signal.favours_player_id ?? "") === String(pickId ?? "");
  return `<div class="signal-row"><span>${escapeHtml(signal.factor || "Signal")}</span><div class="signal-meter"><i class="${favoursPick ? "positive" : "counter"}"></i><i class="${favoursPick ? "positive" : "counter"}"></i><i class="${signal.strength === "strong" ? (favoursPick ? "positive" : "counter") : ""}"></i><i></i><i></i></div></div>`;
}

function renderPrediction(match) {
  const frag = $("predictionTemplate").content.cloneNode(true);
  const card = frag.querySelector(".prediction-card");
  card.querySelector(".tour").textContent = `${match.tour || "TOUR"} ${match.tournament || ""}${match.round ? ` · ${match.round}` : ""}`;
  card.querySelector(".time").textContent = fmtTime(match.date);
  card.querySelector(".surface").textContent = String(match.surface || "unknown").replaceAll("_", " ").toUpperCase();

  [[".player-a", match.p1, match.p1Rank], [".player-b", match.p2, match.p2Rank]].forEach(([selector, name, rank]) => {
    const player = card.querySelector(selector);
    player.querySelector(".player-avatar").textContent = initials(name);
    player.querySelector(".player-name").textContent = name;
    player.querySelector(".player-rank").textContent = rank ? `#${rank}` : "";
  });

  card.querySelector(".pick-name").textContent = match.pick || "—";
  card.querySelector(".probability").textContent = fmtPct(match.probability);
  const badge = card.querySelector(".confidence");
  badge.textContent = match.confidence.toUpperCase();
  badge.classList.add(match.confidence);

  const signals = card.querySelector(".signals");
  const topSignals = (match.signals || []).slice(0, 4);
  signals.innerHTML = topSignals.length ? topSignals.map((s) => renderSignal(s, match.pickId)).join("") : '<div class="signal-empty">No strong secondary signal.</div>';

  card.querySelector(".analysis-link").addEventListener("click", () => openMatchDialog(match));
  return frag;
}

function renderPredictions() {
  const rows = currentFilteredPredictions();
  const grid = $("predictionGrid");
  grid.innerHTML = "";
  rows.slice(0, 24).forEach((match) => grid.appendChild(renderPrediction(match)));
  if (!rows.length) grid.innerHTML = '<div class="state-card">No current prediction matches these filters.</div>';
  $("matchCount").textContent = String(rows.length);
}

function openMatchDialog(match) {
  const content = $("dialogContent");
  content.innerHTML = `
    <div class="dialog-eyebrow">${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}</div>
    <h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2>
    <div class="dialog-pick"><div><small>BlinQ prediction</small><strong>${escapeHtml(match.pick)}</strong></div><div class="dialog-prob">${fmtPct(match.probability)}<span class="confidence ${match.confidence}">${match.confidence.toUpperCase()}</span></div></div>
    <div class="dialog-section"><h3>Why BlinQ favours this pick</h3>${(match.signals || []).slice(0, 5).map((s) => `<div class="dialog-signal"><span>${escapeHtml(s.factor)}</span><strong>${escapeHtml(s.strength || "signal")}</strong><small>${escapeHtml(s.favours_player_name || "")}</small></div>`).join("") || '<p>No strong secondary signal is available.</p>'}</div>
    <div class="dialog-meta"><span>Surface: ${escapeHtml(match.surface)}</span><span>Time: ${escapeHtml(fmtTime(match.date))}</span><span>Model: ${escapeHtml(match.model || "current")}</span></div>`;
  $("matchDialog").showModal();
}


function isAdminSession() {
  return Boolean(state.user?.role === "admin" || (cfg.authMode === "preview" && cfg.previewAdmin === true));
}

function previewAdminUsers() {
  try { return JSON.parse(localStorage.getItem("blinq_preview_admin_users") || "[]"); } catch { return []; }
}
function savePreviewAdminUsers(rows) { localStorage.setItem("blinq_preview_admin_users", JSON.stringify(rows)); }
function previewAccessHistory() {
  try { return JSON.parse(localStorage.getItem("blinq_preview_access_history") || "[]"); } catch { return []; }
}
function savePreviewAccessHistory(rows) { localStorage.setItem("blinq_preview_access_history", JSON.stringify(rows)); }

function seedPreviewAdminUser() {
  if (cfg.authMode !== "preview" || !state.user) return;
  const rows = previewAdminUsers();
  const email = String(state.user.email || "").toLowerCase();
  if (!email || rows.some((x) => String(x.email || "").toLowerCase() === email)) return;
  rows.push({
    user_id: `preview-${btoa(email).replace(/=+$/g, "").slice(0, 18)}`,
    email,
    telegram_nick: "@preview_user",
    display_name: state.user.name || "BlinQ User",
    role: "admin",
    plan: "trial",
    status: "active",
    access_started_at: new Date(state.user.startedAt || Date.now()).toISOString(),
    access_ends_at: new Date((state.user.startedAt || Date.now()) + 24*3600*1000).toISOString(),
    lifetime_access: false,
    payment_reference: "",
    admin_note: "Preview account"
  });
  savePreviewAdminUsers(rows);
}

function planDurationMs(plan) {
  return ({ trial: 24*3600e3, pro: 30*86400e3, elite: 90*86400e3, legend: 365*86400e3 })[plan] || 0;
}
function effectiveStatus(user) {
  const status = String(user?.status || "locked").toLowerCase();
  if (["banned","suspended","locked"].includes(status)) return status;
  if (user?.lifetime_access || user?.plan === "goat") return "active";
  const end = new Date(user?.access_ends_at || 0).getTime();
  return end > Date.now() ? "active" : "locked";
}
function remainingLabel(user) {
  if (user?.lifetime_access || user?.plan === "goat") return "Lifetime access";
  const ms = new Date(user?.access_ends_at || 0).getTime() - Date.now();
  if (ms <= 0) return "Access expired";
  const days = Math.floor(ms / 86400e3);
  const hours = Math.floor((ms % 86400e3) / 3600e3);
  return days ? `${days}d ${hours}h remaining` : `${hours}h remaining`;
}
function showAdminToast(message, isError=false) {
  document.querySelector(".admin-toast")?.remove();
  const node=document.createElement("div");
  node.className=`admin-toast${isError ? " error" : ""}`;
  node.textContent=message;
  document.body.appendChild(node);
  setTimeout(()=>node.remove(),2600);
}
function renderAdminHistory(userId) {
  const host=$("adminHistoryList");
  const rows=previewAccessHistory().filter((x)=>x.user_id===userId).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
  host.innerHTML=rows.length ? rows.map((x)=>`<div class="admin-history-row"><span>${escapeHtml(new Date(x.created_at).toLocaleString())}</span><strong>${escapeHtml(String(x.plan||x.action||"").toUpperCase())}</strong><span>${escapeHtml(x.detail||"")}</span></div>`).join("") : '<div class="admin-history-empty">No access changes recorded yet.</div>';
}
function renderAdminUser(user) {
  state.adminUser={...user};
  $("adminEmptyState").hidden=true;
  $("adminUserEditor").hidden=false;
  $("adminUserAvatar").textContent=initials(user.display_name || user.email);
  $("adminUserEmail").textContent=user.email || "—";
  $("adminUserTelegram").textContent=user.telegram_nick || "No Telegram nick";
  $("adminUserId").textContent=user.user_id || "—";
  $("adminCurrentPlan").textContent=String(user.plan || "trial").toUpperCase();
  $("adminEffectiveStatus").textContent=effectiveStatus(user).toUpperCase();
  $("adminAccessRemaining").textContent=remainingLabel(user);
  $("adminPlan").value=user.plan || "trial";
  $("adminStatus").value=user.status || "active";
  $("adminTelegramNick").value=user.telegram_nick || "";
  $("adminPaymentReference").value=user.payment_reference || "";
  $("adminNote").value=user.admin_note || "";
  renderAdminHistory(user.user_id);
}
function adminFindUser() {
  if (!isAdminSession()) return showAdminToast("Admin access required.", true);
  seedPreviewAdminUser();
  const q=$("adminUserSearch").value.trim().toLowerCase().replace(/^@/,"");
  if (!q) return showAdminToast("Enter email, Telegram nick or user ID.", true);
  const row=previewAdminUsers().find((u)=>
    String(u.email||"").toLowerCase().includes(q) ||
    String(u.telegram_nick||"").toLowerCase().replace(/^@/,"").includes(q) ||
    String(u.user_id||"").toLowerCase().includes(q)
  );
  if (!row) {
    $("adminUserEditor").hidden=true;
    $("adminEmptyState").hidden=false;
    $("adminEmptyState").textContent="No matching preview account found.";
    return;
  }
  renderAdminUser(row);
}
function applyPreviewPlan(plan, mode="reset") {
  if (!state.adminUser) return;
  const rows=previewAdminUsers();
  const index=rows.findIndex((x)=>x.user_id===state.adminUser.user_id);
  if (index<0) return;
  const now=Date.now();
  const duration=planDurationMs(plan);
  const currentEnd=new Date(rows[index].access_ends_at || 0).getTime();
  const startBase=mode === "extend" && currentEnd > now ? currentEnd : now;
  rows[index].plan=plan;
  rows[index].status="active";
  rows[index].access_started_at=new Date(now).toISOString();
  rows[index].lifetime_access=plan === "goat";
  rows[index].access_ends_at=plan === "goat" ? null : new Date(startBase + duration).toISOString();
  rows[index].telegram_nick=$("adminTelegramNick").value.trim();
  rows[index].payment_reference=$("adminPaymentReference").value.trim();
  rows[index].admin_note=$("adminNote").value.trim();
  savePreviewAdminUsers(rows);
  const hist=previewAccessHistory();
  hist.push({user_id:rows[index].user_id,created_at:new Date().toISOString(),plan,action:mode,detail:`${mode === "extend" ? "Extended" : "Activated"} ${plan.toUpperCase()}${rows[index].payment_reference ? ` · payment ${rows[index].payment_reference}` : ""}`});
  savePreviewAccessHistory(hist);
  renderAdminUser(rows[index]);
  showAdminToast(`${plan.toUpperCase()} access applied in preview mode.`);
}
function saveAdminUserPreview() {
  if (!state.adminUser) return showAdminToast("Find a user first.", true);
  if (cfg.authMode !== "preview") return showAdminToast("Supabase admin RPC will be connected with production auth.", true);
  const plan=$("adminPlan").value;
  const status=$("adminStatus").value;
  if (status === "active") return applyPreviewPlan(plan, $("adminActivationMode").value);
  const rows=previewAdminUsers();
  const index=rows.findIndex((x)=>x.user_id===state.adminUser.user_id);
  if (index<0) return;
  rows[index].status=status;
  rows[index].telegram_nick=$("adminTelegramNick").value.trim();
  rows[index].payment_reference=$("adminPaymentReference").value.trim();
  rows[index].admin_note=$("adminNote").value.trim();
  savePreviewAdminUsers(rows);
  const hist=previewAccessHistory();
  hist.push({user_id:rows[index].user_id,created_at:new Date().toISOString(),action:status,detail:`Account status changed to ${status.toUpperCase()}`});
  savePreviewAccessHistory(hist);
  renderAdminUser(rows[index]);
  showAdminToast(`Account status changed to ${status.toUpperCase()}.`);
}
function showMainModule(route) {
  const isAdmin = route === "admin_users";
  $("adminUsersPanel").hidden = !isAdmin;
  $("predictionToolbar").hidden = isAdmin || state.ui?.panels?.predictionToolbar?.enabled === false;
  $("predictionsPanel").hidden = isAdmin || state.ui?.panels?.predictionsPanel?.enabled === false;
  $("howBlinqWorks").hidden = isAdmin || state.ui?.panels?.howBlinqWorks?.enabled === false;
  $("bannerTop").hidden = isAdmin || !state.ui?.banners?.home_banner_top?.enabled;
  $("bannerMiddle").hidden = isAdmin || !state.ui?.banners?.home_banner_middle?.enabled;
  $("bannerBottom").hidden = isAdmin || !state.ui?.banners?.home_banner_bottom?.enabled;
  if (isAdmin) {
    $("pageEyebrow").textContent="BLINQ ADMIN";
    $("pageTitle").textContent="Account Management";
    $("pageSubtitle").textContent="Manage manual payments, tiers and time-based access.";
    $("adminModeNote").textContent = cfg.authMode === "preview" ? "Preview mode: UI changes are stored only in this browser. Run the included Supabase migration and connect production auth before using this for real accounts." : "Changes are protected by the admin role.";
  } else {
    $("pageEyebrow").textContent="PRE-MATCH ANALYTICS";
    if (route === "predictions") {
      $("pageTitle").textContent="Today's Predictions";
      $("pageSubtitle").textContent="Real model output from the currently available data.";
    }
  }
}

function setupEvents() {
  document.querySelectorAll("[data-auth-view]").forEach((button) => button.addEventListener("click", () => setAuthView(button.dataset.authView)));

  $("loginForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const email = $("emailInput").value.trim();
    const user = { email, name: email.split("@")[0] || "BlinQ User", startedAt: Date.now() };
    savePreviewSession(user);
    startSession(user);
  });

  $("registerForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const telegram = normalizeTelegram($("telegramInput").value);
    const email = $("registerEmailInput").value.trim();
    const password = $("registerPasswordInput").value;
    const repeat = $("registerPasswordRepeatInput").value;
    if (password !== repeat) return authMessage("Passwords do not match.", "error");
    if (password.length < 8) return authMessage("Password must contain at least 8 characters.", "error");
    const pending = { email, telegram_nick: telegram, created_at: new Date().toISOString() };
    localStorage.setItem("blinq_preview_pending_registration", JSON.stringify(pending));
    authMessage("Preview registration accepted. No email is sent in preview mode yet. Email verification will be enabled when Supabase Auth + Brevo is connected.");
  });

  $("forgotForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const email = $("forgotEmailInput").value.trim();
    authMessage(`Preview only: reset request prepared for ${email}. No reset email is sent until production auth is connected.`);
  });
  $("refreshButton").addEventListener("click", loadPredictions);
  ["tourFilter", "tournamentFilter", "surfaceFilter", "confidenceFilter"].forEach((id) => $(id).addEventListener("change", renderPredictions));
  $("searchInput").addEventListener("input", renderPredictions);
  $("dialogClose").addEventListener("click", () => $("matchDialog").close());
  $("matchDialog").addEventListener("click", (event) => { if (event.target === $("matchDialog")) $("matchDialog").close(); });
  $("adminFindUser").addEventListener("click", adminFindUser);
  $("adminUserSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); adminFindUser(); } });
  $("adminSaveUser").addEventListener("click", saveAdminUserPreview);
  $("adminLockUser").addEventListener("click", () => { if (!state.adminUser) return; $("adminStatus").value = "locked"; saveAdminUserPreview(); });
  document.querySelectorAll("[data-plan-action]").forEach((button) => button.addEventListener("click", () => { if (!state.adminUser) return showAdminToast("Find a user first.", true); $("adminPlan").value=button.dataset.planAction; $("adminStatus").value="active"; $("adminActivationMode").value="extend"; applyPreviewPlan(button.dataset.planAction, "extend"); }));
  document.addEventListener("click", (event) => {
    const route = event.target.closest("[data-route]")?.dataset.route;
    if (!route) return;
    event.preventDefault();
    document.querySelectorAll(".nav-link").forEach((x) => x.classList.toggle("active", x.dataset.route === route));
    showMainModule(route);
    if (!["predictions","admin_users"].includes(route)) {
      $("pageTitle").textContent = route === "account" ? "Account" : route.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
      $("pageSubtitle").textContent = "This module is prepared in navigation and can be connected next.";
    }
  });
}

async function boot() {
  setupEvents();
  await loadUiConfig();
  const session = loadPreviewSession();
  if (session) startSession(session);
  else {
    $("loginScreen").hidden = false;
    $("appShell").hidden = true;
  }
  setInterval(updateTrialTimer, 60 * 1000);
  setInterval(() => { if (state.user) loadPredictions(); }, Math.max(1, Number(cfg.refreshMinutes || 5)) * 60 * 1000);
}

boot();
