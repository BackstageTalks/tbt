(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const percent = n => `${(100 * Number(n || 0)).toFixed(1).replace('.',',')} %`;
  const date = (stamp, time=false) => stamp ? new Date(stamp).toLocaleString('sk-SK',time ? {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'} : {day:'numeric',month:'short'}) : '—';
  const time = stamp => new Date(stamp).toLocaleTimeString('sk-SK',{hour:'2-digit',minute:'2-digit'});
  const surfaceNames = {hard:'Tvrdý',clay:'Antuka',grass:'Tráva',indoor_hard:'Hala',unknown:'Povrch neurčený'};
  const titles = {overview:['Tenis. V súvislostiach.','Predzápasové pravdepodobnosti a výsledky na jednom mieste.'],predictions:['Každý zápas má príbeh.','Porovnaj hráčov, pravdepodobnosti a dostupné dáta.'],results:['Výsledky bez prikrášlenia.','Záznamy vytvorené pred zápasom. Úspešné aj neúspešné.'],model:['Poznaj svoj model.','Ako sa darilo na neskorších dátach, ktoré model pri tréningu nevidel.'],account:['Tvoj priestor.','Spravuj svoj profil a prístup k BlinQ.']};
  const names = {overview:'Prehľad',predictions:'Predikcie',results:'Výsledky',model:'Model',account:'Môj účet'};
  let data={upcoming:[],results:[],performance:{},history:{},model:null}, page='overview', tour='all', authMode='login', enabled=false, demo=false, limit=50;
  function notice(message='') { $('globalStatus').textContent=message; $('globalStatus').hidden=!message; }
  function empty(title,body) { return `<div class="empty"><span class="empty-symbol">◈</span><h2>${escape(title)}</h2><p>${escape(body)}</p></div>`; }
  function auth(mode='login') {
    authMode=mode; $('authMessage').textContent='';
    $('nameLabel').hidden=mode!=='signup'; $('emailLabel').hidden=mode==='recovery'; $('passwordLabel').hidden=mode==='reset';
    $('authEmail').required=mode!=='recovery'; $('authPassword').required=mode!=='reset'; $('authName').required=mode==='signup';
    $('authPassword').autocomplete=mode==='login'?'current-password':'new-password';
    $('authTitle').textContent={login:'Vitaj späť.',signup:'Začni sledovať súvislosti.',reset:'Obnoviť prístup.',recovery:'Nastav nové heslo.'}[mode];
    $('authSubtitle').textContent={login:'Prihlás sa k svojim tenisovým analýzam.',signup:'Vytvor si účet. Existujúci členovia používajú pôvodné prihlásenie.',reset:'Pošleme ti odkaz na obnovenie hesla.',recovery:'Zvoľ heslo s aspoň ôsmimi znakmi.'}[mode];
    $('authSubmit').textContent={login:'Prihlásiť sa',signup:'Vytvoriť účet',reset:'Poslať odkaz',recovery:'Uložiť heslo'}[mode];
    $('switchSignup').textContent=mode==='login'?'Vytvoriť účet':'Späť na prihlásenie';
    $('switchReset').hidden=mode!=='login'; $('authSubmit').disabled=!enabled;
    if (!enabled) $('authMessage').textContent='Prihlasovanie sa pripravuje. Skús to neskôr.';
    if (!$('authDialog').open) $('authDialog').showModal();
  }
  $('authDialog').addEventListener('cancel',event=>event.preventDefault());
  $('switchSignup').onclick=()=>auth(authMode==='login'?'signup':'login');
  $('switchReset').onclick=()=>auth('reset');
  $('authForm').onsubmit=async event=>{
    event.preventDefault(); const button=$('authSubmit'); button.disabled=true; $('authMessage').textContent='Spracúvame…';
    const email=$('authEmail').value.trim(), password=$('authPassword').value;
    try {
      if(authMode==='reset'){await BlinqAuth.reset(email);$('authMessage').textContent='Ak účet existuje, odkaz príde na tvoj e-mail.';return;}
      if(authMode==='recovery') await BlinqAuth.update({password});
      else if(authMode==='signup') {const session=await BlinqAuth.signUp(email,password,$('authName').value.trim());if(!session){$('authMessage').textContent='Skontroluj e-mail a potvrď registráciu. Potom sa prihlás.';return;}}
      else await BlinqAuth.signIn(email,password);
      $('authPassword').value='';$('authDialog').close();await load();
    } catch(error){$('authMessage').textContent=error.status===400?'Skontroluj údaje a prípadné potvrdenie e-mailu.':error.message;}
    finally{button.disabled=false;}
  };
  function metrics() {
    const p=data.performance || {}, rows=data.upcoming || [];
    const cells=[['Nadchádzajúce zápasy',rows.length,'ATP + WTA / najbližšie dni'],['Pravdepodobnosť ≥ 75 %',rows.filter(r=>r.confidence>=.75).length,'Podiel podľa aktuálneho modelu'],['Úspešnosť zverejnených',p.n?percent(p.accuracy):'—',p.n?`${p.n} vyhodnotených predikcií`:'Zatiaľ bez vyhodnotených predikcií'],['Posledná aktualizácia',data.generated_at?time(data.generated_at):'—',data.generated_at?date(data.generated_at):'Čakáme na prvé dáta']];
    $('metrics').innerHTML=cells.map((c,i)=>`<div class="metric ${i===2?'accent':''}"><span>${c[0]}</span><strong>${escape(c[1])}</strong><small>${escape(c[2])}</small></div>`).join('');
    $('navCount').textContent=rows.length;
  }
  function filtered(rows) {
    const query=$('search').value.trim().toLocaleLowerCase('sk'), surface=$('surface').value, confidence=Number($('confidence').value);
    return rows.filter(r=>(tour==='all'||r.tour===tour)&&(surface==='all'||r.surface===surface)&&r.confidence>=confidence&&`${r.player1.name} ${r.player2.name} ${r.tournament}`.toLocaleLowerCase('sk').includes(query));
  }
  function player(row,who) {const p=row[who];return `<div class="player-row ${p.id===row.winner_id?'winner':''}"><span class="player-name"><span class="initial" aria-hidden="true">${escape(p.name.slice(0,1))}</span>${escape(p.name)}</span><strong>${percent(p.probability)}</strong></div>`;}
  function card(row) {return `<article class="match-card"><div class="match-meta"><span class="pill">${escape(row.tour)}</span><span>${escape(surfaceNames[row.surface]||row.surface)}</span><time datetime="${escape(row.scheduled_at)}">${escape(date(row.scheduled_at,true))}</time></div><div class="tournament">${escape(row.tournament)}</div>${player(row,'player1')}${player(row,'player2')}<div class="probability-bar" aria-hidden="true"><span style="width:${Math.max(0,Math.min(100,Number(row.player1.probability)*100))}%"></span></div><div class="card-foot"><span><i class="quality"></i>${row.data_depth>=.6?'Širšia história hráčov':'Obmedzená história'}</span><button data-match="${escape(row.id)}">Detail zápasu ↗</button></div></article>`;}
  function matches() {
    const rows=filtered(data.upcoming || []), shown=page==='overview'?rows.slice(0,9):rows.slice(0,limit);
    if(!rows.length) return empty(data.ready?'Momentálne bez zápasov vo výbere.':'Prvé predikcie sa pripravujú.',data.ready?'Skús upraviť filtre alebo sa vráť po ďalšej aktualizácii.':'Keď bude model overený a budú dostupné zápasy, nájdeš ich tu.');
    const strip=page==='overview'?`<div class="summary-strip"><div><strong>Čísla s kontextom.</strong><p>Pri každom zápase sleduj aj hĺbku histórie a dostupnosť štatistík.</p></div><button class="button secondary" data-open="model">Ako čítať model ↗</button></div>`:'';
    return `${strip}<div class="section-head"><h2>${page==='overview'?'Najbližšie na kurte':'Predzápasový prehľad'}</h2><span>${rows.length} zápasov</span></div><div class="cards">${shown.map(card).join('')}</div>${rows.length>shown.length?'<button class="button secondary more" id="more">Zobraziť ďalšie zápasy</button>':''}`;
  }
  function results() {
    const rows=filtered(data.results || []);
    if(!rows.length)return empty('Príbeh výsledkov sa ešte píše.','Tu uvidíš vyhodnotené predikcie vrátane tých, ktoré nevyšli.');
    return `<div class="section-head"><h2>Zverejnené pred zápasom</h2><span>${rows.length} záznamov vo výbere</span></div><div class="result-list">${rows.slice(0,limit).map(r=>`<article class="result-row"><div class="result-date">${escape(date(r.scheduled_at))}<small>${escape(r.tour)}</small></div><div>${escape(r.player1.name)} — ${escape(r.player2.name)}<small>${escape(r.tournament)}</small></div><div>${percent(r.confidence)}<small>Pred zápasom</small></div><strong class="${r.result.correct?'result-good':'result-bad'}">${r.result.correct?'✓ Úspešná':'× Neúspešná'}</strong></article>`).join('')}</div>${rows.length>limit?'<button class="button secondary more" id="more">Ďalšie výsledky</button>':''}`;
  }
  const decimal = v=>Number.isFinite(v)?v.toFixed(3):'—';

  function qualityTables(report,title) {
    if(!report || !Object.keys(report).length)return '';
    const labels={surface:'Povrch',competition:'Súťaž',tournament:'Turnaj',history_band:'História oboch hráčov',surface_history_band:'História na povrchu',tour:'Okruh'};
    return `<section class="panel"><h2>${escape(title)}</h2><p class="muted">Skupiny s menej než 100 zápasmi majú malú vzorku. Interval je orientačný; väčšia história sama osebe nezaručuje správny tip.</p>${Object.entries(report).map(([dimension,groups])=>`<details><summary>${escape(labels[dimension]||dimension)}</summary><div class="table-wrap"><table><thead><tr><th>Skupina</th><th>Zápasy</th><th>Úspešnosť</th><th>95 % interval</th><th>Log loss</th><th>Vzorka</th></tr></thead><tbody>${Object.entries(groups).map(([name,m])=>`<tr><td>${escape(surfaceNames[name]||name)}</td><td>${m.n}</td><td>${percent(m.accuracy)}</td><td>${m.accuracy_ci95_wilson?.map(percent).join(' – ')||'—'}</td><td>${decimal(m.log_loss)}</td><td>${m.small_sample?'Malá':'100+ zápasov'}</td></tr>`).join('')}</tbody></table></div></details>`).join('')}</section>`;
  }

  function model() {
    const r=data.model?.report,h=r?.holdout,b=r?.elo_baseline_holdout;
    if(!h)return empty('Model sa pripravuje.','Po overení tu uvidíš výsledky testovania, porovnanie so základným modelom aj kvalitu pravdepodobností.');
    const bins=h.calibration_bins || [], selective=h.selective_accuracy || [];
    return `<div class="model-grid"><section class="panel"><p class="eyebrow">CHRONOLOGICKÉ TESTOVANIE</p><h2>Výkon na neskorších zápasoch</h2><p class="muted">${h.n} testovacích zápasov. Historický test sa odlišuje od priebežných výsledkov zverejnených predikcií.</p><table><thead><tr><th>Metrika</th><th>BlinQ</th><th>Elo základ</th></tr></thead><tbody><tr><td>Úspešnosť</td><td>${percent(h.accuracy)}</td><td>${percent(b?.accuracy)}</td></tr><tr><td>Log loss · menej je lepšie</td><td>${decimal(h.log_loss)}</td><td>${decimal(b?.log_loss)}</td></tr><tr><td>Brier skóre · menej je lepšie</td><td>${decimal(h.brier_score)}</td><td>${decimal(b?.brier_score)}</td></tr></tbody></table></section><section class="panel"><h2>Zodpovedajú percentá výsledkom?</h2><p class="muted">Porovnanie predpokladanej a skutočnej frekvencie výhier v jednotlivých pásmach.</p><div class="calibration" role="img" aria-label="Graf kalibrácie; presné hodnoty sú uvedené v tabuľke nižšie">${bins.map(v=>`<div><span style="height:${Math.max(0,Math.min(100,v.mean_probability*100))}%"></span><i style="height:${Math.max(0,Math.min(100,v.actual_win_rate*100))}%"></i><small>${Math.round(v.mean_probability*100)} %</small></div>`).join('')}</div><div class="legend"><b>Predikcia</b><em>Skutočnosť</em></div><details><summary class="muted">Presné hodnoty</summary><table><tbody>${bins.map(v=>`<tr><td>${percent(v.mean_probability)}</td><td>${percent(v.actual_win_rate)}</td><td>${v.count} zápasov</td></tr>`).join('')}</tbody></table></details></section></div><section class="panel"><h2>Vyššia istota, menší výber</h2><p class="muted">Pri vyššom prahu zostáva menej zápasov. Prahy sú pevné; nejde o odporúčanie vybrané podľa najlepšieho výsledku testu.</p><div class="table-wrap"><table><thead><tr><th>Minimálna pravdepodobnosť</th><th>Zápasy</th><th>Podiel všetkých</th><th>Úspešnosť</th></tr></thead><tbody>${selective.map(s=>`<tr><td>${percent(s.threshold)}</td><td>${s.n}</td><td>${percent(s.coverage)}</td><td>${s.n?percent(s.accuracy):'—'}</td></tr>`).join('')}</tbody></table></div></section>${qualityTables(r.subgroups,"Kvalita podľa skupín · historický test")}${qualityTables(data.performance_subgroups,"Kvalita podľa skupín · vydané predikcie")}<p class="detail-note">Verzia: ${escape(data.model.version)} · História: ${Number(data.history?.matches || 0).toLocaleString('sk-SK')} zápasov · ${escape(date(data.history?.start))} – ${escape(date(data.history?.end))}</p>`;
  }
  function account() {return `<section class="panel account-card"><p class="eyebrow">BLINQ MEMBERS</p><h2>${escape(data.account?.name || 'Môj účet')}</h2><form id="profileForm"><label>E-mail<input type="email" value="${escape(data.account?.email || '')}" disabled></label><label>Zobrazované meno<input id="profileName" value="${escape(data.account?.name || '')}" maxlength="80" required autocomplete="name"></label><button class="button primary" type="submit" ${demo?'disabled':''}>Uložiť profil</button><p id="profileMessage" role="status" class="muted"></p></form><div class="account-actions"><button id="resetFromAccount" class="button secondary" ${demo?'disabled':''}>Obnoviť heslo</button><button id="logout" class="button secondary">Odhlásiť sa</button></div></section>`;}
  function render() {
    metrics(); $('pageTitle').textContent=titles[page][0];$('pageSubtitle').textContent=titles[page][1];$('breadcrumb').textContent=`Pracovný priestor / ${names[page]}`;
    $('filters').hidden=!['overview','predictions','results'].includes(page);$('metrics').hidden=page==='account';
    document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});
    $('content').innerHTML=page==='results'?results():page==='model'?model():page==='account'?account():matches();
    $('content').querySelectorAll('[data-match]').forEach(b=>b.onclick=()=>detail(b.dataset.match));
    $('content').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>navigate(b.dataset.open));
    if($('more'))$('more').onclick=()=>{if(page==='overview')navigate('predictions');else{limit+=50;render();}};
    if($('logout'))$('logout').onclick=async()=>{if(demo){notice('Ukážkový režim nemá prihlásený účet.');return;}await BlinqAuth.signOut();data={upcoming:[],results:[],performance:{}};render();auth();};
    if($('resetFromAccount'))$('resetFromAccount').onclick=async()=>{try{await BlinqAuth.reset(data.account.email);$('profileMessage').textContent='Odkaz na obnovenie bol odoslaný.';}catch(e){$('profileMessage').textContent=e.message;}};
    if($('profileForm'))$('profileForm').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await BlinqAuth.update({data:{display_name:$('profileName').value.trim()}});await load();$('profileMessage').textContent='Profil bol uložený.';}catch(error){$('profileMessage').textContent=error.message;}finally{b.disabled=false;}};
  }
  function navigate(next) {page=next;limit=50;render();history.replaceState(null,'',`#${page}`);}
  function detail(id) {
    const row=data.upcoming.find(r=>r.id===id);if(!row)return;
    $('matchDetail').innerHTML=`<p class="eyebrow">${escape(row.tour)} · ${escape(surfaceNames[row.surface]||row.surface)}</p><h2 id="matchTitle">${escape(row.tournament)}</h2><p class="muted">${escape(date(row.scheduled_at,true))} · ${escape(row.round||'')}</p>${['player1','player2'].map(key=>`<div class="detail-player"><span>${escape(row[key].name)}</span><strong>${percent(row[key].probability)}</strong></div>`).join('')}${row.quality?`<h3>História dostupná pri predikcii</h3><p class="muted">Súťaž: ${escape(row.competition||'Neznáma')}<br>${escape(row.player1.name)}: ${Number(row.quality.player1.matches)} zápasov, na povrchu ${Number(row.quality.player1.surface_matches)}<br>${escape(row.player2.name)}: ${Number(row.quality.player2.matches)} zápasov, na povrchu ${Number(row.quality.player2.surface_matches)}<br>Počty opisujú uloženú históriu, nie všetky kariérne zápasy.</p>`:''}<h3>Súvislosti v dátach</h3><ul class="signals">${row.signals.length?row.signals.map(s=>`<li><span>${escape(s.label)}</span>${escape(row.player1.id===s.player_id?row.player1.name:row.player2.name)}</li>`).join(''):'<li>Model nemá dostatočne výrazný čiastkový signál.</li>'}</ul><p class="detail-note">${row.stats_available?'Štatistiky servisu a returnu sú dostupné pre oboch hráčov.':'Detailné štatistiky nie sú dostupné pre oboch hráčov.'}<br>Vytvorené ${escape(date(row.issued_at||row.created_at,true))}<br>Model ${escape(row.model_version)}</p>`;
    $('matchDialog').showModal();
  }
  $('closeMatch').onclick=()=>$('matchDialog').close();
  document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));
  document.querySelectorAll('[data-tour]').forEach(b=>b.onclick=()=>{tour=b.dataset.tour;document.querySelectorAll('[data-tour]').forEach(x=>x.classList.toggle('selected',x===b));render();});
  ['search','surface','confidence'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',()=>{limit=50;render();}));
  $('accountShortcut').onclick=()=>navigate('account');
  $('refresh').onclick=()=>load();
  async function load() {
    $('refresh').disabled=true;
    try{data=await BlinqAuth.feed();demo=Boolean(data.demo);$('demoBanner').hidden=!demo;$('accountShortcut').textContent=(data.account?.name||'B').slice(0,1).toUpperCase();notice(data.stale?'Dáta sú staršie než 12 hodín. Pri hodnotení predikcií skontroluj čas ich vytvorenia.':'');render();}
    catch(error){if(error.status===401){auth();notice('Pre zobrazenie predikcií sa prihlás.');}else notice('Dáta sa nepodarilo načítať. Skús obnovenie o chvíľu.');}
    finally{$('refresh').disabled=false;}
  }
  (async()=>{try{const cfg=await BlinqAuth.init();enabled=cfg.enabled;demo=Boolean(cfg.demo);const hash=location.hash.slice(1);if(titles[hash])page=hash;if(cfg.recovery){auth('recovery');return;}if(demo||await BlinqAuth.restore())await load();else{render();auth();}}catch(error){notice(error.message);render();auth();}})();
})();
