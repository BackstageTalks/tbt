const cfg = window.BLINQ_CONFIG || {};
const state = { predictions: [], ui: null, user: null };
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
    .filter((item) => item.enabled !== false)
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

function startSession(user) {
  state.user = user;
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

function setupEvents() {
  $("loginForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const user = { email: $("emailInput").value.trim(), name: $("nameInput").value.trim(), startedAt: Date.now() };
    savePreviewSession(user);
    startSession(user);
  });
  $("refreshButton").addEventListener("click", loadPredictions);
  ["tourFilter", "tournamentFilter", "surfaceFilter", "confidenceFilter"].forEach((id) => $(id).addEventListener("change", renderPredictions));
  $("searchInput").addEventListener("input", renderPredictions);
  $("dialogClose").addEventListener("click", () => $("matchDialog").close());
  $("matchDialog").addEventListener("click", (event) => { if (event.target === $("matchDialog")) $("matchDialog").close(); });
  document.addEventListener("click", (event) => {
    const route = event.target.closest("[data-route]")?.dataset.route;
    if (!route) return;
    if (route !== "predictions") {
      event.preventDefault();
      document.querySelectorAll(".nav-link").forEach((x) => x.classList.toggle("active", x.dataset.route === route));
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
