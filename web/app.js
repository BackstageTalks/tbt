(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = { feed: {upcoming:[],results:[],performance:{},history:{},model:null}, ui:null, uiSource:null, route:'predictions', page:0, showAll:false, authMode:'login', authEnabled:false, draftLoaded:false, selectedElement:'HEADER_BANNER_1', adminPlan:'rookie', adminTab:'layout', adminUsers:null, adminUsersLoading:false, adminSelectedUser:null, previewPlan:null, newsPool:[], bannerObserver:null, bannerTimers:new WeakMap(), adminAnalytics:null, adminAnalyticsLoading:false, runtimeConfigLoaded:false, adminCampaignId:null, adminAdvertiserId:null, resultsFilters:{category:'all',tour:'',surface:'',window:'all'}, marketPage:{top_daily:0,value:0,doubles:0,ace:0,sg:0}, dashboardVisibility:null, demoFeedBackup:null, demoMode:false };
  const pageSize = () => innerWidth >= 1700 ? 6 : innerWidth >= 1450 ? 5 : innerWidth >= 1200 ? 4 : innerWidth >= 900 ? 3 : 1;
  const dashboardCardsPerPanel = () => { const wide=Math.max(1,Number(state.ui?.dashboard?.cards_per_panel_wide)||3),desktop=Math.max(1,Number(state.ui?.dashboard?.cards_per_panel_desktop)||2); return innerWidth >= 1900 ? wide : innerWidth >= 760 ? desktop : 1; };
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const pct = value => `${(Number(value || 0) * (Number(value || 0) <= 1 ? 100 : 1)).toFixed(1)}%`;
  const number = (value, digits=3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const fmtTime = value => value ? new Intl.DateTimeFormat(locale==='sk'?'sk-SK':'en-GB',{hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : 'TBA';
  const fmtDate = value => value ? new Intl.DateTimeFormat(locale==='sk'?'sk-SK':'en-GB',{day:'2-digit',month:'short',year:'numeric'}).format(new Date(value)) : '—';
  const fmtToday = () => new Intl.DateTimeFormat(locale==='sk'?'sk-SK':'en-GB',{weekday:'short',day:'2-digit',month:'short',year:'numeric'}).format(new Date());
  const fmtClock = () => new Intl.DateTimeFormat(locale==='sk'?'sk-SK':'en-GB',{hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());
  const initials = name => String(name || 'B').trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase();
  const flagEmoji = code => { const value=String(code||'').trim().toUpperCase(); if(!/^[A-Z]{2}$/.test(value))return ''; return [...value].map(ch=>String.fromCodePoint(127397+ch.charCodeAt(0))).join(''); };
  const safePhotoUrl = value => { const url=String(value||'').trim(); return /^\/assets\/players\/[A-Za-z0-9_.-]+$/.test(url)?url:''; };
  const safeUiAsset = value => { const url=String(value||'').trim(); return /^\/assets\/[A-Za-z0-9_.\/-]+$/.test(url)?url:''; };
  function playerFallbackUrl(tour){
    const key=String(tour||'').trim().toLowerCase();
    const map=state.ui?.assets?.player_fallback||{};
    if(key.startsWith('wta'))return safeUiAsset(map.wta);
    if(key.startsWith('atp'))return safeUiAsset(map.atp);
    return '';
  }
  function accountAvatarUrl(account){
    const admin=Boolean(account?.is_admin||String(account?.role||'').toLowerCase()==='admin');
    const configuredPlan=String(state.ui?.assets?.admin_avatar_plan||'goat').trim().toLowerCase();
    const plan=admin?configuredPlan:String(account?.plan||'').trim().toLowerCase();
    const variant=String(account?.avatar_variant||'').trim().toLowerCase();
    const entry=state.ui?.assets?.account_avatars?.[plan];
    if(!entry||typeof entry!=='object')return '';
    if(entry.default)return safeUiAsset(entry.default);
    return ['m','w'].includes(variant)?safeUiAsset(entry[variant]):safeUiAsset(entry.m||entry.w);
  }
  function accountAvatarFallback(account){
    return account?.is_admin||String(account?.role||'').toLowerCase()==='admin'?'♛':initials(account?.name||account?.email||'B');
  }
  function setAccountAvatar(host,account){
    if(!host)return;
    const fallback=accountAvatarFallback(account);
    const src=accountAvatarUrl(account);
    host.textContent=fallback;host.classList.remove('has-photo');
    if(!src)return;
    const img=document.createElement('img');img.src=src;img.alt='';img.loading='eager';
    img.addEventListener('error',()=>{host.classList.remove('has-photo');host.textContent=fallback},{once:true});
    host.textContent='';host.classList.add('has-photo');host.appendChild(img);
  }
  const playerMetaLabel = (rank,country) => [flagEmoji(country),Number.isFinite(Number(rank))&&Number(rank)>0?`#${Math.trunc(Number(rank))}`:''].filter(Boolean).join(' ');
  const confidenceBand = p => p >= .80 ? 'very-high' : p >= .70 ? 'high' : p >= .60 ? 'medium' : 'low';
  function remainingLabel(value){
    if(!value)return '';
    const ms=new Date(value).getTime()-Date.now();if(!Number.isFinite(ms)||ms<=0)return 'ending';
    const hours=Math.ceil(ms/3600000),days=Math.floor(hours/24),rest=hours%24;
    return days?`${days}d ${rest}h`:`${hours}h`;
  }

  async function getJSON(url) {
    const response = await fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  const clone = value => JSON.parse(JSON.stringify(value));
  function mergeConfig(base, override){
    if(Array.isArray(override)) return clone(override);
    if(!override || typeof override!=='object') return override===undefined?clone(base):override;
    const out=(base && typeof base==='object' && !Array.isArray(base))?clone(base):{};
    Object.entries(override).forEach(([key,value])=>{
      if(value && typeof value==='object' && !Array.isArray(value)) out[key]=mergeConfig(out[key],value);
      else out[key]=clone(value);
    });
    return out;
  }
  const accessStates = ['active','locked','blurred','hidden'];
  const accessContexts = ['expired','rookie','pro','elite','goat','legend'];
  const requestedLocale = new URLSearchParams(location.search).get('lang');
  const locale = requestedLocale==='sk' ? 'sk' : 'en';
  const dashboardPickSectionKeys=['prime','top_daily','value','doubles','ace','sg'];
  const dashboardSectionKeys=[...dashboardPickSectionKeys,'results','btts'];
  const dashboardSectionFallback={
    prime:{label:'Prime Picks',panel_id:'predictionsPanel',sidebar_element:'SIDEBAR_PRIME',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:1,preview_limit:10},
    top_daily:{label:'Top Bets',panel_id:'topDailyPanel',sidebar_element:'SIDEBAR_TOP_DAILY',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:2,preview_limit:10},
    value:{label:'Value Picks',panel_id:'valuePanel',sidebar_element:'SIDEBAR_VALUE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:3,preview_limit:10},
    doubles:{label:'Doubles',panel_id:'doublesPanel',sidebar_element:'SIDEBAR_DOUBLES',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:4,preview_limit:10},
    ace:{label:'Ace Picks',panel_id:'acePanel',sidebar_element:'SIDEBAR_ACE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:5,preview_limit:10},
    sg:{label:'S/G Picks',panel_id:'sgPanel',sidebar_element:'SIDEBAR_SG',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:6,preview_limit:10},
    results:{label:'Results',panel_id:'resultsPreviewPanel',sidebar_element:'SIDEBAR_RESULTS',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:7,preview_limit:5},
    btts:{label:'BTTS Bonus',panel_id:'bttsBonusPanel',sidebar_element:'SIDEBAR_BTTS',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:8,preview_limit:5},
  };
  const isAdminAccount = () => Boolean(state.feed?.account?.is_admin || state.feed?.account?.role === 'admin');
  const draftKey = () => state.ui?.admin?.draft_storage_key || state.uiSource?.admin?.draft_storage_key || 'blinq_admin_ui_config_v1';
  const elements = () => state.ui?.elements || {};
  const elementList = (kind=null, zone=null) => Object.entries(elements())
    .map(([id,value])=>({id,...(value||{})}))
    .filter(item=>(!kind||item.kind===kind)&&(!zone||item.zone===zone))
    .sort((a,b)=>Number(a.order||0)-Number(b.order||0));

  async function loadUiConfig() {
    try {
      state.uiSource = await getJSON('/ui-config.json');
    } catch {
      state.uiSource = {schema:2,navigation:{learn:[]},plans:{},elements:{},admin:{draft_storage_key:'blinq_admin_ui_config_v1'}};
    }
    state.ui = clone(state.uiSource);
    try {
      const runtime = await getJSON('/api/v1/ui-config');
      if(runtime?.configured && runtime?.config?.schema===2){
        state.ui=mergeConfig(state.uiSource,runtime.config); state.runtimeConfigLoaded=true;
        if(String(runtime.config.ui_revision||'')!==String(state.uiSource.ui_revision||'')){
          state.ui.ui_revision=state.uiSource.ui_revision;
          state.ui.dashboard=mergeConfig(state.uiSource.dashboard||{},state.ui.dashboard||{});
          // Release-level display policy migrations must not be undone by an
          // older persisted runtime config. Preserve editable entitlements, but
          // adopt the new public dashboard chrome and default active windows.
          for(const field of ['visible_slots','user_switches','show_disabled_strip','auto_replace_empty_sections','cards_per_panel_desktop','cards_per_panel_wide','section_order']){
            if(Object.prototype.hasOwnProperty.call(state.uiSource.dashboard||{},field))state.ui.dashboard[field]=clone(state.uiSource.dashboard[field]);
          }
          for(const key of dashboardPickSectionKeys){
            const sourceSection=state.uiSource.dashboard?.sections?.[key],targetSection=state.ui.dashboard?.sections?.[key];
            if(sourceSection&&targetSection)targetSection.dashboard_enabled=sourceSection.dashboard_enabled;
          }
          state.ui.content_rows=state.ui.content_rows||{};
          state.ui.content_rows.content_top=clone(state.uiSource.content_rows?.content_top||{enabled:true,preset:'2+1+1'});
          for(const zone of ['content_mid','content_bottom']) state.ui.content_rows[zone]=mergeConfig(state.uiSource.content_rows?.[zone]||{},state.ui.content_rows?.[zone]||{});
          ['CONTENT_TOP_1','CONTENT_TOP_2','CONTENT_TOP_3','CONTENT_TOP_4','HEADER_BANNER_1','HEADER_BANNER_2','HEADER_BANNER_3'].forEach(id=>{
            if(state.uiSource?.elements?.[id]?.content) state.ui.elements[id].content=clone(state.uiSource.elements[id].content);
          });
        }
      }
    } catch {}
    try {
      const links = await getJSON('/membership-links.json');
      Object.entries(links?.plans||{}).forEach(([id,row])=>{
        const url=String((typeof row==='string'?row:(row?.payment_url||row?.url))||'').trim();
        if(url&&state.ui?.plans?.[id]) state.ui.plans[id].url=url;
      });
    } catch {}
    renderAllUiContent();
  }

  function loadAdminDraft(){
    if(!isAdminAccount() || state.draftLoaded) return;
    state.draftLoaded=true;
    try{
      const saved=JSON.parse(localStorage.getItem(draftKey())||'null');
      if(saved?.schema===2 && saved?.elements && saved?.plans) state.ui=saved;
    }catch{}
  }

  function renderNavigationGroup(items, containerId) {
    const host=$(containerId); host.innerHTML='';
    [...(items||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
      const href=item.href||`#${item.id}`;
      const direct=href.startsWith('/')||/^https?:\/\//i.test(href);
      const a=document.createElement('a'); a.href=href;
      if(!direct&&item.id) a.dataset.route=item.id;
      if(item.element_id) a.dataset.uiElement=item.element_id;
      a.className=`nav-link${state.route===item.id?' active':''}`;
      a.innerHTML=`<span class="nav-icon">${escapeHtml(item.icon||'•')}</span><span>${escapeHtml(item.label||item.id)}${item.beta?' <em class="nav-beta">BETA</em>':''}</span>`;
      host.appendChild(a);
    });
  }

  function dashboardSectionConfig(key){
    const base=dashboardSectionFallback[key]||{};
    const configured=state.ui?.dashboard?.sections?.[key]||{};
    return {...base,...configured,plans:{...(configured.plans||{})}};
  }
  function dashboardPlanKey(){const p=accountPlan();return p==='admin'?'goat':p;}
  function dashboardPlanEntitlement(key,plan=dashboardPlanKey()){
    if(accountPlan()==='admin'&&!state.previewPlan)return {visible_picks:'ALL',blur_remaining:false,see_all:true};
    const section=dashboardSectionConfig(key);const normalized=plan==='trial'?'rookie':plan;
    return section.plans?.[plan]||section.plans?.[normalized]||section.plans?.rookie||{visible_picks:'ALL',blur_remaining:false,see_all:true};
  }
  function visiblePickCount(key,total){
    const raw=dashboardPlanEntitlement(key).visible_picks;
    if(String(raw).toUpperCase()==='ALL')return total;
    const n=Math.max(0,Math.min(total,Number(raw)||0));return n;
  }
  function dashboardPreviewLimit(key,total){
    const raw=dashboardSectionConfig(key).preview_limit;
    if(String(raw).toUpperCase()==='ALL')return total;
    return Math.max(1,Math.min(total,Number(raw)||5));
  }
  function firstUnlockPlan(key,index=0,forSeeAll=false){
    const section=dashboardSectionConfig(key);const plans=['rookie','pro','elite','goat','legend']
      .filter(id=>state.ui?.plans?.[id]?.enabled!==false)
      .sort((a,b)=>Number(state.ui?.plans?.[a]?.order||99)-Number(state.ui?.plans?.[b]?.order||99));
    for(const plan of plans){const ent=section.plans?.[plan]||{};if(forSeeAll){if(ent.see_all)return plan;continue;}const raw=ent.visible_picks;if(String(raw).toUpperCase()==='ALL'||Number(raw)>index)return plan;}
    return 'goat';
  }
  function upgradePlanLabel(plan){return state.ui?.plans?.[plan]?.label||String(plan||'PRO').toUpperCase();}
  function dashboardSectionKeyForSidebarElement(elementId){return dashboardSectionKeys.find(key=>dashboardSectionConfig(key).sidebar_element===elementId)||'';}
  function dashboardSectionKeyForPanelId(panelId){return dashboardSectionKeys.find(key=>dashboardSectionConfig(key).panel_id===panelId)||'';}
  function sectionSeeAllNode(key){if(key==='prime')return $('primeSeeAllCard');if(key==='btts')return $('bttsBonusPanel')?.querySelector('.section-see-all-card')||null;return document.querySelector(`[data-route="${key}"][class~="section-see-all-card"]`);}
  function dashboardVisibilityDefaults(){
    const out={};dashboardPickSectionKeys.forEach(key=>{out[key]=dashboardSectionConfig(key).dashboard_enabled!==false;});return out;
  }
  function dashboardVisibilityState(){
    if(state.dashboardVisibility)return state.dashboardVisibility;
    const defaults=dashboardVisibilityDefaults();
    if(state.ui?.dashboard?.user_switches===true){
      try{
        const saved=JSON.parse(localStorage.getItem('blinq_dashboard_sections_v2')||'null');
        if(saved&&typeof saved==='object')dashboardPickSectionKeys.forEach(key=>{if(typeof saved[key]==='boolean')defaults[key]=saved[key];});
      }catch{}
    }
    const max=Math.max(1,Number(state.ui?.dashboard?.visible_slots)||4);
    let enabled=dashboardPickSectionKeys.filter(key=>defaults[key]);
    if(enabled.length>max){const keep=new Set(enabled.slice(0,max));dashboardPickSectionKeys.forEach(key=>{defaults[key]=keep.has(key);});}
    state.dashboardVisibility=defaults;return defaults;
  }
  function saveDashboardVisibility(){
    try{localStorage.setItem('blinq_dashboard_sections_v2',JSON.stringify(dashboardVisibilityState()));}catch{}
  }
  function toggleDashboardSection(key){
    if(state.ui?.dashboard?.user_switches!==true)return;
    if(!dashboardPickSectionKeys.includes(key))return;
    const prefs=dashboardVisibilityState(),max=Math.max(1,Number(state.ui?.dashboard?.visible_slots)||4),wasOn=Boolean(prefs[key]);
    prefs[key]=!wasOn;
    if(wasOn){
      const start=dashboardPickSectionKeys.indexOf(key)+1;
      const next=[...dashboardPickSectionKeys.slice(start),...dashboardPickSectionKeys.slice(0,start)].find(candidate=>candidate!==key&&!prefs[candidate]&&dashboardSectionConfig(candidate).sidebar_enabled!==false);
      if(next&&dashboardPickSectionKeys.filter(candidate=>prefs[candidate]).length<max)prefs[next]=true;
    }else{
      const enabled=dashboardPickSectionKeys.filter(candidate=>prefs[candidate]);
      if(enabled.length>max){
        const replacement=[...enabled].reverse().find(candidate=>candidate!==key);
        if(replacement)prefs[replacement]=false;
      }
    }
    saveDashboardVisibility();
    state.page=0;Object.keys(state.marketPage||{}).forEach(k=>{state.marketPage[k]=0;});
    renderPredictions();renderMarketSections();renderDashboardComposition();
  }
  function renderDashboardSectionToggles(){
    const host=$('dashboardSectionToggles'),status=$('dashboardSectionsStatus'),switcher=$('dashboardSectionSwitcher'),disabled=$('dashboardDisabledSections');if(!host)return;
    const userSwitches=state.ui?.dashboard?.user_switches===true;
    if(switcher)switcher.hidden=!userSwitches;
    if(!userSwitches){host.innerHTML='';if(disabled){disabled.hidden=true;disabled.innerHTML='';}return;}
    const prefs=dashboardVisibilityState();
    host.innerHTML=dashboardPickSectionKeys.map(key=>{const cfg=dashboardSectionConfig(key),on=Boolean(prefs[key]);return `<button type="button" class="dashboard-section-toggle${on?' is-on':''}" data-dashboard-toggle="${escapeHtml(key)}" aria-pressed="${on?'true':'false'}"><span class="switch-dot" aria-hidden="true"><i></i></span><span><strong>${escapeHtml(cfg.label||key)}</strong><small>${on?'ON':'OFF'}</small></span></button>`;}).join('');
    const active=dashboardPickSectionKeys.filter(key=>prefs[key]);
    if(status)status.textContent=`${Math.min(active.length,Number(state.ui?.dashboard?.visible_slots)||4)} of ${dashboardPickSectionKeys.length} sections shown`;
    if(disabled){
      const hidden=dashboardPickSectionKeys.filter(key=>!prefs[key]);
      disabled.hidden=!hidden.length||state.ui?.dashboard?.show_disabled_strip===false;
      disabled.innerHTML=hidden.map(key=>`<button type="button" data-dashboard-toggle="${escapeHtml(key)}"><span>${escapeHtml(dashboardSectionConfig(key).label||key)}</span><small>OFF · enable to show</small></button>`).join('');
    }
  }
  function renderDashboardComposition(){
    const view=$('predictionsView');if(!view)return;
    const top=$('bannerTop'),mid=$('bannerMid'),bottom=$('bannerBottom');if(top)top.style.order='10';if(mid){mid.style.order='900';mid.hidden=true;}if(bottom){bottom.style.order='910';bottom.hidden=true;}
    const prefs=dashboardVisibilityState(),max=Math.max(1,Number(state.ui?.dashboard?.visible_slots)||4);
    const configured=dashboardPickSectionKeys.filter(key=>prefs[key]&&dashboardSectionConfig(key).sidebar_enabled!==false).slice(0,max);
    const countFor=key=>marketRows(key).length;
    let active=[...configured];
    if(state.ui?.dashboard?.auto_replace_empty_sections!==false){
      const replacements=dashboardPickSectionKeys.filter(key=>!active.includes(key)&&dashboardSectionConfig(key).sidebar_enabled!==false&&countFor(key)>0);
      active=active.map(key=>countFor(key)>0?key:(replacements.shift()||key));
    }
    dashboardPickSectionKeys.forEach(key=>{
      const cfg=dashboardSectionConfig(key),panel=$(cfg.panel_id);if(!panel)return;
      panel.hidden=!active.includes(key);panel.style.order=String(20+active.indexOf(key));
    });
    for(const key of ['results','btts']){const cfg=dashboardSectionConfig(key),panel=$(cfg.panel_id);if(panel)panel.hidden=true;}
    dashboardSectionKeys.forEach(key=>{
      const see=sectionSeeAllNode(key),ent=dashboardPlanEntitlement(key);if(!see)return;
      see.hidden=false;see.classList.toggle('section-see-all-locked',!ent.see_all);see.dataset.dashboardSection=key;
      const b=see.querySelector('b');
      if(ent.see_all){see.dataset.route=key;see.href=key==='btts'?'/btts':`#${key}`;delete see.dataset.upgradePlan;if(b)b.textContent=key==='btts'?'Open →':'See all →';}
      else{delete see.dataset.route;see.href='#';see.dataset.upgradePlan=firstUnlockPlan(key,0,true);if(b)b.textContent=`Unlock with ${upgradePlanLabel(see.dataset.upgradePlan).replace(/^BlinQ\s+/i,'')} →`;}
    });
    renderDashboardSectionToggles();
  }
  
  function lockedPickCard(key,index){
    const plan=firstUnlockPlan(key,index,false),label=upgradePlanLabel(plan),section=dashboardSectionConfig(key);
    return `<article class="prediction-card dashboard-locked-card" data-upgrade-plan="${escapeHtml(plan)}" data-upgrade-section="${escapeHtml(section.label||key)}"><div class="locked-ghost"><span></span><i>VS</i><span></span></div><div class="locked-pick-copy"><b aria-hidden="true">⌑</b><strong>Unlock this pick</strong><small>Available with ${escapeHtml(label)}.</small><button type="button" class="btn btn-primary">Upgrade to unlock →</button></div></article>`;
  }
  function translateSignalLabel(label){
    const raw=String(label||'Model signal');if(locale==='sk')return raw;
    const map={'Celková výkonnosť':'Overall performance','Sila na povrchu':'Surface strength','Aktuálna forma':'Recent form','Vzájomné zápasy':'Head to head','Výkonnosť':'Performance','Forma':'Recent form'};
    return map[raw]||raw;
  }

  function renderNavigation(){
    const primaryNav=[
      ['predictions','Dashboard','⌂'],['prime','Prime Picks','✦'],['top_daily','Top Bets','★'],
      ['value','Value Picks','◇'],['doubles','Doubles','◈'],['ace','Ace Picks','♠'],
      ['sg','S/G Picks','▥'],['results','Results','✓'],['btts','BTTS Bonus','⚽'],
    ];
    const configNav=elementList('navigation');
    const main=primaryNav.map(([id,label,icon],index)=>{
      const item=configNav.find(entry=>entry.content?.route===id);
      const section=dashboardSectionKeys.includes(id)?dashboardSectionConfig(id):null;
      return {id,label,icon,order:index+1,enabled:section?section.sidebar_enabled!==false:true,beta:id==='btts',href:id==='btts'?'/btts':`#${id}`,element_id:item?.id||''};
    });
    renderNavigationGroup(main,'mainNavigation');
    const adminWrap=$('adminNavigationWrap');
    if(adminWrap){
      adminWrap.hidden=!isAdminAccount();
      renderNavigationGroup(isAdminAccount()?[{id:'admin',href:'#admin',icon:'⚙',label:'Admin',order:1,enabled:true}]:[],'adminNavigation');
    }
    const footer=$('footerLearnNavigation');
    if(footer){
      footer.innerHTML='';
      [...(state.ui?.navigation?.learn||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
        const a=document.createElement('a'); a.href=item.href||`#${item.id}`; a.dataset.route=item.id||''; a.textContent=item.label||item.id; footer.appendChild(a);
      });
    }
  }

  function watermarkHtml(item){
    const wm=item?.watermark||{};
    const preset=String(wm.preset||'violet').replace(/[^a-z0-9_-]/gi,''); return wm.enabled?`<span class="slot-watermark wm-${escapeHtml(preset)}">${escapeHtml(wm.text||'COMING SOON')}</span>`:'';
  }
  function safeLink(value, fallback='#predictions'){
    const text=String(value||'').trim();
    if(!text)return fallback;
    if(text.startsWith('#')||text.startsWith('/')||/^https?:\/\//i.test(text))return text;
    return fallback;
  }
  function isExternalLink(value){ return /^https?:\/\//i.test(String(value||'')); }
  function contentActive(content){
    if(content?.enabled===false)return false;
    const now=Date.now();
    const from=content?.active_from?Date.parse(content.active_from):NaN;
    const until=content?.active_until?Date.parse(content.active_until):NaN;
    if(Number.isFinite(from)&&now<from)return false;
    if(Number.isFinite(until)&&now>until)return false;
    return true;
  }
  function internalFallbackContent(){
    return clone(state.ui?.ad_fallbacks?.internal||{eyebrow:'BLINQ',headline:'BlinQ Tennis Intelligence',text:'No active advertisement or RSS item is available right now.',button_text:'Open dashboard',link:'#predictions',route:'predictions',theme:'blue'});
  }
  function fallbackContent(item,index=0){
    const original=item?.content||{};
    const preference=String(original.ad_hidden_fallback||'auto').toLowerCase();
    const news=state.newsPool||[];
    const images=state.ui?.ad_fallbacks?.fallback_images||[];
    const useNews=(preference==='rss'||preference==='auto')&&news.length;
    if(useNews){
      const article=index < news.length ? news[index] : null;
      if(article){
      return {type:'rss',enabled:true,eyebrow:article.source||'TENNIS NEWS',headline:article.title||'Tennis news',text:article.published_at?`Published ${fmtDate(article.published_at)}`:'Latest tennis coverage',button_text:'Read article →',link:article.url,route:'',theme:'blue',sponsored:false,campaign_id:`rss:${String(article.source||'news').toLowerCase().replace(/[^a-z0-9]+/g,'-').slice(0,50)}`,advertiser_id:'rss',span:original.span||1,image_url:''};
      }
    }
    const useImage=preference==='image'&&images.length;
    if(useImage){
      const src=String(images[index%images.length]||'');
      return {...internalFallbackContent(),type:'image',image_url:src,campaign_id:`fallback-image-${index+1}`,advertiser_id:'blinq',span:original.span||1};
    }
    return {...internalFallbackContent(),type:'internal',campaign_id:'blinq-neutral-fallback',advertiser_id:'blinq',span:original.span||1};
  }
  function campaignContent(slotContent){
    const content=slotContent||{};
    const campaignId=String(content.campaign_id||'').trim();
    if(content.type!=='advertisement'||!campaignId)return content;
    const campaign=state.ui?.campaigns?.[campaignId];
    if(!campaign||typeof campaign!=='object')return content;
    return {
      ...content,
      ...campaign,
      type:'advertisement',
      campaign_id:campaignId,
      advertiser_id:campaign.advertiser_id||content.advertiser_id||'unassigned',
      sponsored:campaign.sponsored!==false,
      enabled:content.enabled!==false && campaign.enabled!==false,
      ad_hidden_fallback:content.ad_hidden_fallback||'auto',
    };
  }
  function resolvedBannerContent(item,index=0){
    const content=campaignContent(item?.content||{});
    const ad=content.type==='advertisement'||content.sponsored===true;
    if(!contentActive(content))return fallbackContent({...item,content},index);
    if(content.type==='rss')return fallbackContent({...item,content:{...content,ad_hidden_fallback:'rss'}},index);
    return content;
  }
  const rowPresetMap={
    '1+1+1+1':[[0,1],[1,1],[2,1],[3,1]],
    '2+2':[[0,2],[2,2]],
    '2+1+1':[[0,2],[2,1],[3,1]],
    '1+1+2':[[0,1],[1,1],[2,2]],
    '4':[[0,4]],
  };
  const contentRowZones=['content_top','content_mid','content_bottom'];
  function rowConfig(zone){ return state.ui?.content_rows?.[zone]||{}; }
  function rowEnabled(zone){ return rowConfig(zone).enabled!==false; }
  function rowPreset(zone){
    const preset=String(rowConfig(zone).preset||'1+1+1+1');
    return rowPresetMap[preset]?preset:'1+1+1+1';
  }
  function rowItems(zone){
    if(!rowEnabled(zone))return [];
    const all=elementList('large_banner',zone);
    const slots=[0,1,2,3].map(index=>all.find(item=>Number(item.order||0)%10===index+1)||all[index]).filter(Boolean);
    return rowPresetMap[rowPreset(zone)].map(([start,span])=>({item:slots[start],span,start})).filter(entry=>entry.item);
  }

  function marketingAvatarUrl(planId){
    const id=String(planId||'').toLowerCase(),plan=state.ui?.plans?.[id]||{};
    const explicit=safeUiAsset(plan.marketing_avatar||'');if(explicit)return explicit;
    const entry=state.ui?.assets?.account_avatars?.[id]||{};
    return safeUiAsset(entry.default||entry.w||entry.m||'');
  }
  function promoPlanAvatarHtml(content,compact=false){
    const planId=String(content?.plan_id||'').toLowerCase();if(!planId)return '';
    const src=marketingAvatarUrl(planId);if(!src)return '';
    return `<span class="promo-plan-avatar plan-${escapeHtml(planId)}${compact?' compact':''}" aria-hidden="true"><img src="${escapeHtml(src)}" alt="" loading="lazy"></span>`;
  }

  function bannerAttrs(item,content){
    const slot=String(item.id||'');
    const campaign=String(content?.campaign_id||slot);
    const advertiser=String(content?.advertiser_id||'unassigned');
    return `data-banner-slot="${escapeHtml(slot)}" data-campaign-id="${escapeHtml(campaign)}" data-advertiser-id="${escapeHtml(advertiser)}"`;
  }
  function bannerImageHtml(content,span=1){
    const variants=content?.images&&typeof content.images==='object'?content.images:{};
    const raw=variants[String(span)]||variants[span]||content?.image_url||'';
    const mobileRaw=content?.mobile_image_url||'';
    const src=safeLink(raw,'');
    const mobile=safeLink(mobileRaw,'');
    const fit=['cover','contain'].includes(String(content?.image_fit||'cover'))?String(content.image_fit||'cover'):'cover';
    const position=['center','left','right','top','bottom'].includes(String(content?.image_position||'center'))?String(content.image_position||'center'):'center';
    if(!src||src.startsWith('#'))return '<div class="promo-art" aria-hidden="true"></div>';
    const image=`<img class="promo-image fit-${escapeHtml(fit)} pos-${escapeHtml(position)}" src="${escapeHtml(src)}" alt="" loading="lazy">`;
    if(mobile&&!mobile.startsWith('#'))return `<picture class="promo-picture"><source media="(max-width: 700px)" srcset="${escapeHtml(mobile)}">${image}</picture>`;
    return image;
  }
  function headerSlotHtml(item,index=0){
    const c=resolvedBannerContent(item,index),route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#predictions'),external=isExternalLink(href);
    return `<a href="${escapeHtml(href)}" ${external?'target="_blank" rel="noopener"':''} ${route&&!external?`data-route="${escapeHtml(route)}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)} class="header-slot theme-${escapeHtml(c.theme||'blue')}${c.plan_id?' has-plan-avatar':''}"><div class="header-slot-copy"><small>${escapeHtml(c.eyebrow||item.label)}</small><strong>${escapeHtml(c.headline||'')}</strong><span>${escapeHtml(c.text||'')}</span></div>${promoPlanAvatarHtml(c,true)}${watermarkHtml(item)}</a>`;
  }
  function renderHeaderSlots(){
    const host=$('headerFeatureStrip'); if(!host)return;
    const managed=elementList('header_slot','header');
    if(managed.length){
      host.innerHTML=managed.map((item,index)=>headerSlotHtml(item,index)).join('');
      installBannerTracking(host);
      return;
    }
    const promos=[
      ['pro','PRO','Unlock the full daily board','More daily picks and complete section access'],
      ['elite','ELITE','Advanced match intelligence','Deeper coverage and richer context'],
      ['legend','LEGEND','Maximum BlinQ access','Premium workflow for power users'],
    ];
    host.innerHTML=promos.map(([plan,label,headline,text])=>`<button type="button" class="header-plan-promo plan-${plan}" data-upgrade-plan="${plan}" data-upgrade-section="${label}"><small>${label}</small><strong>${headline}</strong><span>${text}</span></button>`).join('');
  }
  function bannerHtml(item, sidebar=false, index=0, spanOverride=null){
    const c=resolvedBannerContent(item,index),route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#account'),external=isExternalLink(href); const theme=String(c.theme||'violet').replace(/[^a-z0-9_-]/gi,'');
    const sponsored=c.sponsored?'<span class="sponsored-label">SPONSORED</span>':'';
    const attrs=`${route&&!external?`data-route="${escapeHtml(route)}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)}`;
    const target=external?'target="_blank" rel="noopener"':'';
    if(sidebar){
      return `<a class="sidebar-promo theme-${theme}${c.plan_id?' has-plan-avatar':''}" href="${escapeHtml(href)}" ${target} ${attrs}>${sponsored}<div class="sidebar-promo-copy"><small>${escapeHtml(c.eyebrow||'BLINQ')}</small><strong>${escapeHtml(c.headline||'')}</strong><span>${escapeHtml(c.text||'')}</span><b>${escapeHtml(c.button_text||'Open')}</b></div>${promoPlanAvatarHtml(c,true)}${watermarkHtml(item)}</a>`;
    }
    const span=Math.max(1,Math.min(4,Number(spanOverride||c.span)||1));
    const fullCreative=c.creative_mode==='full'||(c.type==='advertisement'&&c.show_copy===false);
    const showCopy=c.show_copy!==false;
    return `<a class="promo-banner promo-card theme-${theme} span-${span}${fullCreative?' creative-full':''}${showCopy?'':' no-copy'}${c.plan_id?' has-plan-avatar':''}" href="${escapeHtml(href)}" ${target} ${attrs}>${sponsored}${bannerImageHtml(c,span)}${showCopy?`<div class="promo-copy"><span class="promo-eyebrow">${escapeHtml(c.eyebrow||'BLINQ')}</span><strong>${escapeHtml(c.headline||'')}</strong><p>${escapeHtml(c.text||'')}</p><span class="promo-cta">${escapeHtml(c.button_text||'Open')}</span></div>`:''}${promoPlanAvatarHtml(c,false)}${watermarkHtml(item)}</a>`;
  }
  function renderBanners(){
    const hosts={content_top:$('bannerTop'),content_mid:$('bannerMid'),content_bottom:$('bannerBottom')};
    let offset=0;
    contentRowZones.forEach(zone=>{
      const host=hosts[zone]; if(!host)return;
      const rows=rowItems(zone); host.dataset.layout=rowPreset(zone); host.dataset.rowEnabled=rowEnabled(zone)?'true':'false'; host.hidden=!rowEnabled(zone)||!rows.length;
      host.innerHTML=rows.map((entry,index)=>bannerHtml(entry.item,false,index+offset,entry.span)).join('');
      if(!host.hidden)installBannerTracking(host); offset+=4;
    });
  }
  function renderSidebarPromos(){
    const host=$('sidebarPromoZone'); if(!host)return;
    host.innerHTML=elementList('sidebar_promo','sidebar').map((item,index)=>bannerHtml(item,true,index+8)).join('');
    installBannerTracking(host);
  }
  function visitorId(){
    const key='blinq_banner_visitor_v1'; let value=localStorage.getItem(key);
    if(!value){const secure=(window.crypto&&typeof window.crypto.randomUUID==='function')?window.crypto.randomUUID():'';value=secure||`${Date.now()}-${Math.random().toString(36).slice(2)}`;localStorage.setItem(key,value);} return value;
  }
  function trackBanner(node,eventType){
    if(!node?.dataset?.bannerSlot)return;
    const payload={event_type:eventType,slot_id:node.dataset.bannerSlot,campaign_id:node.dataset.campaignId||node.dataset.bannerSlot,advertiser_id:node.dataset.advertiserId||'unassigned',client_id:visitorId()};
    BlinqAuth.bannerEvent(payload,eventType==='click').catch(()=>{});
  }
  function installBannerTracking(root=document){
    const nodes=[...root.querySelectorAll?.('[data-banner-slot]')||[]]; if(!nodes.length)return;
    if(!('IntersectionObserver' in window))return;
    if(!state.bannerObserver){
      const threshold=Math.max(.1,Math.min(1,Number(state.ui?.analytics?.impression_threshold)||.5));
      state.bannerObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{
        const node=entry.target;
        if(entry.intersectionRatio>=threshold&&!node.dataset.impressionTracked){
          if(state.bannerTimers.get(node))return;
          const timer=setTimeout(()=>{if(node.isConnected&&!node.dataset.impressionTracked){node.dataset.impressionTracked='1';trackBanner(node,'impression');}state.bannerTimers.delete(node);},Math.max(250,Number(state.ui?.analytics?.impression_ms)||1000));
          state.bannerTimers.set(node,timer);
        }else if(entry.intersectionRatio<threshold){const timer=state.bannerTimers.get(node);if(timer){clearTimeout(timer);state.bannerTimers.delete(node);}}
      }),{threshold:[threshold]});
    }
    nodes.forEach(node=>state.bannerObserver.observe(node));
  }
  async function loadNewsPool(){
    const rssSlots=elementList().some(item=>['header_slot','large_banner','sidebar_promo'].includes(item.kind)&&item.content?.type==='rss');
    const adSlots=elementList().some(item=>['header_slot','large_banner','sidebar_promo'].includes(item.kind)&&(item.content?.type==='advertisement'||item.content?.sponsored===true));
    const needed=Boolean(state.ui?.ad_fallbacks?.rss_enabled!==false&&(rssSlots||adSlots));
    if(!needed){state.newsPool=[];return;}
    try{const data=await BlinqAuth.contentNews();state.newsPool=Array.isArray(data?.items)?data.items:[];}catch{state.newsPool=[];}
  }
  function accountPlan(){
    if(state.previewPlan && isAdminAccount()) return state.previewPlan;
    const account=state.feed?.account||{};
    if(account.is_admin||String(account.role||'').toLowerCase()==='admin')return 'admin';
    const status=String(account.status||'expired').toLowerCase();
    if(status==='trial')return 'rookie';
    if(!['active','lifetime'].includes(status))return 'expired';
    return String(account.plan||'expired').toLowerCase();
  }
  function elementAccess(id, plan=accountPlan()){
    if(plan==='admin' && !state.previewPlan) return 'active';
    const value=String(elements()?.[id]?.access?.[plan]||'active').toLowerCase();
    return accessStates.includes(value)?value:'active';
  }
  function accessLabel(plan=accountPlan()){
    return state.ui?.plans?.[plan]?.label || String(plan||'').toUpperCase();
  }
  function applyAccessStates(root=document){
    root.querySelectorAll?.('[data-ui-element]').forEach(node=>{
      const id=node.dataset.uiElement; const mode=elementAccess(id);
      node.classList.remove('ui-state-active','ui-state-locked','ui-state-blurred','ui-state-hidden');
      node.classList.add(`ui-state-${mode}`); node.dataset.uiState=mode;
      node.dataset.uiStateLabel=mode==='active'?'':`${mode.toUpperCase()} · ${accessLabel()}`;
      node.setAttribute('aria-disabled',mode==='active'?'false':'true');
    });
  }
  function renderAllUiContent(){ if(state.bannerObserver){state.bannerObserver.disconnect();state.bannerObserver=null;}state.bannerTimers=new WeakMap();renderNavigation(); renderHeaderSlots(); renderBanners(); renderSidebarPromos(); renderMarketSections(); renderDashboardResultsPreview(); renderDashboardComposition(); applyAccessStates(); }

  function auth(mode='login'){
    state.authMode=mode; $('authMessage').textContent='';
    $('nameLabel').hidden=mode!=='signup'; $('emailLabel').hidden=mode==='recovery'; $('passwordLabel').hidden=mode==='reset';
    $('authEmail').required=mode!=='recovery'; $('authPassword').required=mode!=='reset'; $('authName').required=mode==='signup';
    $('authPassword').autocomplete=mode==='login'?'current-password':'new-password';
    $('authTitle').textContent={login:'Welcome back.',signup:'Create your BlinQ account.',reset:'Restore access.',recovery:'Set a new password.'}[mode];
    $('authSubtitle').textContent={login:'Sign in to your tennis intelligence workspace.',signup:'Create an account to access your BlinQ workspace.',reset:'We will send a password recovery link to your email.',recovery:'Choose a password with at least eight characters.'}[mode];
    $('authSubmit').textContent={login:'Sign in',signup:'Create account',reset:'Send recovery link',recovery:'Save password'}[mode];
    $('switchSignup').textContent=mode==='login'?'Create account':'Back to sign in'; $('switchReset').hidden=mode!=='login';
    $('authSubmit').disabled=!state.authEnabled;
    if(!state.authEnabled) $('authMessage').textContent='Authentication is temporarily unavailable.';
    $('appShell').hidden=true;
    if(!$('authDialog').open) $('authDialog').showModal();
  }

  async function handleAuthSubmit(event){
    event.preventDefault(); const button=$('authSubmit'); button.disabled=true; $('authMessage').textContent='Working…';
    const email=$('authEmail').value.trim(), password=$('authPassword').value;
    try{
      if(state.authMode==='reset'){ await BlinqAuth.reset(email); $('authMessage').textContent='If the account exists, check your email for the recovery link.'; return; }
      if(state.authMode==='recovery') await BlinqAuth.update({password});
      else if(state.authMode==='signup'){
        const session=await BlinqAuth.signUp(email,password,$('authName').value.trim());
        if(!session){ $('authMessage').textContent='Check your email and confirm registration, then sign in.'; return; }
      } else await BlinqAuth.signIn(email,password);
      $('authPassword').value=''; if($('authDialog').open) $('authDialog').close(); await loadFeed();
    } catch(error){ $('authMessage').textContent=error.status===400?'Check your credentials and email confirmation.':error.message; }
    finally{ button.disabled=false; }
  }

  function normalize(row){
    const player1=row?.player1||{},player2=row?.player2||{};
    const p1=Number(player1?.probability||0), p2=Number(player2?.probability||0);
    const winnerId=String(row?.winner_id || (p1>=p2?player1?.id:player2?.id) || '');
    const winner=winnerId===String(player1?.id)?player1:player2;
    const probability=Math.max(p1,p2);
    const betting=row?.betting&&typeof row.betting==='object'?row.betting:{};
    return {id:row?.event_id||row?.id,date:row?.scheduled_at,tour:String(row?.tour||'').toUpperCase(),tournament:row?.tournament||'Tournament',surface:row?.surface||'unknown',round:row?.round||'',p1:player1?.name||'Player 1',p2:player2?.name||'Player 2',p1Id:player1?.id,p2Id:player2?.id,p1Prob:p1,p2Prob:p2,p1Rank:player1?.rank??null,p2Rank:player2?.rank??null,p1Country:player1?.country_code||'',p2Country:player2?.country_code||'',p1Photo:safePhotoUrl(player1?.photo_url),p2Photo:safePhotoUrl(player2?.photo_url),pick:winner?.name||'—',pickId:winnerId,probability,confidence:confidenceBand(probability),signals:Array.isArray(row?.signals)?row.signals:[],quality:row?.quality&&typeof row.quality==='object'?row.quality:{},dataDepth:Number(row?.data_depth),odds:Number(betting.odds),edge:Number(betting.edge),expectedValue:Number(betting.expected_value),bettingDay:betting.betting_day||'',model:row?.model_version||state.feed?.model?.version||'',raw:row};
  }

  function populateSelect(id,values,label){ const select=$(id),selected=select.value; select.innerHTML=`<option value="">${label}</option>`; [...values].filter(Boolean).sort().forEach(value=>{const opt=document.createElement('option');opt.value=value;opt.textContent=String(value).replaceAll('_',' ');select.appendChild(opt)}); if([...select.options].some(o=>o.value===selected)) select.value=selected; }
  function populateFilters(){ const rows=(state.feed.upcoming||[]).map(normalize); populateSelect('tournamentFilter',new Set(rows.map(x=>x.tournament)),'All Tournaments'); populateSelect('surfaceFilter',new Set(rows.map(x=>x.surface)),'All Surfaces'); }
  function compactCount(value){ const n=Number(value); if(!Number.isFinite(n)) return '—'; if(n>=1000000) return `${(n/1000000).toFixed(n>=10000000?0:1)}M`; if(n>=1000) return `${(n/1000).toFixed(n>=100000?0:1)}K`; return String(Math.round(n)); }
  function rankedPredictions(){
    return marketRows('prime').map(normalize).sort((a,b)=>b.probability-a.probability || new Date(a.date)-new Date(b.date)).map((m,index)=>({...m,accessIndex:index}));
  }
  function filtered(){ const rows=rankedPredictions(),tour=$('tourFilter')?.value||'',tournament=$('tournamentFilter')?.value||'',surface=$('surfaceFilter')?.value||'',confidence=$('confidenceFilter')?.value||'',q=($('searchInput')?.value||'').trim().toLowerCase(); return rows.filter(m=>{ if(tour&&m.tour!==tour)return false;if(tournament&&m.tournament!==tournament)return false;if(surface&&m.surface!==surface)return false;if(confidence&&m.confidence!==confidence)return false;if(q&&!`${m.p1} ${m.p2} ${m.tournament}`.toLowerCase().includes(q))return false;return true; }); }

  function marketRows(key){
    const candidates={prime:['prime_picks','prime'],top_daily:['top_daily_picks','daily_picks','top_daily'],value:['value_picks','value'],doubles:['doubles_picks','doubles'],ace:['ace_picks','aces','ace_markets'],sg:['sg_picks','sets_games','set_game_picks']}[key]||[];
    for(const field of candidates){const value=state.feed?.[field];if(Array.isArray(value))return value;}
    const markets=state.feed?.markets;if(markets&&Array.isArray(markets[key]))return markets[key];
    return [];
  }
  function marketProbability(row){const raw=row?.probability??row?.win_probability??row?.model_probability??row?.confidence_probability;const value=Number(raw);return Number.isFinite(value)?(value>1?value/100:value):null;}
  function marketPreviewCard(row,key,index=0,locked=false){
    if(locked)return lockedPickCard(key,index);
    const p1=row?.player1||{},p2=row?.player2||{};const probability=marketProbability(row);const pick=row?.pick||row?.selection||row?.prediction||'—';const odds=Number(row?.odds),edge=Number(row?.edge),ev=Number(row?.expected_value);
    const projection=Number(row?.projection),opponentProjection=Number(row?.opponent_projection),projectionGap=Number(row?.projection_gap),projectionConfidence=Number(row?.projection_confidence);const samples=row?.projection_samples||{};const projectionOnly=row?.price_status==='projection_only'&&Number.isFinite(projection);
    let meta='',badge='',mainValue='—',confidenceClass='low',pickLabel=key==='prime'?'Prime Pick':key==='value'?'Value Pick':key==='ace'?'Ace / DF Pick':key==='sg'?'Set / Game Pick':'Top Bet';
    if(projectionOnly){
      const marketLabel=row?.market_type||String(row?.market||'Projection').replaceAll('_',' ');const sampleText=Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`Data ${samples.player1}/${samples.player2}`:'';const unit=String(row?.projection_unit||'count');const reference=Number(row?.reference_projection??row?.baseline_projection);
      if(key==='sg'&&unit==='probability'){mainValue=`${pct(projection)}<small> proj.</small>`;meta=[marketLabel,Number.isFinite(reference)?`Baseline ${pct(reference)}`:'',Number.isFinite(projectionGap)?`Gap ${(projectionGap*100).toFixed(1)} pp`:'',Number.isFinite(projectionConfidence)?`Score ${Math.round(projectionConfidence*100)}/100`:'',sampleText,'Projection only · no odds'].filter(Boolean).join(' · ');pickLabel='Sets Projection';}
      else if(key==='sg'&&unit==='games'){mainValue=`${projection.toFixed(1)}<small> games</small>`;meta=[marketLabel,Number.isFinite(reference)?`Baseline ${reference.toFixed(1)}`:'',Number.isFinite(projectionGap)?`Δ ${projectionGap.toFixed(1)} games`:'',Number.isFinite(projectionConfidence)?`Score ${Math.round(projectionConfidence*100)}/100`:'',sampleText,'Projection only · no odds'].filter(Boolean).join(' · ');pickLabel='Games Projection';}
      else{meta=[marketLabel,Number.isFinite(opponentProjection)?`Opponent proj. ${opponentProjection.toFixed(1)}`:'',Number.isFinite(projectionGap)?`Gap +${projectionGap.toFixed(1)}`:'',Number.isFinite(projectionConfidence)?`Score ${Math.round(projectionConfidence*100)}/100`:'',sampleText,'Projection only · no odds'].filter(Boolean).join(' · ');mainValue=`${projection.toFixed(1)}<small> proj.</small>`;pickLabel='Ace / DF Projection';}
      badge='PROJECTION';confidenceClass=Number.isFinite(projectionConfidence)?confidenceBand(projectionConfidence):'medium';
    }else{
      if(key==='top_daily'){const depth=Number(row?.data_depth),q=row?.quality||{},s1=Number(q?.player1?.surface_matches),s2=Number(q?.player2?.surface_matches);meta=[Number.isFinite(odds)?`Odds ${odds.toFixed(2)}`:'',Number.isFinite(depth)?`Data ${Math.round(depth*100)}%`:'',Number.isFinite(s1)&&Number.isFinite(s2)?`Surface ${Math.min(s1,s2)}+ each`:''].filter(Boolean).join(' · ');}
      else{meta=[Number.isFinite(odds)?`Odds ${odds.toFixed(2)}`:'',Number.isFinite(edge)?`Model edge ${edge>0?'+':''}${(edge*(Math.abs(edge)<=1?100:1)).toFixed(1)} pp`:'',Number.isFinite(ev)?`EV ${ev>0?'+':''}${(ev*(Math.abs(ev)<=1?100:1)).toFixed(1)}%`:''].filter(Boolean).join(' · ');}
      badge=probability==null?'MODEL':confidenceBand(probability).replace('-',' ').toUpperCase();mainValue=probability==null?'—':pct(probability);confidenceClass=probability==null?'low':confidenceBand(probability);
    }
    const p1Photo=safePhotoUrl(p1.photo_url),p2Photo=safePhotoUrl(p2.photo_url),fallback=playerFallbackUrl(row?.tour);const avatar=(photo,name)=>{const src=photo||fallback;return src?`<span class="player-avatar has-photo"><img src="${escapeHtml(src)}" alt="" loading="lazy" /></span>`:`<span class="player-avatar">${escapeHtml(initials(name))}</span>`};const p1Name=p1.name||row?.player1_name||'Player 1',p2Name=p2.name||row?.player2_name||'Player 2';
    return `<article class="prediction-card featured market-card${projectionOnly?' projection-card':''}"><div class="card-meta"><span class="tour">${escapeHtml(String(row?.tour||'').toUpperCase())} ${escapeHtml(row?.tournament||row?.competition||'')}</span><span class="time">${escapeHtml(fmtTime(row?.scheduled_at||row?.date))}</span><span class="surface">${escapeHtml(String(row?.surface||key).replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row"><div class="player">${avatar(p1Photo,p1Name)}<strong class="player-name">${escapeHtml(p1Name)}</strong><small class="player-rank">${escapeHtml(playerMetaLabel(p1.rank,p1.country_code))}</small></div><div class="vs">VS</div><div class="player">${avatar(p2Photo,p2Name)}<strong class="player-name">${escapeHtml(p2Name)}</strong><small class="player-rank">${escapeHtml(playerMetaLabel(p2.rank,p2.country_code))}</small></div></div><div class="pick-row"><div><small>${escapeHtml(pickLabel)}</small><strong class="pick-name">${escapeHtml(pick)}</strong></div><div class="probability">${mainValue}</div><span class="confidence ${confidenceClass}">${escapeHtml(badge)}</span></div><div class="market-card-meta">${escapeHtml(meta||row?.market||row?.market_type||'')}</div></article>`;
  }

  function renderMarketSection(key,hostId,emptyText){
    const host=$(hostId);if(!host)return;
    const rows=marketRows(key),previewMax=dashboardPreviewLimit(key,rows.length||1),preview=rows.slice(0,previewMax);
    const perPage=dashboardCardsPerPanel(),pageCount=Math.max(1,Math.ceil(preview.length/perPage));
    state.marketPage[key]=Math.min(Number(state.marketPage[key]||0),pageCount-1);
    const start=state.marketPage[key]*perPage,visible=preview.slice(start,start+perPage),unlocked=visiblePickCount(key,preview.length),ent=dashboardPlanEntitlement(key);
    host.innerHTML=visible.length?visible.map((row,localIndex)=>{const absoluteIndex=start+localIndex;const locked=ent.blur_remaining!==false&&absoluteIndex>=unlocked;return marketPreviewCard(row,key,absoluteIndex,locked)}).join(''):`<div class="state-card market-empty">${escapeHtml(emptyText)}</div>`;
    const count=$(key==='top_daily'?'topDailyCount':`${key}Count`);if(count)count.textContent=`${rows.length} ${rows.length===1?'pick':'picks'}`;
    const seeCount=$(key==='top_daily'?'topDailySeeAllCardCount':`${key}SeeAllCardCount`);if(seeCount)seeCount.textContent=`${rows.length} published`;
    const shell=host.closest('.market-carousel-shell');if(shell){const prev=shell.querySelector('[data-market-prev]'),next=shell.querySelector('[data-market-next]');if(prev){prev.hidden=pageCount<=1;prev.disabled=state.marketPage[key]<=0;}if(next){next.hidden=pageCount<=1;next.disabled=state.marketPage[key]>=pageCount-1;}}
  }
  function renderMarketSections(){renderMarketSection('top_daily','topDailyGrid','No Top Bets pass the adaptive 80 → 78 → 76 → 74 → 72 → 70 → 68 confidence cascade.');renderMarketSection('value','valueGrid','No Value Picks pass the current odds, edge and EV guardrails.');renderMarketSection('doubles','doublesGrid','Doubles picks are not published yet. The separate pair/team model remains isolated from singles.');renderMarketSection('ace','aceGrid','No Aces / Double Faults projections pass the current data-depth and gap guardrails yet.');renderMarketSection('sg','sgGrid','No Sets / Games projections pass the current data-depth and signal guardrails yet.');}

  function signalMeta(signal,m){ const id=String(signal?.player_id ?? signal?.favours_player_id ?? ''); const favours=id===String(m.pickId); const label=translateSignalLabel(signal?.label||signal?.factor||'Model signal'); return {label,favours}; }
  function renderSignal(signal,m){ const s=signalMeta(signal,m); return `<div class="signal-row"><span>${escapeHtml(s.label)}</span><div class="signal-meter"><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i></i><i></i></div></div>`; }
  function setPlayerIdentity(box,name,rank,country,photo,tour){
    const avatar=box.querySelector('.player-avatar'),fallbackText=initials(name),fallback=playerFallbackUrl(tour),safe=safePhotoUrl(photo);
    avatar.textContent=fallbackText;avatar.classList.remove('has-photo');
    const install=src=>{if(!src)return;const img=document.createElement('img');img.src=src;img.alt='';img.loading='lazy';img.addEventListener('error',()=>{if(src!==fallback&&fallback){install(fallback);return;}avatar.classList.remove('has-photo');avatar.textContent=fallbackText},{once:true});avatar.textContent='';avatar.classList.add('has-photo');avatar.replaceChildren(img);};
    install(safe||fallback);
    box.querySelector('.player-name').textContent=name;box.querySelector('.player-rank').textContent=playerMetaLabel(rank,country);
  }
  function dataDepthLabel(m){const q=m.quality||{},a=q.player1||{},b=q.player2||{};const values=[a.matches,b.matches,a.surface_matches,b.surface_matches].map(Number);if(values.every(Number.isFinite))return `History ${values[0]} / ${values[1]} · Surface ${values[2]} / ${values[3]}`;if(Number.isFinite(m.dataDepth))return `Data depth ${Math.round(m.dataDepth*100)}%`;return '';}
  function renderCard(m, slotIndex=0){ const template=$('predictionTemplate').content.cloneNode(true),card=template.querySelector('.prediction-card'); card.dataset.id=m.id; card.dataset.uiElement=slotIndex<8?`TOP_PICK_${slotIndex+1}`:'TOP_PICK_MORE'; card.classList.add('featured'); card.querySelector('.tour').textContent=`${m.tour} ${m.tournament}${m.round?` · ${m.round}`:''}`; card.querySelector('.time').textContent=fmtTime(m.date); card.querySelector('.surface').textContent=String(m.surface).replaceAll('_',' ').toUpperCase(); setPlayerIdentity(card.querySelector('.player-a'),m.p1,m.p1Rank,m.p1Country,m.p1Photo,m.tour);setPlayerIdentity(card.querySelector('.player-b'),m.p2,m.p2Rank,m.p2Country,m.p2Photo,m.tour); const depth=card.querySelector('.data-depth-row');if(depth){const label=dataDepthLabel(m);depth.textContent=label;depth.hidden=!label;} card.querySelector('.pick-name').textContent=m.pick; card.querySelector('.probability').textContent=pct(m.probability); const conf=card.querySelector('.confidence'); conf.textContent=m.confidence==='very-high'?'VERY HIGH':m.confidence.toUpperCase(); conf.classList.add(m.confidence); const bettingRow=card.querySelector('.betting-row');if(bettingRow&&Number.isFinite(m.odds)&&m.odds>1){bettingRow.hidden=false;card.querySelector('.betting-odds').textContent=`Odds ${m.odds.toFixed(2)}`;card.querySelector('.betting-edge').textContent=Number.isFinite(m.edge)?`Model edge ${m.edge>=0?'+':''}${(m.edge*100).toFixed(1)} pp`:'Model edge —';card.querySelector('.betting-ev').textContent=Number.isFinite(m.expectedValue)?`EV ${m.expectedValue>=0?'+':''}${(m.expectedValue*100).toFixed(1)}%`:'EV —';} const signals=card.querySelector('.signals'); signals.innerHTML=m.signals.length?m.signals.slice(0,4).map(s=>renderSignal(s,m)).join(''):'<div class="signal-empty">No strong secondary signal is available.</div>'; card.querySelector('.analysis-link').onclick=()=>openMatch(m); return template; }


  function renderDots(pageCount){ const host=$('carouselDots'); if(!host)return; host.innerHTML=''; if(pageCount<=1)return; for(let i=0;i<pageCount;i++){const b=document.createElement('button');b.type='button';b.className=i===state.page?'active':'';b.setAttribute('aria-label',`Show Prime Picks page ${i+1}`);b.onclick=()=>{state.page=i;renderPredictions()};host.appendChild(b)} }
  function renderPredictions(){
    const allRows=rankedPredictions(),limit=dashboardPreviewLimit('prime',allRows.length||1),rows=allRows.slice(0,limit),grid=$('predictionGrid'),size=dashboardCardsPerPanel();if(!grid)return;
    $('matchCount').textContent=allRows.length;const primeSeeCount=$('primeSeeAllCardCount');if(primeSeeCount)primeSeeCount.textContent=`${allRows.length} published`;
    const pageCount=Math.max(1,Math.ceil(rows.length/size));state.page=Math.min(state.page,pageCount-1);const start=state.page*size,visible=rows.slice(start,start+size),unlocked=visiblePickCount('prime',rows.length),ent=dashboardPlanEntitlement('prime');
    grid.classList.remove('show-all');grid.innerHTML='';
    if(!visible.length)grid.innerHTML='<div class="state-card">No Prime Picks pass the current accuracy/data-quality guardrails.</div>';
    else visible.forEach((m,index)=>{const absoluteIndex=start+index;if(ent.blur_remaining!==false&&absoluteIndex>=unlocked)grid.insertAdjacentHTML('beforeend',lockedPickCard('prime',absoluteIndex));else grid.appendChild(renderCard(m,Number.isInteger(m.accessIndex)?m.accessIndex:absoluteIndex));});
    $('prevPick').hidden=pageCount<=1;$('nextPick').hidden=pageCount<=1;$('prevPick').disabled=state.page<=0;$('nextPick').disabled=state.page>=pageCount-1;renderDots(pageCount);renderDashboardComposition();applyAccessStates(grid);
  }

  function openMatch(m){ const signalRows=m.signals.length?m.signals.map(s=>{const meta=signalMeta(s,m);const favoursId=String(s?.player_id??s?.favours_player_id??'');const favours=favoursId===String(m.p1Id)?m.p1:favoursId===String(m.p2Id)?m.p2:'—';return `<div class="dialog-signal"><span>${escapeHtml(meta.label)}</span><strong>${escapeHtml(favours)}</strong><small>${meta.favours?'supports pick':'counter-signal'}</small></div>`}).join(''):'<p class="signal-empty">No secondary signals are available.</p>'; const betting=Number.isFinite(m.odds)&&m.odds>1?`<div class="dialog-section dialog-market"><h3>Current market snapshot</h3><div class="dialog-market-grid"><span>Odds <strong>${m.odds.toFixed(2)}</strong></span><span>Model edge <strong>${Number.isFinite(m.edge)?`${m.edge>=0?'+':''}${(m.edge*100).toFixed(1)} pp`:'—'}</strong></span><span>EV <strong>${Number.isFinite(m.expectedValue)?`${m.expectedValue>=0?'+':''}${(m.expectedValue*100).toFixed(1)}%`:'—'}</strong></span></div></div>`:''; $('dialogContent').innerHTML=`<div class="dialog-eyebrow">${escapeHtml(m.tour)} · ${escapeHtml(m.tournament)}</div><h2>${escapeHtml(m.p1)} <span>vs</span> ${escapeHtml(m.p2)}</h2><div class="dialog-pick"><div><small>BlinQ Pick</small><strong>${escapeHtml(m.pick)}</strong></div><div class="dialog-prob">${pct(m.probability)} <span class="confidence ${m.confidence}">${m.confidence==='very-high'?'VERY HIGH':m.confidence.toUpperCase()}</span></div></div>${betting}<div class="dialog-section"><h3>Model signals</h3>${signalRows}</div><div class="dialog-meta"><span>${escapeHtml(String(m.surface).replaceAll('_',' '))}</span><span>${fmtDate(m.date)} · ${fmtTime(m.date)}</span><span>Model ${escapeHtml(m.model||'—')}</span></div>`; $('matchDialog').showModal(); }

  const routeMeta={
    predictions:['TENNIS INTELLIGENCE','Dashboard','Prime Picks, daily selections, market picks and current BlinQ intelligence.'],
    prime:['MATCH WINNER','Prime Picks','Accuracy-first Match Winner picks; preferred odds 1.20–1.50, without a hard odds band.'],
    top_daily:['CONFIDENCE FIRST','Top Bets','Strongest remaining Match Winner picks, ranked by model probability and data quality.'],
    value:['VALUE EDGE','Value Picks','Higher-priced model-vs-market opportunities with stricter edge and EV guardrails.'],
    doubles:['DOUBLES','Doubles','Separate doubles model and team-pair intelligence.'],
    ace:['ACES + DOUBLE FAULTS','Ace Picks','Top Aces and Double Faults market selections.'],
    sg:['SETS + GAMES','S/G Picks','Top Sets and Games market selections.'],
    results:['SETTLED PICKS','Results','Settled selections, hit rate, ROI, units and related performance statistics.'],
    account:['BLINQ MEMBERS','Account','Manage your profile and access.'],
    admin:['BLINQ CONTROL','Admin Control Center','Internal model performance, backtests, publishing, access and workspace configuration.'],
    how_blinq_works:['LEARN','How BlinQ Works','How the BlinQ workflow turns point-in-time tennis data into probabilities.'],
    methodology:['LEARN','Methodology','The principles used to keep predictions point-in-time and auditable.'],
    model_data:['LEARN','Model & Data','What the published feed exposes about data and model state.'],
    faq:['LEARN','FAQ','Common questions about probabilities, results and model output.'],
    responsible_use:['LEARN','Responsible Use','Use probabilities as information, never as guarantees.']
  };

  function setRoute(route,push=true){ if(!routeMeta[route]) route='predictions'; if(route==='admin'&&!isAdminAccount()) route='predictions'; const section=dashboardSectionKeys.includes(route)?dashboardSectionConfig(route):null; if(section&&route!=='predictions'&&elementAccess(section.sidebar_element)!=='active'&&state.route!=='admin'){showUpgradePrompt(firstUnlockPlan(route,0,true),section.label||route);route='predictions';} if(route==='admin') state.previewPlan=null; state.route=route; state.page=0; const meta=routeMeta[route]; const overview=route==='predictions'; $('pageEyebrow').textContent=meta[0]; $('pageTitle').textContent=meta[1]; $('pageSubtitle').textContent=meta[2]; const topbar=document.querySelector('.dashboard-topbar'); if(topbar) topbar.classList.toggle('overview-mode',overview); $('predictionsView').hidden=!overview; $('routePanel').hidden=overview; renderNavigation(); if(overview){renderPredictions();renderMarketSections();renderDashboardResultsPreview();applyAccessStates();} else renderRoute(route); if(push) history.replaceState(null,'',`#${route}`); }

  function metricCards(items){ return `<div class="metric-cards">${items.map(([label,value,note])=>`<div class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note||'')}</span></div>`).join('')}</div>`; }
  function issuedMarketPublications(row){
    return (Array.isArray(row?.market_publications)?row.market_publications:[]).filter(p=>p&&p.issued_at&&p.result&&!p.excluded_reason);
  }
  function resultTags(row){
    const tags=[];
    issuedMarketPublications(row).forEach(p=>{const section=String(p.section||'');if(section&&!tags.includes(section))tags.push(section);});
    return tags;
  }
  function resultCategoryLabel(value){return ({all:'All published',prime:'Prime',top_daily:'Top Bet',value:'Value',doubles:'Doubles',ace:'Aces',double_faults:'Double Faults',sets:'Sets',games:'Games'})[value]||String(value||'').replaceAll('_',' ');}
  function resultPublication(row,category='all'){
    const pubs=issuedMarketPublications(row);
    const filtered=['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category)?pubs.filter(p=>p.section===category):pubs;
    return filtered.sort((a,b)=>new Date(a.issued_at)-new Date(b.issued_at))[0]||null;
  }
  function filteredResults(){
    const filters=state.resultsFilters||{},now=Date.now(),windowDays=Number(filters.window);
    return (state.feed.results||[]).filter(row=>{
      if(filters.tour&&String(row?.tour||'').toUpperCase()!==filters.tour)return false;
      if(filters.surface&&String(row?.surface||'').toLowerCase()!==filters.surface)return false;
      if(Number.isFinite(windowDays)&&windowDays>0){const ts=new Date(row?.scheduled_at||0).getTime();if(!Number.isFinite(ts)||ts<now-windowDays*86400000)return false;}
      const category=filters.category||'all';
      if(['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category)&&!resultTags(row).includes(category))return false;
      return typeof row?.result?.correct==='boolean';
    });
  }
  function renderResultsFilters(){
    const rows=state.feed.results||[],filters=state.resultsFilters||{};
    const tours=[...new Set(rows.map(r=>String(r?.tour||'').toUpperCase()).filter(Boolean))].sort();
    const surfaces=[...new Set(rows.map(r=>String(r?.surface||'').toLowerCase()).filter(Boolean))].sort();
    const option=(value,label,selected)=>`<option value="${escapeHtml(value)}"${value===selected?' selected':''}>${escapeHtml(label)}</option>`;
    return `<div class="results-filter-bar"><label>Category<select id="resultsCategory">${['all','prime','top_daily','value','doubles','ace','double_faults','sets','games'].map(v=>option(v,resultCategoryLabel(v),filters.category||'all')).join('')}</select></label><label>Tour<select id="resultsTour">${option('','All Tours',filters.tour||'')}${tours.map(v=>option(v,v,filters.tour||'')).join('')}</select></label><label>Surface<select id="resultsSurface">${option('','All Surfaces',filters.surface||'')}${surfaces.map(v=>option(v,v.replaceAll('_',' '),filters.surface||'')).join('')}</select></label><label>Period<select id="resultsWindow">${[['all','All time'],['7','7 days'],['30','30 days'],['90','90 days']].map(([v,l])=>option(v,l,filters.window||'all')).join('')}</select></label></div>`;
  }
  function localResultMetrics(rows,category){
    const coreWins=rows.filter(r=>r?.result?.correct===true).length;
    const publications=rows.map(r=>resultPublication(r,category)).filter(Boolean);
    const unique=new Map();publications.forEach(p=>{const key=String(p.selection_key||p.publication_key||'');if(!key)return;if(!unique.has(key)||new Date(p.issued_at)<new Date(unique.get(key).issued_at))unique.set(key,p);});
    const bets=[...unique.values()].filter(p=>p?.result&&typeof p.result.correct==='boolean');
    const betWins=bets.filter(p=>p.result.correct===true).length,profit=bets.reduce((sum,p)=>sum+Number(p.result.profit_units||0),0),stake=bets.reduce((sum,p)=>sum+Number(p.result.staked_units||0),0),odds=bets.map(p=>Number(p.odds)).filter(Number.isFinite);
    const categoryIsBet=['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category);const wins=categoryIsBet?betWins:coreWins;const sample=categoryIsBet?bets.length:rows.length;
    return {wins,losses:Math.max(0,sample-wins),sample,hit:sample?wins/sample:null,avgOdds:odds.length?odds.reduce((a,b)=>a+b,0)/odds.length:null,roi:stake?profit/stake:null,profit,oddsSample:bets.length};
  }
  function renderResults(){
    const rows=filteredResults(),category=state.resultsFilters?.category||'all';
    if(!rows.length)return '<div class="state-card">No settled published predictions match these filters yet.</div>';
    const body=rows.slice(0,250).map(r=>{const p1=r.player1||{},p2=r.player2||{},publication=resultPublication(r,category),marketMode=Boolean(publication&&['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category));const correct=marketMode?publication?.result?.correct:r?.result?.correct;const pickId=marketMode?publication?.selection_id:r?.winner_id;const pickName=marketMode?(publication?.selection||'—'):(pickId===p1.id?p1.name:pickId===p2.id?p2.name:'—');const probability=marketMode?Number(publication?.model_probability):Number(r?.confidence);const odds=Number(publication?.odds),units=Number(publication?.result?.profit_units);const tags=resultTags(r).map(t=>`<span class="result-tag ${escapeHtml(t)}">${escapeHtml(resultCategoryLabel(t))}</span>`).join('');return `<tr><td>${escapeHtml(fmtDate(r.scheduled_at))}<small>${escapeHtml(fmtTime(r.scheduled_at))}</small></td><td>${tags||'<span class="result-tag">Model</span>'}</td><td><strong>${escapeHtml(p1.name||'Player 1')}</strong><small>vs ${escapeHtml(p2.name||'Player 2')} · ${escapeHtml(r.tournament||'')}</small></td><td>${escapeHtml(pickName)}</td><td>${Number.isFinite(probability)?pct(probability):'—'}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td><td><b class="${correct?'correct':'wrong'}">${correct===true?'✓ WON':correct===false?'× LOST':'—'}</b></td><td class="${Number.isFinite(units)&&units>=0?'correct':'wrong'}">${Number.isFinite(units)?`${units>0?'+':''}${units.toFixed(2)}u`:'—'}</td></tr>`}).join('');
    return `<div class="admin-table-wrap results-table-wrap"><table class="admin-analytics-table results-table"><thead><tr><th>Date</th><th>Category</th><th>Match</th><th>Pick</th><th>Probability</th><th>Odds</th><th>Result</th><th>Units</th></tr></thead><tbody>${body}</tbody></table></div>${rows.length>250?`<div class="results-limit-note">Showing latest 250 of ${rows.length} matching settled rows in the serving snapshot.</div>`:''}`;
  }
  function wireResultsFilters(){
    [['resultsCategory','category'],['resultsTour','tour'],['resultsSurface','surface'],['resultsWindow','window']].forEach(([id,key])=>{const el=$(id);if(el)el.onchange=()=>{state.resultsFilters[key]=el.value;renderRoute('results');};});
  }

  function planSelectOptions(selected='', includeBlank=true){
    const rows=Object.entries(state.ui?.plans||{}).filter(([id,p])=>!['trial','expired'].includes(id)&&(p.enabled!==false||id===selected));
    return `${includeBlank?`<option value=""${!selected?' selected':''}>No paid plan</option>`:''}${rows.map(([id,p])=>`<option value="${escapeHtml(id)}"${id===selected?' selected':''}>${escapeHtml(p.label||id.toUpperCase())}${p.enabled===false?' · reserved':''}</option>`).join('')}`;
  }
  function statusSelectOptions(selected='expired'){
    const trial=selected==='trial'?'<option value="trial" selected disabled>TRIAL · automatic</option>':'';
    return trial+['active','expired','suspended','lifetime'].map(value=>`<option value="${value}"${value===selected?' selected':''}>${value.toUpperCase()}</option>`).join('');
  }
  function planDefaultExpiry(planId, from=new Date()){
    const plan=state.ui?.plans?.[planId]||{};
    if(plan.lifetime)return null;
    const days=Number(plan.duration_days); if(!Number.isFinite(days)||days<=0)return null;
    return new Date(from.getTime()+days*86400000);
  }
  function planTermLabel(planId){
    const plan=state.ui?.plans?.[planId]||{};
    if(plan.lifetime)return 'Unlimited / lifetime';
    const days=Number(plan.duration_days); return Number.isFinite(days)&&days>0?`${days} days`:'Manual expiration';
  }
  function accessSelect(id, plan){
    const selected=elementAccess(id,plan);
    return `<select data-admin-access="${escapeHtml(plan)}">${accessStates.map(value=>`<option value="${value}"${value===selected?' selected':''}>${value.toUpperCase()}</option>`).join('')}</select>`;
  }
  function adminMiniBlock(id, compact=false, extraClass='', customSmall=''){
    const item=elements()?.[id]; if(!item)return '';
    const mode=elementAccess(id,state.adminPlan); const selected=state.selectedElement===id?' selected':'';
    return `<button type="button" class="admin-mini-block ${compact?'compact ':''}${extraClass}state-${mode}${selected}" data-admin-element="${escapeHtml(id)}"><small>${escapeHtml(customSmall||id)}</small><strong>${escapeHtml(item.label||id)}</strong><span>${mode.toUpperCase()}</span></button>`;
  }
  function rowPrefix(zone){ return zone==='content_top'?'CONTENT_TOP_':zone==='content_mid'?'CONTENT_MID_':'CONTENT_BOTTOM_'; }
  function adminRowHtml(zone){
    const prefix=rowPrefix(zone);
    return rowItems(zone).map(entry=>{const covered=entry.span>1?` · spans ${Array.from({length:entry.span},(_,i)=>`${prefix}${entry.start+i+1}`).join(' + ')}`:'';return adminMiniBlock(entry.item.id,false,`grid-span-${entry.span} `,`${entry.item.id}${covered} · ${creativeSpecText(entry.item,entry.span)}`);}).join('');
  }
  function rowCreativeSummary(zone){if(!rowEnabled(zone))return 'ROW OFF';return rowItems(zone).map(entry=>`${entry.span} col: ${creativeSpecText(entry.item,entry.span)}`).join(' · ');}

  function renderAdminCanvas(){
    const nav=elementList('navigation').map(x=>adminMiniBlock(x.id,true)).join('');const promos=elementList('sidebar_promo','sidebar').map(x=>adminMiniBlock(x.id,true)).join('');const picks=[...Array(8)].map((_,i)=>adminMiniBlock(`TOP_PICK_${i+1}`,true)).join('')+adminMiniBlock('TOP_PICK_MORE',true);const features=elementList('feature','features').map(x=>adminMiniBlock(x.id,true)).join('');
    const rowBlock=(zone,title)=>`<div class="admin-row-caption"><span>${escapeHtml(title)}</span><b>${escapeHtml(rowPreset(zone))} · ${escapeHtml(rowCreativeSummary(zone))}</b></div><div class="admin-slot-row four preset-${escapeHtml(rowPreset(zone).replaceAll('+','-'))}${rowEnabled(zone)?'':' row-off'}">${adminRowHtml(zone)||'<div class="admin-row-off-label">ROW OFF</div>'}</div>`;
    return `<div class="admin-canvas"><div class="admin-canvas-header"><div class="admin-logo-lock">BLINQ LOGO<br><small>FIXED</small></div><div class="admin-header-slots">${adminMiniBlock('HEADER_BANNER_1')}${adminMiniBlock('HEADER_BANNER_2')}${adminMiniBlock('HEADER_BANNER_3')}</div></div><div class="admin-canvas-body"><aside class="admin-canvas-sidebar"><b>SIDEBAR</b>${nav}<div class="admin-canvas-divider"></div><b>3 PROMO SLOTS</b>${promos}${renderDashboardQuickControls()}${features?`<div class="admin-canvas-divider"></div><b>FEATURE FLAGS</b>${features}`:''}</aside><main class="admin-canvas-main"><div class="admin-functional-row">${adminMiniBlock('PREDICTION_TOOLBAR')}</div>${rowBlock('content_top','BANNER ROW · TOP OF DASHBOARD')}<div class="admin-prime-map"><div>${adminMiniBlock('PRIME_PICKS_PANEL')}${adminMiniBlock('TOP_DAILY_PANEL')}</div><div class="admin-pick-strip">${picks}</div></div>${rowBlock('content_mid','OPTIONAL BANNER ROW 2')}<div class="admin-functional-row">${adminMiniBlock('VALUE_PICKS_PANEL')}${adminMiniBlock('DOUBLES_PANEL')}</div>${rowBlock('content_bottom','OPTIONAL BANNER ROW 3')}<div class="admin-functional-row">${adminMiniBlock('ACE_PICKS_PANEL')}${adminMiniBlock('SG_PICKS_PANEL')}</div><div class="admin-functional-row">${adminMiniBlock('RESULTS_PANEL')}${adminMiniBlock('BTTS_BONUS_PANEL')}</div>${adminMiniBlock('FOOTER_SYSTEM')}</main></div></div>`;
  }

  function campaignOptions(selected=''){
    const rows=Object.entries(state.ui?.campaigns||{}).sort((a,b)=>String(a[1]?.name||a[0]).localeCompare(String(b[1]?.name||b[0])));
    return `<option value="">Inline / no campaign</option>`+rows.map(([id,c])=>`<option value="${escapeHtml(id)}"${id===selected?' selected':''}>${escapeHtml(c.name||id)}</option>`).join('');
  }
  function spanForElement(id){
    for(const zone of contentRowZones){
      const entry=rowItems(zone).find(row=>row.item?.id===id);
      if(entry)return entry.span;
    }
    return 1;
  }
  function creativeSpecForItem(item,spanOverride=null){
    const specs=state.ui?.creative_specs||{};
    if(item?.kind==='header_slot')return specs.header_slot||{};
    if(item?.kind==='sidebar_promo')return specs.sidebar_promo||{};
    if(item?.kind==='large_banner'){
      const span=Math.max(1,Math.min(4,Number(spanOverride||spanForElement(item.id))||1));
      return specs[`large_${span}`]||specs.large_1||{};
    }
    return {};
  }
  function creativeSpecText(item,spanOverride=null){
    const spec=creativeSpecForItem(item,spanOverride);
    const parts=[spec.aspect_ratio?`ratio ${spec.aspect_ratio}`:'',spec.recommended?`recommended ${spec.recommended}`:'',spec.minimum?`min ${spec.minimum}`:'',spec.safe_area?`safe ${spec.safe_area}`:''].filter(Boolean);
    return parts.join(' · ')||'fixed BlinQ creative format';
  }
  function contentEditor(item){
    const c=item.content||{};
    if(item.kind==='navigation') return `<div class="admin-field-grid"><label>Button label<input data-admin-content="label" value="${escapeHtml(c.label||'')}"></label><label>Icon<input data-admin-content="icon" value="${escapeHtml(c.icon||'')}"></label><label>Route<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label></div>`;
    if(!['header_slot','large_banner','sidebar_promo'].includes(item.kind)) return '<p class="admin-muted">Functional dashboard element. Use the Dashboard display block below to configure its public placement and pick visibility.</p>';
    const sidebarDestination=item.kind==='sidebar_promo'?`<div class="admin-link-callout span-2"><div><strong>Sidebar banner destination</strong><span>The whole banner is clickable. Use an external https:// URL or an internal #route.</span></div><label>Banner click URL<input data-admin-content="link" value="${escapeHtml(c.link||'')}" placeholder="https://... or #account"></label></div>`:'';
    const standardDestination=item.kind!=='sidebar_promo'?`<label>Destination URL / link<input data-admin-content="link" value="${escapeHtml(c.link||'')}" placeholder="https://... or #account"></label>`:'';
    return `<div class="admin-field-grid">
      ${sidebarDestination}
      <label>Content type<select data-admin-content="type"><option value="internal"${c.type==='internal'?' selected':''}>Internal</option><option value="advertisement"${c.type==='advertisement'?' selected':''}>Advertisement</option><option value="rss"${c.type==='rss'?' selected':''}>RSS / news</option><option value="image"${c.type==='image'?' selected':''}>Image</option><option value="promo"${(!c.type||c.type==='promo')?' selected':''}>Promo</option></select></label>
      <label>Theme<select data-admin-content="theme">${['violet','blue','purple','green','gold'].map(v=>`<option value="${v}"${v===(c.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label>
      <div class="field-hint-box span-2">${escapeHtml(item.kind==='large_banner'?`Banner width is controlled by the fixed row preset. Current creative: ${creativeSpecText(item)}.`:`Fixed creative: ${creativeSpecText(item)}.`)}</div>
      <label class="check-field"><input type="checkbox" data-admin-content="enabled" ${c.enabled!==false?'checked':''}> Content enabled</label>
      <label>Campaign<select data-admin-content="campaign_id">${campaignOptions(String(c.campaign_id||''))}</select></label>
      <label>Advertiser ID<input data-admin-content="advertiser_id" value="${escapeHtml(c.advertiser_id||'')}" placeholder="inline / fallback advertiser"></label>
      <label>Plan avatar<select data-admin-content="plan_id"><option value="">None</option>${['rookie','pro','elite','legend','goat'].map(v=>`<option value="${v}"${v===String(c.plan_id||'').toLowerCase()?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label>Eyebrow<input data-admin-content="eyebrow" value="${escapeHtml(c.eyebrow||'')}"></label>
      <label>Headline<input data-admin-content="headline" value="${escapeHtml(c.headline||'')}"></label>
      <label class="span-2">Text<textarea data-admin-content="text" rows="3">${escapeHtml(c.text||'')}</textarea></label>
      <label>CTA text<input data-admin-content="button_text" value="${escapeHtml(c.button_text||'')}"></label>
      ${standardDestination}
      <label>Internal route (optional)<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label>
      <label class="span-2">Desktop image path / URL<input data-admin-content="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/... or https://..."></label>
      <label class="span-2">Mobile image (optional)<input data-admin-content="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="Optional mobile-specific creative"></label>
      <label>Image fit<select data-admin-content="image_fit"><option value="cover"${(c.image_fit||'cover')==='cover'?' selected':''}>Cover · fill slot</option><option value="contain"${c.image_fit==='contain'?' selected':''}>Contain · show whole image</option></select></label>
      <label>Image position<select data-admin-content="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(c.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label>Show from · optional<input data-admin-content="active_from" type="datetime-local" value="${escapeHtml(c.active_from||'')}"></label>
      <label>Show until · optional<input data-admin-content="active_until" type="datetime-local" value="${escapeHtml(c.active_until||'')}"></label>
      <label>When ad is unavailable<select data-admin-content="ad_hidden_fallback">${['auto','rss','image','internal'].map(v=>`<option value="${v}"${v===(c.ad_hidden_fallback||'auto')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label class="check-field"><input type="checkbox" data-admin-content="sponsored" ${c.sponsored?'checked':''}> Sponsored label</label>
    </div>`;
  }
  function watermarkEditor(item){
    if(!['header_slot','large_banner','sidebar_promo'].includes(item.kind))return '';
    const wm=item.watermark||{},presets=state.ui?.watermark_presets||{violet:{label:'BlinQ Violet'},blue:{label:'Deep Blue'},cyan:{label:'Cyan'},gold:{label:'Legend Gold'},slate:{label:'Slate'}};
    const preset=String(wm.preset||'violet');
    return `<div class="admin-section"><div class="admin-section-title"><strong>Watermark overlay</strong><span>Text and color preset</span></div><div class="admin-field-grid watermark-controls"><label class="check-field"><input type="checkbox" data-admin-watermark="enabled" ${wm.enabled?'checked':''}> Enable watermark</label><label>Watermark text<input data-admin-watermark="text" value="${escapeHtml(wm.text||'COMING SOON')}"></label><label>Color<select data-admin-watermark="preset">${Object.entries(presets).map(([id,row])=>`<option value="${escapeHtml(id)}"${id===preset?' selected':''}>${escapeHtml(row?.label||id)}</option>`).join('')}</select></label></div><div class="watermark-preview wm-${escapeHtml(preset)}"><span>${escapeHtml(wm.text||'COMING SOON')}</span></div></div>`;
  }
  function adminDashboardSectionKeyForElement(id){
    const map={PRIME_PICKS_PANEL:'prime',TOP_DAILY_PANEL:'top_daily',VALUE_PICKS_PANEL:'value',DOUBLES_PANEL:'doubles',ACE_PICKS_PANEL:'ace',SG_PICKS_PANEL:'sg',RESULTS_PANEL:'results',BTTS_BONUS_PANEL:'btts'};
    return map[id]||dashboardSectionKeyForSidebarElement(id)||'';
  }
  function dashboardDisplayEditor(elementId){
    const key=adminDashboardSectionKeyForElement(elementId);if(!key)return '';
    const choices=state.ui?.admin?.dashboard_preview_choices||[0,1,2,3,4,5,'ALL'],previewChoices=[5,10,15,20,'ALL'];
    const cfg=dashboardSectionConfig(key),ent=cfg.plans?.[state.adminPlan]||cfg.plans?.rookie||{};
    const options=choices.map(v=>`<option value="${escapeHtml(v)}"${String(ent.visible_picks).toUpperCase()===String(v).toUpperCase()?' selected':''}>${escapeHtml(v)}</option>`).join('');
    const preview=previewChoices.map(v=>`<option value="${escapeHtml(v)}"${String(cfg.preview_limit).toUpperCase()===String(v).toUpperCase()?' selected':''}>${escapeHtml(v)}</option>`).join('');
    return `<div class="admin-section dashboard-inspector-section" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-title"><strong>Dashboard pick display · ${escapeHtml(cfg.label||key)}</strong><span>Use the free inspector space for panel visibility and card access.</span></div><div class="admin-field-grid"><label class="check-field"><input type="checkbox" data-dashboard-field="sidebar_enabled" ${cfg.sidebar_enabled!==false?'checked':''}> Show in sidebar</label><label class="check-field"><input type="checkbox" data-dashboard-field="dashboard_enabled" ${cfg.dashboard_enabled!==false?'checked':''}> Show on dashboard</label><label>Preview pool<select data-dashboard-field="preview_limit">${preview}</select></label><label>Visible picks · ${escapeHtml(accessLabel(state.adminPlan))}<select data-dashboard-plan-field="visible_picks">${options}</select><small class="field-hint">0 + Blur remaining = the whole pick preview is blurred.</small></label><label class="check-field"><input type="checkbox" data-dashboard-plan-field="blur_remaining" ${ent.blur_remaining!==false?'checked':''}> Blur remaining</label><label class="check-field"><input type="checkbox" data-dashboard-plan-field="see_all" ${ent.see_all?'checked':''}> See all</label></div></div>`;
  }
  function renderAdminInspector(){
    const item=elements()?.[state.selectedElement] || elements()?.HEADER_BANNER_1;
    if(!item)return '<aside class="admin-inspector"><p>No configurable elements.</p></aside>';
    return `<aside class="admin-inspector"><div class="admin-inspector-head"><small>${escapeHtml(state.selectedElement)}</small><h3>${escapeHtml(item.label||state.selectedElement)}</h3><span>${escapeHtml(item.kind||'element')} · ${escapeHtml(item.zone||'')}</span></div>
      <div class="admin-section"><div class="admin-section-title"><strong>Content / details</strong><span>What this fixed position displays</span></div>${contentEditor(item)}</div>
      ${watermarkEditor(item)}
      ${dashboardDisplayEditor(state.selectedElement)}
      <div class="admin-section"><div class="admin-section-title"><strong>Plan access</strong><span>Layout stays reserved even when hidden</span></div><div class="admin-access-grid">${accessContexts.map(plan=>`<label><span>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</span>${accessSelect(state.selectedElement,plan)}</label>`).join('')}</div></div>
    </aside>`;
  }
  function renderDashboardQuickControls(){
    return `<div class="admin-canvas-divider"></div><b>DASHBOARD DISPLAY</b><div class="admin-dashboard-quick">${dashboardPickSectionKeys.map(key=>{const cfg=dashboardSectionConfig(key);return `<label data-dashboard-section="${escapeHtml(key)}"><span>${escapeHtml(cfg.label||key)}</span><input type="checkbox" data-dashboard-field="dashboard_enabled" ${cfg.dashboard_enabled!==false?'checked':''}></label>`}).join('')}</div>`;
  }
  function renderAdminDashboardControls(){ return renderDashboardQuickControls(); }

  function renderAdminLayout(){
    const planOptions=accessContexts.map(id=>`<option value="${id}"${state.adminPlan===id?' selected':''}>${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</option>`).join('');const copyOptions=accessContexts.filter(id=>id!==state.adminPlan).map(id=>`<option value="${id}">${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</option>`).join('');const presets=state.ui?.admin?.row_presets||Object.keys(rowPresetMap);const dashboard=state.ui?.dashboard||{};
    const rowControls=contentRowZones.map(zone=>{const row=rowConfig(zone);const options=presets.map(id=>`<option value="${escapeHtml(id)}"${rowPreset(zone)===id?' selected':''}>${escapeHtml(id)}</option>`).join('');return `<div class="admin-row-control"><label class="check-field"><input type="checkbox" data-admin-row-enabled="${escapeHtml(zone)}" ${rowEnabled(zone)?'checked':''}> ${escapeHtml(row.label||zone)}</label><label>Division<select data-admin-row-preset="${escapeHtml(zone)}">${options}</select></label><small>${escapeHtml(rowCreativeSummary(zone))}</small></div>`}).join('');
    return `<div class="admin-toolbar"><label>Editing access for<select id="adminPlanSelect">${planOptions}</select></label><label>Copy all access from<select id="adminCopyFrom">${copyOptions}</select></label><button class="btn btn-ghost" type="button" data-admin-action="copy-plan">Copy → ${escapeHtml(accessLabel(state.adminPlan))}</button><span class="admin-toolbar-separator"></span><label>Cards / desktop<select data-dashboard-global-field="cards_per_panel_desktop">${[1,2,3].map(v=>`<option value="${v}"${Number(dashboard.cards_per_panel_desktop||2)===v?' selected':''}>${v}</option>`).join('')}</select></label><label>Cards / wide<select data-dashboard-global-field="cards_per_panel_wide">${[2,3,4].map(v=>`<option value="${v}"${Number(dashboard.cards_per_panel_wide||3)===v?' selected':''}>${v}</option>`).join('')}</select></label><label class="admin-toolbar-check"><input type="checkbox" data-dashboard-global-field="auto_replace_empty_sections" ${dashboard.auto_replace_empty_sections!==false?'checked':''}> Auto-fill empty panel</label><span class="admin-toolbar-spacer"></span><button class="btn btn-ghost" type="button" data-admin-action="preview-demo">Preview full board</button><button class="btn btn-ghost" type="button" data-admin-action="preview">Preview as ${escapeHtml(accessLabel(state.adminPlan))}</button><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish changes</button><button class="btn btn-ghost" type="button" data-admin-action="export">Export JSON</button></div><div class="admin-note admin-banner-note"><strong>Dashboard banners</strong><span>The top public promo row is PRO / ELITE / LEGEND. Click any banner block in the canvas to edit copy, destination link, avatar, theme, image or watermark. Dashboard pick-window toggles now live in the left canvas column and each pick panel exposes detailed display settings in the inspector. Replace an empty window with the next section that has published picks when auto-fill is enabled.</span></div><div class="admin-row-controls">${rowControls}</div><div class="admin-editor-grid"><div>${renderAdminCanvas()}</div>${renderAdminInspector()}</div>`;
  }

  function renderAdminPlans(){
    const plans=Object.entries(state.ui?.plans||{}).filter(([id])=>!['trial','expired'].includes(id)).sort((a,b)=>Number(a[1]?.order||99)-Number(b[1]?.order||99));
    return `<div class="admin-note"><strong>Membership catalogue</strong><span>No price is rendered in BlinQ. Membership order is Rookie → PRO → Elite → Legend → GOAT; duration and access remain configurable here.</span></div><div class="admin-plan-grid">${plans.map(([id,p])=>`<article class="admin-plan-card ${p.enabled===false?'disabled':''}" data-plan-card="${escapeHtml(id)}"><div class="admin-plan-head">${planAvatarHtml(id,p)}<small>${escapeHtml(id)}</small><input data-plan-field="label" value="${escapeHtml(p.label||id.toUpperCase())}"><label class="check-field"><input type="checkbox" data-plan-field="enabled" ${p.enabled!==false?'checked':''}> Visible / enabled</label></div><div class="admin-field-grid"><label class="span-2">Description<textarea data-plan-field="description" rows="3">${escapeHtml(p.description||p.note||'')}</textarea></label><label>CTA label<input data-plan-field="cta_label" value="${escapeHtml(p.cta_label||'Open plan')}"></label><label>Avatar level<select data-plan-field="avatar">${['rookie','pro','elite','legend','goat'].map(v=>`<option value="${v}"${v===(p.avatar||id)?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label class="span-2">External plan URL<input data-plan-field="url" value="${escapeHtml(p.url||'')}" placeholder="https://..."></label><label>Display order<input value="${Number(p.order||99)} · fixed" disabled></label><label>Default duration (days)<input data-plan-field="duration_days" type="number" min="1" value="${p.duration_days??''}" ${p.lifetime?'disabled':''}></label><label class="check-field"><input type="checkbox" data-plan-field="lifetime" ${p.lifetime?'checked':''}> Unlimited / lifetime</label></div><div class="admin-plan-term"><span>Default account term</span><strong>${escapeHtml(planTermLabel(id))}</strong></div></article>`).join('')}</div><div class="admin-actions-row"><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish membership changes</button><button class="btn btn-ghost" type="button" data-admin-action="export">Export ui-config.json</button></div>`;
  }
  function userDateValue(value){ if(!value)return ''; const d=new Date(value); if(Number.isNaN(d.getTime()))return ''; const pad=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
  function renderAdminUserEditor(user){
    if(!user)return '<div class="admin-user-empty">Select an account to edit its role and subscription.</div>';
    const self=String(user.id)===String(state.feed?.account?.id);
    const selectedPlan=user.plan&& !['expired','admin'].includes(user.plan)?user.plan:'';
    return `<form id="adminUserForm" class="admin-user-editor"><div class="admin-inspector-head"><small>${escapeHtml(user.id)}</small><h3>${escapeHtml(user.name||user.email||'User')}</h3><span>${escapeHtml(user.email||'')}</span></div><div class="admin-field-grid"><label>Role<select id="adminUserRole" ${self?'disabled':''}><option value="user"${user.role!=='admin'?' selected':''}>USER</option><option value="admin"${user.role==='admin'?' selected':''}>ADMIN</option></select></label><label>Plan<select id="adminUserPlan">${planSelectOptions(selectedPlan,true)}</select><small class="field-hint" id="adminPlanTerm">${escapeHtml(selectedPlan?planTermLabel(selectedPlan):'No paid plan')}</small></label><label>Status<select id="adminUserStatus">${statusSelectOptions(user.status||'expired')}</select></label><label>Expires at<input id="adminUserExpires" type="datetime-local" value="${escapeHtml(userDateValue(user.expires_at))}" ${user.status==='lifetime'?'disabled':''}></label><label class="span-2">Payment / manual reference<input id="adminPaymentReference" maxlength="120" value="${escapeHtml(user.payment_reference||'')}" placeholder="payment link order, note, transaction id..."></label></div><div class="admin-user-meta"><span>Created: ${escapeHtml(fmtDate(user.created_at))}</span><span>Last login: ${escapeHtml(fmtDate(user.last_sign_in_at))}</span><span>Current: ${escapeHtml(user.plan_label||user.plan||'—')} · ${escapeHtml(user.status||'—')}</span>${user.status==='trial'?`<span>Automatic Rookie trial until ${escapeHtml(fmtDate(user.expires_at))}</span>`:''}</div><div class="admin-quick-actions">${['rookie','pro','elite','legend','goat'].filter(id=>state.ui?.plans?.[id]?.enabled!==false).map(id=>`<button type="button" class="btn btn-ghost" data-admin-user-plan="${escapeHtml(id)}">${escapeHtml((state.ui?.plans?.[id]?.label||id).toUpperCase())} · ${escapeHtml(planTermLabel(id))}</button>`).join('')}</div><p id="adminUserMessage" class="form-message"></p><button class="btn btn-primary" type="submit">Apply changes</button>${self?'<small class="admin-muted">Your own ADMIN role is protected from accidental removal.</small>':''}</form>`;
  }
  function renderAdminAccounts(){
    const users=Array.isArray(state.adminUsers)?state.adminUsers:[];
    const list=state.adminUsersLoading?'<div class="state-card">Loading accounts…</div>':users.length?users.map(user=>`<button type="button" class="admin-user-row${state.adminSelectedUser?.id===user.id?' selected':''}" data-admin-user="${escapeHtml(user.id)}" data-search="${escapeHtml(`${user.email||''} ${user.name||''} ${user.plan||''}`.toLowerCase())}"><span class="avatar">${escapeHtml(initials(user.name||user.email||'U'))}</span><span><strong>${escapeHtml(user.name||'Member')}</strong><small>${escapeHtml(user.email||'')}</small></span><b>${escapeHtml(user.plan_label||user.plan||'—')}</b><em>${escapeHtml(user.status||'—')}</em></button>`).join(''):'<div class="admin-user-empty">No accounts loaded. Admin account management is not configured in the runtime.</div>';
    return `<div class="admin-accounts-toolbar"><label class="search-box"><span>⌕</span><input id="adminUserSearch" type="search" placeholder="Search account…"></label><button class="btn btn-ghost" type="button" data-admin-action="refresh-users">↻ Refresh users</button></div><div class="admin-accounts-grid"><div class="admin-user-list">${list}</div>${renderAdminUserEditor(state.adminSelectedUser)}</div>`;
  }
  function nextEntityId(prefix, collection){
    const existing=new Set(Object.keys(collection||{})); let i=1; while(existing.has(`${prefix}-${i}`))i+=1; return `${prefix}-${i}`;
  }
  function advertiserOptions(selected=''){
    const rows=Object.entries(state.ui?.advertisers||{}).sort((a,b)=>String(a[1]?.name||a[0]).localeCompare(String(b[1]?.name||b[0])));
    return `<option value="">Unassigned</option>`+rows.map(([id,a])=>`<option value="${escapeHtml(id)}"${id===selected?' selected':''}>${escapeHtml(a.name||id)}</option>`).join('');
  }
  function renderAdminCampaigns(){
    state.ui.advertisers=state.ui.advertisers||{};state.ui.campaigns=state.ui.campaigns||{};
    const advertisers=Object.entries(state.ui.advertisers);
    const campaigns=Object.entries(state.ui.campaigns);
    if(state.adminCampaignId&&!state.ui.campaigns[state.adminCampaignId])state.adminCampaignId=null;
    if(!state.adminCampaignId&&campaigns.length)state.adminCampaignId=campaigns[0][0];
    const selected=state.adminCampaignId?state.ui.campaigns[state.adminCampaignId]:null;
    const advertiserCards=advertisers.length?advertisers.map(([id,a])=>`<article class="entity-card" data-advertiser-id="${escapeHtml(id)}"><div class="entity-card-head"><small>${escapeHtml(id)}</small><button class="icon-button danger" type="button" data-admin-action="delete-advertiser" data-entity-id="${escapeHtml(id)}" title="Delete advertiser">×</button></div><label>Name<input data-advertiser-field="name" value="${escapeHtml(a.name||'')}"></label><label>Website<input data-advertiser-field="website" value="${escapeHtml(a.website||'')}"></label><label>Note<input data-advertiser-field="note" value="${escapeHtml(a.note||'')}"></label></article>`).join(''):'<div class="admin-user-empty">No advertisers yet.</div>';
    const campaignRows=campaigns.length?campaigns.map(([id,c])=>`<button type="button" class="campaign-row${id===state.adminCampaignId?' selected':''}" data-admin-campaign="${escapeHtml(id)}"><span><strong>${escapeHtml(c.name||id)}</strong><small>${escapeHtml(c.advertiser_id||'unassigned')}</small></span><b>${c.enabled===false?'OFF':'ON'}</b></button>`).join(''):'<div class="admin-user-empty">No campaigns yet.</div>';
    const images=selected?.images&&typeof selected.images==='object'?selected.images:{};
    const specs=state.ui?.creative_specs||{};
    const spec1=specs.large_1||{},spec2=specs.large_2||{},spec4=specs.large_4||{};
    const editor=selected?`<form id="adminCampaignForm" class="campaign-editor"><div class="admin-inspector-head"><small>${escapeHtml(state.adminCampaignId)}</small><h3>${escapeHtml(selected.name||state.adminCampaignId)}</h3><span>Campaign creative and scheduling</span></div><div class="admin-field-grid"><label>Name<input data-campaign-field="name" value="${escapeHtml(selected.name||'')}"></label><label>Advertiser<select data-campaign-field="advertiser_id">${advertiserOptions(String(selected.advertiser_id||''))}</select></label><label class="check-field"><input type="checkbox" data-campaign-field="enabled" ${selected.enabled!==false?'checked':''}> Enabled</label><label class="check-field"><input type="checkbox" data-campaign-field="sponsored" ${selected.sponsored!==false?'checked':''}> Sponsored label</label><label>Creative mode<select data-campaign-field="creative_mode"><option value="full"${(selected.creative_mode||'full')==='full'?' selected':''}>Full image banner</option><option value="split"${selected.creative_mode==='split'?' selected':''}>Image + BlinQ text</option></select></label><label class="check-field"><input type="checkbox" data-campaign-field="show_copy" ${selected.show_copy!==false?'checked':''}> Show headline / CTA over creative</label><label>Theme<select data-campaign-field="theme">${['violet','blue','purple','green'].map(v=>`<option value="${v}"${v===(selected.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label><label>Eyebrow<input data-campaign-field="eyebrow" value="${escapeHtml(selected.eyebrow||'SPONSORED')}"></label><label class="span-2">Headline<input data-campaign-field="headline" value="${escapeHtml(selected.headline||'')}"></label><label class="span-2">Text<textarea data-campaign-field="text" rows="3">${escapeHtml(selected.text||'')}</textarea></label><label>CTA text<input data-campaign-field="button_text" value="${escapeHtml(selected.button_text||'Open')}"></label><label>Destination URL<input data-campaign-field="link" value="${escapeHtml(selected.link||'')}"></label><div class="field-hint-box">Prepare the formats shown below. BlinQ keeps the page structure fixed, centers the creative automatically and selects the 1/2/4-column image for the active row division.</div><label class="span-2">1-column · ${escapeHtml(spec1.aspect_ratio||'4:1')} · rec ${escapeHtml(spec1.recommended||'1200 × 300 px')} · min ${escapeHtml(spec1.minimum||'800 × 200 px')} · safe ${escapeHtml(spec1.safe_area||'center 80%')}<input data-campaign-image="1" value="${escapeHtml(images['1']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">2-column · ${escapeHtml(spec2.aspect_ratio||'8:1')} · rec ${escapeHtml(spec2.recommended||'2400 × 300 px')} · min ${escapeHtml(spec2.minimum||'1600 × 200 px')} · safe ${escapeHtml(spec2.safe_area||'center 85%')}<input data-campaign-image="2" value="${escapeHtml(images['2']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">Full row · ${escapeHtml(spec4.aspect_ratio||'16:1')} · rec ${escapeHtml(spec4.recommended||'2400 × 150 px')} · min ${escapeHtml(spec4.minimum||'1600 × 100 px')} · safe ${escapeHtml(spec4.safe_area||'center 90%')}<input data-campaign-image="4" value="${escapeHtml(images['4']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">Fallback desktop image<input data-campaign-field="image_url" value="${escapeHtml(selected.image_url||'')}" placeholder="Used when a size-specific image is empty"></label><label class="span-2">Mobile image (optional)<input data-campaign-field="mobile_image_url" value="${escapeHtml(selected.mobile_image_url||'')}" placeholder="Optional mobile creative"></label><label>Image fit<select data-campaign-field="image_fit"><option value="cover"${(selected.image_fit||'cover')==='cover'?' selected':''}>Cover · centered crop</option><option value="contain"${selected.image_fit==='contain'?' selected':''}>Contain · full image</option></select></label><label>Image position<select data-campaign-field="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(selected.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label>Active from<input data-campaign-field="active_from" type="datetime-local" value="${escapeHtml(selected.active_from||'')}"></label><label>Active until<input data-campaign-field="active_until" type="datetime-local" value="${escapeHtml(selected.active_until||'')}"></label></div><div class="admin-actions-row"><button class="btn btn-ghost danger" type="button" data-admin-action="delete-campaign" data-entity-id="${escapeHtml(state.adminCampaignId)}">Delete campaign</button></div></form>`:'<div class="admin-user-empty">Create a campaign, then assign it to any fixed content slot.</div>';
    return `<div class="admin-toolbar"><button class="btn btn-ghost" type="button" data-admin-action="add-advertiser">+ Advertiser</button><button class="btn btn-primary" type="button" data-admin-action="add-campaign">+ Campaign</button><span class="admin-toolbar-spacer"></span><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish changes</button></div><div class="campaign-admin-grid"><section><div class="admin-section-title"><strong>Advertisers</strong><span>Partner identity is separate from campaign history.</span></div><div class="entity-grid">${advertiserCards}</div></section><section><div class="admin-section-title"><strong>Campaigns</strong><span>Campaigns can move between slots without losing analytics.</span></div><div class="campaign-workspace"><div class="campaign-list">${campaignRows}</div>${editor}</div></section></div>`;
  }
  function renderAdminFeeds(){
    state.ui.rss=state.ui.rss||{enabled:true,refresh_minutes:60,max_age_hours:48,max_items:24,sources:[]};
    const rss=state.ui.rss;rss.sources=Array.isArray(rss.sources)?rss.sources:[];
    const rows=rss.sources.map((source,index)=>`<article class="rss-source-card" data-rss-source="${index}"><div class="entity-card-head"><small>${escapeHtml(source.id||`rss-${index+1}`)}</small><button class="icon-button danger" type="button" data-admin-action="delete-rss-source" data-source-index="${index}">×</button></div><div class="admin-field-grid"><label class="check-field"><input type="checkbox" data-rss-source-field="enabled" ${source.enabled!==false?'checked':''}> Enabled</label><label>Priority<input type="number" data-rss-source-field="priority" value="${Number(source.priority||0)}"></label><label>Name<input data-rss-source-field="name" value="${escapeHtml(source.name||'')}"></label><label class="span-2">RSS URL<input data-rss-source-field="url" value="${escapeHtml(source.url||'')}" placeholder="https://.../rss"></label></div></article>`).join('');
    return `<div class="admin-note"><strong>RSS fallback pool</strong><span>One or two quality tennis feeds are enough. Articles are normalized and deduplicated before they fill unused ad slots.</span></div><div class="admin-field-grid rss-global"><label class="check-field"><input type="checkbox" data-rss-field="enabled" ${rss.enabled!==false?'checked':''}> RSS enabled</label><label>Refresh (minutes)<input type="number" min="5" max="240" data-rss-field="refresh_minutes" value="${Number(rss.refresh_minutes||60)}"></label><label>Maximum article age (hours)<input type="number" min="1" max="720" data-rss-field="max_age_hours" value="${Number(rss.max_age_hours||48)}"></label><label>Pool size<input type="number" min="1" max="100" data-rss-field="max_items" value="${Number(rss.max_items||24)}"></label></div><div class="rss-sources">${rows||'<div class="admin-user-empty">No RSS sources configured.</div>'}</div><div class="admin-actions-row"><button class="btn btn-ghost" type="button" data-admin-action="add-rss-source">+ RSS source</button><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish RSS settings</button></div>`;
  }
  function renderAdminAnalytics(){
    if(state.adminAnalyticsLoading)return '<div class="state-card">Loading banner analytics…</div>';
    const data=state.adminAnalytics;
    if(!data?.available)return `<div class="admin-note"><strong>Banner analytics unavailable</strong><span>Azure Table Storage is not available in the current runtime. Configure BLINQ_ADMIN_STORAGE_CONNECTION_STRING or use AzureWebJobsStorage.</span></div><button class="btn btn-ghost" type="button" data-admin-action="refresh-analytics">Retry</button>`;
    const summary=data.summary||{};
    const cards=[['Impressions',String(summary.impressions||0)],['Unique views',String(summary.unique_impressions||0)],['Clicks',String(summary.clicks||0)],['Unique clicks',String(summary.unique_clicks||0)],['CTR',pct(summary.ctr||0)],['Campaigns',String(summary.campaigns||0)]];
    const rows=(data.campaigns||[]).map(row=>`<tr><td><strong>${escapeHtml(row.campaign_id)}</strong><small>${escapeHtml(row.advertiser_id||'')}</small></td><td>${row.impressions}</td><td>${row.unique_impressions}</td><td>${row.clicks}</td><td>${row.unique_clicks}</td><td>${pct(row.ctr||0)}</td><td>${escapeHtml(Object.keys(row.slots||{}).join(', ')||'—')}</td><td>${escapeHtml(fmtDate(row.last_seen))}</td></tr>`).join('');
    return `<div class="admin-analytics-head"><div class="metric-cards">${cards.map(([label,value])=>`<div class="metric-card"><small>${label}</small><strong>${value}</strong><span>last ${data.days||30} days</span></div>`).join('')}</div><button class="btn btn-ghost" type="button" data-admin-action="refresh-analytics">↻ Refresh</button></div><div class="admin-table-wrap"><table class="admin-analytics-table"><thead><tr><th>Campaign</th><th>Views</th><th>Unique</th><th>Clicks</th><th>Unique clicks</th><th>CTR</th><th>Slots</th><th>Last seen</th></tr></thead><tbody>${rows||'<tr><td colspan="8">No banner events recorded yet.</td></tr>'}</tbody></table></div><p class="admin-muted">Impression = at least ${Math.round((Number(state.ui?.analytics?.impression_threshold)||.5)*100)}% of the banner visible for about ${Number(state.ui?.analytics?.impression_ms)||1000} ms.</p>`;
  }
  async function loadBannerAnalytics(force=false){
    if(state.adminAnalyticsLoading||(!force&&state.adminAnalytics))return;
    state.adminAnalyticsLoading=true;rerenderAdmin();
    try{state.adminAnalytics=await BlinqAuth.adminBannerAnalytics(Number(state.ui?.analytics?.window_days)||30);}
    catch(error){state.adminAnalytics={available:false,error:error.message};}
    finally{state.adminAnalyticsLoading=false;rerenderAdmin();}
  }
  function renderAdminPerformance(){
    const feed=state.feed||{},p=feed.performance||{},report=feed.model?.report||{},holdout=report.holdout||{},delta=report.delta_vs_elo||{},backtest=report.backtest||report.walk_forward||{};
    return `<div class="admin-note"><strong>Internal model workspace</strong><span>Live performance, model evaluation and backtests live here; none of these items occupy the public sidebar.</span></div>${metricCards([['Model',String(feed.model?.version||'—'),'production artifact'],['Settled',String(p.n??0),'published results'],['Live accuracy',p.accuracy!=null?pct(p.accuracy):'—','settled feed'],['Holdout n',String(holdout.n??'—'),'chronological evaluation'],['Holdout accuracy',holdout.accuracy!=null?pct(holdout.accuracy):'—','model report'],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—','negative is better']])}<div class="route-sub static-copy"><h3>Backtests</h3><p>Historical walk-forward validation is retained inside Model Performance. Latest embedded report: ${escapeHtml(backtest.method||report.method||'available when published with the model artifact')}.</p></div>`;
  }

  function buildDemoMatch(i,section='prime'){
    const names=[['Maya Jensen','Elena Moretti'],['Sofia Marin','Lea Novak'],['Clara Voss','Nina Petrov'],['Emma Lind','Sara Costa'],['Julia Weber','Anna Horak'],['Lina Rossi','Eva Klein'],['Marta Silva','Klara Novak'],['Alice Morel','Daria Ivanova']];
    const [a,b]=names[i%names.length],prob=Math.max(.56,.91-i*.025-(section==='value'?.12:section==='top_daily'?.06:0)),odds=section==='value'?1.82+i*.07:section==='top_daily'?1.42+i*.06:1.24+i*.04;
    const id=`demo-${section}-${i+1}`,tour=i%2?'wta':'atp';
    return {event_id:id,scheduled_at:new Date(Date.now()+(i+2)*3600000).toISOString(),tour,tournament:i%2?'BlinQ Open':'BlinQ Masters',surface:i%3===0?'clay':i%3===1?'hard':'grass',round:'R16',player1:{id:`${id}-a`,name:a,rank:18+i*3,country_code:i%2?'SK':'CZ',probability:prob,photo_url:''},player2:{id:`${id}-b`,name:b,rank:31+i*4,country_code:i%2?'IT':'ES',probability:1-prob,photo_url:''},winner_id:`${id}-a`,pick:a,selection:a,probability:prob,odds,edge:section==='value'?.065:.035,expected_value:section==='value'?.11:.045,data_depth:.88,quality:{player1:{matches:34+i,surface_matches:9+i},player2:{matches:28+i,surface_matches:7+i}},betting:{odds,edge:section==='value'?.065:.035,expected_value:section==='value'?.11:.045,betting_day:new Date().toISOString().slice(0,10)},signals:[{label:'Recent form',player_id:`${id}-a`},{label:'Surface strength',player_id:`${id}-a`},{label:'Return form',player_id:`${id}-a`}],model_version:'demo-preview'};
  }
  function buildDemoProjection(i){
    const row=buildDemoMatch(i,'ace');return {...row,pick:row.player1.name,selection:row.player1.name,price_status:'projection_only',market_type:i%2?'Aces':'Double Faults',projection:6.2+i*.35,opponent_projection:4.1+i*.22,projection_gap:2.1+i*.13,projection_confidence:.82-i*.025,projection_samples:{player1:14+i,player2:12+i},projection_unit:'count'};
  }
  function enableDemoBoardPreview(){
    if(!state.demoFeedBackup)state.demoFeedBackup=clone(state.feed||{});
    const base=clone(state.feed||{});base.generated_at=new Date().toISOString();base.model={...(base.model||{}),version:'DEMO PREVIEW'};base.prime_picks=[0,1,2,3,4].map(i=>buildDemoMatch(i,'prime'));base.top_daily_picks=[0,1,2,3,4,5].map(i=>buildDemoMatch(i,'top_daily'));base.value_picks=[0,1,2,3,4].map(i=>buildDemoMatch(i,'value'));base.ace_picks=[0,1,2,3,4].map(buildDemoProjection);base.doubles_picks=[];base.sg_picks=[];state.feed=base;state.demoMode=true;state.dashboardVisibility=null;state.page=0;Object.keys(state.marketPage||{}).forEach(k=>state.marketPage[k]=0);populateFilters();renderAllUiContent();setRoute('predictions');showStatus('Demo preview only — sample picks are in browser memory and are never published.');
  }

  function renderAdminRoute(){
    const tabs=[['layout','Layout & slots'],['performance','Model Performance'],['campaigns','Campaigns'],['feeds','RSS feeds'],['plans','Plans'],['accounts','Accounts'],['analytics','Banner analytics']];
    const panel=state.adminTab==='layout'?renderAdminLayout():state.adminTab==='performance'?renderAdminPerformance():state.adminTab==='campaigns'?renderAdminCampaigns():state.adminTab==='feeds'?renderAdminFeeds():state.adminTab==='plans'?renderAdminPlans():state.adminTab==='accounts'?renderAdminAccounts():renderAdminAnalytics();
    return `<div class="admin-console"><div class="admin-tabs">${tabs.map(([id,label])=>`<button type="button" class="${state.adminTab===id?'active':''}" data-admin-tab="${id}">${label}</button>`).join('')}</div><div class="admin-panel">${panel}</div></div>`;
  }
  function rerenderAdmin(){ if(state.route!=='admin')return; const host=$('routePanel');host.innerHTML=renderAdminRoute();wireAdmin(); }
  function saveDraft(){ localStorage.setItem(draftKey(),JSON.stringify(state.ui)); showStatus('Admin draft saved in this browser.'); }
  function exportUiConfig(){ const blob=new Blob([JSON.stringify(state.ui,null,2)+'\n'],{type:'application/json'}); const url=URL.createObjectURL(blob); const a=document.createElement('a');a.href=url;a.download='ui-config.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),0); }
  async function loadAdminUsers(force=false){
    if(state.adminUsersLoading||(!force&&Array.isArray(state.adminUsers)))return;
    state.adminUsersLoading=true;rerenderAdmin();
    try{const data=await BlinqAuth.adminUsers(1,200);state.adminUsers=Array.isArray(data?.users)?data.users:[];if(state.adminSelectedUser){state.adminSelectedUser=state.adminUsers.find(x=>x.id===state.adminSelectedUser.id)||null;}}
    catch(error){state.adminUsers=[];showStatus(error.status===503?'Admin account API is not configured in the runtime.':error.message);}
    finally{state.adminUsersLoading=false;rerenderAdmin();}
  }
  function setSelectedElement(id){ if(!elements()?.[id])return;state.selectedElement=id;rerenderAdmin(); }
  function updateSelectedContent(field,target){ const item=elements()?.[state.selectedElement];if(!item)return;item.content=item.content||{};item.content[field]=target.type==='checkbox'?target.checked:target.value;if(field==='campaign_id'&&target.value){item.content.type='advertisement';item.content.sponsored=true;}renderAllUiContent(); }
  function updateSelectedWatermark(field,target){ const item=elements()?.[state.selectedElement];if(!item)return;item.watermark=item.watermark||{enabled:false,text:'COMING SOON',preset:'default'};item.watermark[field]=target.type==='checkbox'?target.checked:target.value;renderAllUiContent(); }
  function setAdminPlanDefaults(planId){
    const status=$('adminUserStatus'),expiry=$('adminUserExpires'),term=$('adminPlanTerm');
    if(!status||!expiry)return;
    if(!planId){status.value='expired';expiry.value='';expiry.disabled=false;if(term)term.textContent='No paid plan';return;}
    const plan=state.ui?.plans?.[planId]||{};if(term)term.textContent=planTermLabel(planId);
    if(plan.lifetime){status.value='lifetime';expiry.value='';expiry.disabled=true;return;}
    status.value='active';expiry.disabled=false;const date=planDefaultExpiry(planId);expiry.value=userDateValue(date?.toISOString());
  }
  async function publishUiConfig(){
    try{await BlinqAuth.adminSaveUiConfig(state.ui);state.runtimeConfigLoaded=true;localStorage.removeItem(draftKey());showStatus('Admin configuration published. New sessions will load it automatically.');}
    catch(error){showStatus(error.status===503?'Runtime config storage is not available; browser draft/export still works.':error.message);}
  }
  function wireAdmin(){
    const host=$('routePanel'); if(!host)return;
    host.onclick=async event=>{
      const tab=event.target.closest('[data-admin-tab]');if(tab){state.adminTab=tab.dataset.adminTab;rerenderAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='analytics')loadBannerAnalytics();return;}
      const element=event.target.closest('[data-admin-element]');if(element){setSelectedElement(element.dataset.adminElement);return;}
      const userButton=event.target.closest('[data-admin-user]');if(userButton){state.adminSelectedUser=(state.adminUsers||[]).find(x=>String(x.id)===String(userButton.dataset.adminUser))||null;rerenderAdmin();return;}
      const campaignButton=event.target.closest('[data-admin-campaign]');if(campaignButton){state.adminCampaignId=campaignButton.dataset.adminCampaign;rerenderAdmin();return;}
      const quick=event.target.closest('[data-admin-user-plan]');if(quick){const select=$('adminUserPlan');if(select&&[...select.options].some(o=>o.value===quick.dataset.adminUserPlan)){select.value=quick.dataset.adminUserPlan;setAdminPlanDefaults(select.value);}return;}
      const actionNode=event.target.closest('[data-admin-action]');const action=actionNode?.dataset.adminAction;if(!action)return;
      if(action==='save-draft')saveDraft();
      else if(action==='publish-config')await publishUiConfig();
      else if(action==='export')exportUiConfig();
      else if(action==='reset'){localStorage.removeItem(draftKey());state.ui=clone(state.uiSource);state.selectedElement='HEADER_BANNER_1';renderAllUiContent();rerenderAdmin();showStatus('Reset to repository defaults. Publish if you want this reset live.');}
      else if(action==='copy-plan'){const source=$('adminCopyFrom')?.value,target=state.adminPlan;if(source&&target){Object.values(elements()).forEach(item=>{item.access=item.access||{};item.access[target]=item.access[source]||'active';if(target==='rookie')item.access.trial=item.access[target];});rerenderAdmin();showStatus(`Access copied from ${accessLabel(source)} to ${accessLabel(target)}.`);}}
      else if(action==='preview-demo'){state.previewPlan=null;enableDemoBoardPreview();}
      else if(action==='preview'){state.previewPlan=state.adminPlan;renderAllUiContent();setRoute('predictions');showStatus(`Previewing page as ${accessLabel(state.previewPlan)}.`);}
      else if(action==='clear-preview'){state.previewPlan=null;renderAllUiContent();rerenderAdmin();showStatus('Admin preview disabled.');}
      else if(action==='add-advertiser'){state.ui.advertisers=state.ui.advertisers||{};const id=nextEntityId('advertiser',state.ui.advertisers);state.ui.advertisers[id]={name:`Advertiser ${Object.keys(state.ui.advertisers).length+1}`,website:'',note:''};rerenderAdmin();}
      else if(action==='delete-advertiser'){const id=String(actionNode.dataset.entityId||'');const used=Object.values(state.ui?.campaigns||{}).some(c=>String(c?.advertiser_id||'')===id);if(used){showStatus('Advertiser is still assigned to a campaign. Reassign the campaign first.');}else if(id&&state.ui?.advertisers?.[id]){delete state.ui.advertisers[id];rerenderAdmin();}}
      else if(action==='add-campaign'){state.ui.campaigns=state.ui.campaigns||{};const id=nextEntityId('campaign',state.ui.campaigns);state.ui.campaigns[id]={name:`Campaign ${Object.keys(state.ui.campaigns).length+1}`,advertiser_id:'',enabled:true,sponsored:true,creative_mode:'full',show_copy:false,theme:'violet',eyebrow:'SPONSORED',headline:'',text:'',button_text:'Open',link:'',image_url:'',mobile_image_url:'',image_fit:'cover',image_position:'center',images:{'1':'','2':'','4':''},active_from:'',active_until:''};state.adminCampaignId=id;rerenderAdmin();}
      else if(action==='delete-campaign'){const id=String(actionNode.dataset.entityId||state.adminCampaignId||'');if(id&&state.ui?.campaigns?.[id]){delete state.ui.campaigns[id];Object.values(elements()).forEach(item=>{if(item?.content?.campaign_id===id)item.content.campaign_id='';});state.adminCampaignId=null;renderAllUiContent();rerenderAdmin();}}
      else if(action==='add-rss-source'){state.ui.rss=state.ui.rss||{enabled:true,sources:[]};state.ui.rss.sources=Array.isArray(state.ui.rss.sources)?state.ui.rss.sources:[];const max=Math.max(1,Number(state.ui?.admin?.max_rss_sources)||8);if(state.ui.rss.sources.length>=max){showStatus(`Maximum ${max} RSS sources.`);}else{const used=new Set(state.ui.rss.sources.map(x=>x.id));let n=1;while(used.has(`rss-${n}`))n++;state.ui.rss.sources.push({id:`rss-${n}`,name:`RSS source ${n}`,url:'',enabled:false,priority:0});rerenderAdmin();}}
      else if(action==='delete-rss-source'){const index=Number(actionNode.dataset.sourceIndex);if(Number.isInteger(index)&&index>=0&&index<(state.ui?.rss?.sources||[]).length){state.ui.rss.sources.splice(index,1);rerenderAdmin();}}
      else if(action==='refresh-users')await loadAdminUsers(true);
      else if(action==='refresh-analytics')await loadBannerAnalytics(true);
    };
    host.onchange=event=>{
      const t=event.target;
      if(t.id==='adminPlanSelect'){state.adminPlan=t.value;rerenderAdmin();return;}
      if(t.dataset.adminRowEnabled){const zone=t.dataset.adminRowEnabled;state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].enabled=t.checked;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminRowPreset){const zone=t.dataset.adminRowPreset;state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].preset=t.value;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.dashboardGlobalField){state.ui.dashboard=state.ui.dashboard||{};let value=t.type==='checkbox'?t.checked:Number(t.value);state.ui.dashboard[t.dataset.dashboardGlobalField]=value;state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();return;}
      const dashboardRow=t.closest('[data-dashboard-section]');
      if(dashboardRow&&t.dataset.dashboardField){const key=dashboardRow.dataset.dashboardSection;state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});let value=t.type==='checkbox'?t.checked:(t.dataset.dashboardField==='preview_limit'&&String(t.value).toUpperCase()!=='ALL'?Number(t.value):t.value);if(t.dataset.dashboardField==='dashboard_enabled'){const pickKeys=dashboardPickSectionKeys;const enabled=pickKeys.filter(k=>(state.ui.dashboard.sections[k]||dashboardSectionFallback[k]||{}).dashboard_enabled!==false);if(value&&!enabled.includes(key)&&enabled.length>=Number(state.ui.dashboard.visible_slots||4)){const victim=[...enabled].reverse().find(k=>k!==key);if(victim)state.ui.dashboard.sections[victim].dashboard_enabled=false;}cfg.dashboard_enabled=value;if(!value){const after=pickKeys.filter(k=>(state.ui.dashboard.sections[k]||dashboardSectionFallback[k]||{}).dashboard_enabled!==false);const start=pickKeys.indexOf(key)+1;const replacement=[...pickKeys.slice(start),...pickKeys.slice(0,start)].find(k=>k!==key&&!after.includes(k)&&(state.ui.dashboard.sections[k]||dashboardSectionFallback[k]||{}).sidebar_enabled!==false);if(replacement&&after.length<Number(state.ui.dashboard.visible_slots||4))state.ui.dashboard.sections[replacement].dashboard_enabled=true;}state.dashboardVisibility=null;}else cfg[t.dataset.dashboardField]=value;renderAllUiContent();rerenderAdmin();return;}
      if(dashboardRow&&t.dataset.dashboardPlanField){const key=dashboardRow.dataset.dashboardSection;state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});cfg.plans=cfg.plans||{};cfg.plans[state.adminPlan]=cfg.plans[state.adminPlan]||{};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.dashboardPlanField==='visible_picks'&&String(value).toUpperCase()!=='ALL')value=Number(value);cfg.plans[state.adminPlan][t.dataset.dashboardPlanField]=value;if(state.adminPlan==='rookie')cfg.plans.trial=clone(cfg.plans.rookie);renderAllUiContent();rerenderAdmin();return;}
      if(t.id==='adminUserPlan'){setAdminPlanDefaults(t.value);return;}
      if(t.id==='adminUserStatus'){const expiry=$('adminUserExpires');if(expiry){expiry.disabled=t.value==='lifetime';if(t.value==='lifetime')expiry.value='';}return;}
      if(t.dataset.adminAccess){const item=elements()?.[state.selectedElement];if(item){item.access=item.access||{};item.access[t.dataset.adminAccess]=t.value;if(t.dataset.adminAccess==='rookie')item.access.trial=t.value;rerenderAdmin();}return;}
      if(t.dataset.adminContent){updateSelectedContent(t.dataset.adminContent,t);rerenderAdmin();return;}
      if(t.dataset.adminWatermark){updateSelectedWatermark(t.dataset.adminWatermark,t);rerenderAdmin();return;}
      const advertiserCard=t.closest('[data-advertiser-id]');if(advertiserCard&&t.dataset.advertiserField){const advertiser=state.ui?.advertisers?.[advertiserCard.dataset.advertiserId];if(advertiser){advertiser[t.dataset.advertiserField]=t.value;rerenderAdmin();}return;}
      if(t.dataset.campaignField&&state.adminCampaignId){const campaign=state.ui?.campaigns?.[state.adminCampaignId];if(campaign){campaign[t.dataset.campaignField]=t.type==='checkbox'?t.checked:t.value;renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.campaignImage&&state.adminCampaignId){const campaign=state.ui?.campaigns?.[state.adminCampaignId];if(campaign){campaign.images=campaign.images&&typeof campaign.images==='object'?campaign.images:{};campaign.images[String(t.dataset.campaignImage)]=t.value;renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.rssField){state.ui.rss=state.ui.rss||{};let value=t.type==='checkbox'?t.checked:t.value;if(['refresh_minutes','max_age_hours','max_items'].includes(t.dataset.rssField))value=Number(value);state.ui.rss[t.dataset.rssField]=value;rerenderAdmin();return;}
      const sourceCard=t.closest('[data-rss-source]');if(sourceCard&&t.dataset.rssSourceField){const source=state.ui?.rss?.sources?.[Number(sourceCard.dataset.rssSource)];if(source){let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.rssSourceField==='priority')value=Number(value);source[t.dataset.rssSourceField]=value;rerenderAdmin();}return;}
      const card=t.closest('[data-plan-card]');if(card&&t.dataset.planField){const plan=state.ui.plans?.[card.dataset.planCard];if(plan){let value=t.type==='checkbox'?t.checked:t.value;if(['duration_days','order'].includes(t.dataset.planField))value=value===''?null:Number(value);plan[t.dataset.planField]=value;if(t.dataset.planField==='lifetime'&&value)plan.duration_days=null;rerenderAdmin();}return;}
    };
    const search=$('adminUserSearch');if(search)search.oninput=()=>{const q=search.value.trim().toLowerCase();host.querySelectorAll('.admin-user-row').forEach(row=>{row.hidden=q&&!String(row.dataset.search||'').includes(q);});};
    const form=$('adminUserForm');if(form)form.onsubmit=async event=>{event.preventDefault();const user=state.adminSelectedUser;if(!user)return;const message=$('adminUserMessage');message.textContent='Saving…';try{const rawExpiry=$('adminUserExpires').value,status=$('adminUserStatus').value;if(status==='trial')throw new Error('Choose ACTIVE, EXPIRED or SUSPENDED before saving an automatic trial.');const payload={role:$('adminUserRole').disabled?'admin':$('adminUserRole').value,plan:$('adminUserPlan').value,status,expires_at:rawExpiry?new Date(rawExpiry).toISOString():null,payment_reference:$('adminPaymentReference').value.trim()};const updated=await BlinqAuth.adminUpdateAccess(user.id,payload);state.adminUsers=(state.adminUsers||[]).map(row=>row.id===updated.id?updated:row);state.adminSelectedUser=updated;message.textContent='Applied.';setTimeout(()=>rerenderAdmin(),450);}catch(error){message.textContent=error.message;}};
  }
  function planAvatarHtml(id,p={}){
    const style=String(p.avatar||id||'').toLowerCase(),src=safeUiAsset(p.marketing_avatar||'')||marketingAvatarUrl(style);
    const glyph={rookie:'○',pro:'◇',elite:'✦',goat:'♛',legend:'♛'}[style]||'◇';
    return `<span class="plan-card-avatar plan-${escapeHtml(style)}${src?' has-photo':''}" aria-label="${escapeHtml((p.label||id).toUpperCase())} avatar">${src?`<img src="${escapeHtml(src)}" alt="" loading="lazy">`:`<b aria-hidden="true">${glyph}</b>`}<em>${escapeHtml(String(p.label||id).replace(/^BlinQ\s+/i,'').slice(0,8))}</em></span>`;
  }
  function renderPlanCardsForAccount(){
    const current=accountPlan();
    const plans=Object.entries(state.ui?.plans||{}).filter(([id,p])=>!['trial','expired'].includes(id)&&p.enabled!==false).sort((a,b)=>Number(a[1]?.order||99)-Number(b[1]?.order||99));
    return `<div class="account-plan-grid">${plans.map(([id,p])=>{const url=String(p.url||'').trim(),active=current===id,restricted=Boolean(p.invite_only||p.verified_only),title=active?'Current plan':(p.card_title||p.description||'BlinQ membership');let action='';if(active)action='<span class="membership-current">CURRENT PLAN</span>';else if(restricted)action=`<button class="btn btn-ghost membership-cta invite-only" type="button" disabled>${escapeHtml(p.cta_label||'Invite / Verified only')}</button>`;else if(url)action=`<a class="btn btn-primary membership-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Open plan')} →</a>`;else action=`<button class="btn btn-ghost membership-cta" type="button" disabled>${escapeHtml(p.cta_fallback_label||'Coming soon')}</button>`;return `<article class="membership-card plan-${escapeHtml(id)}${active?' current-plan':''}${restricted?' restricted-plan':''}">${planAvatarHtml(id,p)}<div class="membership-card-copy"><small>${escapeHtml(p.label||id.toUpperCase())}</small><strong>${escapeHtml(title)}</strong><p>${escapeHtml(p.description||p.note||'')}</p></div>${restricted?'<span class="membership-badge">VERIFIED</span>':''}${action}</article>`}).join('')}</div>`;
  }
  function primeTableRows(){ return rankedPredictions(); }
  function aceProjectionTable(rows){
    if(!rows.length)return '<div class="state-card">No Aces / Double Faults projections are available yet.</div>';
    const body=rows.map(row=>{const p1=row?.player1?.name||row?.player1_name||'Player 1',p2=row?.player2?.name||row?.player2_name||'Player 2',projection=Number(row?.projection),opponent=Number(row?.opponent_projection),gap=Number(row?.projection_gap),score=Number(row?.projection_confidence),samples=row?.projection_samples||{};return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(row?.market_type||String(row?.market||'').replaceAll('_',' '))}</td><td>${escapeHtml(row?.pick||row?.selection||'—')}</td><td>${Number.isFinite(projection)?projection.toFixed(1):'—'}</td><td>${Number.isFinite(opponent)?opponent.toFixed(1):'—'}</td><td>${Number.isFinite(gap)?`+${gap.toFixed(1)}`:'—'}</td><td>${Number.isFinite(score)?`${Math.round(score*100)}/100`:'—'}</td><td>${Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${samples.player1}/${samples.player2}`:'—'}</td></tr>`}).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Market</th><th>Projection pick</th><th>Proj.</th><th>Opp. proj.</th><th>Gap</th><th>Score</th><th>Data</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">Projection only. No bookmaker odds or ROI are inferred until a verified Aces/DF price source is available.</div>`;
  }
  function sgProjectionTable(rows){
    if(!rows.length)return '<div class="state-card">No Sets / Games projections are available yet.</div>';
    const body=rows.map(row=>{const p1=row?.player1?.name||row?.player1_name||'Player 1',p2=row?.player2?.name||row?.player2_name||'Player 2',projection=Number(row?.projection),reference=Number(row?.reference_projection??row?.baseline_projection),gap=Number(row?.projection_gap),score=Number(row?.projection_confidence),samples=row?.projection_samples||{},unit=String(row?.projection_unit||'');const projectionText=Number.isFinite(projection)?(unit==='probability'?pct(projection):`${projection.toFixed(1)} games`):'—';const referenceText=Number.isFinite(reference)?(unit==='probability'?pct(reference):`${reference.toFixed(1)} games`):'—';const gapText=Number.isFinite(gap)?(unit==='probability'?`${(gap*100).toFixed(1)} pp`:`${gap.toFixed(1)} games`):'—';return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(row?.market_type||String(row?.market||'').replaceAll('_',' '))}</td><td>${escapeHtml(row?.pick||row?.selection||'—')}</td><td>${escapeHtml(projectionText)}</td><td>${escapeHtml(referenceText)}</td><td>${escapeHtml(gapText)}</td><td>${Number.isFinite(score)?`${Math.round(score*100)}/100`:'—'}</td><td>${Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${samples.player1}/${samples.player2}`:'—'}</td></tr>`}).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Market</th><th>Projection pick</th><th>Projection</th><th>Baseline</th><th>Gap</th><th>Score</th><th>Data</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">Projection only. Structured historical set/game scores are used; bookmaker odds, edge and ROI stay blank until that market layer is separately calibrated and validated.</div>`;
  }
  function genericTable(rows,key){
    if(key==='ace'&&rows.some(row=>row?.price_status==='projection_only'))return aceProjectionTable(rows);
    if(key==='sg'&&rows.some(row=>row?.price_status==='projection_only'))return sgProjectionTable(rows);
    if(!rows.length)return '<div class="state-card">No published data are available for this section yet.</div>';
    if(key==='top_daily'){const body=rows.map(row=>{const p1=row?.p1||row?.player1?.name||row?.player1_name||'Player 1',p2=row?.p2||row?.player2?.name||row?.player2_name||'Player 2';const probability=marketProbability(row),depth=Number(row?.data_depth),q=row?.quality||{},s1=Number(q?.player1?.surface_matches),s2=Number(q?.player2?.surface_matches),m1=Number(q?.player1?.matches),m2=Number(q?.player2?.matches),odds=Number(row?.odds),pick=row?.pick||row?.selection||row?.prediction||'—';return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(pick)}</td><td>${probability==null?'—':pct(probability)}</td><td>${Number.isFinite(depth)?pct(depth):'—'}</td><td>${Number.isFinite(s1)&&Number.isFinite(s2)?`${s1}/${s2}`:'—'}</td><td>${Number.isFinite(m1)&&Number.isFinite(m2)?`${m1}/${m2}`:'—'}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td></tr>`}).join('');return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Pick</th><th>Probability</th><th>Data depth</th><th>Surface sample</th><th>Overall sample</th><th>Odds</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">Top Bets are confidence-first. Elo, surface Elo, H2H and form are already represented inside model probability; edge/EV do not determine this ranking.</div>`;}
    const body=rows.map(row=>{
      const p1=row?.p1||row?.player1?.name||row?.player1_name||'Player 1',p2=row?.p2||row?.player2?.name||row?.player2_name||'Player 2';
      const rawProb=row?.probability!=null?Number(row.probability):marketProbability(row); const probability=Number.isFinite(rawProb)?(rawProb>1?rawProb/100:rawProb):null; const pick=row?.pick||row?.selection||row?.prediction||'—';
      const odds=Number(row?.odds),edge=Number(row?.edge),ev=Number(row?.expected_value);
      return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(pick)}</td><td>${probability==null?'—':pct(probability)}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td><td>${Number.isFinite(edge)?`${edge>0?'+':''}${(edge*(Math.abs(edge)<=1?100:1)).toFixed(1)} pp`:'—'}</td><td>${Number.isFinite(ev)?`${ev>0?'+':''}${(ev*(Math.abs(ev)<=1?100:1)).toFixed(1)}%`:'—'}</td></tr>`;
    }).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Pick</th><th>Probability</th><th>Odds</th><th>Model Edge</th><th>EV</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }
  function renderDashboardResultsPreview(){
    const host=$('resultsPreviewContent');if(!host)return;
    const rows=(state.feed?.results||[]).filter(row=>typeof row?.result?.correct==='boolean');
    const wins=rows.filter(row=>row.result.correct===true).length,losses=Math.max(0,rows.length-wins),hit=rows.length?wins/rows.length:null;
    const perf=state.feed?.betting_performance?.overall||state.feed?.performance?.betting?.overall||{};
    const roi=Number(perf.roi),units=Number(perf.profit_units);
    host.innerHTML=`<div class="results-preview-metrics"><span><small>Record</small><strong>${wins}-${losses}</strong></span><span><small>Hit rate</small><strong>${hit==null?'—':pct(hit)}</strong></span><span><small>ROI</small><strong>${Number.isFinite(roi)?pct(roi):'—'}</strong></span><span><small>Units</small><strong>${Number.isFinite(units)?`${units>=0?'+':''}${units.toFixed(2)}u`:'—'}</strong></span></div>`;
    const count=$('resultsPreviewCount');if(count)count.textContent=`${rows.length} settled`;const cardCount=$('resultsSeeAllCardCount');if(cardCount)cardCount.textContent=`${rows.length} settled`;
  }

  function resultsSummary(){
    const rows=filteredResults(),category=state.resultsFilters?.category||'all',m=localResultMetrics(rows,category);
    return metricCards([['Record',`${m.wins}-${m.losses}`,'wins - losses'],['Hit Rate',m.hit==null?'—':pct(m.hit),'filtered settled sample'],['Avg Odds',m.avgOdds==null?'—':m.avgOdds.toFixed(2),m.oddsSample?`${m.oddsSample} odds-backed picks`:'no issued odds'],['ROI',m.roi==null?'—':pct(m.roi),'flat 1u on issued odds'],['Units',m.oddsSample?`${m.profit>=0?'+':''}${m.profit.toFixed(2)}u`:'—','profit · flat 1u stake'],['Sample',String(m.sample),'settled published rows']]);
  }

  function renderRoute(route){
    const host=$('routePanel'),feed=state.feed,p=feed.performance||{},history=feed.history||{},report=feed.model?.report||{}; let body='';
    if(route==='admin'){host.innerHTML=renderAdminRoute();wireAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='analytics')loadBannerAnalytics();return;}
    if(route==='prime'){const r=state.ui?.market_rules?.prime||{};body=`<div class="route-sub route-rules"><strong>Prime rule</strong><span>Accuracy first · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · depth ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · surface ${Number(r.min_surface_matches||5)}+/player · preferred odds ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)}, no hard odds band · reject materially negative EV.</span></div>${genericTable(primeTableRows(),'prime')}`;}
    else if(route==='top_daily'){const r=state.ui?.market_rules?.top_daily||{};const day=state.feed?.market_selection?.odds_report?.betting_day||'current';body=`<div class="route-sub route-rules"><strong>Top Bets rule</strong><span>BlinQ betting day ${escapeHtml(day)} · adaptive confidence cascade 80% → 78% → 76% → 74% → 72% → 70% → 68% until at least ${Number(r.target_count||10)} remaining picks qualify · the full qualifying tier stays published · depth ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · surface ${Number(r.min_surface_matches||5)}+/player · odds sanity floor ${Number(r.min_odds||1.20).toFixed(2)} · ranked probability → depth → surface sample → overall sample → odds. Edge/EV are diagnostic only.</span></div>${genericTable(marketRows('top_daily'),'top_daily')}`;}
    else if(route==='value'){const r=state.ui?.market_rules?.value||{};body=`<div class="route-sub route-rules"><strong>Value rule</strong><span>EV first · model ${Math.round(Number(r.min_probability||.55)*100)}%+ · odds ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+.</span></div>${genericTable(marketRows('value'),'value')}`;}
    else if(route==='ace'){body=`<div class="route-sub route-rules"><strong>Aces / Double Faults</strong><span>Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time count projections from stored event statistics. Projection score is not a calibrated win probability; odds/ROI stay blank until a verified price source exists.</span></div>${genericTable(marketRows('ace'),'ace')}`;}
    else if(route==='sg'){body=`<div class="route-sub route-rules"><strong>Sets / Games</strong><span>Point-in-time projections from structured historical set/game scores. Sets use long-match probability; Games use projected total versus the ATP/WTA best-of baseline. No odds/ROI are inferred yet.</span></div>${genericTable(marketRows('sg'),'sg')}`;}
    else if(route==='doubles'){body=`<div class="route-sub route-rules"><strong>Doubles model</strong><span>Separate pair/team model only. Pair identity, pair history, individual strength, surface form and pair chemistry stay isolated from singles probabilities.</span></div>${genericTable(marketRows('doubles'),'doubles')}`;}
    else if(route==='results'){body=renderResultsFilters()+resultsSummary()+`<div class="route-sub results-section-head"><div><h3>Settled predictions</h3><p>Only successfully published pre-match records are graded. ROI uses the odds snapshot that was actually published and a flat 1u stake.</p></div>${renderResults()}</div>`;}
    else if(route==='tournaments'){const names=[...new Set((feed.upcoming||[]).map(x=>x.tournament).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):'No upcoming tournament coverage is currently published.'}</div>`;}
    else if(route==='players'){const names=[...new Set((feed.upcoming||[]).flatMap(x=>[x.player1?.name,x.player2?.name]).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):'No upcoming players are currently published.'}</div>`;}
    else if(route==='stats'){body=metricCards([['Settled predictions',String(p.n??0),'Published and scored'],['Accuracy',p.accuracy!=null?pct(p.accuracy):'—','Observed results'],['Log loss',number(p.log_loss),'Lower is better'],['Brier score',number(p.brier_score),'Probability quality']])+`<div class="route-sub"><h3>Results</h3>${renderResults()}</div>`;}
    else if(route==='model'||route==='backtests'){const h=report.holdout||{},delta=report.delta_vs_elo||{};body=metricCards([['Model',String(feed.model?.version||'—'),'Production artifact'],['Holdout n',String(h.n??'—'),'Chronological holdout'],['Holdout accuracy',h.accuracy!=null?pct(h.accuracy):'—','Evaluation report'],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—','Negative is better']])+`<div class="route-sub static-copy"><h3>Data window</h3><p>${escapeHtml(history.start?fmtDate(history.start):'—')} → ${escapeHtml(history.end?fmtDate(history.end):'—')} · ${escapeHtml(String(history.matches??'—'))} historical matches in the current serving metadata.</p><p>No result here is presented as a guarantee. Holdout metrics describe a specific historical evaluation period.</p></div>`;}
    else if(route==='account'){body=`<section class="account-membership-page"><div class="account-membership-heading"><small>BLINQ MEMBERSHIP</small><h2>Available plans</h2></div>${renderPlanCardsForAccount()}</section>`;}
    else {const copy={how_blinq_works:'BlinQ processes point-in-time tennis history, builds model features without using future results, publishes pre-match probabilities, and later evaluates those same published records against real outcomes.',methodology:'The core rules are chronological evaluation, immutable first-published probabilities, explicit missing-data handling, and honest probability metrics. A prediction is informative only when it existed before the match.',model_data:`Current serving metadata reports ${history.matches??'—'} historical matches. The web application reads only the authenticated published serving feed; it does not fabricate missing tennis data.`,faq:'Probabilities are not certainties. Confidence is derived from the model probability, and performance should always be read together with sample size and coverage.',responsible_use:'Use BlinQ as analytical information. Do not treat any probability as a guaranteed outcome, and do not infer certainty from a high-confidence label.'};body=`<div class="static-copy"><p>${escapeHtml(copy[route]||'This section is available in the BlinQ workspace.')}</p></div>`;}
    host.innerHTML=`<div class="route-card route-card-clean">${body}</div>`; if(route==='results')wireResultsFilters(); applyAccessStates(host);
  }

  function showUpgradePrompt(planId='pro',sectionLabel='this content'){
    const dialog=$('upgradeDialog'),host=$('upgradeDialogContent');if(!dialog||!host)return;
    const plan=state.ui?.plans?.[planId]||state.ui?.plans?.pro||{},url=String(plan.url||'').trim();
    host.innerHTML=`<div class="upgrade-dialog-eyebrow">UNLOCK MORE WITH BLINQ</div><div class="upgrade-dialog-plan">${planAvatarHtml(planId,plan)}<div><h2 id="upgradeDialogTitle">Unlock ${escapeHtml(sectionLabel)}</h2><p>${escapeHtml(plan.description||plan.note||`Available with ${upgradePlanLabel(planId)}.`)}</p></div></div><div class="upgrade-dialog-benefits"><span>More published picks</span><span>Full card details</span><span>See all access</span></div>${url?`<a class="btn btn-primary upgrade-dialog-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">Upgrade to ${escapeHtml(String(plan.label||planId).replace(/^BlinQ\s+/i,''))} →</a>`:`<button class="btn btn-primary upgrade-dialog-cta" type="button" data-route="account">View membership options →</button>`}`;
    if(!dialog.open)dialog.showModal();
  }
  async function signOutCurrentSession(){await BlinqAuth.signOut();state.feed={upcoming:[],results:[],performance:{},history:{},model:null};auth('login');}
  function closeProfileMenu(){const menu=$('profileMenu'),toggle=$('profileMenuToggle');if(menu)menu.hidden=true;if(toggle)toggle.setAttribute('aria-expanded','false');}

  async function loadFeed(showLoading=true){
    if(showLoading&&state.route==='predictions') $('predictionGrid').innerHTML='<div class="state-card">Loading current model predictions…</div>';
    try{
      const feed=await BlinqAuth.feed(); state.feed=feed||{}; state.feed.upcoming=Array.isArray(feed?.upcoming)?feed.upcoming:[]; state.feed.results=Array.isArray(feed?.results)?feed.results:[];
      await loadNewsPool(); loadAdminDraft(); renderAllUiContent(); populateFilters();
      const a=feed.account||{};
      $('profileName').textContent=a.name||a.email||'BlinQ User';
      const resolvedPlan=accountPlan();
      const planLabel=a.plan_label||state.ui?.plans?.[resolvedPlan]?.label||a.plan||'Member';
      $('profilePlan').textContent=planLabel;
      const planIcon={admin:'♛',rookie:'○',pro:'◇',elite:'✦',goat:'♛',legend:'♛',expired:'○'}[resolvedPlan]||'◇';
      const planIconHost=$('profilePlanIcon');if(planIconHost)planIconHost.textContent=planIcon;
      const member=$('memberStatus');
      if(member){
        const status=String(a.status||'active').toLowerCase();
        member.textContent=status==='trial'?`TRIAL · ${remainingLabel(a.expires_at)}`:status==='lifetime'?'LIFETIME':status.toUpperCase();
      }
      const profileButton=$('profileButton');if(profileButton)profileButton.dataset.plan=resolvedPlan;
      setAccountAvatar($('avatar'),a);
      const tooltipName=$('tooltipAccountName'),tooltipEmail=$('tooltipAccountEmail'),tooltipPlan=$('tooltipAccountPlan'),tooltipRemaining=$('tooltipAccountRemaining');
      if(tooltipName)tooltipName.textContent=a.name||a.email||'BlinQ User';
      if(tooltipEmail)tooltipEmail.textContent=a.email||'—';
      if(tooltipPlan)tooltipPlan.textContent=a.plan_label||state.ui?.plans?.[String(a.plan||'').toLowerCase()]?.label||a.plan||planLabel||'Member';
      if(tooltipRemaining){const status=String(a.status||'active').toLowerCase();tooltipRemaining.textContent=status==='lifetime'?'Lifetime':a.expires_at?remainingLabel(a.expires_at):(status==='active'?'Managed manually':status.toUpperCase());}
      $('updatedAt').textContent=feed.generated_at?fmtTime(feed.generated_at):'—'; $('todayLabel').textContent=fmtToday(); updateHeaderClock(); const footerModel=$('footerModelState'); if(footerModel)footerModel.textContent=feed?.model?.version?`Model ${feed.model.version}`:'Production feed'; const headerModel=$('headerModelState');if(headerModel)headerModel.textContent=feed?.model?.version?String(feed.model.version):'Production';
      $('staleNotice').hidden=!feed.stale; $('staleNotice').textContent=feed.stale?'Published data is older than 12 hours. Check prediction creation times before evaluating them.':''; $('appShell').hidden=false; if($('authDialog').open)$('authDialog').close();
      if(state.route==='admin'&&!isAdminAccount())state.route='predictions'; setRoute(state.route,false); applyAccessStates();
    }catch(error){if(error.status===401){BlinqAuth.clear();auth('login');return;}showStatus('Data could not be loaded. Try again shortly.');throw error;}
  }

  function updateHeaderClock(){const date=$('headerDate'),time=$('headerTime');if(date)date.textContent=fmtToday();if(time)time.textContent=fmtClock();}

  function showStatus(message){const n=$('statusBanner');n.textContent=message;n.hidden=!message;if(message)setTimeout(()=>{n.hidden=true},5000)}

  function setupEvents(){
    $('authDialog').addEventListener('cancel',e=>e.preventDefault()); $('authForm').addEventListener('submit',handleAuthSubmit); $('switchSignup').onclick=()=>auth(state.authMode==='login'?'signup':'login'); $('switchReset').onclick=()=>auth('reset');
    $('refreshButton').onclick=()=>loadFeed(); ['tourFilter','tournamentFilter','surfaceFilter','confidenceFilter'].forEach(id=>$(id).addEventListener('change',()=>{state.page=0;state.showAll=false;renderPredictions()})); $('searchInput').addEventListener('input',()=>{state.page=0;state.showAll=false;renderPredictions()});
    $('prevPick').onclick=()=>{state.page=Math.max(0,state.page-1);renderPredictions()}; $('nextPick').onclick=()=>{state.page+=1;renderPredictions()}; $('dialogClose').onclick=()=>$('matchDialog').close(); $('matchDialog').addEventListener('click',e=>{if(e.target===$('matchDialog'))$('matchDialog').close()}); $('profileButton').onclick=()=>{closeProfileMenu();setRoute('account')};
    $('profileMenuToggle').onclick=e=>{e.stopPropagation();const menu=$('profileMenu'),toggle=$('profileMenuToggle'),open=menu.hidden;menu.hidden=!open;toggle.setAttribute('aria-expanded',open?'true':'false');};
    $('headerLogoutButton').onclick=signOutCurrentSession;$('upgradeDialogClose').onclick=()=>$('upgradeDialog').close();$('upgradeDialog').addEventListener('click',e=>{if(e.target===$('upgradeDialog'))$('upgradeDialog').close()});
    document.addEventListener('click',e=>{
      if(!e.target.closest('#profileShell'))closeProfileMenu();
      const dashboardToggle=e.target.closest('[data-dashboard-toggle]');if(dashboardToggle&&state.route==='predictions'){e.preventDefault();toggleDashboardSection(dashboardToggle.dataset.dashboardToggle);return;}
      const upgradeTarget=e.target.closest('[data-upgrade-plan]');if(upgradeTarget&&state.route!=='admin'){e.preventDefault();e.stopPropagation();showUpgradePrompt(upgradeTarget.dataset.upgradePlan||'pro',upgradeTarget.dataset.upgradeSection||'this content');return;}
      const restricted=e.target.closest('[data-ui-element].ui-state-locked,[data-ui-element].ui-state-blurred,[data-ui-element].ui-state-hidden');
      if(restricted&&state.route!=='admin'){e.preventDefault();e.stopPropagation();const plan=firstUnlockPlan(dashboardSectionKeyForSidebarElement(restricted.dataset.uiElement)||'top_daily',0,true);showUpgradePrompt(plan,restricted.querySelector('span:nth-child(2)')?.textContent||'this content');return;}
      const banner=e.target.closest('[data-banner-slot]');if(banner)trackBanner(banner,'click');
      const prev=e.target.closest('[data-market-prev]');if(prev){const key=prev.dataset.marketPrev;state.marketPage[key]=Math.max(0,Number(state.marketPage[key]||0)-1);renderMarketSections();return;}
      const next=e.target.closest('[data-market-next]');if(next){const key=next.dataset.marketNext;state.marketPage[key]=Number(state.marketPage[key]||0)+1;renderMarketSections();return;}
      const target=e.target.closest('[data-route]');if(!target)return;const route=target.dataset.route;if(!routeMeta[route])return;e.preventDefault();setRoute(route);
    });
    let resizeTimer; window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.route==='predictions'){state.page=0;Object.keys(state.marketPage||{}).forEach(k=>{state.marketPage[k]=0;});renderPredictions();renderMarketSections();renderDashboardComposition();}},120)});
  }

  async function boot(){ setupEvents(); updateHeaderClock(); setInterval(updateHeaderClock,30000); await loadUiConfig(); const hash=location.hash.replace(/^#/,''); if(routeMeta[hash])state.route=hash; try{const cfg=await BlinqAuth.init();state.authEnabled=Boolean(cfg.enabled);if(cfg.recovery){auth('recovery');return;}const session=await BlinqAuth.restore();if(session)await loadFeed();else auth('login');}catch(error){showStatus(error.message);auth('login');} }
  boot();
})();
