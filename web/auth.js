(() => {
  "use strict";

  const SESSION_KEY = "blinq_auth_session_v1";
  const apiBase = () => String(window.BLINQ_CONFIG?.apiBase || "").replace(/\/$/, "");
  const api = (path) => `${apiBase()}${path}`;
  let config = null;
  let recoveryMode = false;
  let callbackState = { type: "", error: "", message: "" };

  function readSession() {
    try {
      const value = JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
      return value && typeof value === "object" ? value : null;
    } catch (_) {
      return null;
    }
  }

  function normalizeSession(payload) {
    const source = payload?.session?.access_token ? payload.session : payload;
    if (!source?.access_token) return null;
    const expiresIn = Number(source.expires_in || 3600);
    const expiresAt = Number(source.expires_at || 0) || Math.floor(Date.now() / 1000) + expiresIn;
    return {
      access_token: String(source.access_token),
      refresh_token: String(source.refresh_token || ""),
      token_type: String(source.token_type || "bearer"),
      expires_at: expiresAt,
      user: source.user || payload?.user || null,
    };
  }

  function extractUser(payload) {
    if (payload?.user && typeof payload.user === "object") return payload.user;
    if (payload?.id && typeof payload === "object") return payload;
    return null;
  }

  function redirectBaseUrl() {
    const pathname = String(location.pathname || "/");
    const cleanPath = pathname.endsWith("/")
      ? pathname
      : pathname.replace(/\/[^/]*$/, "/");
    return `${location.origin}${cleanPath}`;
  }

  function cleanAuthCallbackUrl() {
    return `${location.pathname}${location.search}`;
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
    if (!raw) return;

    const params = new URLSearchParams(raw);
    const error = params.get("error_description") || params.get("error") || "";
    const errorCode = params.get("error_code") || "";

    if (error || errorCode) {
      callbackState = {
        type: String(params.get("type") || ""),
        error: String(errorCode || "auth_callback_error"),
        message: String(error || "Authentication link is invalid or expired."),
      };
      history.replaceState(null, "", cleanAuthCallbackUrl());
      return;
    }

    const accessToken = params.get("access_token");
    if (!accessToken) return;

    const type = String(params.get("type") || "");
    const session = saveSession({
      access_token: accessToken,
      refresh_token: params.get("refresh_token") || "",
      token_type: params.get("token_type") || "bearer",
      expires_in: Number(params.get("expires_in") || 3600),
      expires_at: Number(params.get("expires_at") || 0),
    });

    recoveryMode = type === "recovery";
    callbackState = {
      type,
      error: "",
      message: type === "signup"
        ? "Email confirmed successfully."
        : (type === "recovery" ? "Recovery link accepted." : ""),
    };

    if (session) history.replaceState(null, "", cleanAuthCallbackUrl());
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
  function getCallbackState() { return { ...callbackState }; }

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
    const redirectTo = redirectBaseUrl();
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

    // GoTrue /signup has two valid success shapes:
    // 1) AccessTokenResponse when email confirmation is disabled
    // 2) UserSchema at the top level when confirmation is required
    const session = saveSession(data);
    const user = extractUser(data);
    const confirmationRequired = Boolean(user && !session);

    return {
      data,
      user,
      session,
      confirmationRequired,
      telegramHandle,
    };
  }

  async function requestPasswordReset(email) {
    const redirectTo = redirectBaseUrl();
    await jsonFetch(`${authEndpoint("/recover")}?redirect_to=${encodeURIComponent(redirectTo)}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ email: String(email || "").trim() }),
    });
    return true;
  }

  async function resendSignupConfirmation(email) {
    await jsonFetch(authEndpoint("/resend"), {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        email: String(email || "").trim(),
        type: "signup",
      }),
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
    getCallbackState,
    isTelegramEnabled,
    telegramProvider,
    signInWithTelegram,
    restoreSession,
    refreshSession,
    signIn,
    signUp,
    requestPasswordReset,
    resendSignupConfirmation,
    updatePassword,
    signOut,
    me,
    updateProfile,
    authorizationHeader,
    clearSession,
  };
})();
