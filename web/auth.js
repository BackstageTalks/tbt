(() => {
  'use strict';

  // Firebase web configuration is intentionally public client configuration.
  // Server credentials never enter the web bundle.
  const FIREBASE_WEB = Object.freeze({
    apiKey: 'AIzaSyDMH_CDVsJL_nu369r-s3kQDYpGrSfzevE',
    authDomain: 'blinq-182.firebaseapp.com',
    projectId: 'blinq-182',
  });

  const KEY = 'blinq_v4_session';
  const EPOCH_KEY = 'blinq_v4_session_epoch';
  const LEGACY_KEYS = ['blinq_v3_session', 'blinq_v3_session_epoch'];
  let config = null;
  let refreshing = null;

  function epoch() { return localStorage.getItem(EPOCH_KEY) || ''; }
  function mutateEpoch() {
    const value = `${Date.now()}:${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(EPOCH_KEY, value);
    return value;
  }
  function session() {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); }
    catch { return null; }
  }
  function clear() {
    mutateEpoch();
    localStorage.removeItem(KEY);
    sessionStorage.removeItem(KEY);
  }
  function clearLegacy() { LEGACY_KEYS.forEach(key => localStorage.removeItem(key)); }

  function normalizeSession(value, provider = config?.provider || 'firebase') {
    const s = value?.session || value || {};
    const access = s.access_token || s.idToken || s.id_token || '';
    const refresh = s.refresh_token || s.refreshToken || '';
    const expiresIn = Number(s.expires_in || s.expiresIn || 3600);
    if (!access) return null;
    return {
      provider,
      access_token: access,
      refresh_token: refresh,
      expires_at: Number(s.expires_at) || Math.floor(Date.now() / 1000) + expiresIn,
    };
  }
  function save(value, expectedEpoch = null, provider = config?.provider || 'firebase') {
    if (expectedEpoch !== null && epoch() !== expectedEpoch) return null;
    const normalized = normalizeSession(value, provider);
    if (!normalized) return null;
    if (expectedEpoch !== null && epoch() !== expectedEpoch) return null;
    const serialized = JSON.stringify(normalized);
    localStorage.setItem(KEY, serialized);
    if (expectedEpoch !== null && epoch() !== expectedEpoch) {
      if (localStorage.getItem(KEY) === serialized) localStorage.removeItem(KEY);
      return null;
    }
    return normalized;
  }
  function replaceSession(value, provider = config?.provider || 'firebase') {
    const nextEpoch = mutateEpoch();
    return save(value, nextEpoch, provider);
  }

  function errorMessage(data, status) {
    let raw = data?.error_description || data?.msg || data?.message || data?.error || `HTTP ${status}`;
    if (raw && typeof raw === 'object') raw = raw.message || raw.status || JSON.stringify(raw);
    raw = String(raw || `HTTP ${status}`);
    const code = raw.split(' : ')[0].trim().toUpperCase();
    const friendly = {
      INVALID_LOGIN_CREDENTIALS: 'Incorrect email or password.',
      EMAIL_NOT_FOUND: 'Incorrect email or password.',
      INVALID_PASSWORD: 'Incorrect email or password.',
      EMAIL_EXISTS: 'An account with this email already exists.',
      WEAK_PASSWORD: 'Choose a stronger password with at least eight characters.',
      INVALID_EMAIL: 'Enter a valid email address.',
      TOO_MANY_ATTEMPTS_TRY_LATER: 'Too many attempts. Try again later.',
      USER_DISABLED: 'This account has been disabled.',
      TOKEN_EXPIRED: 'Your session expired. Sign in again.',
      INVALID_ID_TOKEN: 'Your session is no longer valid. Sign in again.',
    };
    return friendly[code] || raw.replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
  }

  async function json(url, options = {}) {
    const headers = {Accept: 'application/json', ...(options.headers || {})};
    if (options.body && !Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
      headers['Content-Type'] = 'application/json';
    }
    const response = await fetch(url, {
      ...options,
      headers,
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(errorMessage(data, response.status));
      error.status = response.status;
      error.code = typeof data?.error === 'object' ? data.error.message : data?.error;
      throw error;
    }
    return data;
  }

  function provider() {
    if (!config?.enabled) throw new Error('Authentication is temporarily unavailable.');
    const value = String(config.provider || '').toLowerCase();
    if (value !== 'firebase') throw new Error('Firebase authentication is not configured.');
    return value;
  }
  function firebaseEndpoint(action) {
    return `https://identitytoolkit.googleapis.com/v1/accounts:${action}?key=${encodeURIComponent(FIREBASE_WEB.apiKey)}`;
  }
  function firebaseRefreshEndpoint() {
    return `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(FIREBASE_WEB.apiKey)}`;
  }

  async function restoreFirebase(s, refreshEpoch) {
    const data = await json(firebaseRefreshEndpoint(), {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({grant_type: 'refresh_token', refresh_token: s.refresh_token}).toString(),
    });
    return save(data, refreshEpoch, 'firebase');
  }

  async function restore() {
    const s = session();
    if (!s) return null;
    if (s.expires_at > Date.now() / 1000 + 60) return s;
    if (!s.refresh_token) { clear(); return null; }
    if (!refreshing) {
      const refreshEpoch = epoch();
      refreshing = restoreFirebase(s, refreshEpoch)
        .catch(error => {
          if ([400, 401, 403].includes(error.status)) {
            if (epoch() === refreshEpoch) clear();
            return null;
          }
          throw error;
        })
        .finally(() => { refreshing = null; });
    }
    return refreshing;
  }

  async function init() {
    clearLegacy();
    config = await json('/api/v1/auth/config');
    if (provider() !== 'firebase') throw new Error('Firebase authentication is not configured.');
    if (config.project_id && config.project_id !== FIREBASE_WEB.projectId) {
      throw new Error('Firebase project configuration mismatch.');
    }
    return {...config, recovery: false};
  }

  async function signInFirebase(email, password) {
    const data = await json(firebaseEndpoint('signInWithPassword'), {
      method: 'POST',
      body: JSON.stringify({email, password, returnSecureToken: true}),
    });
    return replaceSession(data, 'firebase');
  }
  async function signIn(email, password) {
    provider();
    return signInFirebase(email, password);
  }

  async function signUpFirebase(email, password, name) {
    const data = await json(firebaseEndpoint('signUp'), {
      method: 'POST',
      body: JSON.stringify({email, password, returnSecureToken: true}),
    });
    let current = data;
    const displayName = String(name || '').trim().slice(0, 80);
    if (displayName) {
      current = await json(firebaseEndpoint('update'), {
        method: 'POST',
        body: JSON.stringify({idToken: data.idToken, displayName, returnSecureToken: true}),
      });
      current.refreshToken = current.refreshToken || data.refreshToken;
    }
    return replaceSession(current, 'firebase');
  }
  async function signUp(email, password, name) {
    provider();
    return signUpFirebase(email, password, name);
  }

  async function resetFirebase(email) {
    return json(firebaseEndpoint('sendOobCode'), {
      method: 'POST',
      body: JSON.stringify({requestType: 'PASSWORD_RESET', email}),
    });
  }
  async function reset(email) {
    provider();
    return resetFirebase(email);
  }

  async function updateFirebase(fields) {
    const s = await restore();
    if (!s) throw new Error('Sign in again.');
    if (fields?.password) {
      const data = await json(firebaseEndpoint('update'), {
        method: 'POST',
        body: JSON.stringify({idToken: s.access_token, password: fields.password, returnSecureToken: true}),
      });
      data.refreshToken = data.refreshToken || s.refresh_token;
      return replaceSession(data, 'firebase');
    }
    if (fields?.data && typeof fields.data === 'object') {
      return json('/api/v1/auth/profile', {
        method: 'PUT',
        headers: {'X-Blinq-Access-Token': s.access_token},
        body: JSON.stringify(fields.data),
      });
    }
    return null;
  }
  async function update(fields) {
    provider();
    return updateFirebase(fields);
  }

  async function signOut() {
    clear();
  }

  async function apiWithSession(url, options = {}) {
    const s = await restore();
    if (!s) throw new Error('Sign in again.');
    return json(url, {
      ...options,
      headers: {'X-Blinq-Access-Token': s.access_token, ...(options.headers || {})},
    });
  }
  async function feed() {
    const s = await restore();
    return json('/api/v1/feed', {headers: s ? {'X-Blinq-Access-Token': s.access_token} : {}});
  }
  async function adminUsers(page = 1, perPage = 100) {
    return apiWithSession(`/api/v1/admin/users?page=${encodeURIComponent(page)}&per_page=${encodeURIComponent(perPage)}`);
  }
  async function adminUpdateAccess(userId, payload) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}/access`, {
      method: 'PUT', body: JSON.stringify(payload || {}),
    });
  }
  async function runtimeUiConfig() { return json('/api/v1/ui-config'); }
  async function contentNews() { return json('/api/v1/content/news'); }
  async function bannerEvent(payload, keepalive = false) {
    return json('/api/v1/banner-events', {method: 'POST', keepalive, body: JSON.stringify(payload || {})});
  }
  async function adminSaveUiConfig(payload) {
    return apiWithSession('/api/v1/admin/ui-config', {method: 'PUT', body: JSON.stringify(payload || {})});
  }
  async function adminBannerAnalytics(days = 30) {
    return apiWithSession(`/api/v1/admin/banner-analytics?days=${encodeURIComponent(days)}`);
  }

  window.BlinqAuth = {
    init, restore, signIn, signUp, reset, update, signOut, feed,
    adminUsers, adminUpdateAccess, runtimeUiConfig, contentNews,
    bannerEvent, adminSaveUiConfig, adminBannerAnalytics, clear,
  };
})();
