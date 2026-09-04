const cfg = window.BLINQ_CONFIG || {};

const state = {
  predictions: [],
  ui: null,
  user: null,
  currentRoute: "dashboard",
  featuredIndex: 0,
  allPredictions: false,
};

const $ = (id) => document.getElementById(id);
const api = (path) => `${String(cfg.apiBase || "").replace(/\/$/, "")}${path}`;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[ch]));
}

function initials(name) {
  return String(name || "BlinQ").trim().split(/\s+/).slice(0, 2).map((x) => x[0] || "").join("").toUpperCase() || "BQ";
}

function fallbackConfidence(probabilityPct) {
  const p = Number(probabilityPct || 0);
  if (p >= 76) return "high";
  if (p >= 63) return "medium";
  return "low";
}

function fmtPct(value) { return `${Number(value || 0).toFixed(1)}%`; }

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
  return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(d);
}

function fmtToday() {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).format(new Date());
}

async function getJSON(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

function loadLocalAdminOverride() {
  try { return JSON.parse(localStorage.getItem("blinq_admin_ui_override") || "null"); } catch { return null; }
}

function applyLocalAdminOverride(ui) {
  const local = loadLocalAdminOverride();
  if (local?.banner_zones) ui.banner_zones = local.banner_zones;
  if (local?.header_ad) ui.header_ad = local.header_ad;
  return ui;
}

async function loadUiConfig() {
  try {
    state.ui = applyLocalAdminOverride(await getJSON(cfg.uiConfigPath || "/ui-config.json"));
  } catch {
    state.ui = { account: {}, navigation: { main: [], learn: [], admin: [] }, banner_zones: {}, plans: [] };
  }
  startPublicSession();
  renderBranding();
  renderNavigation();
  renderHeaderSponsor();
  renderBannerZones();
  renderPlanGrid();
}

function startPublicSession() {
  const account = state.ui?.account || {};
  state.user = {
    name: account.display_name || "BlinQ User",
    plan: String(account.plan || "free").toLowerCase(),
    planLabel: account.plan_label || String(account.plan || "free").toUpperCase(),
    entitlement: account.entitlement_text || "",
    avatarUrl: account.avatar_url || "",
  };
  renderAccount();
  $("todayLabel").textContent = fmtToday();
}

function renderBranding() {
  const branding = state.ui?.branding || {};
  const engineMark = document.querySelector(".engine-mark");
  if (engineMark && branding.engine_mark) engineMark.src = branding.engine_mark;
  const engineText = document.querySelector(".engine-copy strong");
  if (engineText && branding.engine_label) engineText.textContent = branding.engine_label;
  const productLogo = document.querySelector(".product-logo");
  if (productLogo && branding.blinq_logo) productLogo.src = branding.blinq_logo;
}

function renderAccount() {
  const user = state.user || {};
  $("profileName").textContent = user.name || "BlinQ User";
  $("profilePlan").textContent = user.planLabel || "Free";
  $("planName").textContent = String(user.planLabel || user.plan || "FREE").toUpperCase();
  $("planEntitlement").textContent = user.entitlement || "Active";
  const avatar = $("avatar");
  if (user.avatarUrl) {
    avatar.innerHTML = `<img src="${escapeHtml(user.avatarUrl)}" alt="" />`;
  } else {
    avatar.textContent = initials(user.name);
  }
}

function allNavItems() {
  const nav = state.ui?.navigation || {};
  return [...(nav.main || []), ...(nav.learn || []), ...(nav.admin || [])];
}

function navItem(route) { return allNavItems().find((x) => x.id === route); }

function routeAccess(item) {
  if (!item) return { allowed: true };
  if (item.admin_only) {
    return state.user?.plan === "admin"
      ? { allowed: true }
      : { allowed: false, label: "Admin", reason: "This module is available only to administrators." };
  }
  const allowedPlans = item.allowed_plans || ["free", "pro", "elite", "legend", "goat", "admin"];
  if (!allowedPlans.includes(state.user?.plan || "free")) {
    return {
      allowed: false,
      label: item.required_label || allowedPlans[0] || "Premium",
      reason: "This module is visible on your current plan, but it is not unlocked.",
    };
  }
  if (item.data_status) {
    const messages = {
      market_odds_required: "Value Picks need a live bookmaker odds feed so the market probability and odds gap are real, not invented.",
      ace_model_required: "Ace Picks require the dedicated serve/ace prediction model and consistent ace-stat coverage.",
      games_sets_model_required: "Games & Sets require a dedicated set/game model. Match-winner probability is not reused as a fake set prediction.",
    };
    return { allowed: false, label: "Data module", reason: messages[item.data_status] || "The data source for this module is not connected yet." };
  }
  return { allowed: true };
}

function renderNavigationGroup(items, containerId) {
  const host = $(containerId);
  if (!host) return;
  host.innerHTML = "";
  [...(items || [])]
    .filter((item) => item.enabled !== false)
    .sort((a, b) => Number(a.order || 0) - Number(b.order || 0))
    .forEach((item) => {
      if (item.admin_only && state.user?.plan !== "admin") return;
      const access = routeAccess(item);
      const a = document.createElement("a");
      a.href = item.href || `#${item.id}`;
      a.className = `nav-link${state.currentRoute === item.id ? " active" : ""}${access.allowed ? "" : " locked"}`;
      a.dataset.route = item.id;
      a.innerHTML = `<span class="nav-icon">${escapeHtml(item.icon || "•")}</span><span class="nav-text">${escapeHtml(item.label || item.id)}</span>${access.allowed ? "" : '<span class="nav-lock">🔒</span>'}`;
      host.appendChild(a);
    });
}

function renderNavigation() {
  const nav = state.ui?.navigation || {};
  renderNavigationGroup(nav.main, "mainNavigation");
  renderNavigationGroup(nav.learn, "learnNavigation");
  const adminSection = $("adminNavigationSection");
  if (adminSection) adminSection.hidden = state.user?.plan !== "admin";
  if (state.user?.plan === "admin") renderNavigationGroup(nav.admin, "adminNavigation");
}

function renderHeaderSponsor() {
  const ad = state.ui?.header_ad || {};
  const host = $("headerSponsor");
  if (!host) return;
  if (ad.enabled === false) { host.hidden = true; return; }
  host.hidden = false;
  host.href = ad.link || "#";
  const route = String(ad.link || "").startsWith("#") ? String(ad.link).slice(1).replaceAll("-", "_") : "";
  if (route) host.dataset.route = route; else delete host.dataset.route;
  host.innerHTML = `${ad.image ? `<img src="${escapeHtml(ad.image)}" alt="" />` : ""}<span class="header-sponsor-label">${escapeHtml(ad.label || "Sponsored")}</span><span class="header-sponsor-copy"><strong>${escapeHtml(ad.headline || "Partner placement")}</strong><small>${escapeHtml(ad.text || "")}</small></span>`;
}

function sizeHint(count) {
  return ({
    1: "1 × 1200×400",
    2: "2 × 600×400",
    3: "1 × 600×400 + 2 × 300×400",
    4: "4 × 300×400",
  })[Number(count)] || "Flexible";
}

function renderBannerZone(zoneName) {
  const zone = state.ui?.banner_zones?.[zoneName] || { count: 0, items: [] };
  const host = $(zoneName === "top" ? "bannerZoneTop" : "bannerZoneBottom");
  if (!host) return;
  const count = clamp(Number(zone.count || 0), 0, 4);
  const items = (zone.items || []).filter((x) => x.enabled !== false).slice(0, count);
  if (!items.length) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.className = `banner-zone banner-zone-${zoneName} banner-count-${items.length}`;
  host.innerHTML = items.map((banner, index) => {
    const image = banner.image ? `<div class="zone-banner-art"><img src="${escapeHtml(banner.image)}" alt="" /></div>` : '<div class="zone-banner-art generated-art"><span></span></div>';
    const route = String(banner.link || "").startsWith("#") ? String(banner.link).slice(1).replaceAll("-", "_") : "";
    return `<article class="zone-banner zone-banner-${index + 1}">
      <div class="zone-banner-copy">
        <span class="promo-eyebrow">${escapeHtml(banner.eyebrow || (banner.sponsored ? "SPONSORED" : "BLINQ"))}</span>
        <h2>${escapeHtml(banner.headline || "")}</h2>
        <p>${escapeHtml(banner.text || "")}</p>
        <a class="promo-cta" href="${escapeHtml(banner.link || "#")}" ${route ? `data-route="${escapeHtml(route)}"` : ""}>${escapeHtml(banner.button_text || "Open")}</a>
      </div>
      ${image}
      ${banner.sponsored ? '<span class="promo-sponsor">Sponsored</span>' : ""}
    </article>`;
  }).join("");
}

function renderBannerZones() {
  renderBannerZone("top");
  renderBannerZone("bottom");
}

function renderPlanGrid() {
  const host = $("planGrid");
  if (!host) return;
  host.innerHTML = (state.ui?.plans || []).map((plan) => `<article class="plan-option">
    <span>${escapeHtml(plan.label)}</span>
    <h3>${escapeHtml(plan.price || "—")}</h3>
    <ul>${(plan.features || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
    <button class="btn btn-primary btn-full" type="button" data-plan-choice="${escapeHtml(plan.id)}">Choose ${escapeHtml(plan.label)}</button>
  </article>`).join("");
}

function showLocked(item) {
  const access = routeAccess(item);
  $("lockedTitle").textContent = item?.label || "Premium module";
  $("lockedText").textContent = access.reason || "This module is not available on your current plan.";
  $("lockedPlan").textContent = access.label || item?.required_label || "Premium";
  $("lockedDialog").showModal();
}

function openUpgrade() { $("upgradeDialog").showModal(); }

function normalizePrediction(raw) {
  if (raw?.prediction && raw?.player1 && raw?.player2) {
    const probability = Number(raw.prediction.probability_pct ?? Math.max(raw.player1.win_probability_pct || 0, raw.player2.win_probability_pct || 0));
    return {
      id: raw.id || raw.match_id,
      date: raw.scheduled_at,
      tour: String(raw.tour || "").toUpperCase(),
      tournament: raw.tournament || "Tournament",
      surface: raw.surface || "unknown",
      round: raw.round || raw.round_name || "",
      p1: raw.player1.name,
      p2: raw.player2.name,
      p1Id: raw.player1.id,
      p2Id: raw.player2.id,
      p1Rank: raw.player1.rank,
      p2Rank: raw.player2.rank,
      p1Image: raw.player1.image_url || raw.player1.photo_url || raw.player1.image || "",
      p2Image: raw.player2.image_url || raw.player2.photo_url || raw.player2.image || "",
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
    round: raw.round || raw.round_name || "",
    p1: raw.p1 || raw.player1_name || "Player 1",
    p2: raw.p2 || raw.player2_name || "Player 2",
    p1Id: raw.p1_id || raw.player1_id,
    p2Id: raw.p2_id || raw.player2_id,
    p1Rank: raw.p1_rank || raw.player1_rank,
    p2Rank: raw.p2_rank || raw.player2_rank,
    p1Image: raw.p1_image || raw.player1_image || "",
    p2Image: raw.p2_image || raw.player2_image || "",
    p1Prob, p2Prob,
    pick: raw.pick || raw.predicted_winner_name || (p1Prob >= p2Prob ? raw.p1 : raw.p2),
    pickId: raw.pick_id || raw.predicted_winner_id,
    probability,
    confidence: String(raw.confidence || raw.confidence_band || fallbackConfidence(probability)).toLowerCase(),
    signals: raw.signals || [],
    features: raw.features || {},
    model: raw.model || raw.model_version || "",
    generatedAt: raw.generated_at || null,
  };
}

async function fetchPredictions() {
  const days = Number(cfg.predictionsDays || 3);
  try {
    const rich = await getJSON(api(`/api/v1/predictions/upcoming?days=${days}`));
    const rows = Array.isArray(rich?.matches) ? rich.matches : [];
    if (rows.length) return rows;
  } catch (_) {}
  const flat = await getJSON(api(`/api/blinq/predictions?days=${days}`));
  return Array.isArray(flat?.data) ? flat.data : Array.isArray(flat?.matches) ? flat.matches : [];
}

async function loadPredictions() {
  const grid = $("predictionGrid");
  if (grid) grid.innerHTML = '<div class="state-card">Loading current model predictions…</div>';
  try {
    const rows = await fetchPredictions();
    state.predictions = rows.map(normalizePrediction);
    state.featuredIndex = 0;
    populateFilterOptions();
    if (["dashboard", "prime_picks"].includes(state.currentRoute)) renderPredictions();
    else renderCurrentModule();
  } catch (error) {
    state.predictions = [];
    if (grid) grid.innerHTML = `<div class="state-card error">Predictions API is unavailable.<small>${escapeHtml(error.message)}</small></div>`;
    if ($("matchCount")) $("matchCount").textContent = "0";
    renderDots([]);
  }
}

function populateSelect(id, values, firstLabel) {
  const select = $(id);
  if (!select) return;
  const selected = select.value;
  select.innerHTML = `<option value="">${firstLabel}</option>`;
  [...values].filter(Boolean).sort().forEach((value) => {
    const opt = document.createElement("option"); opt.value = value; opt.textContent = String(value).replaceAll("_", " "); select.appendChild(opt);
  });
  if ([...select.options].some((o) => o.value === selected)) select.value = selected;
}

function populateFilterOptions() {
  populateSelect("tournamentFilter", new Set(state.predictions.map((x) => x.tournament)), "All Tournaments");
  populateSelect("surfaceFilter", new Set(state.predictions.map((x) => x.surface)), "All Surfaces");
}

function currentFilteredPredictions() {
  const tour = $("tourFilter")?.value || "";
  const tournament = $("tournamentFilter")?.value || "";
  const surface = $("surfaceFilter")?.value || "";
  const confidence = $("confidenceFilter")?.value || "";
  const q = ($("searchInput")?.value || "").trim().toLowerCase();
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
  const normalized = aliases.map((x) => x.toLowerCase());
  const signal = (match.signals || []).find((s) => normalized.some((alias) => String(s.factor || "").toLowerCase().includes(alias)));
  if (!signal) return fallback;
  const favoursPick = String(signal.favours_player_id ?? "") === String(match.pickId ?? "") || String(signal.favours_player_name ?? "").toLowerCase() === String(match.pick || "").toLowerCase();
  const strong = String(signal.strength || "").toLowerCase() === "strong";
  return favoursPick ? (strong ? 86 : 72) : (strong ? 14 : 28);
}

function signedFeatureScore(match, value, scale, aliases) {
  if (value === null) return signalScore(match, aliases, 50);
  return clamp(50 + 42 * Math.tanh((pickOrientation(match) * value) / scale), 5, 95);
}

function modelFactors(match) {
  const overall = signedFeatureScore(match, numericFeature(match, "elo_diff"), 0.55, ["overall strength"]);
  const surfaceElo = numericFeature(match, "surface_elo_diff");
  const surfaceForm = numericFeature(match, "surface_form_diff");
  const surfaceValue = surfaceElo !== null && surfaceForm !== null ? surfaceElo * 0.72 + surfaceForm * 0.28 : (surfaceElo ?? surfaceForm);
  const surface = signedFeatureScore(match, surfaceValue, 0.45, ["surface strength", "surface form"]);
  const recent = numericFeature(match, "recent_form_diff");
  const adjusted = numericFeature(match, "opponent_adjusted_form_diff");
  const recentValue = recent !== null && adjusted !== null ? recent + adjusted * 0.45 : (recent ?? adjusted);
  const form = signedFeatureScore(match, recentValue, 0.22, ["recent form", "opponent-adjusted form"]);
  const h2h = signedFeatureScore(match, numericFeature(match, "h2h_advantage"), 0.35, ["head-to-head"]);
  const rest = numericFeature(match, "rest_advantage");
  const layoff = numericFeature(match, "layoff_advantage");
  const fatigue3 = numericFeature(match, "fatigue_3d_advantage");
  const fatigue7 = numericFeature(match, "fatigue_7d_advantage");
  const workloadParts = [rest === null ? null : rest * .60, layoff === null ? null : layoff * .25, fatigue3 === null ? null : fatigue3 * .75, fatigue7 === null ? null : fatigue7 * .40].filter((x) => x !== null);
  const workload = signedFeatureScore(match, workloadParts.length ? workloadParts.reduce((a, b) => a + b, 0) : null, 1.05, ["rest / workload"]);
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

function primeScore(match) {
  const settings = state.ui?.prime_picks || {};
  const factors = modelFactors(match);
  const advantages = factors.filter((x) => x.kind === "advantage");
  const agreement = advantages.length ? advantages.reduce((sum, x) => sum + x.score, 0) / advantages.length : 50;
  const depth = factors.find((x) => x.kind === "depth")?.score ?? 50;
  const pW = Number(settings.probability_weight ?? .58);
  const dW = Number(settings.data_depth_weight ?? .22);
  const aW = Number(settings.signal_agreement_weight ?? .20);
  return Number(match.probability || 0) * pW + depth * dW + agreement * aW;
}

function primeRows(rows = currentFilteredPredictions()) {
  const limit = clamp(Number(state.ui?.prime_picks?.limit || 10), 1, 20);
  return [...rows].sort((a, b) => primeScore(b) - primeScore(a) || Number(b.probability || 0) - Number(a.probability || 0)).slice(0, limit);
}

function meterHtml(factor) {
  const on = clamp(Math.round(Number(factor.score || 0) / (100 / 7)), 0, 7);
  const cls = factor.kind === "depth" ? "depth" : factor.score >= 57 ? "" : factor.score <= 43 ? "counter" : "neutral";
  return `<div class="factor-meter ${cls}">${Array.from({ length: 7 }, (_, i) => `<i class="${i < on ? "on" : ""}"></i>`).join("")}</div>`;
}

function playerAvatarHtml(name, image) {
  return image
    ? `<span class="player-avatar player-photo"><img src="${escapeHtml(image)}" alt="" loading="lazy" /></span>`
    : `<span class="player-avatar">${escapeHtml(initials(name))}</span>`;
}

function cardHtml(match, featured = false, rankIndex = 0) {
  const factors = modelFactors(match);
  const surface = String(match.surface || "unknown").replaceAll("_", " ").toUpperCase();
  const meta = `${match.tour || "TOUR"} ${match.tournament || ""}${match.round ? ` · ${match.round}` : ""}`;
  const ribbon = featured ? '<div class="featured-ribbon"><span>★ TOP PRIME</span></div>' : '<div class="prime-badge">★ PRIME PICK</div>';
  return `<article class="pick-card${featured ? " featured" : ""}" data-match-id="${escapeHtml(match.id)}" tabindex="0" role="button">
    ${ribbon}
    <div class="pick-meta"><span class="tour-tournament">${escapeHtml(meta)}</span><span>${escapeHtml(fmtTime(match.date))}</span><span class="surface-badge">${escapeHtml(surface)}</span><span class="card-star">☆</span></div>
    <div class="players">
      <div class="player">${playerAvatarHtml(match.p1, match.p1Image)}<strong class="player-name">${escapeHtml(match.p1)}</strong><small class="player-rank">${match.p1Rank ? `#${escapeHtml(match.p1Rank)}` : "NR"}</small></div>
      <div class="vs">VS</div>
      <div class="player">${playerAvatarHtml(match.p2, match.p2Image)}<strong class="player-name">${escapeHtml(match.p2)}</strong><small class="player-rank">${match.p2Rank ? `#${escapeHtml(match.p2Rank)}` : "NR"}</small></div>
    </div>
    <div class="pick-summary"><div><small>BlinQ Pick</small><strong class="pick-name">${escapeHtml(match.pick || "—")}</strong></div><div class="prob-wrap"><small>Win Probability</small><div class="probability">${fmtPct(match.probability)}</div><span class="confidence ${escapeHtml(match.confidence)}">${escapeHtml(match.confidence.toUpperCase())}</span></div></div>
    <div class="factors">${factors.map((factor) => `<div class="factor-row" title="Normalized display indicator derived from TBT model features."><span class="factor-label">${escapeHtml(factor.label)}</span>${meterHtml(factor)}</div>`).join("")}</div>
    <div class="pick-footer"><span>#${rankIndex + 1} Prime</span><span>${escapeHtml(match.model || "model —")}</span><span>${escapeHtml(fmtShortGenerated(match.generatedAt))}</span></div>
  </article>`;
}

function primeWindow(rows) {
  if (!rows.length) return [];
  const maxVisible = clamp(Number(state.ui?.prime_picks?.visible_cards || 5), 1, 5);
  if (rows.length <= maxVisible) return rows;
  const i = ((state.featuredIndex % rows.length) + rows.length) % rows.length;
  if (maxVisible === 5) return [rows[(i - 2 + rows.length) % rows.length], rows[(i - 1 + rows.length) % rows.length], rows[i], rows[(i + 1) % rows.length], rows[(i + 2) % rows.length]];
  const output = [rows[i]];
  for (let step = 1; output.length < maxVisible; step += 1) output.push(rows[(i + step) % rows.length]);
  return output;
}

function renderDots(rows) {
  const host = $("carouselDots"); if (!host) return;
  host.innerHTML = "";
  if (state.allPredictions || rows.length <= 1) { host.hidden = true; return; }
  host.hidden = false;
  rows.forEach((_, i) => {
    const b = document.createElement("button"); b.type = "button"; b.className = i === state.featuredIndex % rows.length ? "active" : ""; b.setAttribute("aria-label", `Prime Pick ${i + 1}`);
    b.addEventListener("click", () => { state.featuredIndex = i; renderPredictions(); });
    host.appendChild(b);
  });
}

function bindCards(rows) {
  const byId = new Map(rows.map((x) => [String(x.id), x]));
  document.querySelectorAll(".pick-card[data-match-id]").forEach((card) => {
    const open = () => { const match = byId.get(String(card.dataset.matchId)); if (match) openMatchDialog(match); };
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  });
}

function renderPredictions() {
  const filtered = currentFilteredPredictions();
  const primes = primeRows(filtered);
  const grid = $("predictionGrid");
  $("matchCount").textContent = String(primes.length);
  $("viewAllButton").textContent = state.allPredictions ? "← Prime Picks" : (state.currentRoute === "dashboard" ? "Open Prime Picks →" : "All predictions →");
  grid.classList.toggle("expanded", state.allPredictions);
  $("pickCarouselShell").classList.toggle("expanded", state.allPredictions);
  $("prevPick").hidden = state.allPredictions || primes.length <= 1;
  $("nextPick").hidden = state.allPredictions || primes.length <= 1;

  if (!filtered.length) {
    grid.innerHTML = '<div class="state-card">No current prediction matches these filters.</div>';
    renderDots([]); return;
  }

  if (state.allPredictions) {
    const all = [...filtered].sort((a, b) => Number(b.probability || 0) - Number(a.probability || 0)).slice(0, 30);
    grid.innerHTML = all.map((m, i) => cardHtml(m, false, i)).join(""); renderDots([]); bindCards(all); return;
  }

  state.featuredIndex = ((state.featuredIndex % primes.length) + primes.length) % primes.length;
  const windowRows = primeWindow(primes);
  const featured = primes[state.featuredIndex];
  grid.innerHTML = windowRows.map((m) => cardHtml(m, String(m.id) === String(featured.id), primes.findIndex((x) => String(x.id) === String(m.id)))).join("");
  renderDots(primes); bindCards(windowRows);
}

function openMatchDialog(match) {
  const factors = modelFactors(match);
  $("dialogContent").innerHTML = `<div class="dialog-eyebrow">${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}${match.round ? ` · ${escapeHtml(match.round)}` : ""}</div>
    <h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2>
    <div class="dialog-pick"><div><small>BlinQ Prime analysis</small><strong>${escapeHtml(match.pick)}</strong></div><div class="dialog-prob">${fmtPct(match.probability)}<span class="confidence ${escapeHtml(match.confidence)}">${escapeHtml(match.confidence.toUpperCase())}</span></div></div>
    <div class="dialog-section"><h3>Model factor view</h3>${factors.map((f) => `<div class="dialog-factor"><span>${escapeHtml(f.label)}</span>${meterHtml(f)}<small>${f.kind === "depth" ? "data coverage" : f.score >= 57 ? "favours pick" : f.score <= 43 ? "favours opponent" : "balanced"}</small></div>`).join("")}</div>
    <div class="dialog-meta"><span>Prime score: ${primeScore(match).toFixed(1)}</span><span>Surface: ${escapeHtml(match.surface)}</span><span>Time: ${escapeHtml(fmtTime(match.date))}</span><span>Model: ${escapeHtml(match.model || "current")}</span></div>
    <p class="technical-note">Factor bars are normalized indicators from internal TBT features. They are not bookmaker odds, standalone probabilities or externally supplied Elo ratings.</p>`;
  $("matchDialog").showModal();
}

function setRouteHeader(title, subtitle, eyebrow = "TENNIS INTELLIGENCE") {
  $("pageTitle").textContent = title;
  $("pageSubtitle").textContent = subtitle;
  $("pageEyebrow").textContent = eyebrow;
}

function setActiveRoute(route) {
  state.currentRoute = route;
  document.querySelectorAll(".nav-link").forEach((x) => x.classList.toggle("active", x.dataset.route === route));
}

function navigate(route) {
  const item = navItem(route);
  if (item) {
    const access = routeAccess(item);
    if (!access.allowed) { showLocked(item); return; }
  }
  setActiveRoute(route);
  state.allPredictions = false;
  state.featuredIndex = 0;
  if (route === "dashboard" || route === "prime_picks") {
    $("dashboardView").hidden = false; $("moduleView").hidden = true;
    $("bannerZoneTop").hidden = route !== "dashboard";
    $("bannerZoneBottom").hidden = route !== "dashboard";
    if (route === "dashboard") {
      setRouteHeader("Dashboard", "Recommended Prime Picks and current tennis intelligence.");
      $("picksTitle").textContent = "BlinQ Prime Picks";
      $("picksSubtitle").textContent = "The strongest current model selections based on confidence, data quality and signal agreement.";
    } else {
      setRouteHeader("BlinQ Prime Picks", "The best current selections our model can support with the available data.", "PRE-MATCH ANALYTICS");
      $("picksTitle").textContent = "BlinQ Prime Picks · Top 10";
      $("picksSubtitle").textContent = "Navigate through the current Top 10 without reloading the page.";
    }
    renderPredictions();
  } else {
    $("dashboardView").hidden = true; $("moduleView").hidden = false;
    renderCurrentModule();
  }
  history.replaceState(null, "", `#${route.replaceAll("_", "-")}`);
}

function moduleShell(title, subtitle, body) {
  setRouteHeader(title, subtitle);
  $("moduleView").innerHTML = `<div class="module-card">${body}</div>`;
}

function renderTournaments() {
  const groups = new Map();
  state.predictions.forEach((m) => {
    if (!groups.has(m.tournament)) groups.set(m.tournament, []);
    groups.get(m.tournament).push(m);
  });
  const cards = [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([name, rows]) => {
    const top = primeRows(rows)[0];
    return `<article class="data-tile tournament-tile"><span>${escapeHtml(rows[0]?.tour || "")}</span><h3>${escapeHtml(name)}</h3><p>${rows.length} current matches · ${escapeHtml(rows[0]?.surface || "surface unknown")}</p>${top ? `<div class="mini-pick">Top model pick <strong>${escapeHtml(top.pick)}</strong> ${fmtPct(top.probability)}</div>` : ""}</article>`;
  }).join("");
  moduleShell("Tournaments", "Current tournaments with live prediction coverage.", `<div class="module-grid">${cards || '<div class="state-card">No current tournaments in the prediction feed.</div>'}</div>`);
}

function renderPlayers() {
  const players = new Map();
  state.predictions.forEach((m) => {
    [[m.p1Id, m.p1, m.p1Rank, m.p1Image], [m.p2Id, m.p2, m.p2Rank, m.p2Image]].forEach(([id, name, rank, image]) => {
      const key = String(id || name); if (!players.has(key)) players.set(key, { name, rank, image, matches: 0 }); players.get(key).matches += 1;
    });
  });
  const body = [...players.values()].sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999)).slice(0, 30).map((p) => `<article class="player-list-card">${playerAvatarHtml(p.name, p.image)}<div><strong>${escapeHtml(p.name)}</strong><small>${p.rank ? `Rank #${escapeHtml(p.rank)}` : "Ranking unavailable"} · ${p.matches} current match${p.matches === 1 ? "" : "es"}</small></div><button class="btn btn-ghost" type="button">Profile</button></article>`).join("");
  moduleShell("Players", "Player profiles and extended statistics for higher tiers.", `<div class="player-list">${body || '<div class="state-card">No players in the current prediction feed.</div>'}</div>`);
}

function renderStats() {
  const tour = {}; const surface = {}; const confidence = {};
  state.predictions.forEach((m) => { tour[m.tour || "Unknown"] = (tour[m.tour || "Unknown"] || 0) + 1; surface[m.surface || "unknown"] = (surface[m.surface || "unknown"] || 0) + 1; confidence[m.confidence || "low"] = (confidence[m.confidence || "low"] || 0) + 1; });
  const tiles = [
    ["Current predictions", state.predictions.length],
    ["Prime Picks", primeRows(state.predictions).length],
    ["ATP / WTA", `${tour.ATP || 0} / ${tour.WTA || 0}`],
    ["High confidence", confidence.high || 0],
  ].map(([label, value]) => `<article class="metric-card"><small>${label}</small><strong>${value}</strong></article>`).join("");
  const breakdown = (title, data) => `<article class="breakdown-card"><h3>${title}</h3>${Object.entries(data).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${v}</strong></div>`).join("") || '<p>No data.</p>'}</article>`;
  moduleShell("Stats & Insights", "Live summaries from the currently loaded prediction board.", `<div class="metric-grid">${tiles}</div><div class="breakdown-grid">${breakdown("By tour", tour)}${breakdown("By surface", surface)}${breakdown("By confidence", confidence)}</div>`);
}

async function renderModelPerformance() {
  moduleShell("Model Performance", "Current production model status and quality metrics.", '<div class="state-card">Loading model status…</div>');
  try {
    const data = await getJSON(api("/api/v1/model/status"));
    $("moduleView").querySelector(".module-card").innerHTML = `<pre class="json-view">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  } catch (error) {
    $("moduleView").querySelector(".module-card").innerHTML = `<div class="state-card error">Model status endpoint unavailable.<small>${escapeHtml(error.message)}</small></div>`;
  }
}

async function renderBacktests() {
  moduleShell("Backtests", "Chronological holdout and walk-forward evaluation.", '<div class="state-card">Loading latest backtest…</div>');
  try {
    const data = await getJSON(api("/api/v1/backtest/latest"));
    $("moduleView").querySelector(".module-card").innerHTML = `<pre class="json-view">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  } catch (error) {
    $("moduleView").querySelector(".module-card").innerHTML = `<div class="state-card error">Backtest endpoint unavailable.<small>${escapeHtml(error.message)}</small></div>`;
  }
}

function renderAccountPage() {
  const user = state.user;
  moduleShell("Account", "Plan, access and subscription overview.", `<div class="account-page-grid"><article class="account-hero"><div class="avatar avatar-xl">${escapeHtml(initials(user.name))}</div><div><small>ACCOUNT</small><h2>${escapeHtml(user.name)}</h2><p>${escapeHtml(user.planLabel)} · ${escapeHtml(user.entitlement || "Active")}</p></div></article><article class="access-summary"><h3>Current access</h3><p>All menu modules stay visible. Locked modules open an upgrade/data notice instead of disappearing.</p><button class="btn btn-primary" data-upgrade type="button">Upgrade plan</button></article></div>`);
}

function learnBody(route) {
  const content = {
    how_blinq_works: ["How BlinQ Works", "A simple view of the prediction pipeline.", ["1. Real match data is processed point-in-time.", "2. TBT creates strength, surface, form, workload and matchup features.", "3. The model returns a calibrated match-win probability.", "4. BlinQ Prime Picks rank the strongest supported selections.", "5. The user sees probability plus model context, not a guaranteed outcome."]],
    methodology: ["Methodology", "Technical model methodology.", ["Point-in-time feature construction", "Internal overall and surface Elo", "Decayed and opponent-adjusted form", "H2H shrinkage", "Rest, layoff and workload signals", "Chronological validation and probability calibration"]],
    model_data: ["Model & Data", "What comes from providers and what TBT calculates internally.", ["Provider: fixtures, results, tournament, surface, ranking and available match statistics", "TBT: Elo, surface Elo, form, H2H, workload and model features", "Predictions are precomputed and stored before frontend traffic", "No bookmaker edge is shown until a real odds feed is connected"]],
    faq: ["FAQ", "Common questions about BlinQ predictions.", ["Prime Pick means a strongest current model selection, not a safe or guaranteed bet.", "Probability is the calibrated model estimate for the match winner.", "Factor bars are normalized internal indicators, not separate probabilities.", "Value Picks will require live bookmaker odds before activation."]],
    responsible_use: ["Responsible Use", "Probabilities are not guarantees.", ["BlinQ is an analytical tool.", "Prime Picks must never be presented as certain outcomes.", "Do not chase losses or stake money you cannot afford to lose.", "Use model probabilities as one input in a broader decision process."]],
  };
  return content[route];
}

function renderLearn(route) {
  const [title, subtitle, points] = learnBody(route);
  moduleShell(title, subtitle, `<div class="learn-article"><ol>${points.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ol></div>`);
}

function renderPendingModule(route) {
  const item = navItem(route);
  const access = routeAccess(item);
  moduleShell(item?.label || "Module", access.reason || "This module is not connected yet.", `<div class="state-card"><strong>${escapeHtml(item?.label || "Module")}</strong><small>${escapeHtml(access.reason || "Data source not connected yet.")}</small></div>`);
}

function bannerManagerZoneEditor(zoneName) {
  const zone = state.ui?.banner_zones?.[zoneName] || { count: 1, items: [] };
  const count = clamp(Number(zone.count || 1), 1, 4);
  const slots = Array.from({ length: 4 }, (_, i) => zone.items?.[i] || {});
  return `<section class="admin-editor" data-banner-zone="${zoneName}"><div class="admin-editor-head"><div><span>${zoneName.toUpperCase()} BANNER ZONE</span><h3>${sizeHint(count)}</h3></div><label>Layout<select class="admin-count" data-zone="${zoneName}">${[1,2,3,4].map((n)=>`<option value="${n}" ${n===count?"selected":""}>${n} banner${n>1?"s":""}</option>`).join("")}</select></label></div><div class="admin-slot-grid">${slots.map((item,i)=>`<article class="admin-slot" data-zone="${zoneName}" data-index="${i}" ${i>=count?'hidden':''}><strong>Slot ${i+1}</strong><label>Headline<input data-field="headline" value="${escapeHtml(item.headline || "")}" /></label><label>Text<input data-field="text" value="${escapeHtml(item.text || "")}" /></label><label>Link<input data-field="link" value="${escapeHtml(item.link || "#account")}" /></label><label>Image URL / path<input data-field="image" value="${escapeHtml(item.image || "")}" /></label><label class="file-label">Preview upload<input type="file" accept="image/*" data-banner-upload /></label><small class="admin-image-note">Upload is stored as a local browser preview in this build. Use the final storage API for global publishing.</small></article>`).join("")}</div></section>`;
}

function renderAdminBanners() {
  moduleShell("Banner Manager", "Switch 1–4 banners per zone and preview creative without editing HTML/CSS.", `${bannerManagerZoneEditor("top")}${bannerManagerZoneEditor("bottom")}<div class="admin-actions"><button class="btn btn-primary" id="saveBannerConfig" type="button">Save local preview</button><button class="btn btn-ghost" id="exportBannerConfig" type="button">Export JSON</button><button class="btn btn-ghost" id="resetBannerConfig" type="button">Reset local preview</button></div>`);
  bindBannerManager();
}

function readBannerEditorToState() {
  ["top", "bottom"].forEach((zoneName) => {
    const editor = document.querySelector(`[data-banner-zone="${zoneName}"]`); if (!editor) return;
    const zone = state.ui.banner_zones[zoneName]; zone.count = Number(editor.querySelector(".admin-count").value || 1);
    editor.querySelectorAll(".admin-slot").forEach((slot) => {
      const i = Number(slot.dataset.index); zone.items[i] = zone.items[i] || { enabled: true };
      slot.querySelectorAll("[data-field]").forEach((input) => { zone.items[i][input.dataset.field] = input.value; });
    });
  });
}

function bindBannerManager() {
  document.querySelectorAll(".admin-count").forEach((select) => select.addEventListener("change", () => {
    const zone = select.dataset.zone; const count = Number(select.value || 1);
    document.querySelectorAll(`.admin-slot[data-zone="${zone}"]`).forEach((slot) => { slot.hidden = Number(slot.dataset.index) >= count; });
    select.closest(".admin-editor-head").querySelector("h3").textContent = sizeHint(count);
  }));
  document.querySelectorAll("[data-banner-upload]").forEach((input) => input.addEventListener("change", () => {
    const file = input.files?.[0]; if (!file) return;
    if (file.size > 1_500_000) { alert("For local preview keep the image under 1.5 MB. Production upload will use Storage."); input.value = ""; return; }
    const reader = new FileReader(); reader.onload = () => { input.closest(".admin-slot").querySelector('[data-field="image"]').value = String(reader.result || ""); }; reader.readAsDataURL(file);
  }));
  $("saveBannerConfig")?.addEventListener("click", () => {
    readBannerEditorToState();
    localStorage.setItem("blinq_admin_ui_override", JSON.stringify({ banner_zones: state.ui.banner_zones, header_ad: state.ui.header_ad }));
    renderBannerZones(); alert("Local admin preview saved in this browser.");
  });
  $("exportBannerConfig")?.addEventListener("click", () => {
    readBannerEditorToState();
    const blob = new Blob([JSON.stringify({ banner_zones: state.ui.banner_zones, header_ad: state.ui.header_ad }, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "blinq-banner-config.json"; a.click(); URL.revokeObjectURL(a.href);
  });
  $("resetBannerConfig")?.addEventListener("click", () => { localStorage.removeItem("blinq_admin_ui_override"); location.reload(); });
}

function renderAdminUsers() {
  moduleShell("User Management", "Admin-only account management shell.", '<div class="state-card">User management UI is prepared. Connect it to the account/subscription backend before enabling writes.</div>');
}

function renderAdminAccess() {
  const rows = (state.ui?.navigation?.main || []).map((item) => `<tr><td>${escapeHtml(item.label)}</td><td>${escapeHtml((item.allowed_plans || []).join(", "))}</td><td>${item.data_status ? escapeHtml(item.data_status) : "ready"}</td></tr>`).join("");
  moduleShell("Plan Access", "Current frontend access matrix.", `<div class="table-wrap"><table class="access-table"><thead><tr><th>Module</th><th>Allowed plans</th><th>Data status</th></tr></thead><tbody>${rows}</tbody></table></div>`);
}

function renderCurrentModule() {
  const route = state.currentRoute;
  if (route === "tournaments") return renderTournaments();
  if (route === "players") return renderPlayers();
  if (route === "stats") return renderStats();
  if (route === "model") return renderModelPerformance();
  if (route === "backtests") return renderBacktests();
  if (route === "account") return renderAccountPage();
  if (["how_blinq_works", "methodology", "model_data", "faq", "responsible_use"].includes(route)) return renderLearn(route);
  if (["value_picks", "ace_picks", "games_sets"].includes(route)) return renderPendingModule(route);
  if (route === "admin_banners") return renderAdminBanners();
  if (route === "admin_users") return renderAdminUsers();
  if (route === "admin_access") return renderAdminAccess();
  return moduleShell("Module", "This module is prepared for connection.", '<div class="state-card">Prepared.</div>');
}

function routeFromHash() {
  const raw = String(location.hash || "#dashboard").replace(/^#/, "");
  const aliases = {
    "how-it-works": "how_blinq_works",
    "prime-picks": "prime_picks",
    "value-picks": "value_picks",
    "ace-picks": "ace_picks",
    "games-sets": "games_sets",
    "model-data": "model_data",
    "responsible-use": "responsible_use",
    "admin-banners": "admin_banners",
    "admin-users": "admin_users",
    "admin-access": "admin_access"
  };
  const token = aliases[raw] || raw.replaceAll("-", "_");
  return navItem(token) ? token : "dashboard";
}

function setupEvents() {
  $("refreshButton").addEventListener("click", loadPredictions);
  ["tourFilter", "tournamentFilter", "surfaceFilter", "confidenceFilter"].forEach((id) => $(id).addEventListener("change", () => { state.featuredIndex = 0; state.allPredictions = false; renderPredictions(); }));
  $("searchInput").addEventListener("input", () => { state.featuredIndex = 0; state.allPredictions = false; renderPredictions(); });
  $("prevPick").addEventListener("click", () => { const rows = primeRows(); if (!rows.length) return; state.featuredIndex = (state.featuredIndex - 1 + rows.length) % rows.length; renderPredictions(); });
  $("nextPick").addEventListener("click", () => { const rows = primeRows(); if (!rows.length) return; state.featuredIndex = (state.featuredIndex + 1) % rows.length; renderPredictions(); });
  $("viewAllButton").addEventListener("click", () => {
    if (state.currentRoute === "dashboard" && !state.allPredictions) return navigate("prime_picks");
    state.allPredictions = !state.allPredictions; renderPredictions();
  });

  document.addEventListener("click", (event) => {
    const closeId = event.target.closest("[data-dialog-close]")?.dataset.dialogClose;
    if (closeId) { $(closeId)?.close(); return; }
    if (event.target.closest("[data-upgrade]")) { event.preventDefault(); openUpgrade(); return; }
    const plan = event.target.closest("[data-plan-choice]")?.dataset.planChoice;
    if (plan) { alert(`Checkout for ${plan.toUpperCase()} will be connected in the dedicated upgrade window.`); return; }
    const route = event.target.closest("[data-route]")?.dataset.route;
    if (route) { event.preventDefault(); navigate(route); }
  });

  ["matchDialog", "lockedDialog", "upgradeDialog"].forEach((id) => $(id)?.addEventListener("click", (event) => { if (event.target === $(id)) $(id).close(); }));
}

async function boot() {
  setupEvents();
  await loadUiConfig();
  state.currentRoute = routeFromHash();
  renderNavigation();
  navigate(state.currentRoute);
  await loadPredictions();
  setInterval(loadPredictions, Math.max(1, Number(cfg.refreshMinutes || 5)) * 60 * 1000);
}

boot();
