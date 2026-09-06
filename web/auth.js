(() => {
  'use strict';
  const KEY = 'blinq_v3_session';
  let config = null, refreshing = null;
  let recovery = false;
  function session() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } }
  function clear() { localStorage.removeItem(KEY); sessionStorage.removeItem(KEY); }
  function save(value) {
    const s = value?.session || value;
    if (!s?.access_token) return null;
    const normalized = {access_token:s.access_token,refresh_token:s.refresh_token || '',expires_at:Number(s.expires_at) || Math.floor(Date.now()/1000)+Number(s.expires_in || 3600)};
    localStorage.setItem(KEY,JSON.stringify(normalized)); return normalized;
  }
  async function json(url, options = {}) {
    const response = await fetch(url,{...options,headers:{Accept:'application/json','Content-Type':'application/json',...(options.headers || {})},cache:'no-store',signal:AbortSignal.timeout(20000)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(data.error_description || data.msg || data.message || data.error || `HTTP ${response.status}`); error.status=response.status; throw error; }
    return data;
  }
  function endpoint(path) { if (!config?.enabled) throw new Error('Prihlasovanie zatiaľ nie je nakonfigurované.'); return `${config.supabase_url}/auth/v1${path}`; }
  const headers = token => ({apikey:config.anon_key,...(token ? {Authorization:`Bearer ${token}`} : {})});
  const redirect = () => `${location.origin}/follow-the-data/`;
  async function restore() {
    let s = session(); if (!s) return null;
    if (s.expires_at > Date.now()/1000+60) return s;
    if (!s.refresh_token) { clear(); return null; }
    if (!refreshing) refreshing = json(endpoint('/token?grant_type=refresh_token'),{method:'POST',headers:headers(),body:JSON.stringify({refresh_token:s.refresh_token})})
      .then(save).catch(error => {if ([400,401,403].includes(error.status)){clear();return null;} throw error;}).finally(() => {refreshing=null;});
    return refreshing;
  }
  async function init() {
    config = await json('/api/v1/auth/config');
    const fragment = new URLSearchParams(location.hash.replace(/^#/,''));
    if (fragment.has('error_description')) { history.replaceState(null,'',location.pathname); throw new Error(fragment.get('error_description')); }
    if (fragment.has('access_token')) {
      save(Object.fromEntries(fragment.entries())); recovery = fragment.get('type')==='recovery';
      history.replaceState(null,'',location.pathname);
    }
    return {...config,recovery};
  }
  async function signIn(email,password) { return save(await json(endpoint('/token?grant_type=password'),{method:'POST',headers:headers(),body:JSON.stringify({email,password})})); }
  async function signUp(email,password,name) {
    const data = await json(endpoint(`/signup?redirect_to=${encodeURIComponent(redirect())}`),{method:'POST',headers:headers(),body:JSON.stringify({email,password,data:{display_name:name}})});
    return save(data);
  }
  async function reset(email) { return json(endpoint(`/recover?redirect_to=${encodeURIComponent(redirect())}`),{method:'POST',headers:headers(),body:JSON.stringify({email})}); }
  async function update(fields) {
    const s = await restore(); if (!s) throw new Error('Prihlás sa znova.');
    return json(endpoint('/user'),{method:'PUT',headers:headers(s.access_token),body:JSON.stringify(fields)});
  }
  async function signOut() {
    const s = session(); clear();
    if (s) await json(endpoint('/logout'),{method:'POST',headers:headers(s.access_token),body:'{}'}).catch(()=>{});
  }
  async function feed() {
    const s = await restore();
    return json('/api/v1/feed',{headers:s ? {Authorization:`Bearer ${s.access_token}`} : {}});
  }
  window.BlinqAuth={init,restore,signIn,signUp,reset,update,signOut,feed,clear};
})();
