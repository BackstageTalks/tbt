(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = { feed: {upcoming:[],results:[],performance:{},history:{},model:null}, ui:null, uiSource:null, route:'predictions', page:0, showAll:false, authMode:'login', authEnabled:false, draftLoaded:false, selectedElement:'HEADER_BANNER_1', adminPlan:'rookie', adminTab:'layout', adminUsers:null, adminUsersLoading:false, adminSelectedUser:null, previewPlan:null, newsPool:[], bannerObserver:null, bannerTimers:new WeakMap(), adminAnalytics:null, adminAnalyticsLoading:false, runtimeConfigLoaded:false, adminCampaignId:null, adminAdvertiserId:null };
  const pageSize = () => innerWidth >= 1700 ? 6 : innerWidth >= 1450 ? 5 : innerWidth >= 1200 ? 4 : innerWidth >= 900 ? 3 : 1;
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const pct = value => `${(Number(value || 0) * (Number(value || 0) <= 1 ? 100 : 1)).toFixed(1)}%`;
  const number = (value, digits=3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const fmtTime = value => value ? new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : 'TBA';
  const fmtDate = value => value ? new Intl.DateTimeFormat(undefined,{day:'2-digit',month:'short',year:'numeric'}).format(new Date(value)) : '—';
  const fmtToday = () => new Intl.DateTimeFormat(undefined,{weekday:'long',day:'2-digit',month:'short',year:'numeric'}).format(new Date());
  const initials = name => String(name || 'B').trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase();
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
      if(runtime?.configured && runtime?.config?.schema===2){ state.ui=mergeConfig(state.uiSource,runtime.config); state.runtimeConfigLoaded=true; }
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
      const a=document.createElement('a'); a.href=item.href||`#${item.id}`; a.dataset.route=item.id||'';
      if(item.element_id) a.dataset.uiElement=item.element_id;
      a.className=`nav-link${state.route===item.id?' active':''}`;
      a.innerHTML=`<span class="nav-icon">${escapeHtml(item.icon||'•')}</span><span>${escapeHtml(item.label||item.id)}</span>`;
      host.appendChild(a);
    });
  }

  function renderNavigation(){
    const main=elementList('navigation').map(item=>({
      id:item.content?.route||'', href:`#${item.content?.route||''}`, icon:item.content?.icon||'•',
      label:item.content?.label||item.label||item.id, order:item.order, enabled:true, element_id:item.id,
    })).filter(item=>item.id);
    if(isAdminAccount()) main.push({id:'admin',href:'#admin',icon:'⚙',label:'Admin',order:90,enabled:true});
    renderNavigationGroup(main,'mainNavigation');
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
    return wm.enabled?`<span class="slot-watermark">${escapeHtml(wm.text||'COMING SOON')}</span>`:'';
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
    return clone(state.ui?.ad_fallbacks?.internal||{eyebrow:'BLINQ',headline:'Ad-free workspace',text:'BlinQ tennis content.',button_text:'Explore',link:'#predictions',route:'predictions',theme:'blue'});
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
    const useImage=(preference==='image'||preference==='auto')&&images.length;
    if(useImage){
      const src=String(images[index%images.length]||'');
      return {...internalFallbackContent(),type:'image',image_url:src,campaign_id:`fallback-image-${index+1}`,advertiser_id:'blinq',span:original.span||1};
    }
    return {...internalFallbackContent(),type:'internal',campaign_id:'blinq-adfree-fallback',advertiser_id:'blinq',span:original.span||1};
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
    if(state.feed?.account?.hide_ads&&ad)return fallbackContent({...item,content},index);
    return content;
  }
  const rowPresetMap={
    '1+1+1+1':[[0,1],[1,1],[2,1],[3,1]],
    '2+2':[[0,2],[2,2]],
    '2+1+1':[[0,2],[2,1],[3,1]],
    '1+1+2':[[0,1],[1,1],[2,2]],
    '4':[[0,4]],
  };
  function rowPreset(zone){
    const preset=String(state.ui?.content_rows?.[zone]?.preset||'1+1+1+1');
    return rowPresetMap[preset]?preset:'1+1+1+1';
  }
  function rowItems(zone){
    const all=elementList('large_banner',zone);
    const slots=[0,1,2,3].map(index=>all.find(item=>Number(item.order||0)%10===index+1)||all[index]).filter(Boolean);
    return rowPresetMap[rowPreset(zone)].map(([start,span])=>({item:slots[start],span,start})).filter(entry=>entry.item);
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
    const src=safeLink(raw,'');
    return src&&!src.startsWith('#')?`<img class="promo-image" src="${escapeHtml(src)}" alt="" loading="lazy">`:'<div class="promo-art" aria-hidden="true"></div>';
  }
  function headerSlotHtml(item,index=0){
    const c=resolvedBannerContent(item,index),route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#predictions'),external=isExternalLink(href);
    return `<a href="${escapeHtml(href)}" ${external?'target="_blank" rel="noopener"':''} ${route&&!external?`data-route="${escapeHtml(route)}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)} class="header-slot theme-${escapeHtml(c.theme||'blue')}"><small>${escapeHtml(c.eyebrow||item.label)}</small><strong>${escapeHtml(c.headline||'')}</strong><span>${escapeHtml(c.text||'')}</span>${watermarkHtml(item)}</a>`;
  }
  function renderHeaderSlots(){
    const host=$('headerFeatureStrip'); if(!host)return;
    host.innerHTML=elementList('header_slot','header').map((item,index)=>headerSlotHtml(item,index)).join('');
    installBannerTracking(host);
  }
  function bannerHtml(item, sidebar=false, index=0, spanOverride=null){
    const c=resolvedBannerContent(item,index),route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#account'),external=isExternalLink(href); const theme=String(c.theme||'violet').replace(/[^a-z0-9_-]/gi,'');
    const sponsored=c.sponsored?'<span class="sponsored-label">SPONSORED</span>':'';
    const attrs=`${route&&!external?`data-route="${escapeHtml(route)}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)}`;
    const target=external?'target="_blank" rel="noopener"':'';
    if(sidebar){
      return `<a class="sidebar-promo theme-${theme}" href="${escapeHtml(href)}" ${target} ${attrs}>${sponsored}<small>${escapeHtml(c.eyebrow||'BLINQ')}</small><strong>${escapeHtml(c.headline||'')}</strong><span>${escapeHtml(c.text||'')}</span><b>${escapeHtml(c.button_text||'Open')}</b>${watermarkHtml(item)}</a>`;
    }
    const span=Math.max(1,Math.min(4,Number(spanOverride||c.span)||1));
    const fullCreative=c.creative_mode==='full'||(c.type==='advertisement'&&c.show_copy===false);
    const showCopy=c.show_copy!==false;
    return `<a class="promo-banner promo-card theme-${theme} span-${span}${fullCreative?' creative-full':''}${showCopy?'':' no-copy'}" href="${escapeHtml(href)}" ${target} ${attrs}>${sponsored}${bannerImageHtml(c,span)}${showCopy?`<div class="promo-copy"><span class="promo-eyebrow">${escapeHtml(c.eyebrow||'BLINQ')}</span><strong>${escapeHtml(c.headline||'')}</strong><p>${escapeHtml(c.text||'')}</p><span class="promo-cta">${escapeHtml(c.button_text||'Open')}</span></div>`:''}${watermarkHtml(item)}</a>`;
  }
  function renderBanners(){
    const top=$('bannerTop'),bottom=$('bannerBottom');
    if(top){const rows=rowItems('content_top');top.dataset.layout=rowPreset('content_top');top.hidden=!rows.length;top.innerHTML=rows.map((entry,index)=>bannerHtml(entry.item,false,index,entry.span)).join('');installBannerTracking(top);}
    if(bottom){const rows=rowItems('content_bottom');bottom.dataset.layout=rowPreset('content_bottom');bottom.hidden=!rows.length;bottom.innerHTML=rows.map((entry,index)=>bannerHtml(entry.item,false,index+4,entry.span)).join('');installBannerTracking(bottom);}
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
    const needed=Boolean(state.ui?.ad_fallbacks?.rss_enabled!==false&&(state.feed?.account?.hide_ads||rssSlots));
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
  function renderAllUiContent(){ if(state.bannerObserver){state.bannerObserver.disconnect();state.bannerObserver=null;}state.bannerTimers=new WeakMap();renderNavigation(); renderHeaderSlots(); renderBanners(); renderSidebarPromos(); applyAccessStates(); }

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
    const p1=Number(row?.player1?.probability||0), p2=Number(row?.player2?.probability||0);
    const winnerId=String(row?.winner_id || (p1>=p2?row?.player1?.id:row?.player2?.id) || '');
    const winner=winnerId===String(row?.player1?.id)?row?.player1:row?.player2;
    const probability=Math.max(p1,p2);
    return {id:row?.event_id||row?.id,date:row?.scheduled_at,tour:String(row?.tour||'').toUpperCase(),tournament:row?.tournament||'Tournament',surface:row?.surface||'unknown',round:row?.round||'',p1:row?.player1?.name||'Player 1',p2:row?.player2?.name||'Player 2',p1Id:row?.player1?.id,p2Id:row?.player2?.id,p1Prob:p1,p2Prob:p2,pick:winner?.name||'—',pickId:winnerId,probability,confidence:confidenceBand(probability),signals:Array.isArray(row?.signals)?row.signals:[],model:row?.model_version||state.feed?.model?.version||'',raw:row};
  }

  function populateSelect(id,values,label){ const select=$(id),selected=select.value; select.innerHTML=`<option value="">${label}</option>`; [...values].filter(Boolean).sort().forEach(value=>{const opt=document.createElement('option');opt.value=value;opt.textContent=String(value).replaceAll('_',' ');select.appendChild(opt)}); if([...select.options].some(o=>o.value===selected)) select.value=selected; }
  function populateFilters(){ const rows=(state.feed.upcoming||[]).map(normalize); populateSelect('tournamentFilter',new Set(rows.map(x=>x.tournament)),'All Tournaments'); populateSelect('surfaceFilter',new Set(rows.map(x=>x.surface)),'All Surfaces'); }
  function compactCount(value){ const n=Number(value); if(!Number.isFinite(n)) return '—'; if(n>=1000000) return `${(n/1000000).toFixed(n>=10000000?0:1)}M`; if(n>=1000) return `${(n/1000).toFixed(n>=100000?0:1)}K`; return String(Math.round(n)); }
  function renderSnapshot(){
    const host=$('dashboardSnapshot'); if(!host) return;
    const rows=(state.feed.upcoming||[]).map(normalize);
    const top=rows.length?Math.max(...rows.map(x=>Number(x.probability)||0)):null;
    const elite=rows.filter(x=>x.probability>=.80).length;
    const high=rows.filter(x=>x.probability>=.70).length;
    const tournaments=new Set(rows.map(x=>x.tournament).filter(Boolean)).size;
    const history=state.feed?.history?.matches;
    const cards=[
      ['UPCOMING',String(rows.length),'current board'],
      ['TOP PROBABILITY',top!=null?pct(top):'—','highest current pick'],
      ['≥ 80%',String(elite),'elite confidence'],
      ['HIGH CONFIDENCE',String(high),'70%+ candidates'],
      ['TOURNAMENTS',String(tournaments),'active in feed'],
      ['HISTORY DEPTH',compactCount(history),'serving metadata']
    ];
    host.innerHTML=cards.map(([label,value,note])=>`<div class="snapshot-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></div>`).join('');
  }
  function rankedPredictions(){
    return (state.feed.upcoming||[]).map(normalize).sort((a,b)=>b.probability-a.probability || new Date(a.date)-new Date(b.date)).map((m,index)=>({...m,accessIndex:index}));
  }
  function filtered(){ const rows=rankedPredictions(),tour=$('tourFilter').value,tournament=$('tournamentFilter').value,surface=$('surfaceFilter').value,confidence=$('confidenceFilter').value,q=$('searchInput').value.trim().toLowerCase(); return rows.filter(m=>{ if(tour&&m.tour!==tour)return false;if(tournament&&m.tournament!==tournament)return false;if(surface&&m.surface!==surface)return false;if(confidence&&m.confidence!==confidence)return false;if(q&&!`${m.p1} ${m.p2} ${m.tournament}`.toLowerCase().includes(q))return false;return true; }); }

  function signalMeta(signal,m){ const id=String(signal?.player_id ?? signal?.favours_player_id ?? ''); const favours=id===String(m.pickId); const label=signal?.label||signal?.factor||'Model signal'; return {label,favours}; }
  function renderSignal(signal,m){ const s=signalMeta(signal,m); return `<div class="signal-row"><span>${escapeHtml(s.label)}</span><div class="signal-meter"><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i></i><i></i></div></div>`; }
  function renderCard(m, slotIndex=0){ const template=$('predictionTemplate').content.cloneNode(true),card=template.querySelector('.prediction-card'); card.dataset.id=m.id; card.dataset.uiElement=slotIndex<8?`TOP_PICK_${slotIndex+1}`:'TOP_PICK_MORE'; card.classList.add('featured'); card.querySelector('.tour').textContent=`${m.tour} ${m.tournament}${m.round?` · ${m.round}`:''}`; card.querySelector('.time').textContent=fmtTime(m.date); card.querySelector('.surface').textContent=String(m.surface).replaceAll('_',' ').toUpperCase(); const players=[['.player-a',m.p1,m.p1Prob],['.player-b',m.p2,m.p2Prob]]; players.forEach(([sel,name,prob])=>{const box=card.querySelector(sel);box.querySelector('.player-avatar').textContent=initials(name);box.querySelector('.player-name').textContent=name;box.querySelector('.player-rank').textContent=pct(prob)}); card.querySelector('.pick-name').textContent=m.pick; card.querySelector('.probability').textContent=pct(m.probability); const conf=card.querySelector('.confidence'); conf.textContent=m.confidence==='very-high'?'VERY HIGH':m.confidence.toUpperCase(); conf.classList.add(m.confidence); const signals=card.querySelector('.signals'); signals.innerHTML=m.signals.length?m.signals.slice(0,4).map(s=>renderSignal(s,m)).join(''):'<div class="signal-empty">No strong secondary signal is available.</div>'; card.querySelector('.analysis-link').onclick=()=>openMatch(m); return template; }

  function renderDots(pageCount){ const host=$('carouselDots'); host.innerHTML=''; if(state.showAll||pageCount<=1)return; for(let i=0;i<pageCount;i++){const b=document.createElement('button');b.type='button';b.className=i===state.page?'active':'';b.setAttribute('aria-label',`Show picks page ${i+1}`);b.onclick=()=>{state.page=i;renderPredictions()};host.appendChild(b)} }
  function renderPredictions(){ const rows=filtered(),grid=$('predictionGrid'),size=pageSize(); $('matchCount').textContent=rows.length; const pageCount=Math.max(1,Math.ceil(rows.length/size)); state.page=Math.min(state.page,pageCount-1); const start=state.showAll?0:state.page*size; let visible=state.showAll?rows:rows.slice(start,start+size); grid.classList.toggle('show-all',state.showAll); grid.innerHTML=''; if(!visible.length){grid.innerHTML='<div class="state-card">No upcoming published predictions match the current filters.</div>';} else visible.forEach((m,index)=>grid.appendChild(renderCard(m,Number.isInteger(m.accessIndex)?m.accessIndex:start+index))); $('prevPick').hidden=state.showAll||pageCount<=1; $('nextPick').hidden=state.showAll||pageCount<=1; $('prevPick').disabled=state.page<=0; $('nextPick').disabled=state.page>=pageCount-1; $('viewAllButton').textContent=state.showAll?'Featured picks ←':'View all matches →'; renderDots(pageCount); applyAccessStates(grid); }

  function openMatch(m){ const signalRows=m.signals.length?m.signals.map(s=>{const meta=signalMeta(s,m);const favoursId=String(s?.player_id??s?.favours_player_id??'');const favours=favoursId===String(m.p1Id)?m.p1:favoursId===String(m.p2Id)?m.p2:'—';return `<div class="dialog-signal"><span>${escapeHtml(meta.label)}</span><strong>${escapeHtml(favours)}</strong><small>${meta.favours?'supports pick':'counter-signal'}</small></div>`}).join(''):'<p class="signal-empty">No secondary signals are available.</p>'; $('dialogContent').innerHTML=`<div class="dialog-eyebrow">${escapeHtml(m.tour)} · ${escapeHtml(m.tournament)}</div><h2>${escapeHtml(m.p1)} <span>vs</span> ${escapeHtml(m.p2)}</h2><div class="dialog-pick"><div><small>BlinQ Pick</small><strong>${escapeHtml(m.pick)}</strong></div><div class="dialog-prob">${pct(m.probability)} <span class="confidence ${m.confidence}">${m.confidence==='very-high'?'VERY HIGH':m.confidence.toUpperCase()}</span></div></div><div class="dialog-section"><h3>Model signals</h3>${signalRows}</div><div class="dialog-meta"><span>${escapeHtml(String(m.surface).replaceAll('_',' '))}</span><span>${fmtDate(m.date)} · ${fmtTime(m.date)}</span><span>Model ${escapeHtml(m.model||'—')}</span></div>`; $('matchDialog').showModal(); }

  const routeMeta={
    predictions:['TENNIS INTELLIGENCE','Dashboard','Recommended Prime Picks and current tennis intelligence from the published production feed.'],
    tournaments:['TOURNAMENT VIEW','Tournaments','Current tournament coverage derived from published upcoming matches.'],
    players:['PLAYER VIEW','Players','Current players appearing in the published prediction feed.'],
    stats:['PERFORMANCE','Stats & Insights','Observed model performance from settled published predictions.'],
    model:['MODEL TRANSPARENCY','Model Performance','Current production model metadata and evaluation report.'],
    backtests:['VALIDATION','Backtests','Out-of-time evaluation information published with the production model.'],
    account:['BLINQ MEMBERS','Account','Manage your profile and access.'],
    admin:['BLINQ CONTROL','Admin Control Center','Configure fixed page slots, plan presentation and manually assign account access.'],
    how_blinq_works:['LEARN','How BlinQ Works','How the BlinQ workflow turns point-in-time tennis data into probabilities.'],
    methodology:['LEARN','Methodology','The principles used to keep predictions point-in-time and auditable.'],
    model_data:['LEARN','Model & Data','What the published feed exposes about data and model state.'],
    faq:['LEARN','FAQ','Common questions about probabilities, results and model output.'],
    responsible_use:['LEARN','Responsible Use','Use probabilities as information, never as guarantees.']
  };

  function setRoute(route,push=true){ if(!routeMeta[route]) route='predictions'; if(route==='admin'&&!isAdminAccount()) route='predictions'; if(route==='admin') state.previewPlan=null; state.route=route; state.page=0; const meta=routeMeta[route]; $('pageEyebrow').textContent=meta[0]; $('pageTitle').textContent=meta[1]; $('pageSubtitle').textContent=meta[2]; $('predictionsView').hidden=route!=='predictions'; $('routePanel').hidden=route==='predictions'; renderNavigation(); if(route==='predictions'){renderPredictions();applyAccessStates();} else renderRoute(route); if(push) history.replaceState(null,'',`#${route}`); }

  function metricCards(items){ return `<div class="metric-cards">${items.map(([label,value,note])=>`<div class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note||'')}</span></div>`).join('')}</div>`; }
  function renderResults(){ const rows=state.feed.results||[]; const html=rows.slice(0,100).map(r=>{const p1=r.player1||{},p2=r.player2||{},winner=r.result?.winner_id,correct=r.result?.correct;return `<div class="result-row"><small>${fmtDate(r.scheduled_at)} · ${escapeHtml(r.tour||'')}</small><strong>${escapeHtml(p1.name||'Player 1')} vs ${escapeHtml(p2.name||'Player 2')}</strong><span>Winner: ${escapeHtml(winner===p1.id?p1.name:winner===p2.id?p2.name:'—')}</span><b class="${correct?'correct':'wrong'}">${correct===true?'✓ Correct':correct===false?'× Miss':'—'}</b></div>`}).join(''); return html||'<div class="state-card">No settled published predictions are available yet.</div>'; }

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
    if(plan.lifetime||String(plan.billing||'').toLowerCase()==='lifetime')return null;
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
  function adminRowHtml(zone){
    const prefix=zone==='content_top'?'CONTENT_TOP_':'CONTENT_BOTTOM_';
    return rowItems(zone).map(entry=>{
      const covered=entry.span>1?` · spans ${Array.from({length:entry.span},(_,i)=>`${prefix}${entry.start+i+1}`).join(' + ')}`:'';
      return adminMiniBlock(entry.item.id,false,`grid-span-${entry.span} `,`${entry.item.id}${covered}`);
    }).join('');
  }
  function renderAdminCanvas(){
    const nav=elementList('navigation').map(x=>adminMiniBlock(x.id,true)).join('');
    const promos=elementList('sidebar_promo','sidebar').map(x=>adminMiniBlock(x.id,true)).join('');
    const top=adminRowHtml('content_top');
    const bottom=adminRowHtml('content_bottom');
    const picks=[...Array(8)].map((_,i)=>adminMiniBlock(`TOP_PICK_${i+1}`,true)).join('')+adminMiniBlock('TOP_PICK_MORE',true);
    const features=elementList('feature','features').map(x=>adminMiniBlock(x.id,true)).join('');
    return `<div class="admin-canvas">
      <div class="admin-canvas-header"><div class="admin-logo-lock">BLINQ LOGO<br><small>FIXED</small></div><div class="admin-header-slots">${adminMiniBlock('HEADER_BANNER_1')}${adminMiniBlock('HEADER_BANNER_2')}${adminMiniBlock('HEADER_BANNER_3')}</div></div>
      <div class="admin-canvas-body"><aside class="admin-canvas-sidebar"><b>SIDEBAR</b>${nav}<div class="admin-canvas-divider"></div>${promos}${features?`<div class="admin-canvas-divider"></div><b>FEATURE FLAGS</b>${features}`:''}</aside>
      <main class="admin-canvas-main"><div class="admin-functional-row">${adminMiniBlock('PREDICTION_TOOLBAR')}${adminMiniBlock('DASHBOARD_SNAPSHOT')}</div><div class="admin-row-caption"><span>TOP CONTENT ROW</span><b>${escapeHtml(rowPreset('content_top'))}</b></div><div class="admin-slot-row four preset-${escapeHtml(rowPreset('content_top').replaceAll('+','-'))}">${top}</div><div class="admin-prime-map"><div>${adminMiniBlock('PRIME_PICKS_PANEL')}</div><div class="admin-pick-strip">${picks}</div></div><div class="admin-row-caption"><span>BOTTOM CONTENT ROW</span><b>${escapeHtml(rowPreset('content_bottom'))}</b></div><div class="admin-slot-row four preset-${escapeHtml(rowPreset('content_bottom').replaceAll('+','-'))}">${bottom}</div>${adminMiniBlock('FOOTER_SYSTEM')}</main></div>
    </div>`;
  }
  function campaignOptions(selected=''){
    const rows=Object.entries(state.ui?.campaigns||{}).sort((a,b)=>String(a[1]?.name||a[0]).localeCompare(String(b[1]?.name||b[0])));
    return `<option value="">Inline / no campaign</option>`+rows.map(([id,c])=>`<option value="${escapeHtml(id)}"${id===selected?' selected':''}>${escapeHtml(c.name||id)}</option>`).join('');
  }
  function spanForElement(id){
    for(const zone of ['content_top','content_bottom']){
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
    const parts=[spec.aspect_ratio?`ratio ${spec.aspect_ratio}`:'',spec.recommended?`recommended ${spec.recommended}`:''].filter(Boolean);
    return parts.join(' · ')||'fixed BlinQ creative format';
  }
  function contentEditor(item){
    const c=item.content||{};
    if(item.kind==='navigation') return `<div class="admin-field-grid"><label>Button label<input data-admin-content="label" value="${escapeHtml(c.label||'')}"></label><label>Icon<input data-admin-content="icon" value="${escapeHtml(c.icon||'')}"></label><label>Route<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label></div>`;
    if(!['header_slot','large_banner','sidebar_promo'].includes(item.kind)) return '<p class="admin-muted">This is a functional element. Configure its plan access below; its internal data placement will be wired after the layout is approved.</p>';
    return `<div class="admin-field-grid">
      <label>Content type<select data-admin-content="type"><option value="internal"${c.type==='internal'?' selected':''}>Internal</option><option value="advertisement"${c.type==='advertisement'?' selected':''}>Advertisement</option><option value="rss"${c.type==='rss'?' selected':''}>RSS / news</option><option value="image"${c.type==='image'?' selected':''}>Image</option><option value="promo"${(!c.type||c.type==='promo')?' selected':''}>Promo</option></select></label>
      <label>Theme<select data-admin-content="theme">${['violet','blue','purple','green'].map(v=>`<option value="${v}"${v===(c.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label>
      <div class="field-hint-box">${escapeHtml(item.kind==='large_banner'?`Banner width is controlled by the fixed row preset. Current creative: ${creativeSpecText(item)}.`:`Fixed creative: ${creativeSpecText(item)}.`)}</div>
      <label class="check-field"><input type="checkbox" data-admin-content="enabled" ${c.enabled!==false?'checked':''}> Content enabled</label>
      <label>Campaign<select data-admin-content="campaign_id">${campaignOptions(String(c.campaign_id||''))}</select></label>
      <label>Advertiser ID<input data-admin-content="advertiser_id" value="${escapeHtml(c.advertiser_id||'')}" placeholder="inline / fallback advertiser"></label>
      <label>Eyebrow<input data-admin-content="eyebrow" value="${escapeHtml(c.eyebrow||'')}"></label>
      <label>Headline<input data-admin-content="headline" value="${escapeHtml(c.headline||'')}"></label>
      <label class="span-2">Text<textarea data-admin-content="text" rows="3">${escapeHtml(c.text||'')}</textarea></label>
      <label>CTA text<input data-admin-content="button_text" value="${escapeHtml(c.button_text||'')}"></label>
      <label>Link<input data-admin-content="link" value="${escapeHtml(c.link||'')}"></label>
      <label>Route<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label>
      <label class="span-2">Image path / URL<input data-admin-content="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/banner-fallback/... or https://..."></label>
      <label>Active from<input data-admin-content="active_from" type="datetime-local" value="${escapeHtml(c.active_from||'')}"></label>
      <label>Active until<input data-admin-content="active_until" type="datetime-local" value="${escapeHtml(c.active_until||'')}"></label>
      <label>When ads are hidden<select data-admin-content="ad_hidden_fallback">${['auto','rss','image','internal'].map(v=>`<option value="${v}"${v===(c.ad_hidden_fallback||'auto')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label class="check-field"><input type="checkbox" data-admin-content="sponsored" ${c.sponsored?'checked':''}> Sponsored label</label>
    </div>`;
  }
  function watermarkEditor(item){
    if(!['header_slot','large_banner','sidebar_promo'].includes(item.kind))return '';
    const wm=item.watermark||{};
    return `<div class="admin-section"><div class="admin-section-title"><strong>Watermark overlay</strong><span>One fixed visual style</span></div><div class="admin-field-grid"><label class="check-field"><input type="checkbox" data-admin-watermark="enabled" ${wm.enabled?'checked':''}> Enable watermark</label><label>Watermark text<input data-admin-watermark="text" value="${escapeHtml(wm.text||'COMING SOON')}"></label></div><div class="watermark-preview"><span>${escapeHtml(wm.text||'COMING SOON')}</span></div></div>`;
  }
  function renderAdminInspector(){
    const item=elements()?.[state.selectedElement] || elements()?.HEADER_BANNER_1;
    if(!item)return '<aside class="admin-inspector"><p>No configurable elements.</p></aside>';
    return `<aside class="admin-inspector"><div class="admin-inspector-head"><small>${escapeHtml(state.selectedElement)}</small><h3>${escapeHtml(item.label||state.selectedElement)}</h3><span>${escapeHtml(item.kind||'element')} · ${escapeHtml(item.zone||'')}</span></div>
      <div class="admin-section"><div class="admin-section-title"><strong>Content / details</strong><span>What this fixed position displays</span></div>${contentEditor(item)}</div>
      ${watermarkEditor(item)}
      <div class="admin-section"><div class="admin-section-title"><strong>Plan access</strong><span>Layout stays reserved even when hidden</span></div><div class="admin-access-grid">${accessContexts.map(plan=>`<label><span>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</span>${accessSelect(state.selectedElement,plan)}</label>`).join('')}</div></div>
    </aside>`;
  }
  function renderAdminLayout(){
    const planOptions=accessContexts.map(id=>`<option value="${id}"${state.adminPlan===id?' selected':''}>${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</option>`).join('');
    const copyOptions=accessContexts.filter(id=>id!==state.adminPlan).map(id=>`<option value="${id}">${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</option>`).join('');
    const presets=state.ui?.admin?.row_presets||Object.keys(rowPresetMap);
    const presetOptions=zone=>presets.map(id=>`<option value="${escapeHtml(id)}"${rowPreset(zone)===id?' selected':''}>${escapeHtml(id)}</option>`).join('');
    return `<div class="admin-toolbar"><label>Editing access for<select id="adminPlanSelect">${planOptions}</select></label><label>Copy all access from<select id="adminCopyFrom">${copyOptions}</select></label><button class="btn btn-ghost" type="button" data-admin-action="copy-plan">Copy → ${escapeHtml(accessLabel(state.adminPlan))}</button><label>Top row layout<select id="adminTopRowPreset">${presetOptions('content_top')}</select></label><label>Bottom row layout<select id="adminBottomRowPreset">${presetOptions('content_bottom')}</select></label><span class="admin-toolbar-spacer"></span><button class="btn btn-ghost" type="button" data-admin-action="preview">Preview as ${escapeHtml(accessLabel(state.adminPlan))}</button><button class="btn btn-ghost" type="button" data-admin-action="clear-preview">Exit preview</button><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish changes</button><button class="btn btn-ghost" type="button" data-admin-action="export">Export JSON</button><button class="btn btn-ghost" type="button" data-admin-action="reset">Reset</button></div><div class="admin-editor-grid"><div>${renderAdminCanvas()}</div>${renderAdminInspector()}</div>`;
  }
  function renderAdminPlans(){
    const plans=Object.entries(state.ui?.plans||{}).filter(([id])=>!['trial','expired'].includes(id));
    return `<div class="admin-note"><strong>Plan catalogue</strong><span>Plan defaults come from this JSON/runtime configuration. Account activation remains manual.</span></div><div class="admin-plan-grid">${plans.map(([id,p])=>`<article class="admin-plan-card ${p.enabled===false?'disabled':''}" data-plan-card="${escapeHtml(id)}"><div class="admin-plan-head"><small>${escapeHtml(id)}</small><input data-plan-field="label" value="${escapeHtml(p.label||id.toUpperCase())}"><label class="check-field"><input type="checkbox" data-plan-field="enabled" ${p.enabled!==false?'checked':''}> Enabled</label></div><div class="admin-field-grid"><label>Price<input data-plan-field="price" value="${escapeHtml(p.price||'')}"></label><label>Currency<input data-plan-field="currency" value="${escapeHtml(p.currency||'EUR')}"></label><label>Billing<input data-plan-field="billing" value="${escapeHtml(p.billing||'')}"></label><label>Default duration (days)<input data-plan-field="duration_days" type="number" min="1" value="${p.duration_days??''}" ${p.lifetime?'disabled':''}></label><label class="check-field"><input type="checkbox" data-plan-field="lifetime" ${p.lifetime?'checked':''}> Unlimited / lifetime</label><label class="check-field"><input type="checkbox" ${p.hide_ads_allowed?'checked':''} disabled> Hide Ads eligibility</label><label class="span-2">Payment link<input data-plan-field="payment_link" value="${escapeHtml(p.payment_link||'')}" placeholder="https://..."></label><label class="span-2">Note<textarea data-plan-field="note" rows="2">${escapeHtml(p.note||'')}</textarea></label></div><div class="admin-plan-term"><span>Default account term</span><strong>${escapeHtml(planTermLabel(id))}</strong></div></article>`).join('')}</div><div class="admin-actions-row"><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish plan changes</button><button class="btn btn-ghost" type="button" data-admin-action="export">Export ui-config.json</button></div>`;
  }
  function userDateValue(value){ if(!value)return ''; const d=new Date(value); if(Number.isNaN(d.getTime()))return ''; const pad=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
  function renderAdminUserEditor(user){
    if(!user)return '<div class="admin-user-empty">Select an account to edit its role and subscription.</div>';
    const self=String(user.id)===String(state.feed?.account?.id);
    const selectedPlan=user.plan&& !['expired','admin'].includes(user.plan)?user.plan:'';
    return `<form id="adminUserForm" class="admin-user-editor"><div class="admin-inspector-head"><small>${escapeHtml(user.id)}</small><h3>${escapeHtml(user.name||user.email||'User')}</h3><span>${escapeHtml(user.email||'')}</span></div><div class="admin-field-grid"><label>Role<select id="adminUserRole" ${self?'disabled':''}><option value="user"${user.role!=='admin'?' selected':''}>USER</option><option value="admin"${user.role==='admin'?' selected':''}>ADMIN</option></select></label><label>Plan<select id="adminUserPlan">${planSelectOptions(selectedPlan,true)}</select><small class="field-hint" id="adminPlanTerm">${escapeHtml(selectedPlan?planTermLabel(selectedPlan):'No paid plan')}</small></label><label>Status<select id="adminUserStatus">${statusSelectOptions(user.status||'expired')}</select></label><label>Expires at<input id="adminUserExpires" type="datetime-local" value="${escapeHtml(userDateValue(user.expires_at))}" ${user.status==='lifetime'?'disabled':''}></label><label class="span-2">Payment / manual reference<input id="adminPaymentReference" maxlength="120" value="${escapeHtml(user.payment_reference||'')}" placeholder="payment link order, note, transaction id..."></label></div><div class="admin-user-meta"><span>Created: ${escapeHtml(fmtDate(user.created_at))}</span><span>Last login: ${escapeHtml(fmtDate(user.last_sign_in_at))}</span><span>Current: ${escapeHtml(user.plan_label||user.plan||'—')} · ${escapeHtml(user.status||'—')}</span>${user.status==='trial'?`<span>Automatic Rookie trial until ${escapeHtml(fmtDate(user.expires_at))}</span>`:''}</div><div class="admin-quick-actions">${['rookie','pro','elite','goat'].filter(id=>state.ui?.plans?.[id]?.enabled!==false).map(id=>`<button type="button" class="btn btn-ghost" data-admin-user-plan="${escapeHtml(id)}">${escapeHtml((state.ui?.plans?.[id]?.label||id).toUpperCase())} · ${escapeHtml(planTermLabel(id))}</button>`).join('')}</div><p id="adminUserMessage" class="form-message"></p><button class="btn btn-primary" type="submit">Apply changes</button>${self?'<small class="admin-muted">Your own ADMIN role is protected from accidental removal.</small>':''}</form>`;
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
    const editor=selected?`<form id="adminCampaignForm" class="campaign-editor"><div class="admin-inspector-head"><small>${escapeHtml(state.adminCampaignId)}</small><h3>${escapeHtml(selected.name||state.adminCampaignId)}</h3><span>Campaign creative and scheduling</span></div><div class="admin-field-grid"><label>Name<input data-campaign-field="name" value="${escapeHtml(selected.name||'')}"></label><label>Advertiser<select data-campaign-field="advertiser_id">${advertiserOptions(String(selected.advertiser_id||''))}</select></label><label class="check-field"><input type="checkbox" data-campaign-field="enabled" ${selected.enabled!==false?'checked':''}> Enabled</label><label class="check-field"><input type="checkbox" data-campaign-field="sponsored" ${selected.sponsored!==false?'checked':''}> Sponsored label</label><label>Creative mode<select data-campaign-field="creative_mode"><option value="full"${(selected.creative_mode||'full')==='full'?' selected':''}>Full image banner</option><option value="split"${selected.creative_mode==='split'?' selected':''}>Image + BlinQ text</option></select></label><label class="check-field"><input type="checkbox" data-campaign-field="show_copy" ${selected.show_copy!==false?'checked':''}> Show headline / CTA over creative</label><label>Theme<select data-campaign-field="theme">${['violet','blue','purple','green'].map(v=>`<option value="${v}"${v===(selected.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label><label>Eyebrow<input data-campaign-field="eyebrow" value="${escapeHtml(selected.eyebrow||'SPONSORED')}"></label><label class="span-2">Headline<input data-campaign-field="headline" value="${escapeHtml(selected.headline||'')}"></label><label class="span-2">Text<textarea data-campaign-field="text" rows="3">${escapeHtml(selected.text||'')}</textarea></label><label>CTA text<input data-campaign-field="button_text" value="${escapeHtml(selected.button_text||'Open')}"></label><label>Destination URL<input data-campaign-field="link" value="${escapeHtml(selected.link||'')}"></label><div class="field-hint-box">Use the variant that matches the active row preset. BlinQ keeps the slot geometry fixed and selects 1/2/4-column creative automatically.</div><label class="span-2">1-column image · ${escapeHtml(spec1.aspect_ratio||'4:3')} · ${escapeHtml(spec1.recommended||'1200 × 900 px')}<input data-campaign-image="1" value="${escapeHtml(images['1']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">2-column image · ${escapeHtml(spec2.aspect_ratio||'8:3')} · ${escapeHtml(spec2.recommended||'2400 × 900 px')}<input data-campaign-image="2" value="${escapeHtml(images['2']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">4-column image · ${escapeHtml(spec4.aspect_ratio||'16:3')} · ${escapeHtml(spec4.recommended||'2400 × 450 px')}<input data-campaign-image="4" value="${escapeHtml(images['4']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">Fallback image path / URL<input data-campaign-field="image_url" value="${escapeHtml(selected.image_url||'')}" placeholder="Used when a size-specific image is empty"></label><label>Active from<input data-campaign-field="active_from" type="datetime-local" value="${escapeHtml(selected.active_from||'')}"></label><label>Active until<input data-campaign-field="active_until" type="datetime-local" value="${escapeHtml(selected.active_until||'')}"></label></div><div class="admin-actions-row"><button class="btn btn-ghost danger" type="button" data-admin-action="delete-campaign" data-entity-id="${escapeHtml(state.adminCampaignId)}">Delete campaign</button></div></form>`:'<div class="admin-user-empty">Create a campaign, then assign it to any fixed content slot.</div>';
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
  function renderAdminRoute(){
    const tabs=[['layout','Layout & slots'],['campaigns','Campaigns'],['feeds','RSS feeds'],['plans','Plans'],['accounts','Accounts'],['analytics','Banner analytics']];
    const panel=state.adminTab==='layout'?renderAdminLayout():state.adminTab==='campaigns'?renderAdminCampaigns():state.adminTab==='feeds'?renderAdminFeeds():state.adminTab==='plans'?renderAdminPlans():state.adminTab==='accounts'?renderAdminAccounts():renderAdminAnalytics();
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
      else if(action==='preview'){state.previewPlan=state.adminPlan;renderAllUiContent();setRoute('predictions');showStatus(`Previewing page as ${accessLabel(state.previewPlan)}.`);}
      else if(action==='clear-preview'){state.previewPlan=null;renderAllUiContent();rerenderAdmin();showStatus('Admin preview disabled.');}
      else if(action==='add-advertiser'){state.ui.advertisers=state.ui.advertisers||{};const id=nextEntityId('advertiser',state.ui.advertisers);state.ui.advertisers[id]={name:`Advertiser ${Object.keys(state.ui.advertisers).length+1}`,website:'',note:''};rerenderAdmin();}
      else if(action==='delete-advertiser'){const id=String(actionNode.dataset.entityId||'');const used=Object.values(state.ui?.campaigns||{}).some(c=>String(c?.advertiser_id||'')===id);if(used){showStatus('Advertiser is still assigned to a campaign. Reassign the campaign first.');}else if(id&&state.ui?.advertisers?.[id]){delete state.ui.advertisers[id];rerenderAdmin();}}
      else if(action==='add-campaign'){state.ui.campaigns=state.ui.campaigns||{};const id=nextEntityId('campaign',state.ui.campaigns);state.ui.campaigns[id]={name:`Campaign ${Object.keys(state.ui.campaigns).length+1}`,advertiser_id:'',enabled:true,sponsored:true,creative_mode:'full',show_copy:false,theme:'violet',eyebrow:'SPONSORED',headline:'',text:'',button_text:'Open',link:'',image_url:'',images:{'1':'','2':'','4':''},active_from:'',active_until:''};state.adminCampaignId=id;rerenderAdmin();}
      else if(action==='delete-campaign'){const id=String(actionNode.dataset.entityId||state.adminCampaignId||'');if(id&&state.ui?.campaigns?.[id]){delete state.ui.campaigns[id];Object.values(elements()).forEach(item=>{if(item?.content?.campaign_id===id)item.content.campaign_id='';});state.adminCampaignId=null;renderAllUiContent();rerenderAdmin();}}
      else if(action==='add-rss-source'){state.ui.rss=state.ui.rss||{enabled:true,sources:[]};state.ui.rss.sources=Array.isArray(state.ui.rss.sources)?state.ui.rss.sources:[];const max=Math.max(1,Number(state.ui?.admin?.max_rss_sources)||8);if(state.ui.rss.sources.length>=max){showStatus(`Maximum ${max} RSS sources.`);}else{const used=new Set(state.ui.rss.sources.map(x=>x.id));let n=1;while(used.has(`rss-${n}`))n++;state.ui.rss.sources.push({id:`rss-${n}`,name:`RSS source ${n}`,url:'',enabled:false,priority:0});rerenderAdmin();}}
      else if(action==='delete-rss-source'){const index=Number(actionNode.dataset.sourceIndex);if(Number.isInteger(index)&&index>=0&&index<(state.ui?.rss?.sources||[]).length){state.ui.rss.sources.splice(index,1);rerenderAdmin();}}
      else if(action==='refresh-users')await loadAdminUsers(true);
      else if(action==='refresh-analytics')await loadBannerAnalytics(true);
    };
    host.onchange=event=>{
      const t=event.target;
      if(t.id==='adminPlanSelect'){state.adminPlan=t.value;rerenderAdmin();return;}
      if(t.id==='adminTopRowPreset'){state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows.content_top=state.ui.content_rows.content_top||{};state.ui.content_rows.content_top.preset=t.value;renderAllUiContent();rerenderAdmin();return;}
      if(t.id==='adminBottomRowPreset'){state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows.content_bottom=state.ui.content_rows.content_bottom||{};state.ui.content_rows.content_bottom.preset=t.value;renderAllUiContent();rerenderAdmin();return;}
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
      const card=t.closest('[data-plan-card]');if(card&&t.dataset.planField){const plan=state.ui.plans?.[card.dataset.planCard];if(plan){let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.planField==='duration_days')value=value===''?null:Number(value);plan[t.dataset.planField]=value;if(t.dataset.planField==='lifetime'&&value)plan.duration_days=null;rerenderAdmin();}return;}
    };
    const search=$('adminUserSearch');if(search)search.oninput=()=>{const q=search.value.trim().toLowerCase();host.querySelectorAll('.admin-user-row').forEach(row=>{row.hidden=q&&!String(row.dataset.search||'').includes(q);});};
    const form=$('adminUserForm');if(form)form.onsubmit=async event=>{event.preventDefault();const user=state.adminSelectedUser;if(!user)return;const message=$('adminUserMessage');message.textContent='Saving…';try{const rawExpiry=$('adminUserExpires').value,status=$('adminUserStatus').value;if(status==='trial')throw new Error('Choose ACTIVE, EXPIRED or SUSPENDED before saving an automatic trial.');const payload={role:$('adminUserRole').disabled?'admin':$('adminUserRole').value,plan:$('adminUserPlan').value,status,expires_at:rawExpiry?new Date(rawExpiry).toISOString():null,payment_reference:$('adminPaymentReference').value.trim()};const updated=await BlinqAuth.adminUpdateAccess(user.id,payload);state.adminUsers=(state.adminUsers||[]).map(row=>row.id===updated.id?updated:row);state.adminSelectedUser=updated;message.textContent='Applied.';setTimeout(()=>rerenderAdmin(),450);}catch(error){message.textContent=error.message;}};
  }
  function renderPlanCardsForAccount(){
    const plans=Object.entries(state.ui?.plans||{}).filter(([id,p])=>!['trial','expired'].includes(id)&&p.enabled!==false);
    return `<div class="account-plan-grid">${plans.map(([id,p])=>`<article><small>${escapeHtml(p.label||id.toUpperCase())}</small><strong>${escapeHtml(p.price?`${p.price} ${p.currency||'EUR'}`:'Price on request')}</strong><span>${escapeHtml(p.billing||'')}</span><p>${escapeHtml(p.note||'')}</p>${p.payment_link?`<a class="btn btn-primary" href="${escapeHtml(p.payment_link)}" target="_blank" rel="noopener">Payment link</a>`:'<button class="btn btn-ghost" type="button" disabled>Payment link not set</button>'}</article>`).join('')}</div>`;
  }
  function renderRoute(route){
    const host=$('routePanel'),feed=state.feed,p=feed.performance||{},history=feed.history||{},report=feed.model?.report||{}; let body='';
    if(route==='admin'){host.innerHTML=renderAdminRoute();wireAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='analytics')loadBannerAnalytics();return;}
    if(route==='tournaments'){const names=[...new Set((feed.upcoming||[]).map(x=>x.tournament).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):'No upcoming tournament coverage is currently published.'}</div>`;}
    else if(route==='players'){const names=[...new Set((feed.upcoming||[]).flatMap(x=>[x.player1?.name,x.player2?.name]).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):'No upcoming players are currently published.'}</div>`;}
    else if(route==='stats'){body=metricCards([['Settled predictions',String(p.n??0),'Published and scored'],['Accuracy',p.accuracy!=null?pct(p.accuracy):'—','Observed results'],['Log loss',number(p.log_loss),'Lower is better'],['Brier score',number(p.brier_score),'Probability quality']])+`<div class="route-sub"><h3>Results</h3>${renderResults()}</div>`;}
    else if(route==='model'||route==='backtests'){const h=report.holdout||{},delta=report.delta_vs_elo||{};body=metricCards([['Model',String(feed.model?.version||'—'),'Production artifact'],['Holdout n',String(h.n??'—'),'Chronological holdout'],['Holdout accuracy',h.accuracy!=null?pct(h.accuracy):'—','Evaluation report'],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—','Negative is better']])+`<div class="route-sub static-copy"><h3>Data window</h3><p>${escapeHtml(history.start?fmtDate(history.start):'—')} → ${escapeHtml(history.end?fmtDate(history.end):'—')} · ${escapeHtml(String(history.matches??'—'))} historical matches in the current serving metadata.</p><p>No result here is presented as a guarantee. Holdout metrics describe a specific historical evaluation period.</p></div>`;}
    else if(route==='account'){const a=feed.account||{};const adToggle=a.hide_ads_allowed?`<label class="preference-toggle"><span><strong>Hide advertisements</strong><small>Replace external ads with RSS/news, repo images or BlinQ content. Layout stays fixed.</small></span><input id="hideAdsToggle" type="checkbox" ${a.hide_ads?'checked':''}></label>`:'';body=`<div class="account-grid"><form id="profileForm" class="account-panel"><div class="account-access-summary"><small>${escapeHtml(a.plan_label||a.plan||'Member')}</small><strong>${escapeHtml(String(a.status||'active').toUpperCase())}</strong><span>${a.expires_at?`until ${escapeHtml(fmtDate(a.expires_at))}`:a.status==='lifetime'?'no expiry':'managed manually'}</span></div><label>Email<input value="${escapeHtml(a.email||'')}" disabled /></label><label>Display name<input id="profileDisplayName" maxlength="80" value="${escapeHtml(a.name||'')}" /></label>${adToggle}<p id="profileMessage" class="form-message"></p><div class="account-actions"><button class="btn btn-primary" type="submit">Save profile</button><button class="btn btn-ghost" id="passwordResetButton" type="button">Reset password</button><button class="btn btn-ghost" id="logoutButton" type="button">Sign out</button></div></form><aside class="account-side"><small class="trial-eyebrow">BLINQ MEMBERS</small><strong>${escapeHtml(a.name||'BlinQ Member')}</strong><p>${escapeHtml(a.email||'')}</p><p>Role: ${escapeHtml(a.role||'user')} · Plan: ${escapeHtml(a.plan_label||a.plan||'—')}</p><p>Payments are external; access is paired to the account by an administrator.</p></aside></div><div class="route-sub"><h3>Available plans</h3>${renderPlanCardsForAccount()}</div>`;}
    else {const copy={how_blinq_works:'BlinQ processes point-in-time tennis history, builds model features without using future results, publishes pre-match probabilities, and later evaluates those same published records against real outcomes.',methodology:'The core rules are chronological evaluation, immutable first-published probabilities, explicit missing-data handling, and honest probability metrics. A prediction is informative only when it existed before the match.',model_data:`Current serving metadata reports ${history.matches??'—'} historical matches. The web application reads only the authenticated published serving feed; it does not fabricate missing tennis data.`,faq:'Probabilities are not certainties. Confidence is derived from the model probability, and performance should always be read together with sample size and coverage.',responsible_use:'Use BlinQ as analytical information. Do not treat any probability as a guaranteed outcome, and do not infer certainty from a high-confidence label.'};body=`<div class="static-copy"><p>${escapeHtml(copy[route]||'This section is available in the BlinQ workspace.')}</p></div>`;}
    host.innerHTML=`<div class="route-card"><h2>${escapeHtml(routeMeta[route][1])}</h2><p>${escapeHtml(routeMeta[route][2])}</p>${body}</div>`; if(route==='account')wireAccount(); applyAccessStates(host);
  }

  function wireAccount(){
    $('profileForm').onsubmit=async e=>{e.preventDefault();const msg=$('profileMessage');msg.textContent='Saving…';try{await BlinqAuth.update({data:{display_name:$('profileDisplayName').value.trim()}});await loadFeed(false);setRoute('account',false);$('profileMessage').textContent='Profile saved.';}catch(err){msg.textContent=err.message;}};
    const hideAds=$('hideAdsToggle');if(hideAds)hideAds.onchange=async()=>{const msg=$('profileMessage');msg.textContent='Updating ad preference…';try{await BlinqAuth.update({data:{blinq_hide_ads:hideAds.checked}});await loadFeed(false);setRoute('account',false);$('profileMessage').textContent='Ad preference saved.';}catch(err){msg.textContent=err.message;}};
    $('passwordResetButton').onclick=async()=>{const email=state.feed.account?.email;if(!email)return;const msg=$('profileMessage');msg.textContent='Sending…';try{await BlinqAuth.reset(email);msg.textContent='Recovery email requested.';}catch(err){msg.textContent=err.message;}};
    $('logoutButton').onclick=async()=>{await BlinqAuth.signOut();state.feed={upcoming:[],results:[],performance:{},history:{},model:null};auth('login');};
  }

  async function loadFeed(showLoading=true){
    if(showLoading&&state.route==='predictions') $('predictionGrid').innerHTML='<div class="state-card">Loading current model predictions…</div>';
    try{
      const feed=await BlinqAuth.feed(); state.feed=feed||{}; state.feed.upcoming=Array.isArray(feed?.upcoming)?feed.upcoming:[]; state.feed.results=Array.isArray(feed?.results)?feed.results:[];
      await loadNewsPool(); loadAdminDraft(); renderAllUiContent(); populateFilters(); renderSnapshot();
      const a=feed.account||{}; $('profileName').textContent=a.name||a.email||'BlinQ User'; $('profilePlan').textContent=a.plan_label||a.plan||'Member'; $('memberStatus').textContent=a.status==='trial'?`Trial · ${remainingLabel(a.expires_at)}`:String(a.status||'active').replaceAll('_',' '); $('avatar').textContent=initials(a.name||a.email||'B');
      $('updatedAt').textContent=feed.generated_at?fmtTime(feed.generated_at):'—'; $('todayLabel').textContent=fmtToday(); const sidebarModel=$('sidebarModelState'); if(sidebarModel)sidebarModel.textContent=feed?.model?.version?`Model ${feed.model.version}`:'Production feed';
      $('staleNotice').hidden=!feed.stale; $('staleNotice').textContent=feed.stale?'Published data is older than 12 hours. Check prediction creation times before evaluating them.':''; $('appShell').hidden=false; if($('authDialog').open)$('authDialog').close();
      if(state.route==='admin'&&!isAdminAccount())state.route='predictions'; setRoute(state.route,false); applyAccessStates();
    }catch(error){if(error.status===401){BlinqAuth.clear();auth('login');return;}showStatus('Data could not be loaded. Try again shortly.');throw error;}
  }

  function showStatus(message){const n=$('statusBanner');n.textContent=message;n.hidden=!message;if(message)setTimeout(()=>{n.hidden=true},5000)}

  function setupEvents(){
    $('authDialog').addEventListener('cancel',e=>e.preventDefault()); $('authForm').addEventListener('submit',handleAuthSubmit); $('switchSignup').onclick=()=>auth(state.authMode==='login'?'signup':'login'); $('switchReset').onclick=()=>auth('reset');
    $('refreshButton').onclick=()=>loadFeed(); ['tourFilter','tournamentFilter','surfaceFilter','confidenceFilter'].forEach(id=>$(id).addEventListener('change',()=>{state.page=0;state.showAll=false;renderPredictions()})); $('searchInput').addEventListener('input',()=>{state.page=0;state.showAll=false;renderPredictions()});
    $('prevPick').onclick=()=>{state.page=Math.max(0,state.page-1);renderPredictions()}; $('nextPick').onclick=()=>{state.page+=1;renderPredictions()}; $('viewAllButton').onclick=()=>{state.showAll=!state.showAll;state.page=0;renderPredictions()}; $('dialogClose').onclick=()=>$('matchDialog').close(); $('matchDialog').addEventListener('click',e=>{if(e.target===$('matchDialog'))$('matchDialog').close()}); $('profileButton').onclick=()=>setRoute('account');
    document.addEventListener('click',e=>{
      const restricted=e.target.closest('[data-ui-element].ui-state-locked,[data-ui-element].ui-state-blurred,[data-ui-element].ui-state-hidden');
      if(restricted&&state.route!=='admin'){e.preventDefault();e.stopPropagation();showStatus(`${restricted.dataset.uiStateLabel||'Locked'} — change plan access in BlinQ Admin.`);return;}
      const banner=e.target.closest('[data-banner-slot]');if(banner)trackBanner(banner,'click');
      const target=e.target.closest('[data-route]');if(!target)return;const route=target.dataset.route;if(!routeMeta[route])return;e.preventDefault();setRoute(route);
    });
    let resizeTimer; window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.route==='predictions'&&!state.showAll){state.page=0;renderPredictions();}},120)});
  }

  async function boot(){ setupEvents(); await loadUiConfig(); const hash=location.hash.replace(/^#/,''); if(routeMeta[hash])state.route=hash; try{const cfg=await BlinqAuth.init();state.authEnabled=Boolean(cfg.enabled);if(cfg.recovery){auth('recovery');return;}const session=await BlinqAuth.restore();if(session)await loadFeed();else auth('login');}catch(error){showStatus(error.message);auth('login');} }
  boot();
})();
