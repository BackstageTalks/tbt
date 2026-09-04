(() => {
  "use strict";

  const SESSION_KEY = "blinq_auth_session_v1";
  const apiBase = () => String(window.BLINQ_CONFIG?.apiBase || "").replace(/\/$/, "");
  const api = (path) => `${apiBase()}${path}`;
  let config = null;
  let recoveryMode = false;

  function readSession() {
    try {
      const value = JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
      return value && typeof value === "object" ? value : null;
    } catch (_) {
      return null;
    }
  }

  function normalizeSession(payload) {
    if (!payload?.access_token) return null;
    const expiresIn = Number(payload.expires_in || 3600);
    const expiresAt = Number(payload.expires_at || 0) || Math.floor(Date.now() / 1000) + expiresIn;
    return {
      access_token: String(payload.access_token),
      refresh_token: String(payload.refresh_token || ""),
      token_type: String(payload.token_type || "bearer"),
      expires_at: expiresAt,
      user: payload.user || null,
    };
  }

  function saveSession(payload) {
    const session = normalizeSession(payload);
    if (!session) return null;
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    return session;
  }

  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
  }

  async function jsonFetch(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...(options.headers || {}) },
      cache: "no-store",
    });
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      const message = data?.msg || data?.message || data?.error_description || data?.error || `HTTP ${response.status}`;
      const error = new Error(String(message));
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }

  function authEndpoint(path) {
    if (!config?.supabase_url) throw new Error("Authentication is not configured.");
    return `${String(config.supabase_url).replace(/\/$/, "")}/auth/v1${path}`;
  }

  function authHeaders(session = null) {
    const headers = { apikey: config?.anon_key || "" };
    if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
    return headers;
  }

  function consumeCallbackFragment() {
    const raw = String(location.hash || "").replace(/^#/, "");
    if (!raw.includes("access_token=")) return;
    const params = new URLSearchParams(raw);
    const accessToken = params.get("access_token");
    if (!accessToken) return;
    const session = saveSession({
      access_token: accessToken,
      refresh_token: params.get("refresh_token") || "",
      token_type: params.get("token_type") || "bearer",
      expires_in: Number(params.get("expires_in") || 3600),
      expires_at: Number(params.get("expires_at") || 0),
    });
    recoveryMode = params.get("type") === "recovery";
    if (session) history.replaceState(null, "", `${location.pathname}${location.search}#dashboard`);
  }

  async function init() {
    config = await jsonFetch(api("/api/v1/auth/config"));
    consumeCallbackFragment();
    return config;
  }

  function isEnabled() { return Boolean(config?.enabled); }

  function isTelegramEnabled() { return Boolean(config?.telegram_enabled && config?.telegram_provider); }
  function telegramProvider() { return String(config?.telegram_provider || "custom:telegram"); }

  function signInWithTelegram() {
    if (!isTelegramEnabled()) throw new Error("Telegram login is not configured yet.");
    const redirectTo = `${location.origin}${location.pathname}${location.search}`;
    const params = new URLSearchParams({
      provider: telegramProvider(),
      redirect_to: redirectTo,
    });
    location.assign(`${authEndpoint("/authorize")}?${params.toString()}`);
  }
  function isRequired() { return config?.required !== false; }
  function isRecovery() { return recoveryMode; }

  async function refreshSession() {
    const current = readSession();
    if (!current?.refresh_token) return null;
    try {
      const data = await jsonFetch(authEndpoint("/token?grant_type=refresh_token"), {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
      return saveSession(data);
    } catch (_) {
      clearSession();
      return null;
    }
  }

  async function restoreSession() {
    let session = readSession();
    if (!session?.access_token) return null;
    const now = Math.floor(Date.now() / 1000);
    if (Number(session.expires_at || 0) <= now + 60) session = await refreshSession();
    return session;
  }

  async function signIn(email, password) {
    const data = await jsonFetch(authEndpoint("/token?grant_type=password"), {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ email: String(email || "").trim(), password: String(password || "") }),
    });
    return saveSession(data);
  }

  function normalizeTelegramHandle(value) {
    const raw = String(value || "").trim().replace(/^@+/, "");
    if (!/^[A-Za-z0-9_]{5,32}$/.test(raw)) throw new Error("Enter a valid Telegram username, e.g. @backstagetalks.");
    return `@${raw}`;
  }

  async function signUp(telegramAccount, email, password) {
    const redirectTo = `${location.origin}${location.pathname.replace(/[^/]*$/, "")}`;
    const telegramHandle = normalizeTelegramHandle(telegramAccount);
    const data = await jsonFetch(`${authEndpoint("/signup")}?redirect_to=${encodeURIComponent(redirectTo)}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        email: String(email || "").trim(),
        password: String(password || ""),
        data: {
          display_name: telegramHandle,
          telegram_handle: telegramHandle.replace(/^@/, ""),
          preferred_username: telegramHandle.replace(/^@/, ""),
        },
      }),
    });
    const session = saveSession(data);
    const identities = Array.isArray(data?.user?.identities) ? data.user.identities : null;
    const existingAccount = Boolean(data?.user && identities && identities.length === 0);
    const confirmationRequired = Boolean(data?.user && !session && !existingAccount);
    return { data, session, existingAccount, confirmationRequired, telegramHandle };
  }

  async function requestPasswordReset(email) {
    const redirectTo = `${location.origin}${location.pathname.replace(/[^/]*$/, "")}`;
    await jsonFetch(`${authEndpoint("/recover")}?redirect_to=${encodeURIComponent(redirectTo)}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ email: String(email || "").trim() }),
    });
    return true;
  }

  async function updatePassword(password) {
    const session = await restoreSession();
    if (!session?.access_token) throw new Error("Recovery session expired. Request a new reset link.");
    await jsonFetch(authEndpoint("/user"), {
      method: "PUT",
      headers: authHeaders(session),
      body: JSON.stringify({ password: String(password || "") }),
    });
    recoveryMode = false;
    return true;
  }

  async function signOut() {
    const session = readSession();
    if (session?.access_token) {
      try {
        await jsonFetch(authEndpoint("/logout"), {
          method: "POST",
          headers: authHeaders(session),
          body: JSON.stringify({}),
        });
      } catch (_) {}
    }
    clearSession();
  }

  function authorizationHeader() {
    const session = readSession();
    return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
  }

  async function me() {
    const session = await restoreSession();
    if (!session?.access_token) throw new Error("Not signed in.");
    return jsonFetch(api("/api/v1/auth/me"), { headers: authorizationHeader() });
  }

  async function updateProfile(fields) {
    const session = await restoreSession();
    if (!session?.access_token) throw new Error("Not signed in.");
    return jsonFetch(api("/api/v1/auth/profile"), {
      method: "POST",
      headers: authorizationHeader(),
      body: JSON.stringify(fields || {}),
    });
  }

  window.BLINQ_AUTH = {
    init,
    isEnabled,
    isRequired,
    isRecovery,
    isTelegramEnabled,
    telegramProvider,
    signInWithTelegram,
    restoreSession,
    refreshSession,
    signIn,
    signUp,
    requestPasswordReset,
    updatePassword,
    signOut,
    me,
    updateProfile,
    authorizationHeader,
    clearSession,
  };
})();
