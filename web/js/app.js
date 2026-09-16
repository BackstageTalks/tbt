const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];

const [picks, results, config, messages] = await Promise.all([
  fetch('data/picks.json').then(r=>r.json()),
  fetch('data/results.json').then(r=>r.json()),
  fetch('data/config.json').then(r=>r.json()),
  fetch('data/messages.json').then(r=>r.json())
]);

let currentLevel = localStorage.getItem('blinq-demo-level') || config.defaultLevel || 'Rookie';
let activeCategory = 'TOP';
const levelRules = () => config.levels[currentLevel] || config.levels.Rookie;

const icons = {TOP:'★',VALUE:'▥',ESA:'◎',GAMES:'◒',SETS:'≡','SEE ALL':'▦'};
const descriptions = {
  TOP:'— najlepšie predikcie dňa podľa modelu',
  VALUE:'— užší value filter; kvalifikované príležitosti s vyšším edge',
  ESA:'— ESA model picks',
  GAMES:'— pripravujeme samostatný games model',
  SETS:'— pripravujeme samostatný sets model',
  'SEE ALL':'— všetky kvalifikované predikcie na jednom mieste'
};

function renderTabs(){
  const tabs = $('#categoryTabs');
  tabs.innerHTML = config.tabs.map(tab=>{
    const soon = config.comingSoon.includes(tab) ? '<span class="soon">soon</span>' : '';
    return `<button class="category-tab ${tab===activeCategory?'active':''}" data-category="${tab}"><span class="tab-icon">${icons[tab]||'•'}</span><span>${tab}</span>${soon}</button>`;
  }).join('');
  $$('.category-tab').forEach(btn=>btn.addEventListener('click',()=>{
    activeCategory=btn.dataset.category;
    renderTabs(); renderBoard();
  }));
}

function permittedPicks(category){
  const rules = levelRules();
  if(config.comingSoon.includes(category)) return [];
  if(category==='SEE ALL'){
    if(!rules.seeAll) return null;
    return picks.filter(p=>!config.comingSoon.includes(p.category)).sort((a,b)=>b.probability-a.probability);
  }
  return picks.filter(p=>p.category===category).sort((a,b)=>a.rank-b.rank).slice(0,rules.picksPerCategory);
}

function renderBoard(){
  $('#categoryTitle').textContent = activeCategory;
  $('#categoryDescription').textContent = descriptions[activeCategory] || '';
  const holder = $('#predictionRows'); const empty = $('#boardEmpty');
  holder.innerHTML=''; empty.classList.add('hidden');

  if(config.comingSoon.includes(activeCategory)){
    empty.classList.remove('hidden');
    empty.innerHTML = `<strong>${activeCategory}</strong><br><span>Coming soon — karta je už pripravená v dizajne, ale dáta sa zatiaľ nenačítavajú.</span>`;
    return;
  }

  const rows = permittedPicks(activeCategory);
  if(rows===null){
    holder.innerHTML=`<div class="locked-row"><span class="lock-pill">ELITE+</span><span>SEE ALL je dostupné od ELITE. Rookie/PRO si tieto dáta vôbec nenačítavajú.</span></div>`;
    return;
  }
  if(!rows.length){
    empty.classList.remove('hidden'); empty.textContent='V tejto kategórii dnes nie sú žiadne kvalifikované picky.'; return;
  }

  holder.innerHTML = rows.slice(0,10).map((p,i)=>`
    <div class="prediction-row">
      <span class="rank">${i+1}</span>
      <span class="time">${p.time}</span>
      <span class="tour">${p.country} ${p.tour}</span>
      <span class="match"><span class="flag">${p.opponentFlag}</span>${p.match}</span>
      <span class="pick">${p.pick}</span>
      <span class="odds">${p.odds.toFixed(2)}</span>
      <span class="probability">${p.probability}%</span>
      <span class="value">+${p.value}%</span>
      <button class="star-btn" aria-label="Obľúbené">☆</button>
      <button class="detail-btn" data-id="${p.id}">Detail <span>→</span></button>
    </div>`).join('');
  $$('.detail-btn',holder).forEach(btn=>btn.addEventListener('click',()=>openDetail(Number(btn.dataset.id))));
}

function renderResults(){
  const list=$('#resultList');
  list.innerHTML=results.map(r=>`<div class="result-row"><span>${r.date}</span><span>${r.tour}</span><span>${r.match}</span><span>${r.pick}</span><span>${r.odds.toFixed(2)}</span><span class="result-status ${r.result==='WIN'?'win':'loss'}">${r.result==='WIN'?'✓ WIN':'✕ LOSS'}</span></div>`).join('');
  const r=levelRules();
  $('#historyRule').textContent = r.resultsHours ? `${currentLevel}: história výsledkov posledných ${r.resultsHours} hodín.` : `${currentLevel}: celá história + mesačné ROI / Yield.`;
}

function renderNotifications(){
  const allowed = levelRules().live ? messages : [];
  $('#notifCount').textContent = allowed.length;
  $('#notifCount').style.display = allowed.length ? 'grid':'none';
  $('#notificationsList').innerHTML = allowed.length ? allowed.map(m=>`<div class="notification-item"><span class="notification-type ${m.type==='PREMIUM'?'premium':''}">${m.type==='LIVE'?'LIVE • COMEBACK RADAR':'PREMIUM INFO'}</span><strong>${m.title}</strong><p>${m.body}</p></div>`).join('') : `<div class="notification-item"><strong>ELITE+</strong><p>Comeback LIVE Radar a Premium Info sú dostupné od ELITE.</p></div>`;
}

function openDetail(id){
  const p=picks.find(x=>x.id===id); if(!p) return;
  $('#detailMatch').textContent=p.match; $('#detailPick').textContent=p.pick; $('#detailOdds').textContent=p.odds.toFixed(2); $('#detailProbability').textContent=`${p.probability}%`; $('#detailValue').textContent=`+${p.value}%`;
  $('#detailModal').classList.add('open'); $('#detailModal').setAttribute('aria-hidden','false');
}
$('#detailClose').addEventListener('click',()=>$('#detailModal').classList.remove('open'));
$('#detailModal').addEventListener('click',e=>{if(e.target.id==='detailModal') $('#detailModal').classList.remove('open')});

function setView(name){
  $$('.view').forEach(v=>v.classList.remove('active')); $(`#${name}View`)?.classList.add('active');
  $$('.nav-link').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  window.scrollTo({top:0,behavior:'smooth'});
}
$$('.nav-link').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));

function togglePopover(el){
  $$('.popover').forEach(p=>{if(p!==el)p.classList.remove('open')}); el.classList.toggle('open');
}
$('#notificationBtn').addEventListener('click',()=>togglePopover($('#notificationsPopover')));
$('#accountBtn').addEventListener('click',()=>togglePopover($('#accountPopover')));
$$('[data-close-popover]').forEach(b=>b.addEventListener('click',()=>b.closest('.popover').classList.remove('open')));
document.addEventListener('click',e=>{if(!e.target.closest('.popover')&&!e.target.closest('.top-actions')) $$('.popover').forEach(p=>p.classList.remove('open'))});

$('#allResultsBtn').addEventListener('click',()=>alert(levelRules().resultsHours ? `Tvoj ${currentLevel} účet má Results limit ${levelRules().resultsHours} hodín.` : 'Plná história výsledkov je dostupná.'));
$('#upgradeBtn').addEventListener('click',()=>alert('Tu sa neskôr pripojí JSON platobný link podľa levelu.'));

$('#levelLabel').textContent=currentLevel;
renderTabs();renderBoard();renderResults();renderNotifications();

// Keep loading visible just long enough to avoid blank screen on fast loads.
window.addEventListener('load',()=>setTimeout(()=>$('#bootScreen').classList.add('is-done'),520));
