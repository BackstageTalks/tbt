const cfg = window.BLINQ_CONFIG || {};

const state = {
  predictions: [],
  ui: null,
  user: null,
  currentRoute: "dashboard",
  featuredIndex: 0,
  allPredictions: false,
  playerProfiles: [],
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

function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", year: "numeric" }).format(d);
}

function fmtInt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? new Intl.NumberFormat().format(n) : "—";
}

function pctMetric(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(Math.abs(n) <= 1.000001 ? n * 100 : n).toFixed(digits)}%`;
}

function decMetric(value, digits = 4) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function metricCard(label, value, note = "") {
  return `<article class="metric-card performance-metric"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong>${note ? `<span>${escapeHtml(note)}</span>` : ""}</article>`;
}

function metricDelta(value, goodWhenPositive = true) {
  const n = Number(value);
  if (!Number.isFinite(n)) return { text: "—", cls: "neutral" };
  const good = goodWhenPositive ? n > 0 : n < 0;
  const bad = goodWhenPositive ? n < 0 : n > 0;
  return { text: `${n > 0 ? "+" : ""}${(n * 100).toFixed(2)} pp`, cls: good ? "positive" : bad ? "negative" : "neutral" };
}

function numericDelta(value, goodWhenNegative = true, digits = 4) {
  const n = Number(value);
  if (!Number.isFinite(n)) return { text: "—", cls: "neutral" };
  const good = goodWhenNegative ? n < 0 : n > 0;
  const bad = goodWhenNegative ? n > 0 : n < 0;
  return { text: `${n > 0 ? "+" : ""}${n.toFixed(digits)}`, cls: good ? "positive" : bad ? "negative" : "neutral" };
}

function normalizeMetricObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function calibrationTable(metrics) {
  const bins = Array.isArray(metrics?.calibration_bins) ? metrics.calibration_bins : [];
  if (!bins.length) return '<div class="state-card compact-state">Calibration bins are not stored for this model snapshot.</div>';
  const rows = bins.map((bin) => {
    const lo = Number(bin.min_probability || 0) * 100;
    const hi = Number(bin.max_probability || 0) * 100;
    const predicted = Number(bin.mean_probability || 0) * 100;
    const actual = Number(bin.actual_win_rate || 0) * 100;
    const gap = actual - predicted;
    return `<tr><td>${lo.toFixed(0)}–${hi.toFixed(0)}%</td><td>${fmtInt(bin.count)}</td><td>${predicted.toFixed(2)}%</td><td>${actual.toFixed(2)}%</td><td class="${Math.abs(gap) <= 2 ? "positive" : Math.abs(gap) <= 5 ? "neutral" : "negative"}">${gap > 0 ? "+" : ""}${gap.toFixed(2)} pp</td></tr>`;
  }).join("");
  return `<div class="table-wrap"><table class="access-table performance-table"><thead><tr><th>Probability band</th><th>N</th><th>Mean predicted</th><th>Actual win rate</th><th>Gap</th></tr></thead><tbody>${rows}</tbody></table></div>`;
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
  const engineLogo = document.querySelector(".engine-full-logo");
  if (engineLogo && branding.engine_logo) engineLogo.src = branding.engine_logo;
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
      prime: raw.prime || raw.prediction.prime || {},
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
    prime: raw.prime || {},
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
  if (Array.isArray(match.prime?.factors) && match.prime.factors.length) {
    return match.prime.factors.map((factor) => ({
      label: factor.label || "Model factor",
      score: clamp(Number(factor.score ?? 50), 0, 100),
      kind: factor.kind || "advantage",
    }));
  }
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

function primeRankingValue(match) {
  const backend = Number(match.prime?.ranking_value_pct);
  if (Number.isFinite(backend)) return backend;
  return Number(match.probability || 0);
}

function primeTieBreakers(match) {
  const factors = modelFactors(match);
  const advantages = factors.filter((x) => x.kind === "advantage");
  const agreement = Number(match.prime?.factor_agreement_pct);
  const factorAgreement = Number.isFinite(agreement)
    ? agreement
    : (advantages.length ? advantages.reduce((sum, x) => sum + x.score, 0) / advantages.length : 50);
  const backendDepth = Number(match.prime?.data_depth_pct);
  const dataDepth = Number.isFinite(backendDepth)
    ? backendDepth
    : (factors.find((x) => x.kind === "depth")?.score ?? 50);
  return { factorAgreement, dataDepth };
}

function primeRows(rows = currentFilteredPredictions()) {
  const limit = clamp(Number(state.ui?.prime_picks?.limit || 10), 1, 20);
  return [...rows].sort((a, b) => {
    const probabilityDelta = primeRankingValue(b) - primeRankingValue(a);
    if (Math.abs(probabilityDelta) > 1e-9) return probabilityDelta;
    const qa = primeTieBreakers(a);
    const qb = primeTieBreakers(b);
    const agreementDelta = qb.factorAgreement - qa.factorAgreement;
    if (Math.abs(agreementDelta) > 1e-9) return agreementDelta;
    return qb.dataDepth - qa.dataDepth;
  }).slice(0, limit);
}

function primeLevel(match, rankIndex) {
  const settings = state.ui?.prime_picks || {};
  const topThreshold = Number(settings.top_prime_probability_pct ?? 90);
  const primeThreshold = Number(settings.prime_probability_pct ?? 80);
  const probability = primeRankingValue(match);
  if (probability >= topThreshold) return rankIndex === 0 ? "top_prime_1" : "top_prime";
  if (probability >= primeThreshold) return "prime";
  return "candidate";
}

function factorValueLabel(factor) {
  if (factor.kind === "depth") {
    if (factor.score >= 85) return "Excellent";
    if (factor.score >= 65) return "Good";
    if (factor.score >= 40) return "Medium";
    return "Limited";
  }
  if (factor.score >= 72) return "Strong +";
  if (factor.score >= 57) return "Advantage";
  if (factor.score <= 28) return "Strong −";
  if (factor.score <= 43) return "Against";
  return "Balanced";
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
  const level = primeLevel(match, rankIndex);
  const ribbon = level === "top_prime_1"
    ? '<div class="featured-ribbon"><span>★ TOP PRIME · #1</span></div>'
    : level === "top_prime"
      ? '<div class="prime-badge prime-badge-top">★ TOP PRIME</div>'
      : level === "prime"
        ? '<div class="prime-badge">★ PRIME PICK</div>'
        : '<div class="prime-badge prime-badge-candidate">PRIME CANDIDATE</div>';
  const quality = primeTieBreakers(match);
  return `<article class="pick-card${featured ? " featured" : ""}" data-match-id="${escapeHtml(match.id)}" tabindex="0" role="button">
    ${ribbon}
    <div class="pick-meta"><span class="tour-tournament">${escapeHtml(meta)}</span><span>${escapeHtml(fmtTime(match.date))}</span><span class="surface-badge">${escapeHtml(surface)}</span><span class="card-star">☆</span></div>
    <div class="players">
      <div class="player">${playerAvatarHtml(match.p1, match.p1Image)}<strong class="player-name">${escapeHtml(match.p1)}</strong><small class="player-rank">${match.p1Rank ? `#${escapeHtml(match.p1Rank)}` : "NR"}</small></div>
      <div class="vs">VS</div>
      <div class="player">${playerAvatarHtml(match.p2, match.p2Image)}<strong class="player-name">${escapeHtml(match.p2)}</strong><small class="player-rank">${match.p2Rank ? `#${escapeHtml(match.p2Rank)}` : "NR"}</small></div>
    </div>
    <div class="pick-summary"><div><small>BlinQ Pick</small><strong class="pick-name">${escapeHtml(match.pick || "—")}</strong></div><div class="prob-wrap"><small>Win Probability</small><div class="probability">${fmtPct(match.probability)}</div><span class="confidence ${escapeHtml(match.confidence)}">${escapeHtml(match.confidence.toUpperCase())}</span></div></div>
    <div class="factors">${factors.map((factor) => `<div class="factor-row" title="Normalized explanatory indicator derived from point-in-time TBT features."><span class="factor-label">${escapeHtml(factor.label)}</span>${meterHtml(factor)}<span class="factor-value">${escapeHtml(factorValueLabel(factor))}</span></div>`).join("")}</div>
    <div class="quality-strip"><span>Agreement <strong>${quality.factorAgreement.toFixed(0)}%</strong></span><span>Data depth <strong>${quality.dataDepth.toFixed(0)}%</strong></span></div>
    <div class="pick-footer"><span>#${rankIndex + 1} by probability</span><span>${escapeHtml(match.model || "model —")}</span><span>${escapeHtml(fmtShortGenerated(match.generatedAt))}</span></div>
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

function median(values) {
  const nums = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}

function renderDashboardSnapshot(rows = currentFilteredPredictions()) {
  const host = $("dashboardSnapshot");
  if (!host) return;
  if (state.currentRoute !== "dashboard") { host.hidden = true; return; }
  host.hidden = false;

  const sorted = [...rows].sort((a, b) => primeRankingValue(b) - primeRankingValue(a));
  const top = sorted[0];
  const high = rows.filter((m) => m.confidence === "high").length;
  const tournaments = new Set(rows.map((m) => m.tournament).filter(Boolean)).size;
  const depthValues = rows.map((m) => primeTieBreakers(m).dataDepth);
  const medianDepth = median(depthValues);
  const threshold = Number(state.ui?.prime_picks?.prime_probability_pct ?? 80);
  const thresholdCount = rows.filter((m) => primeRankingValue(m) >= threshold).length;

  const cards = [
    ["Upcoming", fmtInt(rows.length), "current board"],
    ["Top probability", top ? fmtPct(top.probability) : "—", top ? top.pick : "no current pick"],
    [`≥ ${threshold.toFixed(0)}%`, fmtInt(thresholdCount), "current candidates"],
    ["High confidence", fmtInt(high), "model confidence band"],
    ["Tournaments", fmtInt(tournaments), "active in feed"],
    ["Median data depth", medianDepth == null ? "—" : `${medianDepth.toFixed(0)}%`, "context quality"],
  ];

  host.innerHTML = cards.map(([label, value, note]) => `
    <article class="snapshot-card">
      <small>${escapeHtml(label)}</small>
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(note)}</span>
    </article>`).join("");
}

function renderPredictions() {
  const filtered = currentFilteredPredictions();
  renderDashboardSnapshot(filtered);
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
  $("matchDialog")?.classList.remove("player-profile-dialog");
  const factors = modelFactors(match);
  $("dialogContent").innerHTML = `<div class="dialog-eyebrow">${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}${match.round ? ` · ${escapeHtml(match.round)}` : ""}</div>
    <h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2>
    <div class="dialog-pick"><div><small>BlinQ Prime analysis</small><strong>${escapeHtml(match.pick)}</strong></div><div class="dialog-prob">${fmtPct(match.probability)}<span class="confidence ${escapeHtml(match.confidence)}">${escapeHtml(match.confidence.toUpperCase())}</span></div></div>
    <div class="dialog-section"><h3>Model factor view</h3>${factors.map((f) => `<div class="dialog-factor"><span>${escapeHtml(f.label)}</span>${meterHtml(f)}<small>${f.kind === "depth" ? "data coverage" : f.score >= 57 ? "favours pick" : f.score <= 43 ? "favours opponent" : "balanced"}</small></div>`).join("")}</div>
    <div class="dialog-meta"><span>Prime rank basis: calibrated probability</span><span>Surface: ${escapeHtml(match.surface)}</span><span>Time: ${escapeHtml(fmtTime(match.date))}</span><span>Model: ${escapeHtml(match.model || "current")}</span></div>
    <p class="technical-note">${escapeHtml(match.prime?.technical_note || "BlinQ Prime Picks are ranked by calibrated model win probability. Factor bars and Data Depth explain model context; they are not bookmaker odds or a second probability.")}</p>`;
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
    if ($("dashboardSnapshot")) $("dashboardSnapshot").hidden = route !== "dashboard";
    if (route === "dashboard") {
      setRouteHeader("Dashboard", "Recommended Prime Picks and current tennis intelligence.");
      $("picksTitle").textContent = "BlinQ Prime Picks";
      $("picksSubtitle").textContent = "Top current selections ranked by calibrated model win probability. Quality factors are shown as context.";
    } else {
      setRouteHeader("BlinQ Prime Picks", "The best current selections our model can support with the available data.", "PRE-MATCH ANALYTICS");
      $("picksTitle").textContent = "BlinQ Prime Picks · Top 10";
      $("picksSubtitle").textContent = "Top 10 ranked by calibrated model win probability; factor agreement and data depth are tie-breakers only.";
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
    const key = m.tournament || "Unknown tournament";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  });

  const buildRows = () => [...groups.entries()].map(([name, rows]) => {
    const sorted = [...rows].sort((a, b) => primeRankingValue(b) - primeRankingValue(a));
    return {
      name,
      rows,
      top: sorted[0] || null,
      second: sorted[1] || null,
      surfaces: [...new Set(rows.map((x) => String(x.surface || "unknown").replaceAll("_", " ")))],
      tours: [...new Set(rows.map((x) => x.tour || "Unknown"))],
      high: rows.filter((x) => x.confidence === "high").length,
      topProbability: sorted[0] ? primeRankingValue(sorted[0]) : 0,
    };
  });

  moduleShell(
    "Tournaments",
    "Explore tournaments currently represented in the prediction feed.",
    `<div class="module-toolbar">
      <label class="search-box module-search"><span aria-hidden="true">⌕</span><input id="tournamentSearch" type="search" placeholder="Search tournaments…" /></label>
      <label class="module-select-label">Sort
        <select id="tournamentSort">
          <option value="probability">Strongest probability</option>
          <option value="matches">Most matches</option>
          <option value="name">Name A–Z</option>
        </select>
      </label>
    </div>
    <div class="module-grid" id="tournamentGrid"></div>`
  );

  const renderGrid = () => {
    const q = String($("tournamentSearch")?.value || "").trim().toLowerCase();
    const sort = $("tournamentSort")?.value || "probability";
    let items = buildRows().filter((item) => !q || `${item.name} ${item.tours.join(" ")} ${item.surfaces.join(" ")}`.toLowerCase().includes(q));
    items.sort((a, b) => sort === "matches"
      ? b.rows.length - a.rows.length || b.topProbability - a.topProbability
      : sort === "name"
        ? a.name.localeCompare(b.name)
        : b.topProbability - a.topProbability || b.rows.length - a.rows.length);

    const cards = items.map((item) => {
      const topPicks = [item.top, item.second].filter(Boolean);
      return `<article class="data-tile tournament-tile">
        <div class="tile-topline"><span>${escapeHtml(item.tours.join(" / "))}</span><small>${item.rows.length} match${item.rows.length === 1 ? "" : "es"}</small></div>
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.surfaces.join(" · "))} · ${item.high} high-confidence</p>
        <div class="tournament-picks">
          ${topPicks.map((pick, index) => `<div class="mini-pick"><span>${index === 0 ? "Strongest current pick" : "Next current pick"}</span><strong>${escapeHtml(pick.pick)}</strong><b>${fmtPct(pick.probability)}</b></div>`).join("")}
        </div>
        <button class="btn btn-ghost tournament-open" type="button" data-open-tournament="${escapeHtml(item.name)}">View predictions →</button>
      </article>`;
    }).join("");

    $("tournamentGrid").innerHTML = cards || '<div class="state-card">No current tournaments match this search.</div>';
    document.querySelectorAll("[data-open-tournament]").forEach((button) => button.addEventListener("click", () => {
      navigate("prime_picks");
      const select = $("tournamentFilter");
      if (select) {
        select.value = button.dataset.openTournament || "";
        state.featuredIndex = 0;
        renderPredictions();
      }
    }));
  };

  $("tournamentSearch")?.addEventListener("input", renderGrid);
  $("tournamentSort")?.addEventListener("change", renderGrid);
  renderGrid();
}


function buildPlayerProfiles() {
  const players = new Map();

  const add = (match, side) => {
    const isP1 = side === 1;
    const id = isP1 ? match.p1Id : match.p2Id;
    const name = isP1 ? match.p1 : match.p2;
    const rank = isP1 ? match.p1Rank : match.p2Rank;
    const image = isP1 ? match.p1Image : match.p2Image;
    const probability = Number(isP1 ? match.p1Prob : match.p2Prob);
    const opponent = isP1 ? match.p2 : match.p1;
    const opponentRank = isP1 ? match.p2Rank : match.p1Rank;
    const key = String(id || name || "");
    if (!key) return;

    if (!players.has(key)) players.set(key, { key, id, name, rank, image, matches: [] });
    const profile = players.get(key);
    if (!profile.rank && rank) profile.rank = rank;
    if (!profile.image && image) profile.image = image;
    const selected = String(match.pickId ?? "") === String(id ?? "")
      || String(match.pick || "").trim().toLowerCase() === String(name || "").trim().toLowerCase();
    profile.matches.push({ match, probability: Number.isFinite(probability) ? probability : 0, opponent, opponentRank, selected });
  };

  state.predictions.forEach((match) => { add(match, 1); add(match, 2); });

  return [...players.values()].map((profile) => {
    const probabilities = profile.matches.map((x) => x.probability).filter((x) => x > 0);
    profile.avgProbability = probabilities.length ? probabilities.reduce((a, b) => a + b, 0) / probabilities.length : 0;
    profile.bestProbability = probabilities.length ? Math.max(...probabilities) : 0;
    profile.selectedCount = profile.matches.filter((x) => x.selected).length;
    profile.surfaces = [...new Set(profile.matches.map((x) => x.match.surface).filter(Boolean))];
    return profile;
  });
}

function fmtPlayerProb(value) {
  return Number(value) > 0 ? fmtPct(value) : "—";
}

function openPlayerProfile(index) {
  const profile = state.playerProfiles[Number(index)];
  if (!profile) return;
  $("matchDialog")?.classList.add("player-profile-dialog");
  const strongest = [...profile.matches].sort((a, b) => b.probability - a.probability)[0];
  const rows = [...profile.matches]
    .sort((a, b) => new Date(a.match.date || 0) - new Date(b.match.date || 0))
    .map((entry) => `<tr>
      <td><strong>${escapeHtml(entry.opponent)}</strong>${entry.opponentRank ? `<small>#${escapeHtml(entry.opponentRank)}</small>` : ""}</td>
      <td>${escapeHtml(entry.match.tournament || "—")}</td>
      <td>${escapeHtml(String(entry.match.surface || "unknown").replaceAll("_", " "))}</td>
      <td>${escapeHtml(fmtDate(entry.match.date))} · ${escapeHtml(fmtTime(entry.match.date))}</td>
      <td><strong>${escapeHtml(fmtPlayerProb(entry.probability))}</strong></td>
      <td>${entry.selected ? '<span class="status-pill positive">BLINQ PICK</span>' : '<span class="status-pill neutral">OPPONENT PICK</span>'}</td>
    </tr>`).join("");

  $("dialogContent").innerHTML = `
    <div class="player-profile-hero">
      ${playerAvatarHtml(profile.name, profile.image)}
      <div><div class="dialog-eyebrow">CURRENT BOARD PLAYER PROFILE</div><h2>${escapeHtml(profile.name)}</h2><p>${profile.rank ? `Rank #${escapeHtml(profile.rank)}` : "Ranking unavailable"} · ${profile.matches.length} current match${profile.matches.length === 1 ? "" : "es"}</p></div>
    </div>
    <div class="metric-grid player-profile-metrics">
      ${metricCard("Current Matches", fmtInt(profile.matches.length), "prediction horizon")}
      ${metricCard("Average Probability", fmtPlayerProb(profile.avgProbability), "current board only")}
      ${metricCard("Strongest Probability", fmtPlayerProb(profile.bestProbability), strongest ? `vs ${strongest.opponent}` : "—")}
      ${metricCard("Selected Picks", fmtInt(profile.selectedCount), "BlinQ winner selections")}
    </div>
    <div class="table-wrap player-match-table-wrap"><table class="performance-table player-match-table">
      <thead><tr><th>Opponent</th><th>Tournament</th><th>Surface</th><th>Start</th><th>Player probability</th><th>Model side</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <p class="technical-note">This profile summarizes only matches currently loaded in the prediction horizon. It is not a fabricated career-stat profile and does not replace a dedicated historical player analytics API.</p>`;
  $("matchDialog").showModal();
}

function renderPlayers() {
  state.playerProfiles = buildPlayerProfiles();

  moduleShell(
    "Players",
    "Current-player explorer built only from the live prediction board; no career statistics are invented.",
    `<div class="module-toolbar">
      <label class="search-box module-search"><span aria-hidden="true">⌕</span><input id="playerSearch" type="search" placeholder="Search players…" /></label>
      <label class="module-select-label">Sort
        <select id="playerSort">
          <option value="rank">Official rank</option>
          <option value="probability">Strongest current probability</option>
          <option value="matches">Current matches</option>
          <option value="name">Name A–Z</option>
        </select>
      </label>
    </div>
    <div class="player-list" id="playerList"></div>`
  );

  const renderList = () => {
    const q = String($("playerSearch")?.value || "").trim().toLowerCase();
    const sort = $("playerSort")?.value || "rank";
    let rows = state.playerProfiles.map((p, index) => ({ p, index }))
      .filter(({ p }) => !q || `${p.name} ${p.surfaces.join(" ")}`.toLowerCase().includes(q));

    rows.sort((a, b) => sort === "probability"
      ? b.p.bestProbability - a.p.bestProbability || Number(a.p.rank || 99999) - Number(b.p.rank || 99999)
      : sort === "matches"
        ? b.p.matches.length - a.p.matches.length || b.p.bestProbability - a.p.bestProbability
        : sort === "name"
          ? a.p.name.localeCompare(b.p.name)
          : Number(a.p.rank || 99999) - Number(b.p.rank || 99999) || a.p.name.localeCompare(b.p.name));

    $("playerList").innerHTML = rows.slice(0, 60).map(({ p, index }) => `<article class="player-list-card">
      ${playerAvatarHtml(p.name, p.image)}
      <div><strong>${escapeHtml(p.name)}</strong><small>${p.rank ? `Rank #${escapeHtml(p.rank)}` : "Ranking unavailable"} · ${p.matches.length} current match${p.matches.length === 1 ? "" : "es"} · best ${escapeHtml(fmtPlayerProb(p.bestProbability))}</small></div>
      <button class="btn btn-ghost" type="button" data-player-profile="${index}">Profile</button>
    </article>`).join("") || '<div class="state-card">No current players match this search.</div>';

    document.querySelectorAll("[data-player-profile]").forEach((button) => button.addEventListener("click", () => openPlayerProfile(button.dataset.playerProfile)));
  };

  $("playerSearch")?.addEventListener("input", renderList);
  $("playerSort")?.addEventListener("change", renderList);
  renderList();
}


function renderStats() {
  const tour = {};
  const surface = {};
  const confidence = {};
  const tournament = {};
  const probabilityBands = { "50–59.9%": 0, "60–69.9%": 0, "70–79.9%": 0, "80–89.9%": 0, "90%+": 0 };
  const depthBands = { "Limited <40%": 0, "Medium 40–64%": 0, "Good 65–84%": 0, "Excellent 85%+": 0 };
  const probabilities = [];
  const depths = [];
  const agreements = [];

  state.predictions.forEach((m) => {
    tour[m.tour || "Unknown"] = (tour[m.tour || "Unknown"] || 0) + 1;
    surface[m.surface || "unknown"] = (surface[m.surface || "unknown"] || 0) + 1;
    confidence[m.confidence || "low"] = (confidence[m.confidence || "low"] || 0) + 1;
    tournament[m.tournament || "Unknown"] = (tournament[m.tournament || "Unknown"] || 0) + 1;

    const p = primeRankingValue(m);
    probabilities.push(p);
    if (p >= 90) probabilityBands["90%+"] += 1;
    else if (p >= 80) probabilityBands["80–89.9%"] += 1;
    else if (p >= 70) probabilityBands["70–79.9%"] += 1;
    else if (p >= 60) probabilityBands["60–69.9%"] += 1;
    else probabilityBands["50–59.9%"] += 1;

    const quality = primeTieBreakers(m);
    depths.push(quality.dataDepth);
    agreements.push(quality.factorAgreement);
    if (quality.dataDepth >= 85) depthBands["Excellent 85%+"] += 1;
    else if (quality.dataDepth >= 65) depthBands["Good 65–84%"] += 1;
    else if (quality.dataDepth >= 40) depthBands["Medium 40–64%"] += 1;
    else depthBands["Limited <40%"] += 1;
  });

  const topProbability = probabilities.length ? Math.max(...probabilities) : null;
  const medianProbability = median(probabilities);
  const medianDepth = median(depths);
  const medianAgreement = median(agreements);
  const threshold = Number(state.ui?.prime_picks?.prime_probability_pct ?? 80);
  const thresholdCount = probabilities.filter((p) => p >= threshold).length;

  const tiles = [
    ["Current predictions", fmtInt(state.predictions.length), "live board"],
    ["Top probability", topProbability == null ? "—" : `${topProbability.toFixed(1)}%`, "strongest current selection"],
    ["Median probability", medianProbability == null ? "—" : `${medianProbability.toFixed(1)}%`, "winner side"],
    [`≥ ${threshold.toFixed(0)}% candidates`, fmtInt(thresholdCount), "configured Prime threshold"],
    ["Median data depth", medianDepth == null ? "—" : `${medianDepth.toFixed(0)}%`, "context coverage"],
    ["Median agreement", medianAgreement == null ? "—" : `${medianAgreement.toFixed(0)}%`, "factor context"],
  ].map(([label, value, note]) => `<article class="metric-card performance-metric"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></article>`).join("");

  const breakdown = (title, data, limit = 12) => `<article class="breakdown-card"><h3>${escapeHtml(title)}</h3>${Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([k, v]) => `<div><span>${escapeHtml(String(k).replaceAll("_", " "))}</span><strong>${fmtInt(v)}</strong></div>`).join("") || '<p>No data.</p>'}</article>`;

  const distribution = (title, data) => {
    const total = Object.values(data).reduce((sum, value) => sum + Number(value || 0), 0);
    return `<article class="distribution-card"><h3>${escapeHtml(title)}</h3>${Object.entries(data).map(([label, count]) => {
      const share = total ? (Number(count) / total) * 100 : 0;
      return `<div class="distribution-row"><div><span>${escapeHtml(label)}</span><strong>${fmtInt(count)} · ${share.toFixed(1)}%</strong></div><div class="distribution-track"><i style="width:${clamp(share, 0, 100).toFixed(1)}%"></i></div></div>`;
    }).join("")}</article>`;
  };

  moduleShell(
    "Stats & Insights",
    "Current prediction-board analytics. Historical hit rate and calibration remain in Model Performance / Backtests.",
    `<div class="metric-grid performance-grid stats-metric-grid">${tiles}</div>
     <div class="stats-distributions">${distribution("Probability distribution", probabilityBands)}${distribution("Data-depth distribution", depthBands)}</div>
     <div class="breakdown-grid stats-breakdowns">${breakdown("By tour", tour)}${breakdown("By surface", surface)}${breakdown("By confidence", confidence)}${breakdown("Top tournaments", tournament, 10)}</div>
     <p class="technical-note">These are descriptive statistics of currently upcoming predictions, not historical success rates. For observed outcomes use the out-of-time Backtests page.</p>`
  );
}


async function renderModelPerformance() {
  moduleShell("Model Performance", "Latest stored model metadata, holdout quality and probability calibration.", '<div class="state-card">Loading model status…</div>');
  try {
    const data = await getJSON(api("/api/v1/model/status"));
    if (state.currentRoute !== "model") return;
    const model = normalizeMetricObject(data?.model);
    if (!Object.keys(model).length) {
      $("moduleView").querySelector(".module-card").innerHTML = '<div class="state-card">No production model metadata is stored yet.</div>';
      return;
    }
    const metadata = normalizeMetricObject(model.metadata);
    const metrics = normalizeMetricObject(model.holdout_metrics || metadata.holdout_metrics);
    const features = Array.isArray(metadata.feature_names) ? metadata.feature_names : [];
    const status = String(model.lifecycle_status || metadata.lifecycle_status || "production").toUpperCase();
    const cards = [
      metricCard("Accuracy", pctMetric(metrics.accuracy), "untouched holdout"),
      metricCard("ROC-AUC", decMetric(metrics.roc_auc), "ranking quality"),
      metricCard("Log Loss", decMetric(metrics.log_loss), "lower is better"),
      metricCard("Brier Score", decMetric(metrics.brier_score), "lower is better"),
      metricCard("ECE", pctMetric(metrics.ece_10), "10-bin calibration"),
      metricCard("Training Matches", fmtInt(model.training_matches || metadata.training_matches), "point-in-time history"),
    ].join("");

    const lifecycleClass = status === "CHAMPION" ? "positive" : status === "REJECTED" ? "negative" : "neutral";
    const detailRows = [
      ["Model version", model.model_version || "—"],
      ["Lifecycle", status],
      ["History start", fmtDate(model.history_start || metadata.history_start)],
      ["History end", fmtDate(model.history_end || metadata.history_end)],
      ["Calibration", metadata.calibration_method || "—"],
      ["Boost blend", metadata.blend_weight_boost != null ? decMetric(metadata.blend_weight_boost, 2) : "—"],
      ["Feature count", features.length || "—"],
      ["Recorded", fmtDate(model.created_at)],
    ];

    $("moduleView").querySelector(".module-card").innerHTML = `
      <div class="performance-hero">
        <div><span class="module-kicker">LATEST MODEL SNAPSHOT</span><h2>${escapeHtml(model.model_version || "Current model")}</h2><p>Metrics below come from stored model metadata. No browser-side metric is invented or recomputed.</p></div>
        <span class="status-pill ${lifecycleClass}">${escapeHtml(status)}</span>
      </div>
      <div class="metric-grid performance-grid">${cards}</div>
      <div class="performance-columns">
        <section class="breakdown-card"><h3>Model metadata</h3>${detailRows.map(([k,v]) => `<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("")}</section>
        <section class="breakdown-card"><h3>Feature engine</h3><p class="module-copy">${features.length ? `${features.length} point-in-time features are recorded in this model artifact.` : "Feature metadata is unavailable for this snapshot."}</p><div class="feature-chips">${features.slice(0, 18).map((x) => `<span>${escapeHtml(x)}</span>`).join("")}${features.length > 18 ? `<span>+${features.length - 18} more</span>` : ""}</div></section>
      </div>
      <section class="performance-section"><div class="section-title-row"><div><span class="module-kicker">CALIBRATION</span><h3>Predicted probability vs observed win rate</h3></div><small>${metrics.n ? `${fmtInt(metrics.n)} holdout predictions` : "Stored holdout bins"}</small></div>${calibrationTable(metrics)}</section>
    `;
  } catch (error) {
    if (state.currentRoute !== "model") return;
    $("moduleView").querySelector(".module-card").innerHTML = `<div class="state-card error">Model status endpoint unavailable.<small>${escapeHtml(error.message)}</small></div>`;
  }
}

async function renderBacktests() {
  moduleShell("Backtests", "Leakage-safe chronological walk-forward evaluation against the internal Elo baseline.", '<div class="state-card">Loading latest backtest…</div>');
  try {
    const data = await getJSON(api("/api/v1/backtest/latest"));
    if (state.currentRoute !== "backtests") return;
    const row = normalizeMetricObject(data?.backtest);
    const report = normalizeMetricObject(row.report);
    if (!Object.keys(report).length) {
      $("moduleView").querySelector(".module-card").innerHTML = '<div class="state-card">No stored backtest report is available yet.</div>';
      return;
    }
    const folds = Array.isArray(report.folds) ? report.folds : [];
    const latestFold = folds[folds.length - 1] || {};
    const latestModel = normalizeMetricObject(latestFold.model);
    const overall = normalizeMetricObject(report.model_overall || report.overall || latestModel);
    const elo = normalizeMetricObject(report.elo_baseline_overall || latestFold.elo_baseline);
    const delta = normalizeMetricObject(report.delta_vs_elo || latestFold.delta_vs_elo);
    const accDelta = metricDelta(delta.accuracy, true);
    const aucDelta = metricDelta(delta.roc_auc, true);
    const logDelta = numericDelta(delta.log_loss, true);
    const brierDelta = numericDelta(delta.brier_score, true);
    const cards = [
      metricCard("Tested Matches", fmtInt(report.tested_matches || overall.n), "all walk-forward folds"),
      metricCard("Model Accuracy", pctMetric(overall.accuracy), latestFold.year ? `latest fold ${latestFold.year}` : "walk-forward"),
      metricCard("Model ROC-AUC", decMetric(overall.roc_auc), "out-of-time"),
      metricCard("Accuracy vs Elo", accDelta.text, "positive favours BlinQ"),
      metricCard("Log Loss", decMetric(overall.log_loss), "lower is better"),
      metricCard("Brier Score", decMetric(overall.brier_score), "lower is better"),
    ].join("");

    const foldRows = folds.map((fold) => {
      const m = normalizeMetricObject(fold.model);
      const e = normalizeMetricObject(fold.elo_baseline);
      const d = normalizeMetricObject(fold.delta_vs_elo);
      return `<tr><td><strong>${escapeHtml(fold.year || "—")}</strong></td><td>${fmtInt(fold.train_rows)}</td><td>${fmtInt(fold.calibration_rows)}</td><td>${fmtInt(fold.test_rows || m.n)}</td><td>${pctMetric(m.accuracy)}</td><td>${pctMetric(e.accuracy)}</td><td class="${Number(d.accuracy) >= 0 ? "positive" : "negative"}">${metricDelta(d.accuracy, true).text}</td><td>${decMetric(m.roc_auc)}</td><td>${decMetric(m.log_loss)}</td><td>${decMetric(m.brier_score)}</td><td>${pctMetric(m.ece_10)}</td></tr>`;
    }).join("");

    $("moduleView").querySelector(".module-card").innerHTML = `
      <div class="performance-hero"><div><span class="module-kicker">WALK-FORWARD</span><h2>${escapeHtml(row.model_version || "Latest stored backtest")}</h2><p>${escapeHtml(report.method || "Chronological out-of-time evaluation.")}</p></div><span class="status-pill positive">OUT-OF-TIME</span></div>
      <div class="metric-grid performance-grid">${cards}</div>
      <div class="delta-strip">
        <div><span>Accuracy Δ</span><strong class="${accDelta.cls}">${accDelta.text}</strong></div>
        <div><span>ROC-AUC Δ</span><strong class="${aucDelta.cls}">${aucDelta.text}</strong></div>
        <div><span>Log Loss Δ</span><strong class="${logDelta.cls}">${logDelta.text}</strong></div>
        <div><span>Brier Δ</span><strong class="${brierDelta.cls}">${brierDelta.text}</strong></div>
      </div>
      <section class="performance-section"><div class="section-title-row"><div><span class="module-kicker">YEARLY FOLDS</span><h3>Chronological validation</h3></div><small>${folds.length} fold${folds.length === 1 ? "" : "s"}</small></div>
        ${folds.length ? `<div class="table-wrap"><table class="access-table performance-table"><thead><tr><th>Year</th><th>Train</th><th>Calibration</th><th>Test</th><th>Accuracy</th><th>Elo</th><th>Δ</th><th>AUC</th><th>Log Loss</th><th>Brier</th><th>ECE</th></tr></thead><tbody>${foldRows}</tbody></table></div>` : '<div class="state-card compact-state">This stored report has no yearly fold detail.</div>'}
      </section>
      <section class="performance-section"><div class="section-title-row"><div><span class="module-kicker">LATEST FOLD CALIBRATION</span><h3>Probability reliability</h3></div><small>${latestFold.year || "latest"}</small></div>${calibrationTable(latestModel)}</section>
    `;
  } catch (error) {
    if (state.currentRoute !== "backtests") return;
    $("moduleView").querySelector(".module-card").innerHTML = `<div class="state-card error">Backtest endpoint unavailable.<small>${escapeHtml(error.message)}</small></div>`;
  }
}

function renderAccountPage() {
  const user = state.user;
  const mainItems = (state.ui?.navigation?.main || []).filter((x) => x.enabled !== false);
  const accessRows = mainItems.map((item) => {
    const access = routeAccess(item);
    return `<div class="account-access-row"><span>${escapeHtml(item.label)}</span><strong class="${access.allowed ? "positive" : "neutral"}">${access.allowed ? "Unlocked" : `Requires ${escapeHtml(item.required_label || "upgrade")}`}</strong></div>`;
  }).join("");
  moduleShell("Account", "Plan, access and subscription overview.", `
    <div class="account-page-grid">
      <article class="account-hero"><div class="avatar avatar-xl">${escapeHtml(initials(user.name))}</div><div><small>ACCOUNT</small><h2>${escapeHtml(user.name)}</h2><p>${escapeHtml(user.planLabel)} · ${escapeHtml(user.entitlement || "Active")}</p></div></article>
      <article class="access-summary"><h3>Current plan</h3><p>Your plan controls access while every product module remains visible in navigation.</p><div class="account-plan-badge">${escapeHtml(String(user.plan || "free").toUpperCase())}</div><button class="btn btn-primary" data-upgrade type="button">View upgrade options</button></article>
    </div>
    <section class="performance-section"><div class="section-title-row"><div><span class="module-kicker">ENTITLEMENTS</span><h3>Module access</h3></div></div><div class="account-access-list">${accessRows}</div></section>
  `);
}

function learnBody(route) {
  const content = {
    how_blinq_works: { title: "How BlinQ Works", subtitle: "From historical tennis data to a calibrated pre-match probability.", sections: [
      ["1 · Point-in-time data", "Every historical prediction is built only from information available before that match. Future results never enter the feature state."],
      ["2 · Feature engine", "Internal overall and surface Elo, recent and medium form, opponent-adjusted form, H2H, ranking context, rest/workload, serve/return statistics and optional environment signals are combined."],
      ["3 · Ensemble model", "A regularized logistic model and gradient boosting model are blended, then calibrated on a chronologically later sample."],
      ["4 · Symmetric inference", "The fixture is evaluated in both player orders and reconciled so player ordering cannot create an artificial prediction advantage."],
      ["5 · Prime Picks", "Current Prime Picks are ranked by calibrated match-win probability. Factor agreement and Data Depth explain context and act only as tie-breakers."],
    ]},
    methodology: { title: "Methodology", subtitle: "The rules that keep evaluation realistic and reproducible.", sections: [
      ["Chronological validation", "Training, calibration and testing are split by time, with whole UTC-day boundaries and later seasons reserved for out-of-time evaluation."],
      ["Strength & surface", "BlinQ maintains internal Elo and surface-specific Elo rather than treating official ranking as the only measure of player strength."],
      ["Form & opponent quality", "Recent results are time-decayed and adjusted for opponent strength so a raw winning streak against weak opposition is not treated the same as elite-level form."],
      ["H2H shrinkage", "Head-to-head history is included conservatively so tiny samples cannot dominate a prediction."],
      ["Workload & environment", "Rest, layoff and recent workload are point-in-time features. Travel, altitude and weather are used only when known; missingness is explicitly flagged."],
      ["Probability calibration", "Model scores are calibrated before being exposed as probabilities. Accuracy alone is not sufficient; Log Loss, Brier Score and ECE are tracked too."],
    ]},
    model_data: { title: "Model & Data", subtitle: "What is provider data and what BlinQ calculates internally.", sections: [
      ["Provider layer", "Fixtures, results, tournament context, surface, available rankings and match statistics are normalized from the tennis data provider."],
      ["Internal calculations", "Overall Elo, surface Elo, form, opponent-adjusted form, H2H, workload and other model features are calculated by TBT from historical match state."],
      ["Environment", "Venue, weather, travel and altitude enrichment is optional and coverage-aware. Unknown values are never presented as measured conditions."],
      ["Prediction storage", "Upcoming predictions are precomputed and stored. Loading the website does not call the upstream tennis provider."],
      ["Market data", "Value Picks remain unavailable until real bookmaker odds are connected. BlinQ does not invent implied probability or betting edge."],
      ["Specialized markets", "Ace Picks and Games & Sets require dedicated labels/models. Match-winner probabilities are not relabeled as ace, set or games predictions."],
    ]},
    faq: { title: "FAQ", subtitle: "How to interpret probabilities, confidence and Prime Picks.", sections: [
      ["What is a Prime Pick?", "One of the strongest current match-winner selections according to calibrated model probability. It is not a guaranteed or 'safe' outcome."],
      ["Is 90% a guarantee?", "No. A calibrated 90% estimate still implies losses can occur. Reliability is measured historically through calibration and out-of-time backtests."],
      ["What are the factor bars?", "Normalized explanatory indicators derived from point-in-time model features. They are context, not independent probabilities."],
      ["What is Data Depth?", "A quality indicator describing how much relevant historical information is available for the matchup. It is not a win probability."],
      ["Why can a prediction change?", "Newly completed matches, updated fixtures, rankings or other pre-match information can change the model state before a fixture begins."],
      ["Where are Value Picks?", "They stay locked until a reliable odds source is connected, because value requires comparing model probability with real market price."],
    ]},
    responsible_use: { title: "Responsible Use", subtitle: "BlinQ is a probability and analytics product, not a promise of outcomes.", sections: [
      ["Probabilities, not certainty", "Every prediction can lose. Labels such as Prime and High Confidence describe model output, not guaranteed results."],
      ["No loss chasing", "Do not increase risk simply to recover previous losses or because a previous model selection failed."],
      ["Risk limits", "Never commit money you cannot afford to lose and use explicit personal limits if you use predictions alongside betting markets."],
      ["Independent decision", "Model output should be one input in your own decision process. Context, data availability and market conditions can matter."],
      ["Adults only", "Where predictions are used in connection with betting, users must comply with local age and gambling laws."],
    ]},
  };
  return content[route];
}

function renderLearn(route) {
  const page = learnBody(route);
  if (!page) return moduleShell("Learn", "BlinQ documentation.", '<div class="state-card">Page unavailable.</div>');
  const sections = page.sections.map(([title, text]) => `<article class="learn-section"><span>${escapeHtml(title)}</span><p>${escapeHtml(text)}</p></article>`).join("");
  moduleShell(page.title, page.subtitle, `<div class="learn-intro"><span class="module-kicker">BLINQ DOCUMENTATION</span><p>Transparent model behavior is part of the product. The descriptions below reflect the current implementation and deliberately avoid claims that are not backed by data.</p></div><div class="learn-sections">${sections}</div>`);
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
