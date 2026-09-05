const cfg = window.BLINQ_CONFIG || {};

const state = {
  predictions: [],
  ui: null,
  user: null,
  currentRoute: "dashboard",
  featuredIndex: 0,
  allPredictions: false,
  playerProfiles: [],
  primeFeed: [],
  predictionStatus: null,
  language: "en",
  avatarVariant: localStorage.getItem("blinq_avatar_variant") || "a",
  avatarChoice: localStorage.getItem("blinq_avatar_choice") || "",
  authConfig: null,
  authenticated: false,
};

const $ = (id) => document.getElementById(id);
const api = (path) => `${String(cfg.apiBase || "").replace(/\/$/, "")}${path}`;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const supportedLanguages = ["en", "sk", "cz", "pl", "hu", "de", "ua", "ru"];
const htmlLanguageCodes = { en: "en", sk: "sk", cz: "cs", pl: "pl", hu: "hu", de: "de", ua: "uk", ru: "ru" };

function resolveLanguage() {
  const params = new URLSearchParams(location.search);
  const requested = String(params.get("lang") || localStorage.getItem("blinq_language") || "").toLowerCase();
  if (supportedLanguages.includes(requested)) return requested;
  const browser = String(navigator.language || "en").slice(0, 2).toLowerCase();
  if (browser === "cs") return "cz";
  if (browser === "uk") return "ua";
  return supportedLanguages.includes(browser) ? browser : "en";
}

function t(key, fallback = "") {
  const dict = window.BLINQ_I18N || {};
  return dict?.[state.language]?.[key] ?? dict?.en?.[key] ?? fallback ?? key;
}

function applyLanguageChrome() {
  document.documentElement.lang = htmlLanguageCodes[state.language] || state.language || "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    const value = t(key, el.textContent);
    if (value) el.textContent = value;
  });
  document.querySelectorAll("[data-lang-choice]").forEach((a) => a.classList.toggle("active", a.dataset.langChoice === state.language));
  const tour = $("tourFilter"); if (tour?.options?.[0]) tour.options[0].textContent = t("filter.tours", "All Tours");
  const tournament = $("tournamentFilter"); if (tournament?.options?.[0]) tournament.options[0].textContent = t("filter.tournaments", "All Tournaments");
  const surface = $("surfaceFilter"); if (surface?.options?.[0]) surface.options[0].textContent = t("filter.surfaces", "All Surfaces");
  const confidence = $("confidenceFilter");
  if (confidence?.options?.[0]) confidence.options[0].textContent = t("filter.confidence", "All Confidence");
  if (confidence?.options?.[1]) confidence.options[1].textContent = t("filter.high", "High");
  if (confidence?.options?.[2]) confidence.options[2].textContent = t("filter.medium", "Medium");
  if (confidence?.options?.[3]) confidence.options[3].textContent = t("filter.low", "Low");
  if ($("searchInput")) $("searchInput").placeholder = t("filter.search", "Search matches or players…");
  if ($("refreshButton")) $("refreshButton").textContent = `↻ ${t("picks.refresh", "Refresh")}`;
}

function localizedBannerValue(item, field, zoneName) {
  const key = item?.i18n_key || (item?.plan ? `${zoneName}.${String(item.plan).toLowerCase()}` : "");
  if (!key) return item?.[field] || "";
  return t(`banner.${key}.${field}`, item?.[field] || "");
}

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
  const response = await fetch(url, { headers: { Accept: "application/json", ...(window.BLINQ_AUTH?.authorizationHeader?.() || {}) }, cache: "no-store" });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

function deepMerge(base, extra) {
  if (!extra || typeof extra !== "object" || Array.isArray(extra)) return base;
  const out = { ...(base || {}) };
  Object.entries(extra).forEach(([key, value]) => {
    out[key] = value && typeof value === "object" && !Array.isArray(value)
      ? deepMerge(out[key] && typeof out[key] === "object" ? out[key] : {}, value)
      : value;
  });
  return out;
}

function adminKey() { return sessionStorage.getItem("blinq_admin_key") || ""; }

async function adminRequest(path, options = {}) {
  const key = adminKey();
  if (!key) throw new Error("Admin key is not set for this browser session.");
  const response = await fetch(api(path), {
    ...options,
    headers: { Accept: "application/json", "Content-Type": "application/json", "x-admin-key": key, ...(options.headers || {}) },
    cache: "no-store",
  });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

async function unlockAdminSession() {
  let key = adminKey();
  if (!key) key = window.prompt("Enter TBT admin key for this browser session:") || "";
  if (!key) return false;
  sessionStorage.setItem("blinq_admin_key", key);
  try {
    await adminRequest("/api/v1/admin/session");
    state.adminSession = true;
    renderNavigation();
    return true;
  } catch (error) {
    sessionStorage.removeItem("blinq_admin_key");
    state.adminSession = false;
    alert(`Admin access failed: ${error.message}`);
    return false;
  }
}

function loadLocalAdminOverride() {
  try { return JSON.parse(localStorage.getItem("blinq_admin_ui_override") || "null"); } catch { return null; }
}

function applyLocalAdminOverride(ui) {
  const local = loadLocalAdminOverride();
  if (local?.banner_zones) ui.banner_zones = local.banner_zones;
  if (local?.sidebar_zone) ui.sidebar_zone = local.sidebar_zone;
  if (local?.header_ad) ui.header_ad = local.header_ad;
  return ui;
}

async function loadUiConfig() {
  try {
    const baseline = await getJSON(cfg.uiConfigPath || "/ui-config.json");
    state.staticUi = baseline;
    let remote = null;
    try { remote = await getJSON(api("/api/v1/ui-config")); } catch (_) { remote = null; }
    const merged = remote?.config ? deepMerge(baseline, remote.config) : baseline;
    state.ui = applyLocalAdminOverride(merged);
    ensureAccessRegistry();
  } catch {
    state.ui = { account: {}, navigation: { main: [], learn: [], admin: [] }, banner_zones: {}, header_zone: { count: 0, items: [] }, sidebar_zone: { count: 0, items: [] }, banner_registry: { version: 1, total_slots: 14, slots: [] }, plans: [] };
  }
  ensureAccessRegistry();
}

function authMessage(message = "", type = "") {
  const box = $("authMessage");
  if (!box) return;
  box.hidden = !message;
  box.className = `auth-message${type ? ` ${type}` : ""}`;
  box.textContent = message || "";
}

function friendlyAuthError(error, fallback = "Authentication failed.") {
  const message = String(error?.message || fallback);
  if (/email.*not.*confirmed|not.*confirmed/i.test(message)) {
    return "Email address is not confirmed yet. Open the confirmation email first, then sign in.";
  }
  if (/invalid.*login|invalid.*credentials/i.test(message)) {
    return "Incorrect email or password.";
  }
  if (/rate.*limit|too many requests|429/i.test(message)) {
    return "Too many email/auth requests. Wait a moment and try again.";
  }
  return message;
}

function showAuthMode(mode = "signin", message = "", type = "") {
  $("authScreen").hidden = false;
  $("appShell").hidden = true;
  if ($("authLoading")) $("authLoading").hidden = true;
  const map = { signin: "authSignIn", signup: "authSignUp", forgot: "authForgot", password: "authNewPassword" };
  Object.values(map).forEach((id) => { if ($(id)) $(id).hidden = true; });
  if ($(map[mode] || map.signin)) $(map[mode] || map.signin).hidden = false;
  authMessage(message, type);
  applyLanguageChrome();
}

function showAuthenticatedApp() {
  if ($("authScreen")) $("authScreen").hidden = true;
  if ($("appShell")) $("appShell").hidden = false;
}

function applyAuthenticatedAccount(account) {
  state.authenticated = true;
  state.avatarVariant = String(account?.avatarVariant || localStorage.getItem("blinq_avatar_variant") || "a") === "b" ? "b" : "a";
  state.avatarChoice = String(account?.avatarUrl || localStorage.getItem("blinq_avatar_choice") || "");
  state.user = {
    id: account?.id || "",
    email: account?.email || "",
    name: account?.name || "BlinQ User",
    plan: String(account?.plan || "free").toLowerCase(),
    storedPlan: String(account?.stored_plan || account?.plan || "free").toLowerCase(),
    planLabel: account?.planLabel || String(account?.plan || "free").toUpperCase(),
    entitlement: account?.entitlement || "Active",
    entitlementExpiresAt: account?.entitlement_expires_at || null,
    avatarUrl: account?.avatarUrl || "",
    tgHandle: account?.tgHandle || "",
    authProvider: account?.authProvider || "email",
    telegramPhotoUrl: account?.telegramPhotoUrl || "",
    authenticated: true,
  };
  $("todayLabel").textContent = fmtToday();
  renderAccount();
}

async function initializeIdentity() {
  const auth = window.BLINQ_AUTH;
  if (!auth) {
    startPublicSession();
    return true;
  }
  try {
    state.authConfig = await auth.init();
    const telegramEnabled = Boolean(auth.isTelegramEnabled?.());
    ["telegramSignIn","telegramSignUp","telegramSignInDivider","telegramSignUpDivider"].forEach((id) => { if ($(id)) $(id).hidden = !telegramEnabled; });

    const callback = auth.getCallbackState?.() || {};
    if (callback.error) {
      showAuthMode("signin", callback.message || "Authentication link is invalid or expired.", "error");
      return false;
    }
  } catch (error) {
    showAuthMode("signin", `Authentication service unavailable: ${friendlyAuthError(error)}`, "error");
    return false;
  }
  if (!auth.isEnabled()) {
    if (auth.isRequired()) {
      showAuthMode("signin", "Authentication is not configured on the server yet.", "error");
      return false;
    }
    startPublicSession();
    return true;
  }
  if (auth.isRecovery()) {
    showAuthMode("password");
    return false;
  }
  const session = await auth.restoreSession();
  if (!session) {
    showAuthMode("signin");
    return false;
  }
  try {
    const result = await auth.me();
    applyAuthenticatedAccount(result.account || {});
    return true;
  } catch (error) {
    auth.clearSession?.();
    showAuthMode("signin", error.message === "account_disabled" ? "This account is disabled." : "Your session expired. Please sign in again.", "error");
    return false;
  }
}

function bindAuthEvents() {
  document.querySelectorAll("[data-auth-mode]").forEach((button) => button.addEventListener("click", () => showAuthMode(button.dataset.authMode || "signin")));
  ["telegramSignIn","telegramSignUp"].forEach((id) => $(id)?.addEventListener("click", () => {
    try { window.BLINQ_AUTH.signInWithTelegram(); }
    catch (error) { authMessage(friendlyAuthError(error), "error"); }
  }));
  $("signInForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    authMessage("Signing in…");
    try {
      const session = await window.BLINQ_AUTH.signIn($("signInEmail").value, $("signInPassword").value);
      if (!session) throw new Error("No session returned.");
      location.reload();
    } catch (error) { authMessage(friendlyAuthError(error), "error"); }
  });
  $("signUpForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
    const password = $("signUpPassword").value;
    const email = String($("signUpEmail").value || "").trim();
    if (password !== $("signUpPassword2").value) { authMessage("Passwords do not match.", "error"); return; }
    if (submit) { submit.disabled = true; submit.textContent = "Creating…"; }
    authMessage("Creating account…");
    try {
      const result = await window.BLINQ_AUTH.signUp($("signUpTelegram").value, email, password);
      if (result.session) { location.reload(); return; }

      if (!result.confirmationRequired) {
        try {
          const session = await window.BLINQ_AUTH.signIn(email, password);
          if (session) { location.reload(); return; }
        } catch (_) {}
      }

      if ($("signInEmail")) $("signInEmail").value = email;
      if ($("signUpPassword")) $("signUpPassword").value = "";
      if ($("signUpPassword2")) $("signUpPassword2").value = "";

      if (result.confirmationRequired) {
        showAuthMode(
          "signin",
          "Account created. Check your inbox and confirm your email address before signing in.",
          "success"
        );
        return;
      }

      showAuthMode(
        "signin",
        "Account request completed. If sign-in does not work, confirm the email address or use Forgot password.",
        "success"
      );
    } catch (error) {
      authMessage(friendlyAuthError(error), "error");
    } finally {
      if (submit && document.body.contains(submit)) { submit.disabled = false; submit.textContent = t("auth.sign_up", "Create account"); }
    }
  });
  $("forgotForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    authMessage("Sending reset link…");
    try {
      await window.BLINQ_AUTH.requestPasswordReset($("forgotEmail").value);
      showAuthMode(
        "signin",
        "If an account exists for this email, a password reset link has been sent. Check Inbox and Spam.",
        "success"
      );
    } catch (error) { authMessage(friendlyAuthError(error), "error"); }
  });
  $("newPasswordForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = $("newPassword").value;
    if (password !== $("newPassword2").value) { authMessage("Passwords do not match.", "error"); return; }
    authMessage("Saving password…");
    try {
      await window.BLINQ_AUTH.updatePassword(password);
      await window.BLINQ_AUTH.signOut();
      showAuthMode("signin", "Password updated. Sign in with your new password.", "success");
    } catch (error) { authMessage(friendlyAuthError(error), "error"); }
  });
}

function startPublicSession() {
  const account = state.ui?.account || {};
  state.user = {
    name: account.display_name || "BlinQ User",
    plan: String(account.plan || "free").toLowerCase(),
    planLabel: account.plan_label || String(account.plan || "free").toUpperCase(),
    entitlement: account.entitlement_text || "",
    avatarUrl: account.avatar_url || "",
    email: "",
    tgHandle: "",
    authProvider: "preview",
    authenticated: false,
  };
  renderAccount();
  $("todayLabel").textContent = fmtToday();
}

function renderBranding() {
  const branding = state.ui?.branding || {};
  const sidebarLogo = document.querySelector(".sidebar-product-logo");
  if (sidebarLogo && branding.blinq_logo) sidebarLogo.src = branding.blinq_logo;
  const productLogo = document.querySelector(".product-logo");
  if (productLogo && branding.blinq_logo) productLogo.src = branding.blinq_logo;
}


const AVATAR_PLAN_ORDER = ["free", "pro", "elite", "legend", "goat", "admin"];

function normalizeAvatarSet(planId) {
  const normalized = String(planId || "free").toLowerCase();
  const sets = state.ui?.avatar_sets || {};
  const rows = Array.isArray(sets[normalized]) ? sets[normalized] : [];
  const fallback = normalized === "goat" || normalized === "admin"
    ? ["/assets/goat.webp"]
    : [`/assets/${normalized}_a.webp`, `/assets/${normalized}_b.webp`];
  return (rows.length ? rows : fallback).map((row, index) => {
    if (row && typeof row === "object") {
      return {
        src: String(row.src || row.url || ""),
        label: String(row.label || `${normalized.toUpperCase()} ${index === 1 ? "Man" : "Woman"}`),
        gender: String(row.gender || (index === 1 ? "man" : "woman")),
        enabled: row.enabled !== false,
      };
    }
    return {
      src: String(row || ""),
      label: normalized === "goat" ? "GOAT" : `${normalized.toUpperCase()} ${index === 1 ? "Man" : "Woman"}`,
      gender: normalized === "goat" ? "goat" : (index === 1 ? "man" : "woman"),
      enabled: true,
    };
  }).filter((row) => row.src && row.enabled !== false);
}

function unlockedAvatarPlans(plan = state.user?.plan || "free") {
  const normalized = String(plan || "free").toLowerCase();
  const limit = Math.max(0, AVATAR_PLAN_ORDER.indexOf(normalized));
  const sequence = AVATAR_PLAN_ORDER.slice(0, limit + 1).filter((value, index, arr) => arr.indexOf(value) === index);
  return normalized === "admin" ? ["free", "pro", "elite", "legend", "goat"] : sequence;
}

function avatarCatalogForPlan(plan = state.user?.plan || "free") {
  const plans = unlockedAvatarPlans(plan);
  return plans.flatMap((planId) => normalizeAvatarSet(planId).map((entry, index) => ({
    key: `${planId}:${entry.src}`,
    src: entry.src,
    plan: planId,
    variant: entry.gender === "man" || index === 1 ? "b" : "a",
    gender: entry.gender,
    label: entry.label,
  })));
}

function currentAvatarOptions(plan = state.user?.plan || "free") {
  return avatarCatalogForPlan(plan);
}

function resolveAvatarChoice(plan = state.user?.plan || "free") {
  const catalog = avatarCatalogForPlan(plan);
  if (!catalog.length) return { key: "", src: "", variant: "a", label: "" };
  const selectedByUrl = catalog.find((entry) => entry.src === state.avatarChoice || entry.key === state.avatarChoice || entry.src === state.user?.avatarUrl);
  if (selectedByUrl) return selectedByUrl;
  const currentPlanSet = normalizeAvatarSet(plan);
  if (currentPlanSet.length > 1 && state.avatarVariant === "b") {
    const match = catalog.find((entry) => entry.src === currentPlanSet[1].src);
    if (match) return match;
  }
  const firstCurrentPlan = catalog.find((entry) => entry.plan === String(plan || "free").toLowerCase());
  return firstCurrentPlan || catalog[0];
}

function currentAvatarUrl() {
  return resolveAvatarChoice().src || "";
}

function deriveTelegramHandle(user = {}) {
  const explicit = String(user.tgHandle || user.tg_handle || "").trim();
  if (explicit) return explicit.startsWith("@") || explicit.startsWith("Telegram #") ? explicit : `@${explicit}`;
  return String(user.email || "").trim();
}

function setAvatarChoice(choiceKey) {
  const catalog = currentAvatarOptions();
  const selected = catalog.find((entry) => entry.key === choiceKey || entry.src === choiceKey) || resolveAvatarChoice();
  state.avatarChoice = selected.key || selected.src || "";
  state.avatarVariant = selected.variant === "b" ? "b" : "a";
  if (state.user) state.user.avatarUrl = selected.src || state.user.avatarUrl || "";
  localStorage.setItem("blinq_avatar_variant", state.avatarVariant);
  localStorage.setItem("blinq_avatar_choice", state.avatarChoice);
  if (state.user?.authenticated && window.BLINQ_AUTH?.updateProfile) {
    window.BLINQ_AUTH.updateProfile({ avatar_variant: state.avatarVariant, avatar_url: selected.src || "" }).catch(() => {});
  }
  renderAccount();
  if (state.currentRoute === "account") renderAccountPage();
}

function renderAccount() {
  const user = state.user || {};
  $("profileName").textContent = user.name || "BlinQ User";
  const handle = deriveTelegramHandle(user);
  $("profileHandle").textContent = handle;
  $("profileHandle").hidden = !handle;
  $("profilePlan").textContent = user.planLabel || "Free";
  $("planName").textContent = String(user.planLabel || user.plan || "FREE").toUpperCase();
  $("planEntitlement").textContent = user.entitlement || "Active";
  const avatar = $("avatar");
  const avatarUrl = currentAvatarUrl();
  if (avatarUrl) {
    avatar.innerHTML = `<img src="${escapeHtml(avatarUrl)}" alt="" onerror="this.parentElement.textContent='${escapeHtml(initials(user.name))}'" />`;
  } else {
    avatar.textContent = initials(user.name);
  }
}


const ACCESS_PLANS = ["free", "pro", "elite", "legend", "goat", "admin"];

const ACCESS_PANEL_CATALOG = [
  { id: "panel.header_banners", label: "Header banner zone", group: "Dashboard / Header", type: "panel", selector: "#headerBannerZone" },
  { id: "panel.header_banner_1", label: "Header banner · Slot 1", group: "Dashboard / Header", type: "panel", selector: '[data-access-feature="panel.header_banner_1"]' },
  { id: "panel.header_banner_2", label: "Header banner · Slot 2", group: "Dashboard / Header", type: "panel", selector: '[data-access-feature="panel.header_banner_2"]' },
  { id: "panel.header_banner_3", label: "Header banner · Slot 3", group: "Dashboard / Header", type: "panel", selector: '[data-access-feature="panel.header_banner_3"]' },
  { id: "panel.sidebar_banners", label: "Sidebar banner zone", group: "Dashboard / Sidebar", type: "panel", selector: "#sidebarBannerZone" },
  { id: "panel.prediction_filters", label: "Prediction filters", group: "Dashboard", type: "panel", selector: "#predictionToolbar" },
  { id: "panel.dashboard_snapshot", label: "Dashboard snapshot", group: "Dashboard", type: "panel", selector: "#dashboardSnapshot" },
  { id: "panel.top_banners", label: "Top banner zone", group: "Dashboard / Banners", type: "panel", selector: "#bannerZoneTop" },
  { id: "panel.top_banner_1", label: "Top banner · Slot 1", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.top_banner_1"]' },
  { id: "panel.top_banner_2", label: "Top banner · Slot 2", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.top_banner_2"]' },
  { id: "panel.top_banner_3", label: "Top banner · Slot 3", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.top_banner_3"]' },
  { id: "panel.top_banner_4", label: "Top banner · Slot 4", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.top_banner_4"]' },
  { id: "panel.prime_picks_board", label: "Prime Picks board", group: "Predictions", type: "panel", selector: "#pickCarouselShell" },
  { id: "panel.bottom_banners", label: "Bottom banner zone", group: "Dashboard / Banners", type: "panel", selector: "#bannerZoneBottom" },
  { id: "panel.bottom_banner_1", label: "Bottom banner · Slot 1", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.bottom_banner_1"]' },
  { id: "panel.bottom_banner_2", label: "Bottom banner · Slot 2", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.bottom_banner_2"]' },
  { id: "panel.bottom_banner_3", label: "Bottom banner · Slot 3", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.bottom_banner_3"]' },
  { id: "panel.bottom_banner_4", label: "Bottom banner · Slot 4", group: "Dashboard / Banners", type: "panel", selector: '[data-access-feature="panel.bottom_banner_4"]' },
  { id: "panel.footer_learn", label: "Footer Learn links", group: "Footer", type: "panel", selector: "#footerLearnNavigation" },
  { id: "panel.language_switcher", label: "Language switcher", group: "Footer", type: "panel", selector: ".footer-languages" },
];

function accessControlState() {
  if (!state.ui) state.ui = {};
  if (!state.ui.access_control || typeof state.ui.access_control !== "object") state.ui.access_control = {};
  const ac = state.ui.access_control;
  ac.version = Number(ac.version || 1);
  ac.default_new_feature_access = "all";
  ac.default_new_feature_visibility = "all";
  if (!ac.entries || typeof ac.entries !== "object" || Array.isArray(ac.entries)) ac.entries = {};
  return ac;
}

function normalizePlanList(value, fallback = ACCESS_PLANS) {
  const rows = Array.isArray(value) ? value.map((x) => String(x).toLowerCase()) : [...fallback];
  return ACCESS_PLANS.filter((plan) => rows.includes(plan));
}

function registerAccessFeature(meta, initialAllowed = ACCESS_PLANS, initialVisible = ACCESS_PLANS) {
  if (!meta?.id) return null;
  const ac = accessControlState();
  const existing = ac.entries[meta.id];
  if (!existing) {
    ac.entries[meta.id] = {
      id: meta.id,
      label: meta.label || meta.id,
      type: meta.type || "panel",
      group: meta.group || "Other",
      source: meta.source || "auto",
      auto_discovered: meta.auto_discovered !== false,
      admin_only: Boolean(meta.admin_only),
      allowed_plans: meta.admin_only ? ["admin"] : normalizePlanList(initialAllowed),
      visible_plans: meta.admin_only ? ["admin"] : normalizePlanList(initialVisible),
    };
  } else {
    existing.label = meta.label || existing.label || meta.id;
    existing.type = meta.type || existing.type || "panel";
    existing.group = meta.group || existing.group || "Other";
    existing.source = meta.source || existing.source || "auto";
    existing.admin_only = Boolean(meta.admin_only || existing.admin_only);
    existing.auto_discovered = existing.auto_discovered !== false;
    existing.allowed_plans = existing.admin_only ? ["admin"] : normalizePlanList(existing.allowed_plans);
    existing.visible_plans = existing.admin_only ? ["admin"] : normalizePlanList(existing.visible_plans);
  }
  return ac.entries[meta.id];
}

function ensureAccessRegistry() {
  const nav = state.ui?.navigation || {};
  [
    ...(nav.main || []).map((item) => ({ item, group: "Main navigation" })),
    ...(nav.learn || []).map((item) => ({ item, group: "Learn / Footer" })),
    ...(nav.admin || []).map((item) => ({ item, group: "Administration" })),
  ].forEach(({ item, group }) => {
    registerAccessFeature(
      { id: `route.${item.id}`, label: item.label || item.id, type: "page", group, source: "navigation", admin_only: Boolean(item.admin_only) },
      item.admin_only ? ["admin"] : (Array.isArray(item.allowed_plans) ? item.allowed_plans : ACCESS_PLANS),
      item.admin_only ? ["admin"] : ACCESS_PLANS,
    );
  });
  ACCESS_PANEL_CATALOG.forEach((meta) => registerAccessFeature({ ...meta, source: "panel_catalog" }, ACCESS_PLANS, ACCESS_PLANS));
  const bannerZones = { header: state.ui?.header_zone, top: state.ui?.banner_zones?.top, bottom: state.ui?.banner_zones?.bottom, sidebar: state.ui?.sidebar_zone };
  Object.entries(bannerZones).forEach(([zoneName, zone]) => (zone?.items || []).forEach((item, index) => ensureBannerAccessEntry(zoneName, index, item)));
  document.querySelectorAll("[data-access-feature]").forEach((node) => {
    registerAccessFeature({
      id: node.dataset.accessFeature,
      label: node.dataset.accessLabel || node.dataset.accessFeature,
      type: "panel",
      group: node.dataset.accessGroup || "Auto-discovered panels",
      source: "dom",
    }, ACCESS_PLANS, ACCESS_PLANS);
  });
  return accessControlState();
}

function accessEntry(featureId) {
  return ensureAccessRegistry().entries?.[featureId] || null;
}

function planHasFeatureAccess(featureId, plan = state.user?.plan || "free") {
  const entry = accessEntry(featureId);
  if (!entry) return true;
  if (entry.admin_only) return String(plan).toLowerCase() === "admin" || state.adminSession;
  return normalizePlanList(entry.allowed_plans).includes(String(plan || "free").toLowerCase());
}

function planCanSeeFeature(featureId, plan = state.user?.plan || "free") {
  const entry = accessEntry(featureId);
  if (!entry) return true;
  if (entry.admin_only) return String(plan).toLowerCase() === "admin" || state.adminSession;
  return normalizePlanList(entry.visible_plans).includes(String(plan || "free").toLowerCase());
}

function applyManagedPanelVisibility() {
  ensureAccessRegistry();
  ACCESS_PANEL_CATALOG.forEach((meta) => {
    document.querySelectorAll(meta.selector).forEach((node) => {
      const visible = planCanSeeFeature(meta.id);
      node.dataset.planVisible = visible ? "1" : "0";
      if (!visible) node.hidden = true;
    });
  });
  document.querySelectorAll("[data-access-feature]").forEach((node) => {
    const id = node.dataset.accessFeature;
    const visible = planCanSeeFeature(id);
    node.dataset.planVisible = visible ? "1" : "0";
    if (!visible) node.hidden = true;
  });
}

function syncRouteAccessBackToNavigation() {
  const nav = state.ui?.navigation || {};
  [...(nav.main || []), ...(nav.learn || []), ...(nav.admin || [])].forEach((item) => {
    const entry = accessEntry(`route.${item.id}`);
    if (!entry) return;
    item.allowed_plans = normalizePlanList(entry.allowed_plans);
  });
}

function allNavItems() {
  const nav = state.ui?.navigation || {};
  return [...(nav.main || []), ...(nav.learn || []), ...(nav.admin || [])];
}

function navItem(route) { return allNavItems().find((x) => x.id === route); }

function routeAccess(item) {
  if (!item) return { allowed: true };
  const featureId = `route.${item.id}`;
  const entry = accessEntry(featureId);
  if (item.admin_only || entry?.admin_only) {
    return (state.user?.plan === "admin" || state.adminSession)
      ? { allowed: true }
      : { allowed: false, label: "Admin", reason: "This module is available only to administrators." };
  }
  if (!planCanSeeFeature(featureId)) {
    return { allowed: false, hidden: true, label: "Unavailable", reason: "This module is hidden for your current account level." };
  }
  const allowedPlans = entry ? normalizePlanList(entry.allowed_plans) : (item.allowed_plans || ACCESS_PLANS);
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

function renderFooterLearnNavigation() {
  const host = $("footerLearnNavigation");
  if (!host) return;
  host.innerHTML = "";
  const items = [...(state.ui?.navigation?.learn || [])]
    .filter((item) => item.enabled !== false)
    .sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
  items.forEach((item) => {
    if (!planCanSeeFeature(`route.${item.id}`)) return;
    const a = document.createElement("a");
    a.href = item.href || `#${item.id}`;
    a.className = `footer-link${state.currentRoute === item.id ? " active" : ""}`;
    a.dataset.route = item.id;
    a.textContent = t(`nav.${item.id}`, item.label || item.id);
    host.appendChild(a);
  });
}

function renderNavigationGroup(items, containerId) {
  const host = $(containerId);
  if (!host) return;
  host.innerHTML = "";
  [...(items || [])]
    .filter((item) => item.enabled !== false)
    .sort((a, b) => Number(a.order || 0) - Number(b.order || 0))
    .forEach((item) => {
      if (item.admin_only && state.user?.plan !== "admin" && !state.adminSession) return;
      const access = routeAccess(item);
      if (access.hidden || !planCanSeeFeature(`route.${item.id}`)) return;
      const a = document.createElement("a");
      a.href = item.href || `#${item.id}`;
      a.className = `nav-link${state.currentRoute === item.id ? " active" : ""}${access.allowed ? "" : " locked"}`;
      a.dataset.route = item.id;
      a.innerHTML = `<span class="nav-icon">${escapeHtml(item.icon || "•")}</span><span class="nav-text">${escapeHtml(t(`nav.${item.id}`, item.label || item.id))}</span>${access.allowed ? "" : '<span class="nav-lock">🔒</span>'}`;
      host.appendChild(a);
    });
}

function renderNavigation() {
  const nav = state.ui?.navigation || {};
  renderNavigationGroup(nav.main, "mainNavigation");
  renderNavigationGroup(nav.learn, "learnNavigation");
  renderFooterLearnNavigation();
  const adminSection = $("adminNavigationSection");
  if (adminSection) adminSection.hidden = !(state.user?.plan === "admin" || state.adminSession);
  if (state.user?.plan === "admin" || state.adminSession) renderNavigationGroup(nav.admin, "adminNavigation");
  applyLanguageChrome();
}

const BANNER_SLOT_IDS = {
  header: ["BLQ-H01","BLQ-H02","BLQ-H03"],
  top: ["BLQ-T01","BLQ-T02","BLQ-T03","BLQ-T04"],
  bottom: ["BLQ-B01","BLQ-B02","BLQ-B03","BLQ-B04"],
  sidebar: ["BLQ-S01","BLQ-S02","BLQ-S03"],
};

function bannerRegistryId(zoneName, index, item = null) {
  return String(item?.banner_id || BANNER_SLOT_IDS?.[zoneName]?.[Number(index)] || `BLQ-${String(zoneName).toUpperCase()}-${Number(index)+1}`);
}

function bannerSlotFeatureId(zoneName, index, item = null) {
  return `banner.${bannerRegistryId(zoneName, index, item)}`;
}

function bannerRequiredPlans(item) {
  const order = ["free","pro","elite","legend","goat","admin"];
  const required = String(item?.plan || "free").toLowerCase();
  const start = Math.max(0, order.indexOf(required));
  return order.slice(start);
}

function ensureBannerAccessEntry(zoneName, index, item = null) {
  const id = bannerSlotFeatureId(zoneName, index, item);
  const ac = accessControlState();
  if (!ac.entries[id]) {
    const bannerId = bannerRegistryId(zoneName, index, item);
    ac.entries[id] = {
      id,
      label: `${bannerId} · ${String(item?.headline || `${zoneName} banner ${Number(index)+1}`)}`,
      group: `Banners / ${zoneName}`,
      type: "panel",
      source: "banner_registry",
      auto_discovered: false,
      visible_plans: [...ACCESS_PLANS],
      allowed_plans: bannerRequiredPlans(item),
    };
  }
  return ac.entries[id];
}

function bannerSlotVisible(zoneName, index, item = null) {
  ensureBannerAccessEntry(zoneName, index, item);
  return planCanSeeFeature(bannerSlotFeatureId(zoneName, index, item));
}

function bannerSlotAccessible(zoneName, index, item = null) {
  ensureBannerAccessEntry(zoneName, index, item);
  return planHasFeatureAccess(bannerSlotFeatureId(zoneName, index, item));
}

function renderHeaderSponsor() {
  const legacy = state.ui?.header_ad ? { count: 1, items: [state.ui.header_ad] } : null;
  const zone = state.ui?.header_zone || legacy || { count: 0, items: [] };
  const host = $("headerBannerZone");
  if (!host) return;
  if (!planCanSeeFeature("panel.header_banners")) { host.hidden = true; host.innerHTML = ""; return; }
  const count = clamp(Number(zone.count || 0), 0, 3);
  const items = (zone.items || [])
    .slice(0, count)
    .map((item, originalIndex) => ({ item, originalIndex }))
    .filter(({ item, originalIndex }) => item?.enabled !== false && bannerSlotVisible("header", originalIndex, item));
  host.className = `header-banner-zone header-count-${items.length}`;
  if (!items.length) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.innerHTML = items.map(({ item: ad, originalIndex }) => {
    const featureId = bannerSlotFeatureId("header", originalIndex, ad);
    const unlocked = bannerSlotAccessible("header", originalIndex, ad);
    const configuredLink = ad.link || "#account";
    const finalLink = unlocked ? configuredLink : "#account";
    const route = String(finalLink || "").startsWith("#") ? String(finalLink).slice(1).replaceAll("-", "_") : "";
    const theme = `plan-${escapeHtml(ad.plan || "default")}`;
    return `<a class="header-banner-card ${theme}${unlocked ? "" : " access-locked"}" href="${escapeHtml(finalLink)}" ${route ? `data-route="${escapeHtml(route)}"` : ""} data-access-feature="${escapeHtml(featureId)}" data-access-label="${escapeHtml(`${bannerRegistryId("header", originalIndex, ad)} · Header slot ${originalIndex + 1}`)}" data-access-group="Dashboard / Header">
      ${ad.image ? `<img src="${escapeHtml(ad.image)}" alt="" loading="lazy" decoding="async" style="object-fit:${escapeHtml(ad.fit || "cover")}" />` : ""}
      <span class="header-sponsor-label">${escapeHtml(ad.eyebrow || ad.label || "BLINQ")}</span>
      <span class="header-sponsor-copy"><strong>${escapeHtml(localizedBannerValue(ad, "headline", "header") || "Upgrade your BlinQ level")}</strong><small>${escapeHtml(localizedBannerValue(ad, "text", "header") || "")}</small></span>
      ${unlocked ? "" : '<span class="banner-access-lock">🔒</span>'}
    </a>`;
  }).join("");
}

function sizeHint(count, zoneName = "main", layoutMode = "row") {
  const n = Number(count);
  if (zoneName === "header") return ({ 1: "1 × 900×180", 2: "2 × 450×180", 3: "3 × 300×180" })[n] || "Flexible";
  if (zoneName === "sidebar") return ({ 1: "1 × 220×420", 2: "2 × 220×205", 3: "3 × 220×130" })[n] || "Flexible";
  if (n === 4 && layoutMode === "grid_2x2") return "2 × 2 grid · 4 × 600×400";
  return ({ 1: "1 × 1200×400", 2: "2 × 600×400", 3: "1 × 600×400 + 2 × 300×400", 4: "4 × 300×400" })[n] || "Flexible";
}

function bannerSlotSpec(zoneName, count, index, layoutMode = "row") {
  const n = Number(count);
  if (zoneName === "header") return ({ 1: ["900×180"], 2: ["450×180", "450×180"], 3: ["300×180", "300×180", "300×180"] })[n]?.[index] || "Flexible";
  if (zoneName === "sidebar") return ({ 1: ["220×420"], 2: ["220×205","220×205"], 3: ["220×130","220×130","220×130"] })[n]?.[index] || "Flexible";
  if (n === 4 && layoutMode === "grid_2x2") return "600×400";
  return ({ 1: ["1200×400"], 2: ["600×400", "600×400"], 3: ["600×400", "300×400", "300×400"], 4: ["300×400", "300×400", "300×400", "300×400"] })[n]?.[index] || "Flexible";
}

function renderBannerZone(zoneName) {
  const zone = state.ui?.banner_zones?.[zoneName] || { count: 0, items: [] };
  const host = $(zoneName === "top" ? "bannerZoneTop" : "bannerZoneBottom");
  if (!host) return;
  const featureId = zoneName === "top" ? "panel.top_banners" : "panel.bottom_banners";
  if (!planCanSeeFeature(featureId)) { host.hidden = true; host.innerHTML = ""; return; }
  const count = clamp(Number(zone.count || 0), 0, 4);
  const items = (zone.items || [])
    .slice(0, count)
    .map((item, originalIndex) => ({ item, originalIndex }))
    .filter(({ item, originalIndex }) => item?.enabled !== false && bannerSlotVisible(zoneName, originalIndex, item));
  if (!items.length) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.className = `banner-zone banner-zone-${zoneName} banner-count-${items.length} banner-layout-${escapeHtml(zone.layout_mode || "row")}`;
  host.innerHTML = items.map(({ item: banner, originalIndex }) => {
    const slotFeatureId = bannerSlotFeatureId(zoneName, originalIndex, banner);
    const unlocked = bannerSlotAccessible(zoneName, originalIndex, banner);
    const image = banner.image ? `<div class="zone-banner-art"><img src="${escapeHtml(banner.image)}" alt="" loading="lazy" decoding="async" style="object-fit:${escapeHtml(banner.fit || "cover")}" /></div>` : '<div class="zone-banner-art generated-art"><span></span></div>';
    const configuredLink = banner.link || "#";
    const finalLink = unlocked ? configuredLink : "#account";
    const route = String(finalLink || "").startsWith("#") ? String(finalLink).slice(1).replaceAll("-", "_") : "";
    return `<article class="zone-banner zone-banner-${originalIndex + 1} plan-${escapeHtml(banner.plan || "default")}${unlocked ? "" : " access-locked"}" data-access-feature="${escapeHtml(slotFeatureId)}" data-access-label="${escapeHtml(`${bannerRegistryId(zoneName, originalIndex, banner)} · ${zoneName === "top" ? "Top" : "Bottom"} slot ${originalIndex + 1}`)}" data-access-group="Dashboard / Banners">
      <div class="zone-banner-copy">
        <span class="promo-eyebrow">${escapeHtml(banner.eyebrow || (banner.sponsored ? "SPONSORED" : "BLINQ"))} <em class="banner-id-tag">${escapeHtml(bannerRegistryId(zoneName, originalIndex, banner))}</em></span>
        <h2>${escapeHtml(localizedBannerValue(banner, "headline", zoneName) || "")}</h2>
        <p>${escapeHtml(localizedBannerValue(banner, "text", zoneName) || "")}</p>
        <a class="promo-cta" href="${escapeHtml(finalLink)}" ${route ? `data-route="${escapeHtml(route)}"` : ""}>${escapeHtml(unlocked ? (banner.button_text || t("button.open", "Open")) : t("shell.upgrade", "Upgrade"))}</a>
      </div>
      ${image}
      ${banner.sponsored ? '<span class="promo-sponsor">Sponsored</span>' : ""}
      ${unlocked ? "" : '<span class="banner-access-lock">🔒</span>'}
    </article>`;
  }).join("");
}

function renderSidebarBanners() {
  const host = $("sidebarBannerZone");
  const zone = state.ui?.sidebar_zone || { count: 0, items: [] };
  if (!host) return;
  if (!planCanSeeFeature("panel.sidebar_banners")) { host.hidden = true; host.innerHTML = ""; return; }
  const count = clamp(Number(zone.count || 0), 0, 3);
  const items = (zone.items || []).slice(0, count).map((item, originalIndex) => ({item, originalIndex}))
    .filter(({item, originalIndex}) => item?.enabled !== false && bannerSlotVisible("sidebar", originalIndex, item));
  if (!items.length) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.className = `sidebar-banner-zone sidebar-count-${items.length}`;
  host.innerHTML = items.map(({item, originalIndex}) => {
    const featureId = bannerSlotFeatureId("sidebar", originalIndex, item);
    const unlocked = bannerSlotAccessible("sidebar", originalIndex, item);
    const configuredLink = item.link || "#account";
    const finalLink = unlocked ? configuredLink : "#account";
    const route = String(finalLink).startsWith("#") ? String(finalLink).slice(1).replaceAll("-","_") : "";
    return `<a class="sidebar-promo-card plan-${escapeHtml(item.plan || "default")}${unlocked ? "" : " access-locked"}" href="${escapeHtml(finalLink)}" ${route ? `data-route="${escapeHtml(route)}"` : ""} data-access-feature="${escapeHtml(featureId)}" data-access-label="${escapeHtml(`${bannerRegistryId("sidebar", originalIndex, item)} · Sidebar slot ${originalIndex+1}`)}" data-access-group="Dashboard / Sidebar">
      <span class="sidebar-promo-id">${escapeHtml(bannerRegistryId("sidebar", originalIndex, item))}</span>
      <small>${escapeHtml(item.eyebrow || "BLINQ")}</small><strong>${escapeHtml(item.headline || "")}</strong><span>${escapeHtml(item.text || "")}</span>${unlocked ? "" : '<b class="banner-access-lock">🔒</b>'}
    </a>`;
  }).join("");
}

function renderBannerZones() {
  renderBannerZone("top");
  renderBannerZone("bottom");
  renderSidebarBanners();
}

function planAvatarSet(planId) {
  const normalized = String(planId || "").toLowerCase();
  if (!normalized) return [];
  if (normalized === "goat") return [{ src: "/assets/goat.webp", alt: "GOAT avatar" }];
  return [
    { src: `/assets/${normalized}_a.webp`, alt: `${normalized} avatar A` },
    { src: `/assets/${normalized}_b.webp`, alt: `${normalized} avatar B` },
  ];
}

function renderPlanGrid() {
  const host = $("planGrid");
  if (!host) return;
  host.innerHTML = (state.ui?.plans || []).map((plan) => {
    const avatars = normalizeAvatarSet(String(plan.id || "").toLowerCase()).map((entry) => `<span class="plan-avatar"><img src="${escapeHtml(entry.src)}" alt="${escapeHtml(entry.label || plan.label)}" loading="lazy" onerror="this.closest('span').style.display='none'" /></span>`).join("");
    const price = String(plan.price || "").trim();
    const priceHtml = price && price !== "—" ? `<h3>${escapeHtml(price)}</h3>` : `<div class="plan-tier-copy">Access tier</div>`;
    return `<article class="plan-option">
      <div class="plan-option-top"><span class="plan-label">${escapeHtml(plan.label)}</span><div class="plan-avatar-row">${avatars}</div></div>
      ${priceHtml}
      <ul>${(plan.features || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
      <button class="btn btn-primary btn-full" type="button" data-plan-choice="${escapeHtml(plan.id)}">${escapeHtml(t("button.choose", "Choose"))} ${escapeHtml(plan.label)}</button>
    </article>`;
  }).join("");
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

async function fetchWindowedJson(paths = []) {
  for (const path of paths) {
    try {
      const payload = await getJSON(api(path));
      const rows = Array.isArray(payload?.matches) ? payload.matches : Array.isArray(payload?.data) ? payload.data : Array.isArray(payload?.predictions) ? payload.predictions : [];
      if (rows.length) return rows;
    } catch (_) {}
  }
  return [];
}

async function fetchPredictions() {
  const baseDays = clamp(Number(cfg.predictionsDays || 3), 1, 14);
  const uniqueDays = [...new Set([baseDays, 7, 14].filter((d) => d >= baseDays && d <= 14).concat([baseDays]))];
  const richPaths = uniqueDays.map((days) => `/api/v1/predictions/upcoming?days=${days}`);
  const flatPaths = uniqueDays.map((days) => `/api/blinq/predictions?days=${days}`);
  const richRows = await fetchWindowedJson(richPaths);
  if (richRows.length) return richRows;
  return fetchWindowedJson(flatPaths);
}

async function fetchPrimePredictions() {
  const limit = clamp(Number(state.ui?.prime_picks?.limit || 10), 1, 20);
  const baseDays = clamp(Number(cfg.predictionsDays || 3), 1, 14);
  const windows = [...new Set([baseDays, 7, 14].filter((d) => d >= baseDays && d <= 14).concat([baseDays]))];
  const paths = [];
  for (const days of windows) {
    paths.push(`/api/v1/predictions/prime?days=${days}&limit=${limit}`);
    paths.push(`/api/v1/predictions/prime?days=${days}&limit=${limit}&minimum_probability=0`);
  }
  return fetchWindowedJson(paths);
}

function dedupeMatches(rows) {
  const out = [];
  const seen = new Set();
  for (const row of rows) {
    const match = normalizePrediction(row);
    const key = String(match.id || `${match.date}|${match.p1}|${match.p2}`);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(match);
  }
  return out;
}

async function fetchPredictionStatus() {
  try { return await getJSON(api("/api/v1/predictions/status")); } catch (_) { return null; }
}

async function loadPredictions() {
  const grid = $("predictionGrid");
  if (grid) grid.innerHTML = '<div class="state-card">Loading current model predictions…</div>';
  try {
    const [boardRows, primeRowsRemote, statusPayload] = await Promise.all([fetchPredictions(), fetchPrimePredictions(), fetchPredictionStatus()]);
    state.predictionStatus = statusPayload;
    state.predictions = dedupeMatches(boardRows);
    state.primeFeed = dedupeMatches(primeRowsRemote);
    if (!state.predictions.length && state.primeFeed.length) state.predictions = [...state.primeFeed];
    if (state.predictions.length && state.primeFeed.length) {
      const existing = new Set(state.predictions.map((m) => String(m.id)));
      for (const m of state.primeFeed) if (!existing.has(String(m.id))) state.predictions.push(m);
    }
    state.featuredIndex = 0;
    populateFilterOptions();
    renderFeedStatus();
    if (["dashboard", "prime_picks"].includes(state.currentRoute)) renderPredictions();
    else renderCurrentModule();
  } catch (error) {
    state.predictions = [];
    state.primeFeed = [];
    renderFeedStatus();
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
  const filteredPrimeFeed = state.primeFeed.length
    ? state.primeFeed.filter((m) => rows.some((row) => String(row.id) === String(m.id)))
    : [];
  const source = filteredPrimeFeed.length ? filteredPrimeFeed : rows;
  return [...source].sort((a, b) => {
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
  if (state.currentRoute !== "dashboard" || !planCanSeeFeature("panel.dashboard_snapshot")) { host.hidden = true; return; }
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

function latestPredictionTimestamp(rows = state.predictions) {
  const timestamps = rows.map((m) => new Date(m.generatedAt || m.date || 0).getTime()).filter(Number.isFinite);
  return timestamps.length ? Math.max(...timestamps) : null;
}

function renderFeedStatus() {
  const host = $("feedStatus");
  if (!host) return;
  const count = state.predictions.length;
  const latest = latestPredictionTimestamp();
  host.classList.remove("ok", "warn", "empty");
  if (!count) {
    host.classList.add("empty");
    const futureCount = Number(state.predictionStatus?.future_count || 0);
    const latestStored = state.predictionStatus?.latest_generated_at || state.predictionStatus?.latest_scheduled_at || null;
    const diagnostic = latestStored ? ` · last ${fmtShortGenerated(latestStored)}` : "";
    host.innerHTML = `<i></i><span>${escapeHtml(t("picks.no_active", "No active feed"))}${futureCount ? ` · ${futureCount} future` : ""}${escapeHtml(diagnostic)}</span>`;
    return;
  }
  const ageHours = latest ? (Date.now() - latest) / 3600000 : null;
  const stale = Number.isFinite(ageHours) && ageHours > 12;
  host.classList.add(stale ? "warn" : "ok");
  const label = latest ? `${count} ${t("picks.loaded", "loaded")} · ${fmtShortGenerated(new Date(latest).toISOString())}` : `${count} ${t("picks.loaded", "loaded")}`;
  host.innerHTML = `<i></i><span>${escapeHtml(label)}</span>`;
}

function renderPredictions() {
  const boardShell = $("pickCarouselShell");
  const boardVisible = planCanSeeFeature("panel.prime_picks_board");
  if (boardShell) boardShell.hidden = !boardVisible;
  renderFeedStatus();
  const filtered = currentFilteredPredictions();
  renderDashboardSnapshot(filtered);
  const primes = primeRows(filtered);
  const grid = $("predictionGrid");
  $("matchCount").textContent = String(primes.length);
  $("viewAllButton").textContent = state.allPredictions ? t("picks.back", "← Prime Picks") : (state.currentRoute === "dashboard" ? t("picks.open", "Open Prime Picks →") : t("picks.all", "All predictions →"));
  grid.classList.toggle("expanded", state.allPredictions);
  $("pickCarouselShell").classList.toggle("expanded", state.allPredictions);
  $("prevPick").hidden = state.allPredictions || primes.length <= 1;
  $("nextPick").hidden = state.allPredictions || primes.length <= 1;

  if (!filtered.length) {
    grid.innerHTML = state.predictions.length ? '<div class="state-card">No current prediction matches these filters.</div>' : `<div class="state-card feed-empty"><strong>${escapeHtml(t("picks.no_board", "No current prediction board"))}</strong><small>${escapeHtml(t("picks.no_board_detail", "Run Refresh TBT predictions to generate current picks."))}</small><button class="btn btn-ghost" id="emptyRetry" type="button">↻ ${escapeHtml(t("picks.retry", "Retry feed"))}</button></div>`; setTimeout(() => $("emptyRetry")?.addEventListener("click", loadPredictions), 0);
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
  const titleKey = ({
    "Dashboard": "route.dashboard.title",
    "BlinQ Prime Picks": "route.prime.title",
    "Tournaments": "nav.tournaments",
    "Players": "nav.players",
    "Stats & Insights": "nav.stats",
    "Model Performance": "nav.model",
    "Backtests": "nav.backtests",
    "Account": "nav.account",
  })[title];
  $("pageTitle").textContent = title === "Dashboard" ? "" : (titleKey ? t(titleKey, title) : title);
  if (title === "Dashboard") $("pageSubtitle").textContent = "";
  else if (title === "BlinQ Prime Picks") $("pageSubtitle").textContent = t("route.prime.subtitle", subtitle);
  else $("pageSubtitle").textContent = subtitle;
  $("pageEyebrow").textContent = eyebrow === "PRE-MATCH ANALYTICS" ? t("route.prime.eyebrow", eyebrow) : eyebrow === "TENNIS INTELLIGENCE" ? t("route.default.eyebrow", eyebrow) : eyebrow;
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
    $("bannerZoneTop").hidden = route !== "dashboard" || !planCanSeeFeature("panel.top_banners");
    $("bannerZoneBottom").hidden = route !== "dashboard" || !planCanSeeFeature("panel.bottom_banners");
    if ($("dashboardSnapshot")) $("dashboardSnapshot").hidden = route !== "dashboard" || !planCanSeeFeature("panel.dashboard_snapshot");
    if ($("predictionToolbar")) $("predictionToolbar").hidden = !planCanSeeFeature("panel.prediction_filters");
    if (route === "dashboard") {
      setRouteHeader("Dashboard", "Recommended Prime Picks and current tennis intelligence.");
      $("picksTitle").textContent = t("picks.title", "BlinQ Prime Picks");
      $("picksSubtitle").textContent = t("picks.subtitle", "Top current selections ranked by calibrated model win probability. Quality factors are shown as context.");
    } else {
      setRouteHeader("BlinQ Prime Picks", "The best current selections our model can support with the available data.", "PRE-MATCH ANALYTICS");
      $("picksTitle").textContent = t("picks.top10", "BlinQ Prime Picks · Top 10");
      $("picksSubtitle").textContent = t("picks.subtitle_top10", "Top 10 ranked by calibrated model win probability; factor agreement and data depth are tie-breakers only.");
    }
    renderPredictions();
    applyManagedPanelVisibility();
  } else {
    $("dashboardView").hidden = true; $("moduleView").hidden = false;
    renderCurrentModule();
    applyManagedPanelVisibility();
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
  const avatarOptions = currentAvatarOptions();
  const activeAvatar = resolveAvatarChoice();
  const avatarChoices = avatarOptions.map((entry) => {
    const selected = activeAvatar.src === entry.src;
    return `<button class="avatar-choice${selected ? " active" : ""}" type="button" data-avatar-choice="${escapeHtml(entry.key)}" ${avatarOptions.length === 1 ? "disabled" : ""}><img src="${escapeHtml(entry.src)}" alt="${escapeHtml(entry.label)}" /><span class="avatar-choice-label">${escapeHtml(entry.label)}</span></button>`;
  }).join("");
  const mainAvatar = currentAvatarUrl();
  const goatLogo = state.ui?.branding?.goat_logo || "/assets/logo_goat.svg";
  const goatFallback = state.ui?.branding?.goat_logo_fallback || "/assets/goat_logo.svg";
  moduleShell("Account", "Plan, access and subscription overview.", `
    <div class="account-page-grid">
      <article class="account-hero"><div class="avatar avatar-xl account-avatar-img">${mainAvatar ? `<img src="${escapeHtml(mainAvatar)}" alt="" />` : escapeHtml(initials(user.name))}</div><div><small>ACCOUNT</small><h2>${escapeHtml(user.name)}</h2><p>${escapeHtml(user.planLabel)} · ${escapeHtml(user.entitlement || "Active")}</p><div class="account-auth-meta"><span>${user.email ? `Signed in as <strong>${escapeHtml(user.email)}</strong>` : "Public preview profile"}</span><span>${user.tgHandle ? `Telegram <strong>${escapeHtml(deriveTelegramHandle(user))}</strong>` : `Login <strong>${escapeHtml(user.email || user.authProvider || "Preview")}</strong>`}</span></div></div></article>
      <article class="access-summary"><h3>Current plan</h3><p>Your plan controls access while every product module remains visible in navigation.</p><div class="account-plan-badge">${escapeHtml(String(user.plan || "free").toUpperCase())}</div><button class="btn btn-primary" data-upgrade type="button">View upgrade options</button></article>
    </div>
    <section class="performance-section"><div class="section-title-row"><div><span class="module-kicker">IDENTITY</span><h3>Profile & session</h3></div><small>${user.authenticated ? "Supabase Auth" : "Preview"}</small></div><div class="account-profile-editor"><label>Display name<input id="accountDisplayName" value="${escapeHtml(user.name || "BlinQ User")}" maxlength="80"></label><button class="btn btn-ghost" id="saveAccountProfile" type="button">Save profile</button></div>${user.authenticated ? '<button class="btn btn-ghost signout-button" id="signOutButton" type="button">Sign out</button>' : ''}</section>
    <div class="account-settings-grid">
      <section class="performance-section avatar-settings"><div class="section-title-row"><div><span class="module-kicker">PROFILE</span><h3>Avatar</h3></div><small>${avatarOptions.length > 1 ? "Unlocked by current plan" : "Plan avatar"}</small></div><div class="avatar-choice-row">${avatarChoices}</div><p class="module-copy">PRO unlocks Free + PRO avatars. Elite adds Elite. Legend adds Legend. GOAT unlocks every previous avatar plus the GOAT profile.</p></section>
      <section class="performance-section engine-summary"><div class="engine-summary-mark"><img src="${escapeHtml(goatLogo)}" data-fallback="${escapeHtml(goatFallback)}" alt="BackstageTalks Statistical Engine" /></div><div><span class="module-kicker">POWERED BY</span><h3>BackstageTalks Statistical Engine</h3><p class="module-copy">BlinQ is the product interface. The statistical engine handles feature construction, model evaluation and prediction generation.</p></div></section>
    </div>
    <section class="performance-section"><div class="section-title-row"><div><span class="module-kicker">ENTITLEMENTS</span><h3>Module access</h3></div></div><div class="account-access-list">${accessRows}</div></section>
    <section class="performance-section admin-access-card"><div class="section-title-row"><div><span class="module-kicker">OWNER TOOLS</span><h3>Admin Studio</h3></div><small>Session-only key</small></div><p class="module-copy">Open persistent Banner Manager, Plan Access and account configuration. The admin key is kept only in sessionStorage for this browser tab/session.</p><button class="btn btn-ghost" id="openAdminStudio" type="button">Open Admin Studio</button></section>
  `);
  document.querySelectorAll("[data-avatar-choice]").forEach((button) => button.addEventListener("click", () => setAvatarChoice(button.dataset.avatarChoice)));
  const engineImage = document.querySelector(".engine-summary-mark img");
  if (engineImage) engineImage.addEventListener("error", function () { if (this.dataset.fallback && this.src !== this.dataset.fallback) this.src = this.dataset.fallback; });
  $("openAdminStudio")?.addEventListener("click", async () => { if (await unlockAdminSession()) navigate("admin_banners"); });
  $("saveAccountProfile")?.addEventListener("click", async () => {
    const value = String($("accountDisplayName")?.value || "").trim();
    if (!value) return;
    if (!user.authenticated || !window.BLINQ_AUTH?.updateProfile) { user.name = value; renderAccount(); renderAccountPage(); return; }
    try {
      const result = await window.BLINQ_AUTH.updateProfile({ display_name: value, avatar_variant: state.avatarVariant, avatar_url: currentAvatarUrl() });
      applyAuthenticatedAccount(result.account || {});
      renderNavigation();
      renderAccountPage();
    } catch (error) { alert(`Profile update failed: ${error.message}`); }
  });
  $("signOutButton")?.addEventListener("click", async () => { await window.BLINQ_AUTH?.signOut?.(); location.reload(); });
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
  const isHeader = zoneName === "header";
  const isSidebar = zoneName === "sidebar";
  const zone = isHeader ? (state.ui?.header_zone || { count: 1, items: [] }) : isSidebar ? (state.ui?.sidebar_zone || { count: 1, items: [] }) : (state.ui?.banner_zones?.[zoneName] || { count: 1, items: [] });
  const max = (isHeader || isSidebar) ? 3 : 4;
  const count = clamp(Number(zone.count || 1), 1, max);
  const slots = Array.from({ length: max }, (_, i) => zone.items?.[i] || {});
  const label = isHeader ? "HEADER BANNER ZONE" : isSidebar ? "SIDEBAR BANNER ZONE" : `${zoneName.toUpperCase()} HOMEPAGE ZONE`;
  const layoutMode = zone.layout_mode || (isSidebar ? "stack" : "row");
  const layoutSelect = (!isHeader && !isSidebar) ? `<label class="banner-layout-select">Layout<select class="admin-layout-mode" data-zone="${zoneName}"><option value="row" ${layoutMode === "row" ? "selected" : ""}>1-row / 1–4 across</option><option value="grid_2x2" ${layoutMode === "grid_2x2" ? "selected" : ""}>2 × 2 grid (4 banners)</option></select></label>` : "";
  return `<section class="admin-editor banner-studio-editor" data-banner-zone="${zoneName}">
    <div class="admin-editor-head"><div><span>${label}</span><h3>${sizeHint(count, isHeader ? "header" : "main")}</h3></div>
      <label>Layout<select class="admin-count" data-zone="${zoneName}">${Array.from({length:max},(_,i)=>i+1).map((n)=>`<option value="${n}" ${n===count?"selected":""}>${n} banner${n>1?"s":""}</option>`).join("")}</select></label>
    </div>
    <div class="admin-preview-toolbar"><span>LIVE PREVIEW</span><button class="preview-device active" type="button" data-preview-device="desktop" data-zone="${zoneName}">Desktop</button><button class="preview-device" type="button" data-preview-device="tablet" data-zone="${zoneName}">Tablet</button><button class="preview-device" type="button" data-preview-device="mobile" data-zone="${zoneName}">Mobile</button></div>
    <div class="banner-live-preview preview-desktop" data-preview-zone="${zoneName}"></div>
    <div class="admin-slot-grid">${slots.map((item,i)=>`<article class="admin-slot" data-zone="${zoneName}" data-index="${i}" ${i>=count?'hidden':''}>
      <div class="admin-slot-title"><strong>Slot ${i+1}</strong><span class="slot-dimension" data-slot-dimension>${bannerSlotSpec(zoneName,count,i)}</span></div>
      <label>Plan / theme<select data-field="plan">${["pro","elite","legend","goat","default"].map((x)=>`<option value="${x}" ${String(item.plan||"default")===x?"selected":""}>${x.toUpperCase()}</option>`).join("")}</select></label>
      <label>Eyebrow<input data-field="eyebrow" value="${escapeHtml(item.eyebrow || "")}" /></label>
      <label>Headline<input data-field="headline" value="${escapeHtml(item.headline || "")}" /></label>
      <label>Text<textarea data-field="text" rows="3">${escapeHtml(item.text || "")}</textarea></label>
      <div class="admin-field-row"><label>CTA text<input data-field="button_text" value="${escapeHtml(item.button_text || "Open")}" /></label><label>Link<input data-field="link" value="${escapeHtml(item.link || "#account")}" /></label></div>
      <label>Image URL / asset path<input data-field="image" value="${escapeHtml(item.image || "")}" placeholder="/assets/banner-name.webp" /></label>
      <div class="admin-field-row"><label>Image fit<select data-field="fit"><option value="cover" ${(item.fit||"cover")==="cover"?"selected":""}>Cover</option><option value="contain" ${item.fit==="contain"?"selected":""}>Contain</option></select></label><label>Sponsored<select data-field="sponsored"><option value="false" ${item.sponsored?"":"selected"}>No</option><option value="true" ${item.sponsored?"selected":""}>Yes</option></select></label></div>
      <label class="file-label">Check local creative<input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" data-banner-upload /></label>
      <div class="image-property-box"><span>Required: <strong data-required-size>${bannerSlotSpec(zoneName,count,i)}</strong></span><span>Actual: <strong data-actual-size>—</strong></span><span data-size-status class="size-status neutral">No image selected</span></div>
      <small class="admin-image-note">Local file is preview-only. For global publishing, upload the optimized file to web/assets or your storage/CDN and use that path above.</small>
    </article>`).join("")}</div>
  </section>`;
}

function bannerPreviewCard(item, header = false) {
  const theme = `plan-${escapeHtml(item.plan || "default")}`;
  const img = item.image ? `<div class="${header ? "header-preview-image" : "zone-banner-art"}"><img src="${escapeHtml(item.image)}" alt="" style="object-fit:${escapeHtml(item.fit || "cover")}" /></div>` : `<div class="${header ? "header-preview-image" : "zone-banner-art"} generated-art"><span></span></div>`;
  if (header) return `<article class="header-banner-card ${theme}"><span class="header-sponsor-label">${escapeHtml(item.eyebrow || "BLINQ")}</span><span class="header-sponsor-copy"><strong>${escapeHtml(item.headline || "Banner headline")}</strong><small>${escapeHtml(item.text || "Banner text")}</small></span>${img}</article>`;
  return `<article class="zone-banner ${theme}"><div class="zone-banner-copy"><span class="promo-eyebrow">${escapeHtml(item.eyebrow || "BLINQ")}</span><h2>${escapeHtml(item.headline || "Banner headline")}</h2><p>${escapeHtml(item.text || "Banner text")}</p><span class="promo-cta">${escapeHtml(item.button_text || "Open")}</span></div>${img}</article>`;
}

function editorZoneState(zoneName) {
  const editor = document.querySelector(`[data-banner-zone="${zoneName}"]`);
  if (!editor) return { count: 0, items: [] };
  const count = Number(editor.querySelector(".admin-count")?.value || 1);
  const items = [];
  editor.querySelectorAll(".admin-slot").forEach((slot) => {
    const item = { enabled: true };
    slot.querySelectorAll("[data-field]").forEach((input) => {
      let value = input.value;
      if (input.dataset.field === "sponsored") value = value === "true";
      item[input.dataset.field] = value;
    });
    items[Number(slot.dataset.index)] = item;
  });
  items.forEach((item, index) => { item.banner_id = bannerRegistryId(zoneName, index, item); item.sort_order = index + 1; });
  const layoutMode = editor.querySelector(".admin-layout-mode")?.value || (zoneName === "sidebar" ? "stack" : "row");
  return { count, layout_mode: layoutMode, items };
}

function renderBannerStudioPreview(zoneName) {
  const preview = document.querySelector(`[data-preview-zone="${zoneName}"]`);
  if (!preview) return;
  const zone = editorZoneState(zoneName);
  const items = zone.items.slice(0, zone.count);
  const header = zoneName === "header";
  const sidebar = zoneName === "sidebar";
  preview.classList.toggle("header-preview-zone", header);
  preview.classList.toggle("sidebar-preview-zone", sidebar);
  preview.classList.toggle("main-preview-zone", !header && !sidebar);
  preview.classList.toggle("preview-grid-2x2", zone.layout_mode === "grid_2x2");
  preview.dataset.count = String(zone.count);
  preview.innerHTML = items.map((item) => bannerPreviewCard(item, header)).join("");
}

function updateSlotDimensions(zoneName) {
  const editor = document.querySelector(`[data-banner-zone="${zoneName}"]`);
  if (!editor) return;
  const count = Number(editor.querySelector(".admin-count")?.value || 1);
  const layoutMode = editor.querySelector(".admin-layout-mode")?.value || (zoneName === "sidebar" ? "stack" : "row");
  editor.querySelectorAll(".admin-slot").forEach((slot) => {
    const i = Number(slot.dataset.index);
    const visible = i < count;
    slot.hidden = !visible;
    if (!visible) return;
    const size = bannerSlotSpec(zoneName, count, i, layoutMode);
    slot.querySelector("[data-slot-dimension]").textContent = size;
    slot.querySelector("[data-required-size]").textContent = size;
  });
  editor.querySelector(".admin-editor-head h3").textContent = sizeHint(count, zoneName, layoutMode);
}

function readBannerEditorToState() {
  const header = editorZoneState("header");
  state.ui.header_zone = header;
  state.ui.sidebar_zone = editorZoneState("sidebar");
  ["top", "bottom"].forEach((zoneName) => { state.ui.banner_zones[zoneName] = editorZoneState(zoneName); });
}

function configForPersistence() {
  return {
    header_zone: state.ui.header_zone,
    sidebar_zone: state.ui.sidebar_zone,
    banner_zones: state.ui.banner_zones,
    banner_registry: state.ui.banner_registry,
    navigation: state.ui.navigation,
    plans: state.ui.plans,
    account: state.ui.account,
    branding: state.ui.branding,
    avatar_sets: state.ui.avatar_sets,
    prime_picks: state.ui.prime_picks,
    banner_admin: state.ui.banner_admin,
    access_control: state.ui.access_control,
  };
}

async function publishUiConfig() {
  readBannerEditorToState();
  const payload = configForPersistence();
  const serialized = JSON.stringify(payload);
  if (serialized.includes("data:image/")) throw new Error("A local preview image is still embedded. Publish asset files/URLs instead of data URLs.");
  await adminRequest("/api/v1/admin/ui-config", { method: "POST", body: serialized });
  localStorage.removeItem("blinq_admin_ui_override");
  renderHeaderSponsor(); renderBannerZones();
}

function renderAdminBanners() {
  moduleShell("Banner Studio", "Build header and homepage banner layouts visually, verify exact creative dimensions and publish the configuration globally.", `
    <div class="admin-studio-intro"><div><span class="module-kicker">PERSISTENT ADMIN</span><h2>Homepage Banner Studio</h2><p>BlinQ has 14 uniquely numbered banner slots: 3 header, 4 top, 4 bottom and 3 sidebar. Every slot has independent visibility and unlocked-access rules. Main 4-banner zones can run as one row or a 2×2 grid.</p></div><div class="dimension-legend"><strong>Creative specs</strong><span>Header: 900×180 / 450×180 / 300×180</span><span>Main: 1200×400 / 600×400 / 300×400</span></div></div>
    ${bannerManagerZoneEditor("header")}${bannerManagerZoneEditor("top")}${bannerManagerZoneEditor("bottom")}${bannerManagerZoneEditor("sidebar")}
    <div class="admin-actions sticky-admin-actions"><button class="btn btn-primary" id="publishBannerConfig" type="button">Publish globally</button><button class="btn btn-ghost" id="saveBannerConfig" type="button">Save browser preview</button><button class="btn btn-ghost" id="exportBannerConfig" type="button">Export JSON</button><button class="btn btn-ghost" id="resetBannerConfig" type="button">Reset preview</button></div>
  `);
  bindBannerManager();
}

function bindBannerManager() {
  ["header","top","bottom","sidebar"].forEach((zone) => { updateSlotDimensions(zone); renderBannerStudioPreview(zone); });
  document.querySelectorAll(".admin-count,.admin-layout-mode").forEach((select) => select.addEventListener("change", () => { const zone=select.dataset.zone; updateSlotDimensions(zone); renderBannerStudioPreview(zone); }));
  document.querySelectorAll(".admin-slot [data-field]").forEach((input) => input.addEventListener("input", () => renderBannerStudioPreview(input.closest(".admin-slot").dataset.zone)));
  document.querySelectorAll("[data-preview-device]").forEach((button) => button.addEventListener("click", () => {
    const zone = button.dataset.zone; const preview=document.querySelector(`[data-preview-zone="${zone}"]`); if(!preview)return;
    button.closest(".admin-editor").querySelectorAll("[data-preview-device]").forEach((x)=>x.classList.remove("active")); button.classList.add("active");
    preview.classList.remove("preview-desktop","preview-tablet","preview-mobile"); preview.classList.add(`preview-${button.dataset.previewDevice}`);
  }));
  document.querySelectorAll("[data-banner-upload]").forEach((input) => input.addEventListener("change", () => {
    const file=input.files?.[0]; if(!file)return; const slot=input.closest(".admin-slot");
    if(file.size>2_000_000){alert("Creative is over 2 MB. Optimize it before publishing; recommended target is under 500 KB for web delivery.");}
    const url=URL.createObjectURL(file); const img=new Image(); img.onload=()=>{
      const actual=`${img.naturalWidth}×${img.naturalHeight}`; slot.querySelector("[data-actual-size]").textContent=actual;
      const required=slot.querySelector("[data-required-size]").textContent; const status=slot.querySelector("[data-size-status]");
      const exact=required===actual; status.className=`size-status ${exact?"positive":"warn"}`; status.textContent=exact?"Exact dimensions":"Resize before final publish";
      slot.dataset.localPreviewUrl=url; const imageInput=slot.querySelector('[data-field="image"]'); imageInput.dataset.remoteValue=imageInput.value; imageInput.value=url; renderBannerStudioPreview(slot.dataset.zone);
    }; img.src=url;
  }));
  $("saveBannerConfig")?.addEventListener("click",()=>{readBannerEditorToState();localStorage.setItem("blinq_admin_ui_override",JSON.stringify({header_zone:state.ui.header_zone,sidebar_zone:state.ui.sidebar_zone,banner_zones:state.ui.banner_zones}));renderHeaderSponsor();renderBannerZones();alert("Browser preview saved locally.");});
  $("publishBannerConfig")?.addEventListener("click",async()=>{try{document.querySelectorAll('.admin-slot [data-field="image"]').forEach((input)=>{if(input.value.startsWith("blob:")&&input.dataset.remoteValue!==undefined)input.value=input.dataset.remoteValue;});await publishUiConfig();alert("Banner configuration published to Supabase.");}catch(error){alert(`Publish failed: ${error.message}`);}});
  $("exportBannerConfig")?.addEventListener("click",()=>{readBannerEditorToState();const blob=new Blob([JSON.stringify(configForPersistence(),null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="blinq-ui-config.json";a.click();URL.revokeObjectURL(a.href);});
  $("resetBannerConfig")?.addEventListener("click",()=>{localStorage.removeItem("blinq_admin_ui_override");location.reload();});
}

async function renderAdminUsers() {
  moduleShell("User Management", "Real Supabase Auth accounts and BlinQ plan entitlements.", `<div class="state-card" id="adminUsersState">Loading users…</div>`);
  const shell = $("moduleView")?.querySelector(".module-card");
  if (!shell) return;
  if (!adminKey()) {
    shell.innerHTML = `<div class="access-manager-intro"><div><span class="module-kicker">SECURE ADMIN</span><h2>User Management</h2><p>Unlock the admin session to manage real account plans and activation status.</p></div><button class="btn btn-primary" id="unlockUsersAdmin" type="button">Unlock Admin</button></div>`;
    $("unlockUsersAdmin")?.addEventListener("click", async () => { if (await unlockAdminSession()) renderAdminUsers(); });
    return;
  }
  try {
    const result = await adminRequest("/api/v1/admin/users");
    const users = Array.isArray(result?.users) ? result.users : [];
    const rows = users.map((user) => {
      const expires = user.entitlement_expires_at ? String(user.entitlement_expires_at).slice(0,10) : "";
      return `<tr data-admin-user="${escapeHtml(user.id)}">
        <td class="user-email"><strong>${escapeHtml(user.email || "—")}</strong><br><small>${escapeHtml(fmtDate(user.created_at))}</small></td>
        <td class="user-name"><input data-user-name value="${escapeHtml(user.display_name || "BlinQ User")}" maxlength="80"></td>
        <td class="user-plan"><select data-user-plan>${ACCESS_PLANS.map((plan)=>`<option value="${plan}" ${String(user.plan||"free")===plan?"selected":""}>${plan.toUpperCase()}</option>`).join("")}</select></td>
        <td class="user-expiry"><input data-user-expiry type="date" value="${escapeHtml(expires)}"></td>
        <td><label class="admin-inline-check"><input data-user-active type="checkbox" ${user.is_active !== false ? "checked" : ""}> Active</label></td>
        <td><span class="user-status-badge ${user.is_active !== false ? "active" : "disabled"}">${user.is_active !== false ? "ACTIVE" : "DISABLED"}</span></td>
        <td><button class="btn btn-ghost" type="button" data-save-user>Save</button></td>
      </tr>`;
    }).join("");
    shell.innerHTML = `<div class="access-manager-intro"><div><span class="module-kicker">AUTH ACCOUNTS</span><h2>User Management</h2><p>Every registered account starts at FREE. Change plan, expiry and activation here. Access Manager then decides exactly what that level can see and open.</p></div><div class="access-policy-box"><span>REGISTERED USERS</span><strong>${users.length}</strong><small>Supabase Auth + user_profiles</small></div></div>
      <div class="table-wrap access-manager-wrap"><table class="access-table user-admin-table"><thead><tr><th>User</th><th>Name</th><th>Plan</th><th>Expiry</th><th>Account</th><th>Status</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="7">No registered users yet.</td></tr>'}</tbody></table></div>`;
    shell.querySelectorAll("[data-save-user]").forEach((button)=>button.addEventListener("click", async()=>{
      const row=button.closest("[data-admin-user]");
      const userId=row?.dataset.adminUser;
      if(!userId)return;
      button.disabled=true; button.textContent="Saving…";
      try{
        const expiry=row.querySelector("[data-user-expiry]")?.value || "";
        const plan=row.querySelector("[data-user-plan]")?.value || "free";
        await adminRequest(`/api/v1/admin/users/${encodeURIComponent(userId)}`,{method:"POST",body:JSON.stringify({
          display_name:row.querySelector("[data-user-name]")?.value || "",
          plan,
          plan_label: plan === "free" ? "Free" : plan.toUpperCase(),
          entitlement_expires_at: expiry ? `${expiry}T23:59:59+00:00` : null,
          is_active:Boolean(row.querySelector("[data-user-active]")?.checked),
        })});
        button.textContent="Saved";
        setTimeout(()=>{button.textContent="Save";button.disabled=false;},900);
      }catch(error){alert(`User update failed: ${error.message}`);button.textContent="Save";button.disabled=false;}
    }));
  } catch (error) {
    shell.innerHTML = `<div class="state-card error">User Management unavailable.<small>${escapeHtml(error.message)}</small></div>`;
  }
}


function avatarAdminRows(plan) {
  const rows = normalizeAvatarSet(plan);
  return rows.map((entry, index) => `<div class="avatar-admin-row" data-avatar-admin-row data-plan="${escapeHtml(plan)}" data-index="${index}">
    <div class="avatar-admin-preview"><img src="${escapeHtml(entry.src)}" alt="" /></div>
    <label>Label<input data-avatar-label value="${escapeHtml(entry.label)}" maxlength="80"></label>
    <label>Asset URL<input data-avatar-src value="${escapeHtml(entry.src)}" maxlength="500"></label>
    <label>Type<select data-avatar-gender><option value="woman" ${entry.gender === "woman" ? "selected" : ""}>Woman</option><option value="man" ${entry.gender === "man" ? "selected" : ""}>Man</option><option value="goat" ${entry.gender === "goat" ? "selected" : ""}>GOAT</option><option value="custom" ${!["woman","man","goat"].includes(entry.gender) ? "selected" : ""}>Custom</option></select></label>
    <button class="btn btn-ghost" type="button" data-remove-avatar>Remove</button>
  </div>`).join("");
}

function readAvatarManagerToState() {
  const sets = {};
  ["free","pro","elite","legend","goat"].forEach((plan) => {
    sets[plan] = [...document.querySelectorAll(`[data-avatar-admin-row][data-plan="${plan}"]`)].map((row) => ({
      src: row.querySelector("[data-avatar-src]")?.value.trim() || "",
      label: row.querySelector("[data-avatar-label]")?.value.trim() || `${plan.toUpperCase()} avatar`,
      gender: row.querySelector("[data-avatar-gender]")?.value || "custom",
      enabled: true,
    })).filter((entry) => entry.src);
  });
  sets.admin = [...(sets.goat || [])];
  state.ui.avatar_sets = sets;
}

async function uploadAvatarFile(plan, file, button) {
  if (!file) return;
  if (file.size > 1_500_000) throw new Error("Avatar is over 1.5 MB. Optimize it before upload.");
  const allowed = ["image/png","image/jpeg","image/webp"];
  if (!allowed.includes(file.type)) throw new Error("Use PNG, JPG or WEBP for avatars.");
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Unable to read image."));
    reader.readAsDataURL(file);
  });
  const base64 = dataUrl.split(",", 2)[1] || "";
  button.disabled = true; button.textContent = "Uploading…";
  try {
    const result = await adminRequest("/api/v1/admin/avatar-upload", {
      method: "POST",
      body: JSON.stringify({ plan, filename: file.name, content_type: file.type, data_base64: base64 }),
    });
    const rows = Array.isArray(state.ui.avatar_sets?.[plan]) ? state.ui.avatar_sets[plan] : [];
    rows.push({ src: result.url, label: `${plan.toUpperCase()} custom`, gender: "custom", enabled: true });
    state.ui.avatar_sets[plan] = rows;
    if (plan === "goat") state.ui.avatar_sets.admin = [...rows];
    renderAdminAvatars();
  } finally { button.disabled = false; button.textContent = "Upload"; }
}

async function renderAdminAvatars() {
  const plans = ["free","pro","elite","legend","goat"];
  moduleShell("Avatar Manager", "Manage tier avatar catalog. Higher plans automatically inherit every lower-tier avatar.", `
    <div class="access-manager-intro"><div><span class="module-kicker">PROFILE ASSETS</span><h2>Avatar Manager</h2><p>FREE sees Free avatars. PRO inherits Free + PRO. Elite inherits all previous, then Legend, and GOAT unlocks the full catalog. Uploads are stored in the public BlinQ asset bucket.</p></div><div class="access-policy-box"><span>INHERITANCE</span><strong>Automatic</strong><small>FREE → PRO → ELITE → LEGEND → GOAT</small></div></div>
    <div class="avatar-admin-grid">${plans.map((plan) => `<section class="avatar-admin-card" data-avatar-plan-card="${plan}"><div class="section-title-row"><div><span class="module-kicker">${plan.toUpperCase()}</span><h3>${plan === "goat" ? "GOAT" : `${plan.toUpperCase()} avatars`}</h3></div><small>${normalizeAvatarSet(plan).length} assets</small></div><div class="avatar-admin-list">${avatarAdminRows(plan)}</div><div class="avatar-upload-row"><input type="file" accept="image/png,image/jpeg,image/webp" data-avatar-upload-file="${plan}"><button class="btn btn-ghost" type="button" data-avatar-upload="${plan}">Upload</button></div></section>`).join("")}</div>
    <div class="admin-actions sticky-admin-actions"><button class="btn btn-primary" id="publishAvatarConfig" type="button">Publish avatar catalog</button><button class="btn btn-ghost" id="saveAvatarPreview" type="button">Save browser preview</button></div>
  `);
  document.querySelectorAll("[data-remove-avatar]").forEach((button) => button.addEventListener("click", () => { button.closest("[data-avatar-admin-row]")?.remove(); }));
  document.querySelectorAll("[data-avatar-upload]").forEach((button) => button.addEventListener("click", async () => {
    const plan = button.dataset.avatarUpload;
    const file = document.querySelector(`[data-avatar-upload-file="${plan}"]`)?.files?.[0];
    try { await uploadAvatarFile(plan, file, button); } catch (error) { alert(`Upload failed: ${error.message}`); button.disabled=false; button.textContent="Upload"; }
  }));
  $("saveAvatarPreview")?.addEventListener("click", () => { readAvatarManagerToState(); localStorage.setItem("blinq_admin_ui_override", JSON.stringify({ avatar_sets: state.ui.avatar_sets })); alert("Avatar preview saved locally."); });
  $("publishAvatarConfig")?.addEventListener("click", async () => { try { readAvatarManagerToState(); await publishUiConfig(); alert("Avatar catalog published globally."); } catch (error) { alert(`Publish failed: ${error.message}`); } });
}

function accessManagerEntries() {
  ensureAccessRegistry();
  const rows = Object.values(state.ui.access_control.entries || {});
  const typeOrder = { page: 0, panel: 1 };
  return rows.sort((a, b) =>
    String(a.group || "").localeCompare(String(b.group || "")) ||
    (typeOrder[a.type] ?? 9) - (typeOrder[b.type] ?? 9) ||
    String(a.label || a.id).localeCompare(String(b.label || b.id))
  );
}

function accessManagerSummary(entries) {
  return ACCESS_PLANS.map((plan) => {
    const total = entries.filter((e) => !e.admin_only || plan === "admin").length;
    const unlocked = entries.filter((e) => normalizePlanList(e.allowed_plans).includes(plan)).length;
    const visible = entries.filter((e) => normalizePlanList(e.visible_plans).includes(plan)).length;
    return `<article class="access-summary-card"><small>${plan.toUpperCase()}</small><strong>${unlocked}/${total}</strong><span>unlocked · ${visible} visible</span></article>`;
  }).join("");
}

function accessManagerRow(entry) {
  const dataStatus = (() => {
    if (!String(entry.id).startsWith("route.")) return "";
    const item = navItem(String(entry.id).slice(6));
    return item?.data_status || "";
  })();
  const cells = ACCESS_PLANS.map((plan) => {
    const locked = entry.admin_only && plan !== "admin";
    const visible = normalizePlanList(entry.visible_plans).includes(plan);
    const allowed = normalizePlanList(entry.allowed_plans).includes(plan);
    return `<td class="access-plan-cell" data-plan-cell="${plan}">
      <label title="Visible"><span>V</span><input type="checkbox" data-access-visible="${plan}" ${visible ? "checked" : ""} ${locked ? "disabled" : ""}></label>
      <label title="Unlocked"><span>A</span><input type="checkbox" data-access-allowed="${plan}" ${allowed ? "checked" : ""} ${locked ? "disabled" : ""}></label>
    </td>`;
  }).join("");
  return `<tr data-access-feature-row="${escapeHtml(entry.id)}" data-access-type="${escapeHtml(entry.type || "other")}" data-access-group="${escapeHtml(entry.group || "Other")}">
    <td class="access-feature-cell"><div><strong>${escapeHtml(entry.label || entry.id)}</strong><small>${escapeHtml(entry.id)}</small></div>${entry.auto_discovered ? '<span class="auto-badge">AUTO</span>' : ""}</td>
    <td><span class="access-type-badge">${escapeHtml(entry.type || "feature")}</span></td>
    <td>${escapeHtml(entry.group || "Other")}</td>
    ${cells}
    <td>${dataStatus ? `<span class="data-status-warn">${escapeHtml(dataStatus)}</span>` : '<span class="data-status-ready">ready</span>'}</td>
    <td class="row-actions"><button class="mini-action" type="button" data-row-grant-all>All</button><button class="mini-action" type="button" data-row-revoke-all>None</button></td>
  </tr>`;
}

function readAccessManagerToState() {
  ensureAccessRegistry();
  document.querySelectorAll("[data-access-feature-row]").forEach((row) => {
    const entry = state.ui.access_control.entries[row.dataset.accessFeatureRow];
    if (!entry) return;
    if (entry.admin_only) {
      entry.allowed_plans = ["admin"];
      entry.visible_plans = ["admin"];
      return;
    }
    entry.visible_plans = ACCESS_PLANS.filter((plan) => row.querySelector(`[data-access-visible="${plan}"]`)?.checked);
    entry.allowed_plans = ACCESS_PLANS.filter((plan) => row.querySelector(`[data-access-allowed="${plan}"]`)?.checked);
    // Access implies visibility. Keep the matrix internally consistent.
    entry.allowed_plans.forEach((plan) => { if (!entry.visible_plans.includes(plan)) entry.visible_plans.push(plan); });
    entry.visible_plans = normalizePlanList(entry.visible_plans);
    entry.allowed_plans = normalizePlanList(entry.allowed_plans);
  });
  syncRouteAccessBackToNavigation();
}

function bindAccessManager() {
  const table = $("accessManagerTable");
  const applyFilter = () => {
    const q = String($("accessSearch")?.value || "").trim().toLowerCase();
    const type = $("accessTypeFilter")?.value || "";
    const group = $("accessGroupFilter")?.value || "";
    document.querySelectorAll("[data-access-feature-row]").forEach((row) => {
      const hay = row.textContent.toLowerCase();
      row.hidden = Boolean((q && !hay.includes(q)) || (type && row.dataset.accessType !== type) || (group && row.dataset.accessGroup !== group));
    });
  };
  $("accessSearch")?.addEventListener("input", applyFilter);
  $("accessTypeFilter")?.addEventListener("change", applyFilter);
  $("accessGroupFilter")?.addEventListener("change", applyFilter);

  table?.addEventListener("change", (event) => {
    const input = event.target.closest("input[type=checkbox]");
    if (!input) return;
    const row = input.closest("[data-access-feature-row]");
    if (!row) return;
    const plan = input.dataset.accessAllowed || input.dataset.accessVisible;
    if (input.dataset.accessAllowed && input.checked) {
      const visible = row.querySelector(`[data-access-visible="${plan}"]`);
      if (visible) visible.checked = true;
    }
    if (input.dataset.accessVisible && !input.checked) {
      const allowed = row.querySelector(`[data-access-allowed="${plan}"]`);
      if (allowed) allowed.checked = false;
    }
  });

  table?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-access-feature-row]");
    if (!row) return;
    if (event.target.closest("[data-row-grant-all]")) {
      row.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach((x) => { x.checked = true; });
    }
    if (event.target.closest("[data-row-revoke-all]")) {
      row.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach((x) => { x.checked = false; });
    }
  });

  document.querySelectorAll("[data-plan-bulk]").forEach((button) => button.addEventListener("click", () => {
    const plan = button.dataset.planBulk;
    const mode = button.dataset.bulkMode;
    document.querySelectorAll(`[data-access-feature-row] [data-access-visible="${plan}"]:not(:disabled), [data-access-feature-row] [data-access-allowed="${plan}"]:not(:disabled)`).forEach((x) => { x.checked = mode === "grant"; });
  }));

  $("grantEverything")?.addEventListener("click", () => {
    document.querySelectorAll('[data-access-feature-row] input[type="checkbox"]:not(:disabled)').forEach((x) => { x.checked = true; });
  });
  $("publishAccessMatrix")?.addEventListener("click", async () => {
    try {
      readAccessManagerToState();
      await adminRequest("/api/v1/admin/ui-config", { method: "POST", body: JSON.stringify(configForPersistence()) });
      renderNavigation(); renderHeaderSponsor(); renderBannerZones(); applyManagedPanelVisibility();
      alert("Access configuration published globally.");
    } catch (error) { alert(`Publish failed: ${error.message}`); }
  });
}

function renderAdminAccess() {
  const entries = accessManagerEntries();
  const groups = [...new Set(entries.map((e) => e.group || "Other"))].sort();
  const rows = entries.map(accessManagerRow).join("");
  const bulkHeads = ACCESS_PLANS.map((plan) => `<th><div class="plan-head"><strong>${plan.toUpperCase()}</strong><span><button type="button" data-plan-bulk="${plan}" data-bulk-mode="grant">All</button><button type="button" data-plan-bulk="${plan}" data-bulk-mode="revoke">None</button></span></div></th>`).join("");
  moduleShell("Access Manager", "Control visibility and unlocked access for every account level. Pages, whole zones and individual banner slots are managed here; new managed features default to all plans.", `
    <div class="access-manager-intro">
      <div><span class="module-kicker">GLOBAL ENTITLEMENTS</span><h2>Pages & panels access</h2><p>Every registered page, managed panel and banner slot appears here automatically. New features default to <strong>Visible + Unlocked for all plans</strong> until you change them. You can hide a panel completely or leave it visible but locked. Admin-only tools remain protected.</p></div>
      <div class="access-policy-box"><span>NEW FEATURE POLICY</span><strong>ALL LEVELS</strong><small>Access does not bypass missing data/model requirements.</small></div>
    </div>
    <div class="access-manager-summary">${accessManagerSummary(entries)}</div>
    <div class="access-manager-toolbar">
      <input id="accessSearch" type="search" placeholder="Search page, panel or feature ID…" />
      <select id="accessTypeFilter"><option value="">All types</option><option value="page">Pages</option><option value="panel">Panels</option></select>
      <select id="accessGroupFilter"><option value="">All groups</option>${groups.map((g)=>`<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join("")}</select>
      <button class="btn btn-ghost" id="grantEverything" type="button">Grant all levels</button>
      <button class="btn btn-primary" id="publishAccessMatrix" type="button">Publish globally</button>
    </div>
    <div class="access-legend"><span><b>V</b> Visible</span><span><b>A</b> Unlocked access</span><span><i class="auto-badge">AUTO</i> auto-registered</span></div>
    <div class="table-wrap access-manager-wrap"><table class="access-table access-editor-table access-manager-table" id="accessManagerTable"><thead><tr><th>Feature</th><th>Type</th><th>Group</th>${bulkHeads}<th>Data</th><th>Row</th></tr></thead><tbody>${rows}</tbody></table></div>
  `);
  bindAccessManager();
}


function loadBetSlip() {
  try {
    const raw = JSON.parse(localStorage.getItem("blinq_bet_slip_beta") || "[]");
    state.betSlip = Array.isArray(raw) ? raw : [];
  } catch (_) { state.betSlip = []; }
}

function saveBetSlip() {
  localStorage.setItem("blinq_bet_slip_beta", JSON.stringify(state.betSlip));
}

function addToBetSlip(match) {
  const max = clamp(Number(state.ui?.bets_beta?.max_slip_selections || 5), 1, 10);
  if (state.betSlip.some((x) => String(x.id) === String(match.id))) return;
  if (state.betSlip.length >= max) { alert(`Beta bet slip supports up to ${max} selections.`); return; }
  state.betSlip.push({
    id: match.id, date: match.date, tour: match.tour, tournament: match.tournament, surface: match.surface,
    p1: match.p1, p2: match.p2, pick: match.pick, probability: match.probability, confidence: match.confidence,
    agreement: primeTieBreakers(match).factorAgreement, dataDepth: primeTieBreakers(match).dataDepth
  });
  saveBetSlip();
  if (state.currentRoute === "bets_beta") renderBetsBeta();
}

function removeFromBetSlip(id) {
  state.betSlip = state.betSlip.filter((x) => String(x.id) !== String(id));
  saveBetSlip();
  if (state.currentRoute === "bets_beta") renderBetsBeta();
}

function betaBetCard(match, index) {
  const quality = primeTieBreakers(match);
  return `<article class="beta-bet-card">
    <div class="beta-bet-top"><span class="beta-chip">BETA · STRAIGHT PICK</span><span>#${index + 1}</span></div>
    <div class="beta-bet-match"><small>${escapeHtml(match.tour || "TOUR")} · ${escapeHtml(match.tournament || "Tournament")}</small><strong>${escapeHtml(match.p1)} <em>vs</em> ${escapeHtml(match.p2)}</strong><span>${escapeHtml(String(match.surface || "unknown").replaceAll("_"," "))} · ${escapeHtml(fmtTime(match.date))}</span></div>
    <div class="beta-bet-selection"><div><small>BlinQ selection</small><strong>${escapeHtml(match.pick || "—")}</strong></div><div><small>Model win probability</small><b>${fmtPct(match.probability)}</b></div></div>
    <div class="beta-bet-quality"><span>Confidence <strong>${escapeHtml(String(match.confidence || "low").toUpperCase())}</strong></span><span>Agreement <strong>${quality.factorAgreement.toFixed(0)}%</strong></span><span>Data depth <strong>${quality.dataDepth.toFixed(0)}%</strong></span></div>
    <button class="btn btn-primary btn-full" type="button" data-add-beta-bet="${escapeHtml(match.id)}">Add to Bet Slip</button>
  </article>`;
}

function renderBetsBeta() {
  loadBetSlip();
  const cfgBet = state.ui?.bets_beta || {};
  const limit = clamp(Number(cfgBet.display_limit || 3), 1, 10);
  const minP = Number(cfgBet.minimum_probability_pct || 0);
  const rows = primeRows(state.predictions).filter((m) => Number(m.probability || 0) >= minP).slice(0, limit);
  const slipRows = state.betSlip.map((x) => `<article class="bet-slip-row"><div><small>${escapeHtml(x.tournament || "Tournament")}</small><strong>${escapeHtml(x.pick || "—")}</strong><span>${escapeHtml(x.p1)} vs ${escapeHtml(x.p2)}</span></div><div><b>${fmtPct(x.probability)}</b><button class="bet-slip-remove" type="button" data-remove-beta-bet="${escapeHtml(x.id)}" aria-label="Remove">×</button></div></article>`).join("");
  moduleShell(
    "BlinQ Bets · Beta",
    "First model-backed straight selections. Market odds are not connected yet, so no value edge, payout or stake recommendation is invented.",
    `<div class="bets-beta-intro"><div><span class="module-kicker">EARLY ACCESS</span><h2>First Bets Beta</h2><p>Selections come from the same calibrated probability engine as Prime Picks. This beta is a shortlist workflow, not a bookmaker-value model.</p></div><span class="status-pill neutral">ODDS FEED: NOT CONNECTED</span></div>
    <div class="bets-beta-layout">
      <section><div class="section-title-row"><div><span class="module-kicker">MODEL SELECTIONS</span><h3>Top straight picks</h3></div><small>Ranked by calibrated win probability</small></div><div class="beta-bet-grid">${rows.length ? rows.map(betaBetCard).join("") : '<div class="state-card feed-empty"><strong>No current selections</strong><small>Run Refresh TBT predictions to populate this beta board.</small></div>'}</div></section>
      <aside class="bet-slip-panel"><div class="section-title-row"><div><span class="module-kicker">PERSONAL SHORTLIST</span><h3>Bet Slip · Beta</h3></div><small>${state.betSlip.length} selected</small></div>${slipRows || '<div class="bet-slip-empty">Add one of the model selections to build a shortlist.</div>'}<div class="bet-slip-note"><strong>No bookmaker odds yet</strong><span>Stake, potential return and Value Pick edge stay disabled until a real market-odds feed is connected.</span></div>${state.betSlip.length ? '<button class="btn btn-ghost btn-full" id="clearBetaSlip" type="button">Clear Bet Slip</button>' : ''}</aside>
    </div>
    <div class="responsible-beta-note">BlinQ probabilities are analytical estimates, not guarantees. Use the beta as decision support and set your own limits.</div>`
  );
  const byId = new Map(state.predictions.map((m)=>[String(m.id),m]));
  document.querySelectorAll("[data-add-beta-bet]").forEach((button)=>button.addEventListener("click",()=>{const m=byId.get(String(button.dataset.addBetaBet));if(m)addToBetSlip(m);}));
  document.querySelectorAll("[data-remove-beta-bet]").forEach((button)=>button.addEventListener("click",()=>removeFromBetSlip(button.dataset.removeBetaBet)));
  $("clearBetaSlip")?.addEventListener("click",()=>{state.betSlip=[];saveBetSlip();renderBetsBeta();});
}

function renderCurrentModule() {
  const route = state.currentRoute;
  if (route === "bets_beta") return renderBetsBeta();
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
  if (route === "admin_avatars") return renderAdminAvatars();
  return moduleShell("Module", "This module is prepared for connection.", '<div class="state-card">Prepared.</div>');
}

function routeFromHash() {
  const raw = String(location.hash || "#dashboard").replace(/^#/, "");
  const aliases = {
    "how-it-works": "how_blinq_works",
    "prime-picks": "prime_picks",
    "bets-beta": "bets_beta",
    "value-picks": "value_picks",
    "ace-picks": "ace_picks",
    "games-sets": "games_sets",
    "model-data": "model_data",
    "responsible-use": "responsible_use",
    "admin-banners": "admin_banners",
    "admin-users": "admin_users",
    "admin-access": "admin_access",
    "admin-avatars": "admin_avatars"
  };
  const token = aliases[raw] || raw.replaceAll("-", "_");
  return navItem(token) ? token : "dashboard";
}

function setupEvents() {
  bindAuthEvents();
  $("refreshButton")?.addEventListener("click", loadPredictions);
  ["tourFilter", "tournamentFilter", "surfaceFilter", "confidenceFilter"].forEach((id) => $(id).addEventListener("change", () => { state.featuredIndex = 0; state.allPredictions = false; renderPredictions(); }));
  $("searchInput").addEventListener("input", () => { state.featuredIndex = 0; state.allPredictions = false; renderPredictions(); });
  $("prevPick").addEventListener("click", () => { const rows = primeRows(); if (!rows.length) return; state.featuredIndex = (state.featuredIndex - 1 + rows.length) % rows.length; renderPredictions(); });
  $("nextPick").addEventListener("click", () => { const rows = primeRows(); if (!rows.length) return; state.featuredIndex = (state.featuredIndex + 1) % rows.length; renderPredictions(); });
  $("viewAllButton").addEventListener("click", () => {
    if (state.currentRoute === "dashboard" && !state.allPredictions) return navigate("prime_picks");
    state.allPredictions = !state.allPredictions; renderPredictions();
  });

  document.addEventListener("click", (event) => {
    const language = event.target.closest("[data-lang-choice]")?.dataset.langChoice;
    if (language && supportedLanguages.includes(language)) { localStorage.setItem("blinq_language", language); return; }
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
  state.language = resolveLanguage();
  applyLanguageChrome();
  setupEvents();
  await loadUiConfig();
  const identityReady = await initializeIdentity();
  if (!identityReady) return;
  renderBranding();
  renderHeaderSponsor();
  renderBannerZones();
  renderPlanGrid();
  ensureAccessRegistry();
  renderNavigation();
  applyManagedPanelVisibility();
  showAuthenticatedApp();
  state.currentRoute = routeFromHash();
  navigate(state.currentRoute);
  await loadPredictions();
  setInterval(loadPredictions, Math.max(1, Number(cfg.refreshMinutes || 5)) * 60 * 1000);
}

boot();
