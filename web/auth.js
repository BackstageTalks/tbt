(() => {
  'use strict';
  const KEY = 'blinq_v3_session';
  const EPOCH_KEY = 'blinq_v3_session_epoch';
  let config = null, refreshing = null;
  let recovery = false;

  function epoch() { return localStorage.getItem(EPOCH_KEY) || ''; }
  function mutateEpoch() {
    const value = `${Date.now()}:${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(EPOCH_KEY, value);
    return value;
  }
  function session() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } }
  function clear() { mutateEpoch(); localStorage.removeItem(KEY); sessionStorage.removeItem(KEY); }
  function save(value, expectedEpoch = null) {
    if (expectedEpoch !== null && epoch() !== expectedEpoch) return null;
    const s = value?.session || value;
    if (!s?.access_token) return null;
    const normalized = {
      access_token: s.access_token,
      refresh_token: s.refresh_token || '',
      expires_at: Number(s.expires_at) || Math.floor(Date.now() / 1000) + Number(s.expires_in || 3600),
    };
    if (expectedEpoch !== null && epoch() !== expectedEpoch) return null;
    const serialized = JSON.stringify(normalized);
    localStorage.setItem(KEY, serialized);
    // Close the tiny cross-tab window between the pre-write epoch check and
    // localStorage.setItem(). Never remove a newer tab's session.
    if (expectedEpoch !== null && epoch() !== expectedEpoch) {
      if (localStorage.getItem(KEY) === serialized) localStorage.removeItem(KEY);
      return null;
    }
    return normalized;
  }
  function replaceSession(value) {
    const nextEpoch = mutateEpoch();
    return save(value, nextEpoch);
  }
  async function json(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {Accept: 'application/json', 'Content-Type': 'application/json', ...(options.headers || {})},
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error_description || data.msg || data.message || data.error || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function endpoint(path) {
    if (!config?.enabled) throw new Error('Prihlasovanie zatiaľ nie je nakonfigurované.');
    return `${config.supabase_url}/auth/v1${path}`;
  }
  const headers = token => ({apikey: config.anon_key, ...(token ? {Authorization: `Bearer ${token}`} : {})});
  const redirect = () => `${location.origin}/follow-the-data/`;

  async function restore() {
    const s = session();
    if (!s) return null;
    if (s.expires_at > Date.now() / 1000 + 60) return s;
    if (!s.refresh_token) { clear(); return null; }
    if (!refreshing) {
      const refreshEpoch = epoch();
      refreshing = json(endpoint('/token?grant_type=refresh_token'), {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({refresh_token: s.refresh_token}),
      })
        .then(value => save(value, refreshEpoch))
        .catch(error => {
          if ([400, 401, 403].includes(error.status)) {
            // A failure from an old tab/request must not clear a newer login.
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
    config = await json('/api/v1/auth/config');
    const fragment = new URLSearchParams(location.hash.replace(/^#/, ''));
    if (fragment.has('error_description')) {
      history.replaceState(null, '', location.pathname);
      throw new Error(fragment.get('error_description'));
    }
    if (fragment.has('access_token')) {
      replaceSession(Object.fromEntries(fragment.entries()));
      recovery = fragment.get('type') === 'recovery';
      history.replaceState(null, '', location.pathname);
    }
    return {...config, recovery};
  }
  async function signIn(email, password) {
    return replaceSession(await json(endpoint('/token?grant_type=password'), {
      method: 'POST', headers: headers(), body: JSON.stringify({email, password}),
    }));
  }
  async function signUp(email, password, name) {
    const data = await json(endpoint(`/signup?redirect_to=${encodeURIComponent(redirect())}`), {
      method: 'POST', headers: headers(), body: JSON.stringify({email, password, data: {display_name: name}}),
    });
    return replaceSession(data);
  }
  async function reset(email) {
    return json(endpoint(`/recover?redirect_to=${encodeURIComponent(redirect())}`), {
      method: 'POST', headers: headers(), body: JSON.stringify({email}),
    });
  }
  async function update(fields) {
    const s = await restore();
    if (!s) throw new Error('Prihlás sa znova.');
    return json(endpoint('/user'), {method: 'PUT', headers: headers(s.access_token), body: JSON.stringify(fields)});
  }
  async function signOut() {
    const s = session();
    clear();
    if (s) await json(endpoint('/logout'), {method: 'POST', headers: headers(s.access_token), body: '{}'}).catch(() => {});
  }
  async function feed() {
    const s = await restore();
    return json('/api/v1/feed', {headers: s ? {'X-Blinq-Access-Token': s.access_token} : {}});
  }

  window.BlinqAuth = {init, restore, signIn, signUp, reset, update, signOut, feed, clear};
})();
