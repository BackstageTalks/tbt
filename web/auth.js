(() => {
  'use strict';

  // Firebase web configuration is intentionally public client configuration.
  // Server credentials never enter the web bundle.
  const FIREBASE_WEB = Object.freeze({
    apiKey: 'AIzaSyDMH_CDVsJL_nu369r-s3kQDYpGrSfzevE',
    authDomain: 'blinq-182.firebaseapp.com',
    projectId: 'blinq-182',
  });

  const AUTH_RUNTIME = '736-r55';
  const AUTH_CONFIG_URL = '/api/v1/auth/config';
  const AUTH_CONFIG_ATTEMPTS = 3;
  const TRANSIENT_AUTH_STATUSES = new Set([0, 408, 425, 429, 500, 502, 503, 504]);

  const KEY = 'blinq_v4_session';
  const EPOCH_KEY = 'blinq_v4_session_epoch';
  const LEGACY_KEYS = ['blinq_v3_session', 'blinq_v3_session_epoch'];
  const PENDING_PROFILE_KEY = 'blinq_v4_pending_registration_profile';
  let config = null;
  let initPromise = null;
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
  function sessionStorageKeys() { return [KEY, EPOCH_KEY]; }
  function sessionEpochKey() { return EPOCH_KEY; }

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

  function wait(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
  function safeTimeout(ms) {
    return typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(ms)
      : undefined;
  }
  function codeOf(error) { return String(error?.code || '').trim().toLowerCase(); }
  function isTransientAuthError(error) {
    return TRANSIENT_AUTH_STATUSES.has(Number(error?.status || 0));
  }
  function isPermanentAuthConfigError(error) {
    return new Set([
      'auth_disabled',
      'firebase_not_configured',
      'firebase_server_config_invalid',
      'firebase_project_mismatch',
    ]).has(codeOf(error));
  }

  async function json(url, options = {}) {
    const {timeoutMs = 20000, ...fetchOptions} = options;
    const headers = {Accept: 'application/json', ...(fetchOptions.headers || {})};
    if (fetchOptions.body && !Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
      headers['Content-Type'] = 'application/json';
    }
    let response;
    try {
      response = await fetch(url, {
        ...fetchOptions,
        headers,
        cache: 'no-store',
        signal: fetchOptions.signal || safeTimeout(timeoutMs),
      });
    } catch (cause) {
      const timeout = cause?.name === 'TimeoutError' || cause?.name === 'AbortError';
      const error = new Error(timeout ? 'Authentication request timed out.' : 'Network request failed.');
      error.status = 0;
      error.code = timeout ? 'AUTH_TIMEOUT' : 'AUTH_NETWORK_ERROR';
      error.cause = cause;
      throw error;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(errorMessage(data, response.status));
      error.status = response.status;
      error.code = typeof data?.error === 'object' ? data.error.message : data?.error;
      throw error;
    }
    return data;
  }

  function pendingRegistrationProfile() {
    try {
      const value=JSON.parse(localStorage.getItem(PENDING_PROFILE_KEY)||'null');
      if(!value||typeof value!=='object'||!value.email||!value.payload)return null;
      return value;
    } catch { return null; }
  }
  function savePendingRegistrationProfile(email,payload) {
    const normalized=String(email||'').trim().toLowerCase();
    if(!normalized||!payload||typeof payload!=='object'||!Object.keys(payload).length){
      localStorage.removeItem(PENDING_PROFILE_KEY);
      return;
    }
    localStorage.setItem(PENDING_PROFILE_KEY,JSON.stringify({email:normalized,payload,created_at:Date.now()}));
  }
  function clearPendingRegistrationProfile(email='') {
    const pending=pendingRegistrationProfile();
    const normalized=String(email||'').trim().toLowerCase();
    if(!pending||!normalized||pending.email===normalized)localStorage.removeItem(PENDING_PROFILE_KEY);
  }
  async function syncPendingRegistrationProfile(accessToken,email='') {
    const pending=pendingRegistrationProfile();
    if(!pending)return true;
    const normalized=String(email||pending.email||'').trim().toLowerCase();
    if(normalized&&pending.email!==normalized)return true;
    await json('/api/v1/auth/profile',{
      method:'PUT',
      headers:{'X-Blinq-Access-Token':accessToken},
      body:JSON.stringify(pending.payload||{}),
      timeoutMs:12000,
    });
    clearPendingRegistrationProfile(pending.email);
    return true;
  }

  function provider() {
    if (!config?.enabled) {
      const error = new Error('Authentication is temporarily unavailable.');
      error.code = 'AUTH_DISABLED';
      throw error;
    }
    const value = String(config.provider || '').toLowerCase();
    if (value !== 'firebase') {
      const error = new Error('Firebase authentication is not configured.');
      error.code = 'FIREBASE_NOT_CONFIGURED';
      throw error;
    }
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

  function validateAuthConfig(value) {
    if (!value || value.enabled !== true) {
      const error = new Error('Authentication is temporarily unavailable.');
      error.code = String(value?.error || 'AUTH_DISABLED').toUpperCase();
      throw error;
    }
    if (String(value.provider || '').toLowerCase() !== 'firebase') {
      const error = new Error('Firebase authentication is not configured.');
      error.code = 'FIREBASE_NOT_CONFIGURED';
      throw error;
    }
    if (value.project_id && value.project_id !== FIREBASE_WEB.projectId) {
      const error = new Error('Firebase project configuration mismatch.');
      error.code = 'FIREBASE_PROJECT_MISMATCH';
      throw error;
    }
    if (value.server_ready === false) {
      const error = new Error('Authentication server configuration is invalid.');
      error.status = 503;
      error.code = String(value.error || 'FIREBASE_SERVER_CONFIG_INVALID').toUpperCase();
      throw error;
    }
    return value;
  }

  function degradedClientConfig() {
    return {
      enabled: true,
      provider: 'firebase',
      release: '7.3.6',
      project_id: FIREBASE_WEB.projectId,
      auth_domain: FIREBASE_WEB.authDomain,
      server_ready: null,
      degraded: true,
      config_unavailable: true,
    };
  }

  async function loadAuthConfig() {
    let lastError = null;
    for (let attempt = 0; attempt < AUTH_CONFIG_ATTEMPTS; attempt += 1) {
      try {
        return validateAuthConfig(await json(AUTH_CONFIG_URL, {timeoutMs: 6000}));
      } catch (error) {
        lastError = error;
        if (isPermanentAuthConfigError(error) || !isTransientAuthError(error)) throw error;
        if (attempt + 1 < AUTH_CONFIG_ATTEMPTS) await wait(250 * (attempt + 1));
      }
    }
    // Firebase web configuration is public and embedded in this bundle. A short
    // Azure Functions cold start must not disable the login form. Protected API
    // calls remain authoritative and will still reject unusable sessions.
    console.warn('[BlinQ auth] auth config endpoint unavailable; continuing with trusted Firebase client configuration.', lastError);
    return degradedClientConfig();
  }

  async function performInit() {
    clearLegacy();
    config = await loadAuthConfig();
    provider();
    return {...config, recovery: false, runtime: AUTH_RUNTIME};
  }

  async function init(options = {}) {
    const force = options?.force === true;
    if (config && !force) return {...config, recovery: false, runtime: AUTH_RUNTIME};
    if (initPromise && !force) return initPromise;
    const pending = performInit();
    initPromise = pending;
    try { return await pending; }
    finally { if (initPromise === pending) initPromise = null; }
  }

  async function ensureReady() {
    if (!config?.enabled) await init();
    provider();
    return config;
  }

  function status() {
    return config ? {...config, runtime: AUTH_RUNTIME} : {enabled: false, provider: 'unknown', runtime: AUTH_RUNTIME};
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
    // Persist the Firebase session before every downstream side effect. This is
    // the durable recovery anchor if profile storage or verification SMTP fails.
    replaceSession(data, 'firebase');
    const verified = await firebaseEmailVerified(data.idToken);
    if (!verified) {
      const error = new Error('Verify your email before opening the BlinQ workspace.');
      error.code = 'EMAIL_NOT_VERIFIED';
      error.status = 403;
      throw error;
    }
    try {
      await syncPendingRegistrationProfile(data.idToken,email);
    } catch (cause) {
      const error=new Error('Your account exists, but profile setup is temporarily unavailable. Please try signing in again.');
      error.code='PROFILE_SETUP_PENDING';
      error.status=503;
      error.cause=cause;
      throw error;
    }
    return session();
  }
  async function signIn(email, password) {
    await ensureReady();
    return signInFirebase(String(email || '').trim().toLowerCase(), password);
  }

  async function signUpFirebase(email, password, telegramNick, legalConsent = {}) {
    const normalizedEmail=String(email||'').trim().toLowerCase();
    const data = await json(firebaseEndpoint('signUp'), {
      method: 'POST',
      body: JSON.stringify({email: normalizedEmail, password, returnSecureToken: true}),
    });
    // The Firebase account is already durable at this point, so persist the new
    // identity immediately. No later profile/SMTP failure may make the client
    // forget which account it just created.
    replaceSession(data, 'firebase');

    const nick = String(telegramNick || '').trim();
    const legalVersion = String(legalConsent?.version || '').trim();
    const legalLocale = String(legalConsent?.locale || 'sk').trim().toLowerCase();
    const profilePayload = {};
    if (nick) profilePayload.telegram_nick = nick;
    if (legalVersion) {
      profilePayload.legal_consent_version = legalVersion;
      profilePayload.legal_consent_locale = ['sk','cz','en'].includes(legalLocale) ? legalLocale : 'sk';
    }
    if (Object.keys(profilePayload).length) savePendingRegistrationProfile(normalizedEmail,profilePayload);

    let profileSynced=true;
    if (Object.keys(profilePayload).length) {
      try { await syncPendingRegistrationProfile(data.idToken,normalizedEmail); }
      catch { profileSynced=false; }
    }

    // Verification delivery is independent from profile persistence. If SMTP
    // fails, the saved Firebase session remains available for Resend. If only
    // profile persistence failed, keep the session so the pending safe payload
    // can be retried after reload/sign-in without creating the account twice.
    await json('/api/v1/auth/email', {
      method: 'POST',
      headers: {'X-Blinq-Access-Token': data.idToken},
      body: JSON.stringify({type: 'verify', email: normalizedEmail}),
    });
    if(profileSynced) clear();
    return {verification_required: true, email: normalizedEmail, profile_pending: !profileSynced};
  }

  async function signUp(email, password, telegramNick, legalConsent = {}) {
    await ensureReady();
    return signUpFirebase(String(email || '').trim().toLowerCase(), password, telegramNick, legalConsent);
  }

  async function resendVerification() {
    await ensureReady();
    const s = await restore();
    if (!s) throw new Error('Sign in once more, then resend the verification email.');
    try { await syncPendingRegistrationProfile(s.access_token); } catch {}
    await json('/api/v1/auth/email', {
      method: 'POST',
      headers: {'X-Blinq-Access-Token': s.access_token},
      body: JSON.stringify({type: 'verify'}),
    });
    return true;
  }

  async function resetFirebase(email) {
    return json('/api/v1/auth/email', {
      method: 'POST',
      body: JSON.stringify({type: 'reset', email}),
    });
  }
  async function reset(email) {
    await ensureReady();
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
    await ensureReady();
    return updateFirebase(fields);
  }

  async function forceRefreshFirebaseSession() {
    const s = session();
    if (!s?.refresh_token) return s;
    const refreshEpoch = epoch();
    return restoreFirebase(s, refreshEpoch);
  }

  async function reactivateFree() {
    await ensureReady();
    const data = await apiWithSession('/api/v1/account/reactivate-free', {method: 'POST'});
    await forceRefreshFirebaseSession();
    return data;
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
  async function matchIntelligence(player1Id, player2Id, surface = '', customId = '', eventId = '') {
    const params = new URLSearchParams({
      player1_id: String(player1Id || ''),
      player2_id: String(player2Id || ''),
      surface: String(surface || ''),
      custom_id: String(customId || ''),
      event_id: String(eventId || ''),
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
  async function runtimeUiConfig() { return json('/api/v1/ui-config'); }
  async function contentNews() { return json('/api/v1/content/news',{timeoutMs:5000}); }
  async function bannerEvent(payload, keepalive = false) {
    return json('/api/v1/banner-events', {method: 'POST', keepalive, body: JSON.stringify(payload || {})});
  }
  async function adminSaveUiConfig(payload) {
    return apiWithSession('/api/v1/admin/ui-config', {method: 'PUT', body: JSON.stringify(payload || {})});
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
    const timeoutSignal = safeTimeout(45000);
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
    init, ensureReady, status, restore, signIn, signUp, resendVerification, reset, update, reactivateFree, signOut, feed, matchIntelligence,
    insights, liveRadar, adminLiveRadar, markInsightRead, adminInsights, adminCreateInsight, adminUpdateInsight, adminDeleteInsight,
    adminDiagnostics, adminUsers, adminUpdateAccess, adminUpdateMetadata, adminUpdateUserProfile, adminDeleteUser,
    runtimeUiConfig, contentNews,
    bannerEvent, adminSaveUiConfig, pushConfig, pushSubscribe, pushUnsubscribe, adminUploadMedia, clear,
    sessionStorageKeys, sessionEpochKey,
  };
})();
