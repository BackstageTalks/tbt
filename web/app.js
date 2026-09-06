(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = { feed: {upcoming:[],results:[],performance:{},history:{},model:null}, ui:null, route:'predictions', page:0, showAll:false, authMode:'login', authEnabled:false };
  const pageSize = () => innerWidth >= 1700 ? 6 : innerWidth >= 1450 ? 5 : innerWidth >= 1200 ? 4 : innerWidth >= 900 ? 3 : 1;
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const pct = value => `${(Number(value || 0) * (Number(value || 0) <= 1 ? 100 : 1)).toFixed(1)}%`;
  const number = (value, digits=3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const fmtTime = value => value ? new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : 'TBA';
  const fmtDate = value => value ? new Intl.DateTimeFormat(undefined,{day:'2-digit',month:'short',year:'numeric'}).format(new Date(value)) : '—';
  const fmtToday = () => new Intl.DateTimeFormat(undefined,{weekday:'long',day:'2-digit',month:'short',year:'numeric'}).format(new Date());
  const initials = name => String(name || 'B').trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase();
  const confidenceBand = p => p >= .80 ? 'elite' : p >= .70 ? 'high' : p >= .60 ? 'medium' : 'low';

  async function getJSON(url) {
    const response = await fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  async function loadUiConfig() {
    try { state.ui = await getJSON('/ui-config.json'); }
    catch { state.ui = {navigation:{main:[],learn:[]},panels:{},banners:{}}; }
    renderNavigation(); renderBanners();
  }

  function renderNavigationGroup(items, containerId) {
    const host=$(containerId); host.innerHTML='';
    [...(items||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
      const a=document.createElement('a'); a.href=item.href||`#${item.id}`; a.dataset.route=item.id||'';
      a.className=`nav-link${state.route===item.id?' active':''}`;
      a.innerHTML=`<span class="nav-icon">${escapeHtml(item.icon||'•')}</span><span>${escapeHtml(item.label||item.id)}</span>`;
      host.appendChild(a);
    });
  }
  function renderNavigation(){
    renderNavigationGroup(state.ui?.navigation?.main,'mainNavigation');
    const footer=$('footerLearnNavigation');
    if(footer){
      footer.innerHTML='';
      [...(state.ui?.navigation?.learn||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
        const a=document.createElement('a');
        a.href=item.href||`#${item.id}`;
        a.dataset.route=item.id||'';
        a.textContent=item.label||item.id;
        footer.appendChild(a);
      });
    }
  }

  function renderBanners(){
    const banners=Object.values(state.ui?.banners||{}).filter(b=>b&&b.enabled!==false);
    const targets=new Set(banners.map(b=>b.target).filter(Boolean));
    for(const target of targets){
      const host=$(target); if(!host) continue;
      const rows=banners.filter(b=>b.target===target);
      host.hidden=!rows.length;
      host.innerHTML=rows.map(b=>{
        const route=b.route||'account';
        const theme=String(b.theme||'violet').replace(/[^a-z0-9_-]/gi,'');
        return `<a class="promo-banner promo-card theme-${theme}" href="${escapeHtml(b.link||'#account')}" data-route="${escapeHtml(route)}"><div class="promo-art" aria-hidden="true"></div><div class="promo-copy"><span class="promo-eyebrow">${escapeHtml(b.eyebrow||'BLINQ')}</span><strong>${escapeHtml(b.headline||'')}</strong><p>${escapeHtml(b.text||'')}</p><span class="promo-cta">${escapeHtml(b.button_text||'Open')}</span></div></a>`;
      }).join('');
    }
    ['bannerTop','bannerBottom'].forEach(target=>{const host=$(target);if(host&&!targets.has(target)){host.hidden=true;host.innerHTML='';}});
  }

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
  function filtered(){ const rows=(state.feed.upcoming||[]).map(normalize),tour=$('tourFilter').value,tournament=$('tournamentFilter').value,surface=$('surfaceFilter').value,confidence=$('confidenceFilter').value,q=$('searchInput').value.trim().toLowerCase(); return rows.filter(m=>{ if(tour&&m.tour!==tour)return false;if(tournament&&m.tournament!==tournament)return false;if(surface&&m.surface!==surface)return false;if(confidence&&m.confidence!==confidence)return false;if(q&&!`${m.p1} ${m.p2} ${m.tournament}`.toLowerCase().includes(q))return false;return true; }).sort((a,b)=>b.probability-a.probability || new Date(a.date)-new Date(b.date)); }

  function signalMeta(signal,m){ const id=String(signal?.player_id ?? signal?.favours_player_id ?? ''); const favours=id===String(m.pickId); const label=signal?.label||signal?.factor||'Model signal'; return {label,favours}; }
  function renderSignal(signal,m){ const s=signalMeta(signal,m); return `<div class="signal-row"><span>${escapeHtml(s.label)}</span><div class="signal-meter"><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i></i><i></i></div></div>`; }
  function renderCard(m){ const template=$('predictionTemplate').content.cloneNode(true),card=template.querySelector('.prediction-card'); card.dataset.id=m.id; card.classList.add('featured'); card.querySelector('.tour').textContent=`${m.tour} ${m.tournament}${m.round?` · ${m.round}`:''}`; card.querySelector('.time').textContent=fmtTime(m.date); card.querySelector('.surface').textContent=String(m.surface).replaceAll('_',' ').toUpperCase(); const players=[['.player-a',m.p1,m.p1Prob],['.player-b',m.p2,m.p2Prob]]; players.forEach(([sel,name,prob])=>{const box=card.querySelector(sel);box.querySelector('.player-avatar').textContent=initials(name);box.querySelector('.player-name').textContent=name;box.querySelector('.player-rank').textContent=pct(prob)}); card.querySelector('.pick-name').textContent=m.pick; card.querySelector('.probability').textContent=pct(m.probability); const conf=card.querySelector('.confidence'); conf.textContent=m.confidence.toUpperCase(); conf.classList.add(m.confidence); const signals=card.querySelector('.signals'); signals.innerHTML=m.signals.length?m.signals.slice(0,4).map(s=>renderSignal(s,m)).join(''):'<div class="signal-empty">No strong secondary signal is available.</div>'; card.querySelector('.analysis-link').onclick=()=>openMatch(m); return template; }

  function renderDots(pageCount){ const host=$('carouselDots'); host.innerHTML=''; if(state.showAll||pageCount<=1)return; for(let i=0;i<pageCount;i++){const b=document.createElement('button');b.type='button';b.className=i===state.page?'active':'';b.setAttribute('aria-label',`Show picks page ${i+1}`);b.onclick=()=>{state.page=i;renderPredictions()};host.appendChild(b)} }
  function renderPredictions(){ const rows=filtered(),grid=$('predictionGrid'),size=pageSize(); $('matchCount').textContent=rows.length; const pageCount=Math.max(1,Math.ceil(rows.length/size)); state.page=Math.min(state.page,pageCount-1); let visible=state.showAll?rows:rows.slice(state.page*size,state.page*size+size); grid.classList.toggle('show-all',state.showAll); grid.innerHTML=''; if(!visible.length){grid.innerHTML='<div class="state-card">No upcoming published predictions match the current filters.</div>';} else visible.forEach(m=>grid.appendChild(renderCard(m))); $('prevPick').hidden=state.showAll||pageCount<=1; $('nextPick').hidden=state.showAll||pageCount<=1; $('prevPick').disabled=state.page<=0; $('nextPick').disabled=state.page>=pageCount-1; $('viewAllButton').textContent=state.showAll?'Featured picks ←':'View all matches →'; renderDots(pageCount); }

  function openMatch(m){ const signalRows=m.signals.length?m.signals.map(s=>{const meta=signalMeta(s,m);const favoursId=String(s?.player_id??s?.favours_player_id??'');const favours=favoursId===String(m.p1Id)?m.p1:favoursId===String(m.p2Id)?m.p2:'—';return `<div class="dialog-signal"><span>${escapeHtml(meta.label)}</span><strong>${escapeHtml(favours)}</strong><small>${meta.favours?'supports pick':'counter-signal'}</small></div>`}).join(''):'<p class="signal-empty">No secondary signals are available.</p>'; $('dialogContent').innerHTML=`<div class="dialog-eyebrow">${escapeHtml(m.tour)} · ${escapeHtml(m.tournament)}</div><h2>${escapeHtml(m.p1)} <span>vs</span> ${escapeHtml(m.p2)}</h2><div class="dialog-pick"><div><small>BlinQ Pick</small><strong>${escapeHtml(m.pick)}</strong></div><div class="dialog-prob">${pct(m.probability)} <span class="confidence ${m.confidence}">${m.confidence.toUpperCase()}</span></div></div><div class="dialog-section"><h3>Model signals</h3>${signalRows}</div><div class="dialog-meta"><span>${escapeHtml(String(m.surface).replaceAll('_',' '))}</span><span>${fmtDate(m.date)} · ${fmtTime(m.date)}</span><span>Model ${escapeHtml(m.model||'—')}</span></div>`; $('matchDialog').showModal(); }

  const routeMeta={
    predictions:['TENNIS INTELLIGENCE','Dashboard','Recommended Prime Picks and current tennis intelligence from the published production feed.'],
    tournaments:['TOURNAMENT VIEW','Tournaments','Current tournament coverage derived from published upcoming matches.'],
    players:['PLAYER VIEW','Players','Current players appearing in the published prediction feed.'],
    stats:['PERFORMANCE','Stats & Insights','Observed model performance from settled published predictions.'],
    model:['MODEL TRANSPARENCY','Model Performance','Current production model metadata and evaluation report.'],
    backtests:['VALIDATION','Backtests','Out-of-time evaluation information published with the production model.'],
    account:['BLINQ MEMBERS','Account','Manage your profile and access.'],
    how_blinq_works:['LEARN','How BlinQ Works','How the BlinQ workflow turns point-in-time tennis data into probabilities.'],
    methodology:['LEARN','Methodology','The principles used to keep predictions point-in-time and auditable.'],
    model_data:['LEARN','Model & Data','What the published feed exposes about data and model state.'],
    faq:['LEARN','FAQ','Common questions about probabilities, results and model output.'],
    responsible_use:['LEARN','Responsible Use','Use probabilities as information, never as guarantees.']
  };

  function setRoute(route,push=true){ if(!routeMeta[route]) route='predictions'; state.route=route; state.page=0; const meta=routeMeta[route]; $('pageEyebrow').textContent=meta[0]; $('pageTitle').textContent=meta[1]; $('pageSubtitle').textContent=meta[2]; $('predictionsView').hidden=route!=='predictions'; $('routePanel').hidden=route==='predictions'; renderNavigation(); if(route==='predictions') renderPredictions(); else renderRoute(route); if(push) history.replaceState(null,'',`#${route}`); }

  function metricCards(items){ return `<div class="metric-cards">${items.map(([label,value,note])=>`<div class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note||'')}</span></div>`).join('')}</div>`; }
  function renderResults(){ const rows=state.feed.results||[]; const html=rows.slice(0,100).map(r=>{const p1=r.player1||{},p2=r.player2||{},winner=r.result?.winner_id,correct=r.result?.correct;return `<div class="result-row"><small>${fmtDate(r.scheduled_at)} · ${escapeHtml(r.tour||'')}</small><strong>${escapeHtml(p1.name||'Player 1')} vs ${escapeHtml(p2.name||'Player 2')}</strong><span>Winner: ${escapeHtml(winner===p1.id?p1.name:winner===p2.id?p2.name:'—')}</span><b class="${correct?'correct':'wrong'}">${correct===true?'✓ Correct':correct===false?'× Miss':'—'}</b></div>`}).join(''); return html||'<div class="state-card">No settled published predictions are available yet.</div>'; }
  function renderRoute(route){ const host=$('routePanel'),feed=state.feed,p=feed.performance||{},history=feed.history||{},report=feed.model?.report||{}; let body=''; if(route==='tournaments'){const names=[...new Set((feed.upcoming||[]).map(x=>x.tournament).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):'No upcoming tournament coverage is currently published.'}</div>`;} else if(route==='players'){const names=[...new Set((feed.upcoming||[]).flatMap(x=>[x.player1?.name,x.player2?.name]).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):'No upcoming players are currently published.'}</div>`;} else if(route==='stats'){body=metricCards([['Settled predictions',String(p.n??0),'Published and scored'],['Accuracy',p.accuracy!=null?pct(p.accuracy):'—','Observed results'],['Log loss',number(p.log_loss),'Lower is better'],['Brier score',number(p.brier_score),'Probability quality']])+`<div class="route-sub"><h3>Results</h3>${renderResults()}</div>`;} else if(route==='model'||route==='backtests'){const h=report.holdout||{},delta=report.delta_vs_elo||{};body=metricCards([['Model',String(feed.model?.version||'—'),'Production artifact'],['Holdout n',String(h.n??'—'),'Chronological holdout'],['Holdout accuracy',h.accuracy!=null?pct(h.accuracy):'—','Evaluation report'],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—','Negative is better']])+`<div class="route-sub static-copy"><h3>Data window</h3><p>${escapeHtml(history.start?fmtDate(history.start):'—')} → ${escapeHtml(history.end?fmtDate(history.end):'—')} · ${escapeHtml(String(history.matches??'—'))} historical matches in the current serving metadata.</p><p>No result here is presented as a guarantee. Holdout metrics describe a specific historical evaluation period.</p></div>`;} else if(route==='account'){const a=feed.account||{};body=`<div class="account-grid"><form id="profileForm" class="account-panel"><label>Email<input value="${escapeHtml(a.email||'')}" disabled /></label><label>Display name<input id="profileDisplayName" maxlength="80" value="${escapeHtml(a.name||'')}" /></label><p id="profileMessage" class="form-message"></p><div class="account-actions"><button class="btn btn-primary" type="submit">Save profile</button><button class="btn btn-ghost" id="passwordResetButton" type="button">Reset password</button><button class="btn btn-ghost" id="logoutButton" type="button">Sign out</button></div></form><aside class="account-side"><small class="trial-eyebrow">BLINQ MEMBERS</small><strong>${escapeHtml(a.name||'BlinQ Member')}</strong><p>${escapeHtml(a.email||'')}</p><p>Authentication is handled by the connected identity service. Tennis data is not stored in the account profile.</p></aside></div>`;} else {const copy={how_blinq_works:'BlinQ processes point-in-time tennis history, builds model features without using future results, publishes pre-match probabilities, and later evaluates those same published records against real outcomes.',methodology:'The core rules are chronological evaluation, immutable first-published probabilities, explicit missing-data handling, and honest probability metrics. A prediction is informative only when it existed before the match.',model_data:`Current serving metadata reports ${history.matches??'—'} historical matches. The web application reads only the authenticated published serving feed; it does not fabricate missing tennis data.`,faq:'Probabilities are not certainties. Confidence is derived from the model probability, and performance should always be read together with sample size and coverage.',responsible_use:'Use BlinQ as analytical information. Do not treat any probability as a guaranteed outcome, and do not infer certainty from a high-confidence label.'};body=`<div class="static-copy"><p>${escapeHtml(copy[route]||'This section is available in the BlinQ workspace.')}</p></div>`;} host.innerHTML=`<div class="route-card"><h2>${escapeHtml(routeMeta[route][1])}</h2><p>${escapeHtml(routeMeta[route][2])}</p>${body}</div>`; if(route==='account') wireAccount(); }

  function wireAccount(){ $('profileForm').onsubmit=async e=>{e.preventDefault();const msg=$('profileMessage');msg.textContent='Saving…';try{await BlinqAuth.update({data:{display_name:$('profileDisplayName').value.trim()}});await loadFeed(false);setRoute('account',false);$('profileMessage').textContent='Profile saved.';}catch(err){msg.textContent=err.message;}}; $('passwordResetButton').onclick=async()=>{const email=state.feed.account?.email;if(!email)return;const msg=$('profileMessage');msg.textContent='Sending…';try{await BlinqAuth.reset(email);msg.textContent='Recovery email requested.';}catch(err){msg.textContent=err.message;}}; $('logoutButton').onclick=async()=>{await BlinqAuth.signOut();state.feed={upcoming:[],results:[],performance:{},history:{},model:null};auth('login');}; }

  async function loadFeed(showLoading=true){ if(showLoading&&state.route==='predictions') $('predictionGrid').innerHTML='<div class="state-card">Loading current model predictions…</div>'; try{const feed=await BlinqAuth.feed();state.feed=feed||{};state.feed.upcoming=Array.isArray(feed?.upcoming)?feed.upcoming:[];state.feed.results=Array.isArray(feed?.results)?feed.results:[];populateFilters();renderSnapshot();const a=feed.account||{};$('profileName').textContent=a.name||a.email||'BlinQ User';$('profilePlan').textContent='Member';$('avatar').textContent=initials(a.name||a.email||'B');$('updatedAt').textContent=feed.generated_at?fmtTime(feed.generated_at):'—';$('todayLabel').textContent=fmtToday();const sidebarModel=$('sidebarModelState');if(sidebarModel)sidebarModel.textContent=feed?.model?.version?`Model ${feed.model.version}`:'Production feed';$('staleNotice').hidden=!feed.stale;$('staleNotice').textContent=feed.stale?'Published data is older than 12 hours. Check prediction creation times before evaluating them.':'';$('appShell').hidden=false;if($('authDialog').open)$('authDialog').close();setRoute(state.route,false);}catch(error){if(error.status===401){BlinqAuth.clear();auth('login');return;}showStatus('Data could not be loaded. Try again shortly.');throw error;} }
  function showStatus(message){const n=$('statusBanner');n.textContent=message;n.hidden=!message;if(message)setTimeout(()=>{n.hidden=true},5000)}

  function setupEvents(){
    $('authDialog').addEventListener('cancel',e=>e.preventDefault()); $('authForm').addEventListener('submit',handleAuthSubmit); $('switchSignup').onclick=()=>auth(state.authMode==='login'?'signup':'login'); $('switchReset').onclick=()=>auth('reset');
    $('refreshButton').onclick=()=>loadFeed(); ['tourFilter','tournamentFilter','surfaceFilter','confidenceFilter'].forEach(id=>$(id).addEventListener('change',()=>{state.page=0;state.showAll=false;renderPredictions()})); $('searchInput').addEventListener('input',()=>{state.page=0;state.showAll=false;renderPredictions()});
    $('prevPick').onclick=()=>{state.page=Math.max(0,state.page-1);renderPredictions()}; $('nextPick').onclick=()=>{state.page+=1;renderPredictions()}; $('viewAllButton').onclick=()=>{state.showAll=!state.showAll;state.page=0;renderPredictions()}; $('dialogClose').onclick=()=>$('matchDialog').close(); $('matchDialog').addEventListener('click',e=>{if(e.target===$('matchDialog'))$('matchDialog').close()}); $('profileButton').onclick=()=>setRoute('account');
    document.addEventListener('click',e=>{const target=e.target.closest('[data-route]');if(!target)return;const route=target.dataset.route;if(!routeMeta[route])return;e.preventDefault();setRoute(route)});
    let resizeTimer; window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.route==='predictions'&&!state.showAll){state.page=0;renderPredictions();}},120)});
  }

  async function boot(){ setupEvents(); await loadUiConfig(); const hash=location.hash.replace(/^#/,''); if(routeMeta[hash])state.route=hash; try{const cfg=await BlinqAuth.init();state.authEnabled=Boolean(cfg.enabled);if(cfg.recovery){auth('recovery');return;}const session=await BlinqAuth.restore();if(session)await loadFeed();else auth('login');}catch(error){showStatus(error.message);auth('login');} }
  boot();
})();
