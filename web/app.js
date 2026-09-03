const cfg = window.BLINQ_CONFIG || {};
const state = {
  predictions: [],
  ui: null,
  user: null,
  featuredIndex: 0,
  expanded: false,
};

const $ = (id) => document.getElementById(id);
const api = (path) => `${String(cfg.apiBase || "").replace(/\/$/, "")}${path}`;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  }[ch]));
}

function fallbackConfidence(probabilityPct) {
  const p = Number(probabilityPct || 0);
  if (p >= 76) return "high";
  if (p >= 63) return "medium";
  return "low";
}

function fmtPct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function fmtTime(value) {
  if (!value) return "TBA";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "TBA";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(d);
}

function fmtShortGenerated(value) {
  if (!value) return "generated —";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "generated —";
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function fmtToday() {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date());
}

function initials(name) {
  return String(name || "?")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((x) => x[0] || "")
    .join("")
    .toUpperCase();
}

async function getJSON(url) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

async function loadUiConfig() {
  try {
    state.ui = await getJSON(cfg.uiConfigPath || "ui-config.json");
  } catch {
    state.ui = { navigation: { main: [], learn: [] }, panels: {}, banners: {}, ads: {} };
  }
  renderNavigation();
  applyPanelConfig();
  renderBanners();
  renderAds();
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
    if (banner.enabled === false) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    const target = banner.link_target || "_self";
    host.innerHTML = `
      <div class="promo-banner">
        <div class="promo-copy">
          <span class="promo-eyebrow">${escapeHtml(banner.eyebrow || (banner.sponsored ? "Sponsored" : "BlinQ"))}</span>
          <strong>${escapeHtml(banner.headline || "")}</strong>
          <p>${escapeHtml(banner.text || "")}</p>
          <div class="promo-actions">
            <a class="promo-cta" href="${escapeHtml(banner.link || "#")}" target="${escapeHtml(target)}" ${target === "_blank" ? 'rel="noopener noreferrer"' : ""}>⚡ ${escapeHtml(banner.button_text || "Open")}</a>
            <span class="promo-meta">${escapeHtml(banner.meta || "")}</span>
          </div>
        </div>
        <div class="promo-visual" aria-hidden="true">
          <div class="promo-court"></div>
          <div class="promo-chart"></div>
          <div class="promo-racket"></div>
          <div class="promo-ball"></div>
        </div>
        ${banner.sponsored ? '<span class="promo-sponsor">Sponsored</span>' : ""}
      </div>`;
  });
}

function renderAds() {
  const ads = state.ui?.ads || {};
  Object.values(ads).forEach((ad) => {
    const host = $(ad.target);
    if (!host) return;
    if (ad.enabled === false) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    const target = ad.link_target || "_self";
    host.innerHTML = `
      <span class="ad-label">${escapeHtml(ad.label || "Ad")}</span>
      <div class="ad-ball" aria-hidden="true"></div>
      <h3>${escapeHtml(ad.headline || "Sponsored partner")}</h3>
      <p>${escapeHtml(ad.text || "")}</p>
      <a class="ad-link" href="${escapeHtml(ad.link || "#")}" target="${escapeHtml(target)}" ${target === "_blank" ? 'rel="noopener noreferrer"' : ""}>${escapeHtml(ad.button_text || "Open")}</a>`;
  });
}

function loadPreviewSession() {
  try { return JSON.parse(localStorage.getItem("blinq_preview_session") || "null"); } catch { return null; }
}

function savePreviewSession(user) {
  localStorage.setItem("blinq_preview_session", JSON.stringify(user));
}

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
    const probability = Number(
      raw.prediction.probability_pct
      ?? Math.max(raw.player1.win_probability_pct || 0, raw.player2.win_probability_pct || 0)
    );
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
      probability,
      confidence: String(raw.prediction.confidence_band || fallbackConfidence(probability)).toLowerCase(),
      signals: raw.prediction.signals || [],
      features: raw.features || raw.prediction.features || {},
      model: raw.model_version || "",
      generatedAt: raw.generated_at || null,
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
    confidence: String(raw.confidence || fallbackConfidence(probability)).toLowerCase(),
    signals: raw.signals || [],
    features: raw.features || {},
    model: raw.model || raw.model_version || "",
    generatedAt: raw.generated_at || null,
  };
}

async function fetchPredictions() {
  const days = Number(cfg.predictionsDays || 3);

  // Prefer the rich public contract because it carries ranks, round and model metadata.
  try {
    const rich = await getJSON(api(`/api/v1/predictions/upcoming?days=${days}`));
    const rows = Array.isArray(rich?.matches) ? rich.matches : [];
    if (rows.length) return { rows, updatedAt: rich.updated_at || rich.generated_at || null };
  } catch (_) {}

  // Compatibility fallback for deployments still exposing only the BlinQ flat endpoint.
  const flat = await getJSON(api(`/api/blinq/predictions?days=${days}`));
  const rows = Array.isArray(flat?.data) ? flat.data : Array.isArray(flat?.matches) ? flat.matches : [];
  return { rows, updatedAt: flat.updated_at || flat.generated_at || null };
}

async function loadPredictions() {
  const grid = $("predictionGrid");
  grid.innerHTML = '<div class="state-card">Loading current model predictions…</div>';
  try {
    const result = await fetchPredictions();
    state.predictions = result.rows.map(normalizePrediction);
    state.featuredIndex = 0;
    populateFilterOptions();
    renderPredictions();

    const generatedTimes = state.predictions
      .map((x) => x.generatedAt ? new Date(x.generatedAt).getTime() : NaN)
      .filter(Number.isFinite);
    const latestGenerated = generatedTimes.length ? new Date(Math.max(...generatedTimes)) : null;
    $("updatedAt").textContent = result.updatedAt
      ? fmtTime(result.updatedAt)
      : latestGenerated
        ? fmtTime(latestGenerated)
        : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (error) {
    state.predictions = [];
    grid.innerHTML = `<div class="state-card error">Predictions API is unavailable.<small>${escapeHtml(error.message)}</small></div>`;
    $("matchCount").textContent = "0";
    renderDots([]);
  }
}

function populateSelect(id, values, firstLabel) {
  const select = $(id);
  const selected = select.value;
  select.innerHTML = `<option value="">${firstLabel}</option>`;
  [...values].filter(Boolean).sort().forEach((value) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = String(value).replaceAll("_", " ");
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

function numericFeature(match, name) {
  const value = Number(match.features?.[name]);
  return Number.isFinite(value) ? value : null;
}

function pickOrientation(match) {
  if (String(match.pickId ?? "") === String(match.p1Id ?? "")) return 1;
  if (String(match.pickId ?? "") === String(match.p2Id ?? "")) return -1;
  return String(match.pick || "").trim().toLowerCase() === String(match.p1 || "").trim().toLowerCase() ? 1 : -1;
}

function signalScore(match, aliases, fallback = 50) {
  const normalizedAliases = aliases.map((x) => x.toLowerCase());
  const signal = (match.signals || []).find((s) => normalizedAliases.some((alias) => String(s.factor || "").toLowerCase().includes(alias)));
  if (!signal) return fallback;
  const favoursPick = String(signal.favours_player_id ?? "") === String(match.pickId ?? "")
    || String(signal.favours_player_name ?? "").toLowerCase() === String(match.pick || "").toLowerCase();
  const strong = String(signal.strength || "").toLowerCase() === "strong";
  return favoursPick ? (strong ? 86 : 72) : (strong ? 14 : 28);
}

function signedFeatureScore(match, value, scale, fallbackAliases) {
  if (value === null) return signalScore(match, fallbackAliases, 50);
  const oriented = pickOrientation(match) * value;
  return clamp(50 + 42 * Math.tanh(oriented / scale), 5, 95);
}

function modelFactors(match) {
  const overall = signedFeatureScore(match, numericFeature(match, "elo_diff"), 0.55, ["overall strength"]);

  const surfaceElo = numericFeature(match, "surface_elo_diff");
  const surfaceForm = numericFeature(match, "surface_form_diff");
  let surfaceValue = null;
  if (surfaceElo !== null && surfaceForm !== null) surfaceValue = surfaceElo * 0.72 + surfaceForm * 0.28;
  else surfaceValue = surfaceElo ?? surfaceForm;
  const surface = signedFeatureScore(match, surfaceValue, 0.45, ["surface strength", "surface form"]);

  const recent = numericFeature(match, "recent_form_diff");
  const opponentAdjusted = numericFeature(match, "opponent_adjusted_form_diff");
  let recentValue = null;
  if (recent !== null && opponentAdjusted !== null) recentValue = recent + opponentAdjusted * 0.45;
  else recentValue = recent ?? opponentAdjusted;
  const form = signedFeatureScore(match, recentValue, 0.22, ["recent form", "opponent-adjusted form"]);

  const h2h = signedFeatureScore(match, numericFeature(match, "h2h_advantage"), 0.35, ["head-to-head"]);

  const rest = numericFeature(match, "rest_advantage");
  const layoff = numericFeature(match, "layoff_advantage");
  const fatigue3 = numericFeature(match, "fatigue_3d_advantage");
  const fatigue7 = numericFeature(match, "fatigue_7d_advantage");
  const workloadParts = [
    rest === null ? null : rest * 0.60,
    layoff === null ? null : layoff * 0.25,
    fatigue3 === null ? null : fatigue3 * 0.75,
    fatigue7 === null ? null : fatigue7 * 0.40,
  ].filter((x) => x !== null);
  const workloadValue = workloadParts.length ? workloadParts.reduce((a, b) => a + b, 0) : null;
  const workload = signedFeatureScore(match, workloadValue, 1.05, ["rest / workload"]);

  const depthRaw = numericFeature(match, "data_depth");
  const depth = depthRaw === null ? 50 : clamp(depthRaw * 100, 0, 100);

  return [
    { label: "Overall Strength", score: overall, kind: "advantage" },
    { label: "Surface Strength", score: surface, kind: "advantage" },
    { label: "Recent Form", score: form, kind: "advantage" },
    { label: "Head-to-Head", score: h2h, kind: "advantage" },
    { label: "Rest / Workload", score: workload, kind: "advantage" },
    { label: "Data Depth", score: depth, kind: "depth" },
  ];
}

function meterHtml(factor) {
  const segments = 7;
  const active = clamp(Math.round((factor.score / 100) * segments), 0, segments);
  let meterClass = factor.kind === "depth" ? "depth" : "";
  if (factor.kind !== "depth") {
    if (factor.score < 43) meterClass = "counter";
    else if (factor.score <= 57) meterClass = "neutral";
  }
  return `<div class="factor-meter ${meterClass}" aria-label="${escapeHtml(factor.label)} indicator">${Array.from({ length: segments }, (_, i) => `<i class="${i < active ? "on" : ""}"></i>`).join("")}</div>`;
}

function cardHtml(match, featured = false) {
  const factors = modelFactors(match);
  const surface = String(match.surface || "unknown").replaceAll("_", " ").toUpperCase();
  const tourTournament = `${match.tour || "TOUR"} ${match.tournament || ""}${match.round ? ` · ${match.round}` : ""}`;
  return `
    <article class="pick-card${featured ? " featured" : ""}" data-match-id="${escapeHtml(match.id)}" tabindex="0" role="button" aria-label="Open analysis for ${escapeHtml(match.p1)} versus ${escapeHtml(match.p2)}">
      ${featured ? '<div class="featured-ribbon"><span>★ MOST CONFIDENT</span></div>' : ""}
      <div class="pick-meta">
        <span class="tour-tournament">${escapeHtml(tourTournament)}</span>
        <span>${escapeHtml(fmtTime(match.date))}</span>
        <span class="surface-badge">${escapeHtml(surface)}</span>
        <span class="card-star" aria-hidden="true">☆</span>
      </div>
      <div class="players">
        <div class="player">
          <span class="player-avatar">${escapeHtml(initials(match.p1))}</span>
          <strong class="player-name">${escapeHtml(match.p1)}</strong>
          <small class="player-rank">${match.p1Rank ? `#${escapeHtml(match.p1Rank)}` : "NR"}</small>
        </div>
        <div class="vs">VS</div>
        <div class="player">
          <span class="player-avatar">${escapeHtml(initials(match.p2))}</span>
          <strong class="player-name">${escapeHtml(match.p2)}</strong>
          <small class="player-rank">${match.p2Rank ? `#${escapeHtml(match.p2Rank)}` : "NR"}</small>
        </div>
      </div>
      <div class="pick-summary">
        <div><small>BlinQ Pick</small><strong class="pick-name">${escapeHtml(match.pick || "—")}</strong></div>
        <div class="prob-wrap"><small>Win Probability</small><div class="probability">${fmtPct(match.probability)}</div><span class="confidence ${escapeHtml(match.confidence)}">${escapeHtml(match.confidence.toUpperCase())}</span></div>
      </div>
      <div class="factors">
        ${factors.map((factor) => `<div class="factor-row" title="Normalized UI indicator derived from TBT model features; not a standalone probability."><span class="factor-label">${escapeHtml(factor.label)}</span>${meterHtml(factor)}</div>`).join("")}
      </div>
      <div class="pick-footer"><span>${escapeHtml(match.model || "model —")}</span><span>${escapeHtml(fmtShortGenerated(match.generatedAt))}</span></div>
    </article>`;
}

function rankedRows(rows) {
  return [...rows].sort((a, b) => {
    const confidenceOrder = { high: 3, medium: 2, low: 1 };
    const bandDelta = (confidenceOrder[b.confidence] || 0) - (confidenceOrder[a.confidence] || 0);
    if (bandDelta) return bandDelta;
    return Number(b.probability || 0) - Number(a.probability || 0);
  });
}

function featuredOrder(topRows) {
  if (!topRows.length) return [];
  const index = ((state.featuredIndex % topRows.length) + topRows.length) % topRows.length;
  const featured = topRows[index];
  const support = topRows.filter((_, i) => i !== index);
  if (support.length <= 1) return [featured, ...support];
  return [support[0], support[1] || support[0], featured, ...support.slice(2)];
}

function renderDots(topRows) {
  const host = $("carouselDots");
  host.innerHTML = "";
  if (state.expanded || topRows.length <= 1) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  topRows.forEach((_, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = i === state.featuredIndex % topRows.length ? "active" : "";
    button.setAttribute("aria-label", `Feature pick ${i + 1}`);
    button.addEventListener("click", () => {
      state.featuredIndex = i;
      renderPredictions();
    });
    host.appendChild(button);
  });
}

function bindCards(rows) {
  const byId = new Map(rows.map((x) => [String(x.id), x]));
  document.querySelectorAll(".pick-card[data-match-id]").forEach((card) => {
    const open = () => {
      const match = byId.get(String(card.dataset.matchId));
      if (match) openMatchDialog(match);
    };
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
}

function renderPredictions() {
  const rows = currentFilteredPredictions();
  const sorted = rankedRows(rows);
  const grid = $("predictionGrid");
  const shell = $("pickCarouselShell");
  const topRows = sorted.slice(0, 5);

  $("matchCount").textContent = String(rows.length);
  $("viewAllButton").textContent = state.expanded ? "← Back to top picks" : "View all matches →";
  grid.classList.toggle("expanded", state.expanded);
  shell.classList.toggle("expanded", state.expanded);
  $("prevPick").hidden = state.expanded || topRows.length <= 1;
  $("nextPick").hidden = state.expanded || topRows.length <= 1;

  if (!rows.length) {
    grid.innerHTML = '<div class="state-card">No current prediction matches these filters.</div>';
    renderDots([]);
    return;
  }

  if (state.expanded) {
    grid.innerHTML = sorted.slice(0, 24).map((match) => cardHtml(match, false)).join("");
    renderDots([]);
    bindCards(sorted.slice(0, 24));
    return;
  }

  state.featuredIndex = clamp(state.featuredIndex, 0, Math.max(0, topRows.length - 1));
  const ordered = featuredOrder(topRows);
  const featured = topRows[state.featuredIndex];
  grid.innerHTML = ordered.map((match) => cardHtml(match, String(match.id) === String(featured.id))).join("");
  renderDots(topRows);
  bindCards(ordered);
}

function openMatchDialog(match) {
  const factors = modelFactors(match);
  const content = $("dialogContent");
  content.innerHTML = `
    <div class="dialog-eyebrow">${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}${match.round ? ` · ${escapeHtml(match.round)}` : ""}</div>
    <h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2>
    <div class="dialog-pick">
      <div><small>BlinQ prediction</small><strong>${escapeHtml(match.pick)}</strong></div>
      <div class="dialog-prob">${fmtPct(match.probability)}<span class="confidence ${escapeHtml(match.confidence)}">${escapeHtml(match.confidence.toUpperCase())}</span></div>
    </div>
    <div class="dialog-section">
      <h3>Model factor view</h3>
      ${factors.map((factor) => `<div class="dialog-factor"><span>${escapeHtml(factor.label)}</span>${meterHtml(factor)}<small>${factor.kind === "depth" ? "data coverage" : factor.score >= 57 ? "favours pick" : factor.score <= 43 ? "favours opponent" : "balanced"}</small></div>`).join("")}
    </div>
    <div class="dialog-meta">
      <span>Surface: ${escapeHtml(match.surface)}</span>
      <span>Time: ${escapeHtml(fmtTime(match.date))}</span>
      <span>Model: ${escapeHtml(match.model || "current")}</span>
      <span>${escapeHtml(fmtShortGenerated(match.generatedAt))}</span>
    </div>
    <p style="color:#647386;font-size:10px;line-height:1.55;margin:18px 0 0">Factor bars are normalized display indicators derived from internal TBT model features. They are not bookmaker odds, standalone probabilities or externally supplied Elo ratings.</p>`;
  $("matchDialog").showModal();
}

function setupEvents() {
  const loginForm = $("loginForm");
  if (loginForm) loginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const user = {
      email: $("emailInput").value.trim(),
      name: $("nameInput").value.trim(),
      startedAt: Date.now(),
    };
    savePreviewSession(user);
    startSession(user);
  });

  $("refreshButton").addEventListener("click", loadPredictions);
  ["tourFilter", "tournamentFilter", "surfaceFilter", "confidenceFilter"].forEach((id) => $(id).addEventListener("change", () => {
    state.featuredIndex = 0;
    state.expanded = false;
    renderPredictions();
  }));
  $("searchInput").addEventListener("input", () => {
    state.featuredIndex = 0;
    state.expanded = false;
    renderPredictions();
  });

  $("prevPick").addEventListener("click", () => {
    const count = Math.min(5, rankedRows(currentFilteredPredictions()).length);
    if (!count) return;
    state.featuredIndex = (state.featuredIndex - 1 + count) % count;
    renderPredictions();
  });
  $("nextPick").addEventListener("click", () => {
    const count = Math.min(5, rankedRows(currentFilteredPredictions()).length);
    if (!count) return;
    state.featuredIndex = (state.featuredIndex + 1) % count;
    renderPredictions();
  });
  $("viewAllButton").addEventListener("click", () => {
    state.expanded = !state.expanded;
    renderPredictions();
  });

  $("dialogClose").addEventListener("click", () => $("matchDialog").close());
  $("matchDialog").addEventListener("click", (event) => {
    if (event.target === $("matchDialog")) $("matchDialog").close();
  });

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

  // Production public dashboard: authentication is intentionally disabled here.
  // This is independent of the current URL path and does not rely on config.js
  // to decide whether the login screen should be shown.
  startSession({ email: "public@blinq.local", name: "BlinQ User", startedAt: Date.now() });

  setInterval(updateTrialTimer, 60 * 1000);
  setInterval(() => {
    if (state.user) loadPredictions();
  }, Math.max(1, Number(cfg.refreshMinutes || 5)) * 60 * 1000);
}

boot();
