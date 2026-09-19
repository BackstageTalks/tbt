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
      EMAIL_NOT_VERIFIED: 'Verify your email before opening the BlinQ workspace.',
      TOKEN_EXPIRED: 'Your session expired. Sign in again.',
      INVALID_ID_TOKEN: 'Your session is no longer valid. Sign in again.',
      ADMIN_STORAGE_UNAVAILABLE: 'Persistent service storage is temporarily unavailable.',
      LIVE_RADAR_STORAGE_UNAVAILABLE: 'LIVE alert storage is temporarily unavailable.',
      UI_CONFIG_STORAGE_UNAVAILABLE: 'Content storage is temporarily unavailable.',
    };
    return friendly[code] || raw.replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
  }

  async function json(url, options = {}) {
    const headers = {Accept: 'application/json', ...(options.headers || {})};
    if (options.body && !Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
      headers['Content-Type'] = 'application/json';
    }
    const timeoutSignal = typeof AbortSignal?.timeout === 'function' ? AbortSignal.timeout(20000) : undefined;
    const response = await fetch(url, {
      ...options,
      headers,
      cache: 'no-store',
      signal: options.signal || timeoutSignal,
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

  async function firebaseEmailVerified(idToken) {
    const lookup = await json(firebaseEndpoint('lookup'), {
      method: 'POST',
      body: JSON.stringify({idToken}),
    });
    return lookup?.users?.[0]?.emailVerified === true;
  }

  async function signInFirebase(email, password) {
    // A failed sign-in must never leave an unrelated previous session available
    // for resend/profile actions. Clear first; an unverified successful sign-in
    // is persisted again below specifically to support verification resend.
    clear();
    const data = await json(firebaseEndpoint('signInWithPassword'), {
      method: 'POST',
      body: JSON.stringify({email, password, returnSecureToken: true}),
    });
    // Persist the Firebase session first so an unverified user can request a
    // fresh verification email without entering the password a second time.
    replaceSession(data, 'firebase');
    const verified = await firebaseEmailVerified(data.idToken);
    if (!verified) {
      const error = new Error('Verify your email before opening the BlinQ workspace.');
      error.code = 'EMAIL_NOT_VERIFIED';
      error.status = 403;
      throw error;
    }
    return session();
  }
  async function signIn(email, password) {
    provider();
    return signInFirebase(String(email || '').trim().toLowerCase(), password);
  }

  async function signUpFirebase(email, password, telegramNick, legalConsent = {}) {
    const data = await json(firebaseEndpoint('signUp'), {
      method: 'POST',
      body: JSON.stringify({email, password, returnSecureToken: true}),
    });
    const nick = String(telegramNick || '').trim();
    const legalVersion = String(legalConsent?.version || '').trim();
    const legalLocale = String(legalConsent?.locale || 'sk').trim().toLowerCase();
    const profilePayload = {};
    if (nick) profilePayload.telegram_nick = nick;
    if (legalVersion) {
      profilePayload.legal_consent_version = legalVersion;
      profilePayload.legal_consent_locale = ['sk','cz','en'].includes(legalLocale) ? legalLocale : 'sk';
    }
    if (Object.keys(profilePayload).length) {
      await json('/api/v1/auth/profile', {
        method: 'PUT',
        headers: {'X-Blinq-Access-Token': data.idToken},
        body: JSON.stringify(profilePayload),
      });
    }
    await json(firebaseEndpoint('sendOobCode'), {
      method: 'POST',
      body: JSON.stringify({requestType: 'VERIFY_EMAIL', idToken: data.idToken}),
    });
    clear();
    return {verification_required: true, email: String(email || '').trim()};
  }
  async function signUp(email, password, telegramNick, legalConsent = {}) {
    provider();
    return signUpFirebase(String(email || '').trim().toLowerCase(), password, telegramNick, legalConsent);
  }

  async function resendVerification() {
    provider();
    const s = await restore();
    if (!s) throw new Error('Sign in once more, then resend the verification email.');
    await json(firebaseEndpoint('sendOobCode'), {
      method: 'POST',
      body: JSON.stringify({requestType: 'VERIFY_EMAIL', idToken: s.access_token}),
    });
    return true;
  }

  async function resetFirebase(email) {
    return json(firebaseEndpoint('sendOobCode'), {
      method: 'POST',
      body: JSON.stringify({requestType: 'PASSWORD_RESET', email}),
    });
  }
  async function reset(email) {
    provider();
    return resetFirebase(String(email || '').trim().toLowerCase());
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
  async function matchIntelligence(player1Id, player2Id, surface = '', customId = '') {
    const params = new URLSearchParams({
      player1_id: String(player1Id || ''),
      player2_id: String(player2Id || ''),
      surface: String(surface || ''),
      custom_id: String(customId || ''),
    });
    return apiWithSession(`/api/v1/match-intelligence?${params.toString()}`);
  }
  async function insights() {
    return apiWithSession('/api/v1/insights');
  }
  async function liveRadar() { return apiWithSession('/api/v1/live-radar'); }
  async function adminLiveRadar(force = false, publish = false) {
    return apiWithSession(`/api/v1/admin/live-radar${force?'?force=1':''}`, {method: publish ? 'POST' : 'GET'});
  }
  async function markInsightRead(insightId) {
    return apiWithSession(`/api/v1/insights/${encodeURIComponent(insightId)}/read`, {method: 'POST'});
  }
  async function adminInsights() {
    return apiWithSession('/api/v1/admin/insights');
  }
  async function adminCreateInsight(payload) {
    return apiWithSession('/api/v1/admin/insights', {method: 'POST', body: JSON.stringify(payload || {})});
  }
  async function adminUpdateInsight(insightId, payload) {
    return apiWithSession(`/api/v1/admin/insights/${encodeURIComponent(insightId)}`, {method: 'PUT', body: JSON.stringify(payload || {})});
  }
  async function adminDeleteInsight(insightId) {
    return apiWithSession(`/api/v1/admin/insights/${encodeURIComponent(insightId)}`, {method: 'DELETE'});
  }
  async function adminDiagnostics() {
    return apiWithSession('/api/v1/admin/diagnostics');
  }
  async function adminUsers(page = 1, perPage = 100) {
    return apiWithSession(`/api/v1/admin/users?page=${encodeURIComponent(page)}&per_page=${encodeURIComponent(perPage)}`);
  }
  async function adminUpdateAccess(userId, payload) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}/access`, {
      method: 'PUT', body: JSON.stringify(payload || {}),
    });
  }
  async function adminUpdateMetadata(userId, payload) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}/metadata`, {
      method: 'PUT', body: JSON.stringify(payload || {}),
    });
  }
  async function adminUpdateUserProfile(userId, payload) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}/profile`, {
      method: 'PUT', body: JSON.stringify(payload || {}),
    });
  }
  async function adminDeleteUser(userId) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}`, {method: 'DELETE'});
  }
  async function adminPayments(userId) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}/payments`);
  }
  async function adminAddPayment(userId, payload) {
    return apiWithSession(`/api/v1/admin/users/${encodeURIComponent(userId)}/payments`, {method: 'POST', body: JSON.stringify(payload || {})});
  }
  async function adminAudit(targetId = '') {
    const suffix = targetId ? `?target_id=${encodeURIComponent(targetId)}` : '';
    return apiWithSession(`/api/v1/admin/audit${suffix}`);
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
  async function pushConfig() {
    return apiWithSession('/api/v1/push/config');
  }
  async function pushSubscribe(subscription) {
    return apiWithSession('/api/v1/push/subscription', {method: 'POST', body: JSON.stringify({subscription})});
  }
  async function pushUnsubscribe(endpoint) {
    return apiWithSession('/api/v1/push/subscription', {method: 'DELETE', body: JSON.stringify({endpoint: String(endpoint || '')})});
  }
  async function adminUploadMedia(file) {
    const s = await restore();
    if (!s) throw new Error('Sign in again.');
    if (!(file instanceof Blob)) throw new Error('Choose an image first.');
    const headers = {
      Accept: 'application/json',
      'X-Blinq-Access-Token': s.access_token,
      'Content-Type': file.type || 'application/octet-stream',
      'X-Blinq-Filename': encodeURIComponent(file.name || 'banner-image').slice(0, 480),
    };
    const timeoutSignal = typeof AbortSignal?.timeout === 'function' ? AbortSignal.timeout(45000) : undefined;
    const response = await fetch('/api/v1/admin/media', {method: 'POST', headers, body: file, cache: 'no-store', signal: timeoutSignal});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(errorMessage(data, response.status));
      error.status = response.status;
      throw error;
    }
    return data;
  }

  window.BlinqAuth = {
    init, restore, signIn, signUp, resendVerification, reset, update, signOut, feed, matchIntelligence,
    insights, liveRadar, adminLiveRadar, markInsightRead, adminInsights, adminCreateInsight, adminUpdateInsight, adminDeleteInsight,
    adminDiagnostics, adminUsers, adminUpdateAccess, adminUpdateMetadata, adminUpdateUserProfile, adminDeleteUser,
    adminPayments, adminAddPayment, adminAudit, runtimeUiConfig, contentNews,
    bannerEvent, adminSaveUiConfig, adminBannerAnalytics, pushConfig, pushSubscribe, pushUnsubscribe, adminUploadMedia, clear,
  };
})();
