const picks = [
  {id:1,featured:true,tag:'TOP VALUE',tournament:'ATP Turin · Final',match:'Jannik Sinner vs Carlos Alcaraz',pick:'Sinner to win',odds:'1.91',confidence:68,ev:'+12.4%',surface:'hard',reason:['Indoor hard profile','Serve + return edge','Strong recent form']},
  {id:2,tag:'MODEL EDGE',tournament:'WTA Finals · SF',match:'Iga Swiatek vs Aryna Sabalenka',pick:'Over 21.5 games',odds:'1.87',confidence:64,ev:'+8.1%',surface:'hard',reason:['Balanced H2H','High hold rates','Tight projected margin']},
  {id:3,tag:'FORM',tournament:'ATP Paris · QF',match:'Alexander Zverev vs Daniil Medvedev',pick:'Zverev +2.5 games',odds:'1.83',confidence:61,ev:'+6.9%',surface:'hard',reason:['Serve stability','Recent indoor form','Close price gap']},
  {id:4,tag:'VALUE',tournament:'ATP Rome · R16',match:'Casper Ruud vs Holger Rune',pick:'Ruud to win',odds:'1.78',confidence:63,ev:'+7.4%',surface:'clay',reason:['Clay win profile','Return depth','Physical edge']},
  {id:5,tag:'MATCHUP',tournament:'WTA Stuttgart · QF',match:'Coco Gauff vs Elena Rybakina',pick:'Over 22.5 games',odds:'1.92',confidence:60,ev:'+5.8%',surface:'clay',reason:['Serve contrast','Break pressure','Projected 3 sets']},
  {id:6,tag:'SURFACE',tournament:'ATP Halle · SF',match:'Jannik Sinner vs Hubert Hurkacz',pick:'Sinner 2–0',odds:'2.05',confidence:59,ev:'+5.1%',surface:'grass',reason:['Return advantage','Fast-court form','Tiebreak resilience']}
];

const tiers = [
  {name:'ROOKIE',price:'Free',desc:'Ochutnávka',features:['Selected public picks','Basic match view','Promo-supported access']},
  {name:'PRO',price:'€9.90',desc:'Full dashboard',features:['More daily picks','Core analytics','Cleaner experience']},
  {name:'ELITE',price:'€19.90',desc:'Premium starts here',features:['VIP group','See All picks','Full Overview','Premium insights'],current:true},
  {name:'LEGEND',price:'€29.90',desc:'Long-term ELITE',features:['Everything in ELITE','Results history','Advanced statistics','Long-term performance']},
  {name:'GOAT',price:'€49.90',desc:'Maximum',features:['Everything in LEGEND','Partner privileges','Banner discounts','Maximum access']}
];

const navButtons = [...document.querySelectorAll('[data-nav]')];
const views = [...document.querySelectorAll('[data-view]')];
function navigate(name){
  views.forEach(v=>v.classList.toggle('is-active', v.dataset.view===name));
  document.querySelectorAll('.nav-link,.mobile-link').forEach(b=>b.classList.toggle('is-active', b.dataset.nav===name));
  window.scrollTo({top:0,behavior:'smooth'});
  history.replaceState(null,'',`#${name}`);
}
navButtons.forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.nav)));

function renderPickCard(p){
  return `<article class="pick-card ${p.featured?'featured':''}" data-pick="${p.id}">
    <div class="pick-head"><div class="pick-title"><span class="rank-badge">${p.featured?'★':'↗'}</span><div><span class="eyebrow ${p.featured?'lime':''}">${p.tag}</span><div style="margin-top:4px;color:#718198;font-size:11px">${p.tournament}</div></div></div><div class="confidence-ring" style="--conf:${p.confidence}"><b>${p.confidence}%</b></div></div>
    ${p.id===1?'<div class="pick-photo" style="background-image:url(assets/hero-players.webp)"></div>':p.id===2?'<div class="pick-photo" style="background-image:url(assets/wta-players.webp)"></div>':''}
    <div class="pick-match"><small>MATCH</small><h3>${p.match}</h3></div>
    <div class="pick-choice"><span>OUR PICK</span><strong>${p.pick}</strong></div>
    <div class="pick-meta"><div><span>ODDS</span><strong>${p.odds}</strong></div><div><span>EV</span><strong class="positive">${p.ev}</strong></div><div><span>SURFACE</span><strong>${p.surface.toUpperCase()}</strong></div></div>
    <span class="analysis-link">View analysis →</span>
  </article>`
}
document.getElementById('pickGrid').innerHTML = picks.slice(0,3).map(renderPickCard).join('');

document.getElementById('allPicksTable').innerHTML = picks.map(p=>`<div class="board-row"><div class="match-name"><strong>${p.match}</strong><small>${p.tournament}</small></div><div>${p.pick}</div><div>${p.odds}</div><div>${p.confidence}%</div><div class="positive">${p.ev}</div><button class="table-action" data-pick="${p.id}">→</button></div>`).join('');

document.getElementById('tiers').innerHTML = tiers.map(t=>`<article class="tier-card ${t.current?'current':''}"><span class="eyebrow ${t.current?'lime':''}">${t.current?'CURRENT PLAN':'MEMBERSHIP'}</span><h3>${t.name}</h3><div style="color:#8090a6;font-size:13px">${t.desc}</div><div class="price">${t.price}${t.price.startsWith('€')?'<small style="font-size:12px;color:#6f8094"> / mo</small>':''}</div><ul>${t.features.map(f=>`<li>${f}</li>`).join('')}</ul><button class="${t.current?'secondary-btn':'primary-btn'} tier-action">${t.current?'Current plan':'Choose '+t.name}</button></article>`).join('');

const overviewList=document.getElementById('overviewList');
function renderOverview(filter='all',query=''){
  const q=query.trim().toLowerCase();
  const list=picks.filter(p=>(filter==='all'||p.surface===filter)&&(!q||`${p.match} ${p.tournament}`.toLowerCase().includes(q)));
  overviewList.innerHTML=list.length?list.map(p=>`<article class="overview-card"><div class="names"><small>${p.tournament}</small><strong>${p.match}</strong></div><div class="ov-stat"><span>MODEL</span><strong>${p.confidence}%</strong></div><div class="ov-stat"><span>EV</span><strong class="positive">${p.ev}</strong></div><div><span class="surface-tag">${p.surface}</span></div><button class="secondary-btn overview-action" data-pick="${p.id}">Analysis</button></article>`).join(''):`<div class="glass-card" style="padding:24px;color:#8090a6">No matches found.</div>`;
}
renderOverview();
let activeFilter='all';
document.getElementById('surfaceFilters').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;activeFilter=b.dataset.filter;document.querySelectorAll('.filter-chip').forEach(x=>x.classList.toggle('is-active',x===b));renderOverview(activeFilter,document.getElementById('overviewSearch').value)});
document.getElementById('overviewSearch').addEventListener('input',e=>renderOverview(activeFilter,e.target.value));

const modalBackdrop=document.getElementById('modalBackdrop');
function openAnalysis(id){
  const p=picks.find(x=>x.id===Number(id)); if(!p)return;
  document.getElementById('modalTitle').textContent=p.match;
  document.getElementById('modalContent').innerHTML=`<div class="modal-summary"><div><span>OUR PICK</span><strong>${p.pick}</strong></div><div><span>CONFIDENCE</span><strong>${p.confidence}%</strong></div><div><span>EXPECTED VALUE</span><strong class="positive">${p.ev}</strong></div></div><div class="analysis-copy"><span class="eyebrow violet">WHY BLINQ LIKES IT</span><ul>${p.reason.map(r=>`<li>${r}</li>`).join('')}</ul><p>Prototype insight: the model combines surface fit, recent form, serve/return performance and price context into one compact decision layer.</p></div>`;
  modalBackdrop.hidden=false;
  document.body.style.overflow='hidden';
}
document.addEventListener('click',e=>{const t=e.target.closest('[data-pick]');if(t)openAnalysis(t.dataset.pick)});
document.getElementById('modalClose').onclick=()=>{modalBackdrop.hidden=true;document.body.style.overflow=''};
modalBackdrop.addEventListener('click',e=>{if(e.target===modalBackdrop){modalBackdrop.hidden=true;document.body.style.overflow=''}});

const supportFab=document.getElementById('supportFab'), supportPanel=document.getElementById('supportPanel');
supportFab.onclick=()=>{supportPanel.classList.toggle('open');supportPanel.setAttribute('aria-hidden',String(!supportPanel.classList.contains('open')))};
document.getElementById('supportClose').onclick=()=>supportPanel.classList.remove('open');
document.getElementById('supportSend').onclick=()=>{document.getElementById('supportStatus').textContent='Demo sent ✓ (backend/email connection comes later).'};

let deferredPrompt; const installBtn=document.getElementById('installBtn');
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();deferredPrompt=e;installBtn.hidden=false});
installBtn.addEventListener('click',async()=>{if(!deferredPrompt)return;deferredPrompt.prompt();await deferredPrompt.userChoice;deferredPrompt=null;installBtn.hidden=true});

if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(()=>{}));}
const initial=(location.hash||'#home').slice(1); if(document.querySelector(`[data-view="${initial}"]`)) navigate(initial);
