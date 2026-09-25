/* BlinQ visual revision: green-login-loader-20260924; public-green-backdrop-20260924 */
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = { feed: {upcoming:[],results:[],performance:{},history:{},model:null}, ui:null, uiSource:null, route:'predictions', page:0, showAll:false, authMode:'login', authEnabled:true, draftLoaded:false, selectedElement:'HERO_BANNER_1', adminPlan:'rookie', adminTab:'accounts', adminUsers:null, adminUsersLoading:false, adminUsersError:'', adminDiagnostics:null, adminDiagnosticsLoading:false, adminSelectedUser:null, adminUsersWarning:'', adminUserFilters:{q:'',plan:'all',status:'all',sort:'email'}, previewPlan:null, newsPool:[], bannerObserver:null, bannerTimers:new WeakMap(), runtimeConfigLoaded:false, resultsFilters:{category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:''}, resultsPage:0, resultsPageSize:50, marketPage:{top_daily:0,value:0,doubles:0,ace:0,sg:0}, dashboardVisibility:null, demoFeedBackup:null, demoMode:false, heroIndex:0, heroTimer:null, heroPaused:false, adminPreviewIndex:0, adminPreviewPaused:false, adminPreviewTimer:null, dailyHubTab:'daily', dailyHubExpanded:false, dashboardSearch:'', dailyHubTournament:'', dailyHubSelected:{daily:'',prime:'',top:'',value:'',ace:'',double_faults:'',games:'',sets:'',doubles:'',board:''}, insights:[], insightsUnread:0, insightsLoading:false, insightsStorageUnavailable:false, insightDrawerOpen:false, insightFilter:'all', insightChannel:'info', liveRadarTab:'comeback', adminInsights:null, adminInsightsLoading:false, adminInsightsError:'', adminInsightEditingId:'', adminLiveRadarStatus:null, adminLiveRadarLoading:false, userLiveRadarStatus:null, userLiveRadarLoading:false, liveRadarHeartbeat:null, privateUpdatesLastPoll:0, privateUpdatesBusy:false, presentationConfig:null, siteContent:null, pushConfig:null, pushBusy:false };
  const pageSize = () => innerWidth >= 1700 ? 6 : innerWidth >= 1450 ? 5 : innerWidth >= 1200 ? 4 : innerWidth >= 900 ? 3 : 1;
  const dashboardCardsPerPanel = () => 1; // v6.5.16: dashboard is a lightweight one-pick preview; See more opens 3–5 picks.
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const pct = value => `${(Number(value || 0) * (Number(value || 0) <= 1 ? 100 : 1)).toFixed(1)}%`;
  const number = (value, digits=3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const fmtTime = value => value ? new Intl.DateTimeFormat(localeTag,{hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : publicText('TBA');
  const fmtDate = value => value ? new Intl.DateTimeFormat(localeTag,{day:'2-digit',month:'short',year:'numeric'}).format(new Date(value)) : '—';
  const fmtCompactDate = value => {
    if(!value)return '—';
    const d=new Date(value);if(Number.isNaN(d.getTime()))return '—';
    const parts=new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'2-digit',year:'2-digit'}).formatToParts(d);
    const get=type=>parts.find(part=>part.type===type)?.value||'';
    return `${get('day')}.${get('month')}.${get('year')}`;
  };
  function timeDateHtml(value,wrapperClass='hub-time-stack'){
    return `<span class="${escapeHtml(wrapperClass)}"><strong>${escapeHtml(fmtTime(value))}</strong><small>${escapeHtml(fmtCompactDate(value))}</small></span>`;
  }
  const fmtToday = () => new Intl.DateTimeFormat(localeTag,{weekday:'short',day:'2-digit',month:'short',year:'numeric'}).format(new Date());
  const fmtClock = () => new Intl.DateTimeFormat(localeTag,{hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());
  const initials = name => String(name || 'B').trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase();
  const countryAlpha3To2 = {ALB:'AL',ARG:'AR',AUS:'AU',AUT:'AT',BEL:'BE',BGR:'BG',BIH:'BA',BLR:'BY',BRA:'BR',CAN:'CA',CHE:'CH',CHL:'CL',CHN:'CN',COL:'CO',CRO:'HR',CZE:'CZ',DEU:'DE',DEN:'DK',DOM:'DO',ECU:'EC',EGY:'EG',ESP:'ES',EST:'EE',FIN:'FI',FRA:'FR',GBR:'GB',GEO:'GE',GRC:'GR',HKG:'HK',HUN:'HU',IDN:'ID',IND:'IN',IRL:'IE',IRN:'IR',ISR:'IL',ITA:'IT',JPN:'JP',KAZ:'KZ',KOR:'KR',LBN:'LB',LTU:'LT',LUX:'LU',LVA:'LV',MAR:'MA',MDA:'MD',MEX:'MX',MKD:'MK',MNE:'ME',NLD:'NL',NOR:'NO',NZL:'NZ',PER:'PE',PHL:'PH',POL:'PL',PRT:'PT',ROU:'RO',RUS:'RU',SAU:'SA',SRB:'RS',SVK:'SK',SVN:'SI',SWE:'SE',THA:'TH',TUN:'TN',TUR:'TR',TPE:'TW',TWN:'TW',UKR:'UA',URY:'UY',USA:'US',UZB:'UZ',VEN:'VE',ZAF:'ZA'};
  const normalizeCountryCode = code => { const value=String(code||'').trim().toUpperCase(); if(/^[A-Z]{2}$/.test(value))return value; if(/^[A-Z]{3}$/.test(value)&&countryAlpha3To2[value])return countryAlpha3To2[value]; return ''; };
  const flagEmoji = code => { const value=normalizeCountryCode(code); if(!value)return ''; return [...value].map(ch=>String.fromCodePoint(127397+ch.charCodeAt(0))).join(''); };
  const flagAssetUrl = code => { const value=normalizeCountryCode(code); return value?`/assets/flags/${value.toLowerCase()}.png`:''; };
  function flagIconHtml(code, compact=false){
    const value=normalizeCountryCode(code);if(!value)return '';
    const src=flagAssetUrl(value),cls=compact?' country-flag hub-flag is-compact':' country-flag hub-flag';
    return `<span class="${cls.trim()}" title="${escapeHtml(value)}" aria-label="${escapeHtml(value)}"><img data-flag-image src="${escapeHtml(src)}" alt="" loading="lazy" referrerpolicy="no-referrer"><span class="country-flag-fallback" hidden>${escapeHtml(value)}</span></span>`;
  }
  function playerMetaHtml(rank,country,tour=''){
    const rankValue=Number(rank),rankText=Number.isFinite(rankValue)&&rankValue>0?`#${Math.trunc(rankValue)}`:'—';
    const tourText=String(tour||'').trim().toUpperCase();
    return `${flagIconHtml(country,true)}<span class="player-rank-number">${escapeHtml(rankText)}</span>${tourText?`<span class="player-rank-tour">${escapeHtml(tourText)}</span>`:''}`;
  }
  const safePhotoUrl = value => { const url=String(value||'').trim(); if(/^\/assets\/[A-Za-z0-9_.\/-]+(?:\?[A-Za-z0-9_=&.%-]+)?$/.test(url)&&!url.split('?')[0].split('/').includes('..'))return url; if(/^\/api\/v1\/(?:tournament-logo|player-image)\/[0-9]{1,12}$/.test(url))return url; if(/^\/api\/v1\/media\/[A-Za-z0-9._-]+(?:\?[A-Za-z0-9_=&.%-]+)?$/.test(url))return url; if(/^https:\/\//i.test(url)){try{const parsed=new URL(url);if(parsed.protocol==='https:'&&parsed.host&&!parsed.username&&!parsed.password)return parsed.href;}catch{}} return ''; };
  const safeUiAsset = value => { const url=String(value||'').trim(); if(!/^\/assets\/[A-Za-z0-9_.\/-]+$/.test(url)||url.split('/').includes('..'))return ''; return url; };
  const webPatch = () => String(document.querySelector('meta[name="blinq-web-patch"]')?.content||'736').trim();
  const versionedPlayerAsset = value => { const url=String(value||'').trim(); return /^\/assets\/(?:players\/|missing_foto_)/.test(url)?`${url}${url.includes('?')?'&':'?'}p=${encodeURIComponent(webPatch())}`:url; };
  const avatarAssetSrc = value => { const url=safeUiAsset(value); return url ? `${url}?v=v6544` : ''; };
  function playerFallbackUrl(tour,gender=''){
    const key=String(tour||'').trim().toLowerCase();
    const g=String(gender||'').trim().toLowerCase();
    const map=state.ui?.assets?.player_fallback||{};
    const women=safeUiAsset(map.wta)||'/assets/missing_foto_w.webp';
    const men=safeUiAsset(map.atp)||'/assets/missing_foto_m.webp';
    if(g.startsWith('f')||g.startsWith('w')||key.startsWith('wta'))return women;
    return men;
  }
  function playerPhotoSource(row,player,side=''){
    const key=String(side||'').trim();
    const presentation=player?.presentation&&typeof player.presentation==='object'?player.presentation:{};
    const candidates=[
      player?.photo_url,player?.image_url,player?.photo,player?.headshot_url,player?.avatar_url,
      player?.image,presentation?.photo_url,presentation?.image_url,presentation?.photo,presentation?.image,
      presentation?.headshot_url,presentation?.avatar_url,presentation?.cached_photo_url,
      key&&row?.[`${key}_photo_url`],key&&row?.[`${key}_image_url`],key&&row?.[`${key}_photo`],key&&row?.[`${key}_image`],key&&row?.[`${key}_headshot_url`],key&&row?.[`${key}_avatar_url`]
    ];
    for(const candidate of candidates){const safe=safePhotoUrl(candidate);if(safe)return safe;}
    return '';
  }
  function playerAvatarParts(photo,name,tour,gender=''){
    const safeBase=safePhotoUrl(photo);
    const fallbackBase=playerFallbackUrl(tour,gender);
    const actual=safeBase&&safeBase!==fallbackBase?versionedPlayerAsset(safeBase):'';
    const fallback=versionedPlayerAsset(fallbackBase);
    const initial=initials(name);
    const fallbackClass=fallbackBase.includes('missing_foto_w.webp')?'player-fallback-wta':'player-fallback-atp';
    return {actual,fallback,initial,fallbackClass};
  }
  function playerAvatarInnerHtml(parts){
    return `<span class="player-avatar-initials" aria-hidden="true">${escapeHtml(parts.initial)}</span>${parts.fallback?`<img class="player-avatar-fallback" data-player-fallback src="${escapeHtml(parts.fallback)}" alt="" loading="lazy">`:''}${parts.actual?`<img class="player-avatar-photo" data-player-photo src="${escapeHtml(parts.actual)}" alt="" loading="lazy">`:''}`;
  }
  function playerAvatarHtml(photo,name,tour,gender='',wrapperClass='player-avatar'){
    const parts=playerAvatarParts(photo,name,tour,gender);
    const hasImage=Boolean(parts.fallback||parts.actual);
    return `<span class="${escapeHtml(wrapperClass)} layered-player-avatar ${parts.fallbackClass}${hasImage?' has-photo':''}">${playerAvatarInnerHtml(parts)}</span>`;
  }
  function applyPlayerAvatarHost(host,photo,name,tour,gender=''){
    if(!host)return;
    const parts=playerAvatarParts(photo,name,tour,gender);
    host.classList.remove('has-photo','player-fallback-wta','player-fallback-atp','using-fallback','using-initials');
    host.classList.add('layered-player-avatar',parts.fallbackClass);
    if(parts.fallback||parts.actual)host.classList.add('has-photo');
    host.innerHTML=playerAvatarInnerHtml(parts);
  }
  function handleAssetImageError(event){
    const img=event?.target;
    if(!(img instanceof HTMLImageElement))return;
    if(img.matches('[data-flag-image]')){
      img.hidden=true;
      const fallback=img.nextElementSibling;
      if(fallback)fallback.hidden=false;
      return;
    }
    if(img.matches('[data-tournament-logo]')){
      const host=img.parentElement;
      if(host)host.classList.add('logo-failed');
      img.remove();
      return;
    }
    if(img.matches('[data-player-photo]')){
      img.hidden=true;
      const host=img.parentElement;
      if(host)host.classList.add('using-fallback');
      return;
    }
    if(img.matches('[data-player-fallback]')){
      const host=img.parentElement;
      // An Admin-configured fallback can point to an old or missing asset.
      // Retry the shipped local ATP/WTA fallback once before showing initials.
      const localFallback=host?.classList.contains('player-fallback-wta')
        ?'/assets/missing_foto_w.webp':'/assets/missing_foto_m.webp';
      if(img.dataset.localFallbackRetry!=='1' &&
         new URL(img.src,location.href).pathname!==localFallback){
        img.dataset.localFallbackRetry='1';
        img.src=localFallback;
        return;
      }
      img.hidden=true;
      if(host){
        host.classList.remove('has-photo','using-fallback');
        host.classList.add('using-initials');
      }
    }
  }
  document.addEventListener('error',handleAssetImageError,true);
  // Layered avatar contract: real photo -> local ATP/WTA fallback -> initials.
  // The fallback stays mounted underneath the real photo, so a cached/late 404
  // can never leave the avatar blank or require a second asynchronous src swap.
  function accountAvatarUrl(account){
    const admin=Boolean(account?.is_admin||String(account?.role||'').toLowerCase()==='admin');
    const configuredPlan=String(state.ui?.assets?.admin_avatar_plan||'goat').trim().toLowerCase();
    const plan=admin?configuredPlan:String(account?.plan||'').trim().toLowerCase();
    const variant=String(account?.avatar_variant||'').trim().toLowerCase();
    const entry=state.ui?.assets?.account_avatars?.[plan];
    if(!entry||typeof entry!=='object')return '';
    if(entry.default)return avatarAssetSrc(entry.default);
    return ['m','w'].includes(variant)?avatarAssetSrc(entry[variant]):avatarAssetSrc(entry.m||entry.w);
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
  const playerMetaLabel = (rank,country) => [normalizeCountryCode(country),Number.isFinite(Number(rank))&&Number(rank)>0?`#${Math.trunc(Number(rank))}`:''].filter(Boolean).join(' ');
  const confidenceBand = p => p >= .80 ? 'very-high' : p >= .70 ? 'high' : p >= .60 ? 'medium' : 'low';
  const confidenceLabel = band => publicText(band==='very-high'?'VERY HIGH':String(band||'MODEL').toUpperCase());
  function remainingLabel(value){
    if(!value)return '';
    const ms=new Date(value).getTime()-Date.now();if(!Number.isFinite(ms)||ms<=0)return publicText('ending');
    const hours=Math.ceil(ms/3600000),days=Math.floor(hours/24),rest=hours%24;
    return publicText(days?`${days}d ${rest}h`:`${hours}h`);
  }

  async function getJSON(url,{timeoutMs=4000}={}) {
    const controller=typeof AbortController!=='undefined'?new AbortController():null;
    let timer=null;
    if(controller&&Number(timeoutMs)>0)timer=setTimeout(()=>controller.abort(),Math.max(250,Number(timeoutMs)||4000));
    try{
      const response=await fetch(url,{headers:{Accept:'application/json'},cache:'no-store',signal:controller?.signal});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
      return data;
    }catch(error){
      if(error?.name==='AbortError'){const timeout=new Error(`Request timed out: ${url}`);timeout.code='UI_REQUEST_TIMEOUT';throw timeout;}
      throw error;
    }finally{if(timer)clearTimeout(timer);}
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
  const membershipHierarchy = ['rookie','pro','elite','legend','goat'];
  const accessContexts = ['expired',...membershipHierarchy];
  const requestedLocale = String(new URLSearchParams(location.search).get('lang')||'').toLowerCase();
  // v6.5.13: the public site is Slovak-first. Czech and English are optional public mutations.
  // Internal identifiers, API payloads and Admin remain English.
  const locale = ['sk','cz','en'].includes(requestedLocale) ? requestedLocale : 'sk';
  const localeTag = ({sk:'sk-SK',cz:'cs-CZ',en:'en-GB'})[locale] || 'sk-SK';
  document.documentElement.lang = locale==='cz' ? 'cs' : locale;
  const PUBLIC_TRANSLATIONS = {
    // English also translates legacy Slovak release/CMS strings. This keeps old
    // published runtime content readable while new public copy uses English as
    // the neutral source language for SK/CZ translation.
    en: {
      'Preskočiť na obsah':'Skip to content','BlinQ potrebuje JavaScript.':'BlinQ requires JavaScript.','Dostupné od ELITE':'Available from ELITE','Upgrade pre plný prístup.':'Upgrade for full access.',
      'Načítavam BlinQ Intelligence':'Loading BlinQ Intelligence','Načítavam model · dáta · dnešné predikcie':'Loading model · data · today’s predictions','Hlavná navigácia':'Main navigation','Rýchla navigácia':'Quick navigation',
      'Predikcie':'Predictions','Účet':'Account','Člen':'Member','Aktívne':'Active','Admin centrum':'Admin center','Otvoriť menu účtu':'Open account menu','Odhlásiť sa':'Sign out','Ukončiť reláciu':'End this session','TENISOVÁ ANALYTIKA':'TENNIS INTELLIGENCE','Prehľad':'Dashboard','BlinQ prehľad':'BlinQ overview',
      'Dnešné predikcie':'Today’s predictions','Dnešný výber':'Today’s selection','TOP · VALUE · jeden board':'TOP · VALUE · one board','Zobraziť celú ponuku':'Show full offer','V tejto kategórii zatiaľ nie sú dostupné predikcie.':'No predictions are available in this category yet.',
      'BlinQ Telegram skupiny':'BlinQ Telegram groups','Telegram skupiny':'Telegram groups','Oficiálne BlinQ kanály pre komunitu, VIP obsah a prevádzkové informácie.':'Official BlinQ channels for the community, VIP content and service updates.',
      'Novinky, diskusia a oznámenia z BlinQ.':'News, discussion and BlinQ announcements.','Extra info picky a prémiové upozornenia pre ELITE a vyššie úrovne.':'Extra info picks and premium alerts for ELITE and higher tiers.','Otvoriť Telegram':'Open Telegram','Otvoriť VIP skupinu':'Open VIP group','KOMUNITA':'COMMUNITY',
      'Doplň odkaz v Admin → Telegram':'Add the link in Admin → Telegram','Vyžaduje ELITE':'Requires ELITE','Všetky systémy funkčné':'All systems operational','Aktualizácia modelu: —':'Model update: —','JAZYK':'LANGUAGE','Zavrieť':'Close','Zavrieť BlinQ Insights':'Close BlinQ Insights',
      'Prihlás sa do svojho analytického priestoru':'Sign in to your analytics workspace','Súhlasím s':'I agree to','a beriem na vedomie':'and acknowledge','Telegram prezývka':'Telegram nickname','Zadaj svoj e-mail':'Enter your email','Heslo':'Password','Zadaj svoje heslo':'Enter your password','Zobraziť':'Show','Súhlasím s':'I agree to','Podmienkami používania':'Terms of Use','a beriem na vedomie':'and acknowledge','Ochranu súkromia':'Privacy Policy',
      'Prihlásiť sa':'Sign in','Vytvoriť účet':'Create account','Zabudnuté heslo':'Forgot password','Poslať overovací e-mail znova':'Resend verification email','Súkromie a cookies':'Privacy and cookies','Viac o cookies':'More about cookies','Iba nevyhnutné':'Essential only','Povoliť analytiku':'Allow analytics',
      'Zavrieť účet':'Close account','Analýza zápasu':'Match analysis','Zavrieť detail':'Close detail','Naša predikcia':'Our prediction','Detail →':'Details →','TOP a VALUE predikcie v jednom rýchlom dátovom boarde.':'TOP and VALUE predictions in one fast data board.',
      'ČAS':'TIME','TURNAJ':'TOURNAMENT','ZÁPAS':'MATCH','PREDIKCIA':'PREDICTION','KURZ':'ODDS','PROJEKCIA':'PROJECTION','ISTOTA':'CONFIDENCE'
    },
    sk: {
      'Skip to content':'Preskočiť na obsah','Close navigation':'Zavrieť navigáciu','Open navigation':'Otvoriť navigáciu',
      'Main navigation':'Hlavná navigácia','Quick navigation':'Rýchla navigácia','Language versions':'Jazykové verzie',
      'Dashboard':'Prehľad','Prime Predictions':'Short Odds','Short Odds':'Short Odds','TOP Predictions':'TOP','Value Predictions':'Value','Doubles':'Štvorhra','Ace Predictions':'Esá','S/G Predictions':'Sety / hry','Results':'Výsledky',
      'Plans':'Plány','Upgrade':'Upgrade','Level':'Úroveň','Remaining':'Zostáva','Account':'Účet','Account & membership':'Účet a členstvo','Profile, access and plans':'Profil, prístup a plány','Sign out':'Odhlásiť sa','End this session':'Ukončiť túto reláciu',
      'Sign in to your analytics workspace':'Prihlás sa do svojho analytického priestoru','Get access':'Získaj prístup','Restore your access':'Obnov svoj prístup','Set a new password':'Nastav nové heslo',
      'Welcome back.':'Vitaj späť.','Sign in to your tennis intelligence workspace.':'Prihlás sa do svojho tenisového analytického priestoru.','Create your BlinQ account.':'Vytvor si účet BlinQ.','Create an account to access your BlinQ workspace.':'Vytvor si účet a získaj prístup do BlinQ.','Restore access.':'Obnov prístup.','We will send a password recovery link to your email.':'Na e-mail ti pošleme odkaz na obnovenie hesla.','Set a new password.':'Nastav nové heslo.','Choose a password with at least eight characters.':'Zvoľ heslo s minimálne ôsmimi znakmi.',
      'Display name':'Zobrazované meno','Email':'E-mail','Password':'Heslo','Enter your email':'Zadaj svoj e-mail','Enter your password':'Zadaj svoje heslo','Show':'Zobraziť','Hide':'Skryť','Show password':'Zobraziť heslo','Hide password':'Skryť heslo','Sign in':'Prihlásiť sa','Create account':'Vytvoriť účet','Back to sign in':'Späť na prihlásenie','Forgot password':'Zabudnuté heslo','Resend verification email':'Poslať overovací e-mail znova','Send recovery link':'Poslať odkaz na obnovu','Save password':'Uložiť heslo','Working…':'Pracujem…','Authentication is temporarily unavailable.':'Prihlasovanie je dočasne nedostupné.',
      'Verification email sent. Open the link in your inbox, then sign in.':'Overovací e-mail bol odoslaný. Otvor odkaz v správe a potom sa prihlás.','Your email is not verified yet. Open the verification link or resend the email.':'Tvoj e-mail ešte nie je overený. Otvor overovací odkaz alebo si pošli e-mail znova.','Verify your email before opening BlinQ. You can resend the verification email below.':'Pred otvorením BlinQ over svoj e-mail. Overovací e-mail si môžeš poslať znova nižšie.','Sending verification email…':'Odosielam overovací e-mail…','Verification email sent again. Check your inbox and spam folder.':'Overovací e-mail bol odoslaný znova. Skontroluj doručenú poštu aj spam.','If the account exists, check your email for the recovery link.':'Ak účet existuje, skontroluj e-mail s odkazom na obnovu.',
      'Your account':'Tvoj účet','YOUR ACCOUNT':'TVOJ ÚČET','CURRENT ACCESS':'AKTUÁLNY PRÍSTUP','Email verified':'E-mail overený','Email not verified':'E-mail nie je overený','Legacy admin · verify email':'Legacy admin · over e-mail','Telegram nick':'Telegram prezývka','Avatar style':'Typ avatara','Default':'Predvolený','Male':'Muž','Female':'Žena','Save profile':'Uložiť profil','Reset password':'Obnoviť heslo','Saving…':'Ukladám…','Profile updated.':'Profil bol uložený.','Sending recovery email…':'Odosielam e-mail na obnovu…','Password reset email sent.':'E-mail na obnovu hesla bol odoslaný.','BLINQ MEMBERSHIP':'BLINQ ČLENSTVO','Available plans':'Dostupné plány','Choose the access level that fits your workflow. Plans without an active checkout stay visible but cannot be purchased online yet.':'Vyber si úroveň prístupu. Plány bez aktívnej platby zostávajú viditeľné, ale zatiaľ ich nemožno kúpiť online.','Current plan':'Aktuálny plán','CURRENT PLAN':'AKTUÁLNY PLÁN','INVITE ONLY':'LEN NA POZVÁNKU','Invite only':'Len na pozvánku','Request invite':'Požiadať o pozvánku','Open plan':'Otvoriť plán','Lifetime access':'Doživotný prístup','Active':'Aktívne','No active access':'Bez aktívneho prístupu','Rookie Trial':'Rookie','Lifetime':'Doživotne','Active membership':'Aktívne členstvo','Expired':'Platnosť skončila','Access':'Prístup','Validity':'Platnosť','Member since':'Člen od','Security':'Zabezpečenie','Verified email':'Overený e-mail','Legacy admin access':'Legacy admin prístup','Verification required':'Vyžaduje sa overenie',
      'LIVE · Connecting…':'LIVE · Pripájam…','Auto-refresh on':'Automatické obnovenie zapnuté','Refresh':'Obnoviť','Live · updated':'Live · aktualizované','picks':'predikcií','published':'publikovaných','settled':'vyhodnotených','See more':'Zobraziť viac','See more →':'Zobraziť viac →','Loading Short Odds…':'Načítavam Short Odds…','All Tours':'Všetky okruhy','All Tournaments':'Všetky turnaje','All Surfaces':'Všetky povrchy','All Confidence':'Všetky úrovne istoty',
      'Unlock this pick':'Odomkni túto predikciu','Upgrade to unlock →':'Upgrade pre odomknutie →','Model signal':'Signál modelu','Overall performance':'Celková výkonnosť','Surface strength':'Sila na povrchu','Recent form':'Aktuálna forma','Head to head':'Vzájomné zápasy','Current market snapshot':'Aktuálny stav trhu','Odds':'Kurz','Model edge':'Výhoda modelu','Model signals':'Signály modelu','supports pick':'podporuje predikciu','counter-signal':'protisignál','No secondary signals are available.':'Nie sú dostupné žiadne sekundárne signály.','History':'História','Surface':'Povrch','Data depth':'Hĺbka dát',
      'Category':'Kategória','All published':'Všetky publikované','Tour':'Okruh','Period':'Obdobie','All time':'Celé obdobie','24 hours':'24 hodín','7 days':'7 dní','30 days':'30 dní','90 days':'90 dní','Date':'Dátum','Match':'Zápas','Pick':'Predikcia','Probability':'Pravdepodobnosť','Result':'Výsledok','Units':'Jednotky','WON':'VÝHRA','LOST':'PREHRA','VOID':'VOID','Record':'Bilancia','Hit rate':'Úspešnosť','ROI':'ROI','Vyhodnotené predikcie':'Vyhodnotené predikcie','Observed results':'Pozorované výsledky','Lower is better':'Nižšie je lepšie','Probability quality':'Kvalita pravdepodobnosti',
      'TENNIS INTELLIGENCE':'TENISOVÁ ANALYTIKA','MATCH WINNER':'VÍŤAZ ZÁPASU','CONFIDENCE FIRST':'ISTOTA NA PRVOM MIESTE','VALUE EDGE':'VALUE VÝHODA','SETTLED PREDICTIONS':'VYHODNOTENÉ PREDIKCIE','BLINQ MEMBERS':'BLINQ ČLENSTVO','LEARN':'INFO','How BlinQ Works':'Ako funguje BlinQ','Methodology':'Metodika','Model & Data':'Model a dáta','Responsible Use':'Zodpovedné používanie',
      'Short Odds rule':'Pravidlo Short Odds','TOP Predictions rule':'Pravidlo TOP predikcií','Value rule':'Pravidlo Value','Doubles model':'Model štvorhry','Aces / Double Faults':'Esá / dvojchyby','Sets / Games':'Sety / hry','Projection only.':'Iba projekcia.','No published data are available for this section yet.':'Pre túto sekciu zatiaľ nie sú dostupné publikované dáta.','No Short Odds predictions available yet. This board updates automatically when new predictions qualify.':'Short Odds zatiaľ nie sú dostupné. Prehľad sa automaticky aktualizuje, keď sa kvalifikujú nové predikcie.','No TOP predictions available yet. New qualifying predictions appear automatically.':'TOP predikcie zatiaľ nie sú dostupné. Nové kvalifikované predikcie sa zobrazia automaticky.','No Value predictions available yet. We are waiting for qualifying opportunities.':'Value predikcie zatiaľ nie sú dostupné. Čakáme na kvalifikované príležitosti.','No Doubles predictions have been published yet.':'Predikcie pre štvorhru zatiaľ neboli publikované.','No Ace predictions available yet. New projections appear automatically.':'Predikcie pre esá zatiaľ nie sú dostupné. Nové projekcie sa zobrazia automaticky.','No Sets / Games predictions available yet. New projections appear automatically.':'Predikcie pre sety / hry zatiaľ nie sú dostupné. Nové projekcie sa zobrazia automaticky.','No settled published predictions match these filters yet.':'Týmto filtrom zatiaľ nezodpovedajú žiadne vyhodnotené publikované predikcie.','No upcoming tournament coverage is currently published.':'Momentálne nie je publikované pokrytie nadchádzajúcich turnajov.','No upcoming players are currently published.':'Momentálne nie sú publikovaní žiadni nadchádzajúci hráči.',
      'BlinQ Prediction':'BlinQ predikcia','Prime predictions':'Short Odds','Short Odds predictions':'Short Odds','TOP predictions':'TOP','Value predictions':'Value','Štvorhra':'Štvorhra','Esá':'Esá','Sety / hry':'Sety / hry','Výsledky':'Výsledky',
      'LANGUAGE':'JAZYK','Live model':'Live model','Production feed':'Produkčný feed','This data is provided for informational and analytical purposes only. Powered by BackstageTalks Statistical Engine.':'Tieto dáta slúžia iba na informačné a analytické účely. Powered by BackstageTalks Statistical Engine.',
      'More published predictions':'Viac publikovaných predikcií','Full card details':'Kompletné detaily karty','See all access':'Prístup ku všetkým predikciám','View membership options →':'Zobraziť možnosti členstva →','UNLOCK MORE WITH BLINQ':'ODOMKNI VIAC S BLINQ',
      'Tennis insights for a smarter tomorrow.':'Tenisové dáta pre lepšie rozhodnutia.','COMMUNITY':'KOMUNITA','Join our Telegram Community':'Pridaj sa do Telegram komunity','News · Predictions · Discussions':'Novinky · Predikcie · Diskusie','JOIN':'PRIDAŤ SA','Premium Predictions':'Prémiové predikcie','Higher value. Better decisions.':'Vyššia hodnota. Lepšie rozhodnutia.','OPEN':'OTVORIŤ','RESULTS & STATS':'VÝSLEDKY A ŠTATISTIKY','Track performance':'Sleduj výkonnosť','Transparent. Verified.':'Transparentné. Overené.','VIEW':'ZOBRAZIŤ','Data. Analysis.':'Dáta. Analýza.','Better Decisions.':'Lepšie rozhodnutia.','Advanced tennis intelligence for informed players.':'Pokročilá tenisová analytika pre informované rozhodnutia.','Join the BlinQ':'Pridaj sa do BlinQ','Telegram Community':'Telegram komunity','Track performance.':'Sleduj výkonnosť.','Stay informed.':'Maj prehľad.','Transparent model results and published statistics.':'Transparentné výsledky modelu a publikované štatistiky.','SEE RESULTS':'VÝSLEDKY','BLINQ NEWS':'BLINQ NOVINKY','Updates & releases':'Novinky a aktualizácie','Product news and new features.':'Novinky produktu a nové funkcie.','BLINQ PARTNER':'BLINQ PARTNER','Your campaign.':'Tvoja kampaň.','Your message.':'Tvoja správa.','Assign a campaign, image, link and schedule in Admin.':'V Adminovi nastav kampaň, obrázok, odkaz a časovanie.',
      'Incorrect email or password.':'Nesprávny e-mail alebo heslo.','An account with this email already exists.':'Účet s týmto e-mailom už existuje.','Choose a stronger password with at least eight characters.':'Zvoľ silnejšie heslo s minimálne ôsmimi znakmi.','Enter a valid email address.':'Zadaj platnú e-mailovú adresu.','Too many attempts. Try again later.':'Príliš veľa pokusov. Skús to neskôr.','This account has been disabled.':'Tento účet bol deaktivovaný.','Verify your email before opening the BlinQ workspace.':'Pred otvorením BlinQ over svoj e-mail.','Your session expired. Sign in again.':'Tvoja relácia vypršala. Prihlás sa znova.','Your session is no longer valid. Sign in again.':'Tvoja relácia už nie je platná. Prihlás sa znova.',
      '✓ Email verified':'✓ E-mail overený','! Email not verified':'! E-mail nie je overený','! Legacy admin · verify email':'! Legacy admin · over e-mail','← Dashboard':'← Prehľad','Loading current model predictions…':'Načítavam aktuálne predikcie modelu…','Data could not be refreshed. Please try again.':'Dáta sa nepodarilo obnoviť. Skús to znova.','Published data is older than 12 hours. Check prediction creation times before evaluating them.':'Publikované dáta sú staršie ako 12 hodín. Pred vyhodnotením skontroluj čas vytvorenia predikcií.','Managed manually':'Spravované manuálne','Production feed':'Produkčný feed','Production':'Produkcia','Member':'Člen','BlinQ User':'Používateľ BlinQ',
      'Short Odds Prediction':'Short Odds','Value Prediction':'Value predikcia','Ace / DF Prediction':'Predikcia es / dvojchýb','Set / Game Prediction':'Predikcia setu / hry','TOP Prediction':'TOP predikcia','Sets Projection':'Projekcia setov','Games Projection':'Projekcia hier','Ace / DF Projection':'Predikcia es / dvojchýb','Projection':'Predikcia','Projection only · no odds':'Iba projekcia · bez kurzu','Baseline':'Základ','Gap':'Rozdiel','Score':'Skóre','Opponent proj.':'Projekcia súpera','Data':'Dáta','games':'hier','proj.':'proj.','MODEL':'MODEL','VERY HIGH':'VEĽMI VYSOKÁ','HIGH':'VYSOKÁ','MEDIUM':'STREDNÁ','LOW':'NÍZKA','PROJECTION':'PREDIKCIA',
      'No published predictions are available in this section yet.':'V tejto sekcii zatiaľ nie sú dostupné publikované predikcie.','Data not connected':'Dáta nie sú pripojené','No demo or fabricated predictions are shown.':'Nezobrazujú sa žiadne demo ani vymyslené predikcie.',
      'Entry access to the BlinQ workspace.':'Základný prístup do BlinQ.','Start with BlinQ':'Začni s BlinQ','Core predictions':'Hlavné predikcie','Core predictions + expanded daily board.':'Hlavné predikcie a rozšírený denný prehľad.','Advanced analytics':'Pokročilá analytika','Expanded analytical access for users who follow more matches and context.':'Rozšírený analytický prístup pre používateľov, ktorí sledujú viac zápasov a kontextu.','Maximum public access':'Najvyšší verejný prístup','The highest publicly available BlinQ tier.':'Najvyššia verejne dostupná úroveň BlinQ.','Private all-access':'Súkromný plný prístup','Lifetime access · All BlinQ features. Private top-tier access for selected members.':'Doživotný prístup · Všetky funkcie BlinQ. Súkromná najvyššia úroveň pre vybraných členov.','Choose Rookie':'Vybrať Rookie','Upgrade to PRO':'Prejsť na PRO','Choose Elite':'Vybrať Elite','Choose Legend':'Vybrať Legend',
      'Tournament':'Turnaj','Market':'Trh','Projection pick':'Predikcia','Proj.':'Proj.','Opp. proj.':'Proj. súpera','Overall sample':'Celková vzorka','Surface sample':'Vzorka na povrchu','Avg Odds':'Priem. kurz','Sample':'Vzorka','Accuracy':'Presnosť','Log loss':'Log loss','Brier score':'Brier skóre','Published and scored':'Publikované a vyhodnotené','filtered settled sample':'filtrovaná vyhodnotená vzorka','no issued odds':'bez publikovaných kurzov','flat 1u on issued odds':'výpočet pri 1u na publikovaných kurzoch','profit · flat 1u stake':'zisk · výpočet pri 1u','settled published rows':'vyhodnotené publikované záznamy','Production artifact':'Produkčný artefakt','Chronological holdout':'Chronologický holdout','Evaluation report':'Vyhodnocovací report','Negative is better':'Záporné je lepšie','Data window':'Dátové obdobie','Model':'Model',
      'TBA':'Bude určené','ending':'končí'
    },
    cz: {
      'Preskočiť na obsah':'Přeskočit na obsah','BlinQ potrebuje JavaScript.':'BlinQ potřebuje JavaScript.','Dostupné od ELITE':'Dostupné od ELITE','Upgrade pre plný prístup.':'Upgrade pro plný přístup.',
      'Načítavam BlinQ Intelligence':'Načítám BlinQ Intelligence','Načítavam model · dáta · dnešné predikcie':'Načítám model · data · dnešní predikce','Hlavná navigácia':'Hlavní navigace','Rýchla navigácia':'Rychlá navigace',
      'Predikcie':'Predikce','Účet':'Účet','Člen':'Člen','Aktívne':'Aktivní','Admin centrum':'Admin centrum','Otvoriť menu účtu':'Otevřít menu účtu','Odhlásiť sa':'Odhlásit se','Ukončiť reláciu':'Ukončit relaci','TENISOVÁ ANALYTIKA':'TENISOVÁ ANALYTIKA','Prehľad':'Přehled','BlinQ prehľad':'BlinQ přehled',
      'Dnešné predikcie':'Dnešní predikce','Dnešný výber':'Dnešní výběr','TOP · VALUE · jeden board':'TOP · VALUE · jeden board','Zobraziť celú ponuku':'Zobrazit celou nabídku','V tejto kategórii zatiaľ nie sú dostupné predikcie.':'V této kategorii zatím nejsou dostupné predikce.',
      'BlinQ Telegram skupiny':'BlinQ Telegram skupiny','Telegram skupiny':'Telegram skupiny','Oficiálne BlinQ kanály pre komunitu, VIP obsah a prevádzkové informácie.':'Oficiální BlinQ kanály pro komunitu, VIP obsah a provozní informace.',
      'Novinky, diskusia a oznámenia z BlinQ.':'Novinky, diskuse a oznámení z BlinQ.','Extra info picky a prémiové upozornenia pre ELITE a vyššie úrovne.':'Extra info tipy a prémiová upozornění pro ELITE a vyšší úrovně.','Otvoriť Telegram':'Otevřít Telegram','Otvoriť VIP skupinu':'Otevřít VIP skupinu','KOMUNITA':'KOMUNITA',
      'Doplň odkaz v Admin → Telegram':'Doplň odkaz v Admin → Telegram','Všetky systémy funkčné':'Všechny systémy funkční','Aktualizácia modelu: —':'Aktualizace modelu: —','JAZYK':'JAZYK','Zavrieť':'Zavřít','Zavrieť BlinQ Insights':'Zavřít BlinQ Insights',
      'Prihlás sa do svojho analytického priestoru':'Přihlas se do svého analytického prostoru','Súhlasím s':'Souhlasím s','a beriem na vedomie':'a beru na vědomí','Telegram prezývka':'Telegram přezdívka','Zadaj svoj e-mail':'Zadej svůj e-mail','Heslo':'Heslo','Zadaj svoje heslo':'Zadej své heslo','Zobraziť':'Zobrazit','Podmienkami používania':'Podmínkami používání','Ochranu súkromia':'Ochranu soukromí',
      'Prihlásiť sa':'Přihlásit se','Vytvoriť účet':'Vytvořit účet','Zabudnuté heslo':'Zapomenuté heslo','Poslať overovací e-mail znova':'Poslat ověřovací e-mail znovu','Súkromie a cookies':'Soukromí a cookies','Viac o cookies':'Více o cookies','Iba nevyhnutné':'Pouze nezbytné','Povoliť analytiku':'Povolit analytiku',
      'Zavrieť účet':'Zavřít účet','Analýza zápasu':'Analýza zápasu','Zavrieť detail':'Zavřít detail','Naša predikcia':'Naše predikce','Detail →':'Detail →','TOP a VALUE predikcie v jednom rýchlom dátovom boarde.':'TOP a VALUE predikce v jednom rychlém datovém přehledu.',
      'Skip to content':'Přeskočit na obsah','Dashboard':'Přehled','Prime Predictions':'Short Odds','Short Odds':'Short Odds','TOP Predictions':'TOP','Value Predictions':'Value','Doubles':'Čtyřhra','Ace Predictions':'Esa','S/G Predictions':'Sety / hry','Results':'Výsledky','Plans':'Plány','Level':'Úroveň','Remaining':'Zbývá','Account':'Účet','Account & membership':'Účet a členství','Profile, access and plans':'Profil, přístup a plány','Sign out':'Odhlásit se','End this session':'Ukončit tuto relaci',
      'Sign in to your analytics workspace':'Přihlas se do svého analytického prostoru','Get access':'Získej přístup','Restore your access':'Obnov svůj přístup','Set a new password':'Nastav nové heslo',
      'Welcome back.':'Vítej zpět.','Sign in to your tennis intelligence workspace.':'Přihlas se do svého tenisového analytického prostoru.','Create your BlinQ account.':'Vytvoř si účet BlinQ.','Create an account to access your BlinQ workspace.':'Vytvoř si účet a získej přístup do BlinQ.','Restore access.':'Obnov přístup.','We will send a password recovery link to your email.':'Na e-mail ti pošleme odkaz pro obnovu hesla.','Set a new password.':'Nastav nové heslo.','Choose a password with at least eight characters.':'Zvol heslo s minimálně osmi znaky.','Email':'E-mail','Password':'Heslo','Enter your email':'Zadej svůj e-mail','Enter your password':'Zadej své heslo','Show':'Zobrazit','Hide':'Skrýt','Show password':'Zobrazit heslo','Hide password':'Skrýt heslo','Sign in':'Přihlásit se','Create account':'Vytvořit účet','Back to sign in':'Zpět na přihlášení','Forgot password':'Zapomenuté heslo','Resend verification email':'Poslat ověřovací e-mail znovu','Send recovery link':'Poslat odkaz pro obnovu','Save password':'Uložit heslo',
      'Your account':'Tvůj účet','YOUR ACCOUNT':'TVŮJ ÚČET','CURRENT ACCESS':'AKTUÁLNÍ PŘÍSTUP','Email verified':'E-mail ověřen','Email not verified':'E-mail není ověřen','Telegram nick':'Telegram přezdívka','Avatar style':'Typ avatara','Default':'Výchozí','Male':'Muž','Female':'Žena','Save profile':'Uložit profil','Reset password':'Obnovit heslo','BLINQ MEMBERSHIP':'BLINQ ČLENSTVÍ','Available plans':'Dostupné plány','Current plan':'Aktuální plán','CURRENT PLAN':'AKTUÁLNÍ PLÁN','INVITE ONLY':'JEN NA POZVÁNKU','Invite only':'Jen na pozvánku','Request invite':'Požádat o pozvánku','Lifetime access':'Doživotní přístup','Active':'Aktivní','No active access':'Bez aktivního přístupu','Rookie Trial':'Rookie','Lifetime':'Doživotně','Active membership':'Aktivní členství','Expired':'Platnost skončila','Access':'Přístup','Validity':'Platnost','Member since':'Člen od','Security':'Zabezpečení','Verified email':'Ověřený e-mail','Verification required':'Vyžaduje se ověření',
      'Refresh':'Obnovit','Auto-refresh on':'Automatické obnovení zapnuto','picks':'predikcí','published':'publikovaných','settled':'vyhodnocených','See more':'Zobrazit více','See more →':'Zobrazit více →','All Tours':'Všechny okruhy','All Tournaments':'Všechny turnaje','All Surfaces':'Všechny povrchy','All Confidence':'Všechny úrovně jistoty','Unlock this pick':'Odemkni tuto predikci','Upgrade to unlock →':'Upgrade pro odemknutí →','Odds':'Kurz','Model edge':'Výhoda modelu','Category':'Kategorie','All published':'Všechny publikované','Tour':'Okruh','Surface':'Povrch','Period':'Období','All time':'Celé období','24 hours':'24 hodin','7 days':'7 dní','30 days':'30 dní','90 days':'90 dní','Date':'Datum','Match':'Zápas','Pick':'Predikce','Probability':'Pravděpodobnost','Result':'Výsledek','Units':'Jednotky','WON':'VÝHRA','LOST':'PROHRA','VOID':'VOID','Record':'Bilance','Hit rate':'Úspěšnost','Vyhodnotené predikcie':'Vyhodnocené predikce','TENNIS INTELLIGENCE':'TENISOVÁ ANALYTIKA','MATCH WINNER':'VÍTĚZ ZÁPASU','CONFIDENCE FIRST':'JISTOTA NA PRVNÍM MÍSTĚ','VALUE EDGE':'VALUE VÝHODA','SETTLED PICKS':'VYHODNOCENÉ PREDIKCE','BLINQ MEMBERS':'BLINQ ČLENSTVÍ','LEARN':'INFO','How BlinQ Works':'Jak funguje BlinQ','Methodology':'Metodika','Model & Data':'Model a data','Responsible Use':'Zodpovědné používání','BlinQ Prediction':'BlinQ predikce','LANGUAGE':'JAZYK',
      'Tennis insights for a smarter tomorrow.':'Tenisová data pro lepší rozhodování.','COMMUNITY':'KOMUNITA','Join our Telegram Community':'Přidej se do Telegram komunity','News · Predictions · Discussions':'Novinky · Predikce · Diskuse','JOIN':'PŘIDAT SE','Premium Predictions':'Prémiové predikce','Higher value. Better decisions.':'Vyšší hodnota. Lepší rozhodnutí.','OPEN':'OTEVŘÍT','RESULTS & STATS':'VÝSLEDKY A STATISTIKY','Track performance':'Sleduj výkonnost','Transparent. Verified.':'Transparentní. Ověřené.','VIEW':'ZOBRAZIT','Data. Analysis.':'Data. Analýza.','Better Decisions.':'Lepší rozhodnutí.','Advanced tennis intelligence for informed players.':'Pokročilá tenisová analytika pro informovaná rozhodnutí.','Join the BlinQ':'Přidej se do BlinQ','Telegram Community':'Telegram komunity','Track performance.':'Sleduj výkonnost.','Stay informed.':'Měj přehled.','Transparent model results and published statistics.':'Transparentní výsledky modelu a publikované statistiky.','SEE RESULTS':'VÝSLEDKY','✓ Email verified':'✓ E-mail ověřen','! Email not verified':'! E-mail není ověřen','← Dashboard':'← Přehled','Loading current model predictions…':'Načítám aktuální predikce modelu…','Data could not be refreshed. Please try again.':'Data se nepodařilo obnovit. Zkus to znovu.','Published data is older than 12 hours. Check prediction creation times before evaluating them.':'Publikovaná data jsou starší než 12 hodin. Před vyhodnocením zkontroluj čas vytvoření predikcí.','Short Odds Prediction':'Short Odds','Value Prediction':'Value predikce','Ace / DF Prediction':'Esa / dvojchyby','Set / Game Prediction':'Predikce setu / hry','TOP Prediction':'TOP predikce','Projection only · no odds':'Pouze projekce · bez kurzu','VERY HIGH':'VELMI VYSOKÁ','HIGH':'VYSOKÁ','MEDIUM':'STŘEDNÍ','LOW':'NÍZKÁ','PROJECTION':'PREDIKCE','No published predictions are available in this section yet.':'V této sekci zatím nejsou dostupné publikované predikce.','Data not connected':'Data nejsou připojena','No demo or fabricated predictions are shown.':'Nezobrazují se žádné demo ani vymyšlené predikce.',
      'Entry access to the BlinQ workspace.':'Základní přístup do BlinQ.','Start with BlinQ':'Začni s BlinQ','Core predictions':'Hlavní predikce','Core predictions + expanded daily board.':'Hlavní predikce a rozšířený denní přehled.','Advanced analytics':'Pokročilá analytika','Maximum public access':'Nejvyšší veřejný přístup','The highest publicly available BlinQ tier.':'Nejvyšší veřejně dostupná úroveň BlinQ.','Private all-access':'Soukromý plný přístup','Lifetime access · All BlinQ features. Private top-tier access for selected members.':'Doživotní přístup · Všechny funkce BlinQ. Soukromá nejvyšší úroveň pro vybrané členy.','Tournament':'Turnaj','Market':'Trh','Projection pick':'Predikce','Opp. proj.':'Proj. soupeře','Overall sample':'Celkový vzorek','Surface sample':'Vzorek na povrchu','Avg Odds':'Prům. kurz','Sample':'Vzorek','Accuracy':'Přesnost','Brier score':'Brier skóre','Published and scored':'Publikované a vyhodnocené','Data window':'Datové období',
      'TBA':'Bude určeno','ending':'končí'
    }
  };
  function publicText(value){
    const raw=String(value??'');
    const dict=PUBLIC_TRANSLATIONS[locale]||{};
    if(Object.prototype.hasOwnProperty.call(dict,raw))return dict[raw];
    let m=raw.match(/^(\d+) picks$/);if(m)return `${m[1]} ${locale==='cz'?'predikcí':'predikcií'}`;
    m=raw.match(/^(\d+) published$/);if(m)return `${m[1]} ${locale==='cz'?'publikovaných':'publikovaných'}`;
    m=raw.match(/^(\d+) settled$/);if(m)return `${m[1]} ${locale==='cz'?'vyhodnocených':'vyhodnotených'}`;
    m=raw.match(/^Showing (\d+) of (\d+) published predictions?\.$/);if(m)return locale==='cz'?`Zobrazeno ${m[1]} z ${m[2]} publikovaných predikcí.`:`Zobrazených ${m[1]} z ${m[2]} publikovaných predikcií.`;
    m=raw.match(/^Available with (.+)\.$/);if(m)return locale==='cz'?`Dostupné s ${m[1]}.`:`Dostupné s ${m[1]}.`;
    m=raw.match(/^(\d+)d (\d+)h$/);if(m)return `${m[1]} d ${m[2]} h`;
    m=raw.match(/^(\d+)h$/);if(m)return `${m[1]} h`;
    return raw;
  }
  const lcopy=(en,sk,cz=sk)=>locale==='sk'?sk:locale==='cz'?cz:en;
  function uiCopy(path,fallback=''){
    const keys=String(path||'').split('.').filter(Boolean);
    const read=source=>{let node=source;for(const key of keys){if(!node||typeof node!=='object')return undefined;node=node[key];}return node;};
    let node=read(state.siteContent?.ui_copy);if(node===undefined)node=read(state.ui?.ui_copy);
    if(node&&typeof node==='object'&&!Array.isArray(node)){const localized=node[locale]??node.sk??node.en;return localized==null?String(fallback??''):String(localized);}
    return node==null?String(fallback??''):String(node);
  }
  function uiCopyTemplate(path,fallback='',values={}){
    let text=uiCopy(path,fallback);for(const [key,value] of Object.entries(values||{}))text=text.replaceAll(`{${key}}`,String(value));return text;
  }
  function applyEditableUiCopy(){
    const eyebrow=$('bootEyebrow'),bootStatus=$('bootStatus');
    if(eyebrow)eyebrow.textContent=uiCopy('loading.eyebrow','BLINQ INTELLIGENCE');
    if(bootStatus)bootStatus.textContent=uiCopy('loading.status',lcopy('Loading model · data · today’s predictions','Načítavam model · dáta · dnešné predikcie','Načítám model · data · dnešní predikce'));
  }
  function translatePublicDom(root=document){
    if(!root)return;
    const shouldSkip=node=>{const el=node?.parentElement;return Boolean(el?.closest?.('.admin-route,.admin-canvas,.admin-inspector,.admin-toolbar,.admin-tabbar,.admin-accounts-grid,.admin-plan-grid,.reference-wordmark'))};
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(node=>{if(shouldSkip(node))return;const raw=node.nodeValue||'';const core=raw.trim();if(!core)return;const translated=publicText(core);if(translated!==core)node.nodeValue=raw.replace(core,translated);});
    root.querySelectorAll?.('[placeholder],[aria-label],[title]').forEach(el=>{if(el.closest?.('.admin-route,.admin-canvas,.admin-inspector,.admin-toolbar,.admin-tabbar'))return;['placeholder','aria-label','title'].forEach(attr=>{if(!el.hasAttribute(attr))return;const raw=el.getAttribute(attr);const translated=publicText(raw);if(translated!==raw)el.setAttribute(attr,translated);});});
  }
  const dashboardPickSectionKeys=['prime','top_daily','value','doubles','ace','sg'];
  const dashboardSectionKeys=[...dashboardPickSectionKeys,'results'];
  const dashboardSectionFallback={
    prime:{label:'Short Odds',panel_id:'predictionsPanel',sidebar_element:'SIDEBAR_PRIME',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:1,preview_limit:5},
    top_daily:{label:'TOP Predictions',panel_id:'topDailyPanel',sidebar_element:'SIDEBAR_TOP_DAILY',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:2,preview_limit:5},
    value:{label:'Value Predictions',panel_id:'valuePanel',sidebar_element:'SIDEBAR_VALUE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:3,preview_limit:5},
    doubles:{label:'Doubles',panel_id:'doublesPanel',sidebar_element:'SIDEBAR_DOUBLES',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:4,preview_limit:5},
    ace:{label:'Ace Predictions',panel_id:'acePanel',sidebar_element:'SIDEBAR_ACE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:5,preview_limit:5},
    sg:{label:'S/G Predictions',panel_id:'sgPanel',sidebar_element:'SIDEBAR_SG',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:6,preview_limit:5},
    results:{label:'Results',panel_id:'resultsPreviewPanel',sidebar_element:'SIDEBAR_RESULTS',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:7,preview_limit:5},
  };
  const isAdminAccount = () => Boolean(state.feed?.account?.is_admin || String(state.feed?.account?.role||'').toLowerCase() === 'admin');
  const draftKey = () => state.ui?.admin?.draft_storage_key || state.uiSource?.admin?.draft_storage_key || 'blinq_admin_ui_config_v1';
  const elements = () => state.ui?.elements || {};
  const elementList = (kind=null, zone=null) => Object.entries(elements())
    .map(([id,value])=>({id,...(value||{})}))
    .filter(item=>(!kind||item.kind===kind)&&(!zone||item.zone===zone))
    .sort((a,b)=>Number(a.order||0)-Number(b.order||0));

  const BANNER_GREYS=[['Predvolené',''],['Čierna','#000000'],['Antracit','#303030'],['Tmavosivá','#555555'],['Sivá','#808080'],['Svetlosivá','#b5b5b5'],['Takmer biela','#e4e4e4'],['Biela','#ffffff']];
  function bannerColorOptions(current){
    const value=String(current||'').trim().toLowerCase();
    const palette=BANNER_GREYS.map(([label,hex])=>hex);
    const legacy=value&&!palette.includes(value)&&/^#[0-9a-f]{6}$/i.test(value)
      ?`<option value="${escapeHtml(value)}" selected>Pôvodná farba (${escapeHtml(value)})</option>`:'';
    return legacy+BANNER_GREYS.map(([label,hex])=>`<option value="${hex}"${value===hex?' selected':''}>${label}${hex?' · '+hex:''}</option>`).join('');
  }
  function bannerCreativeStyle(c={}){
    const n=(v,min,max,fallback)=>{const x=Number(v);return Number.isFinite(x)&&v!==''?Math.max(min,Math.min(max,x)):fallback;};
    const vars=[`--creative-headline-size:${n(c.headline_size,12,72,36)}px`,`--creative-text-size:${n(c.text_size,9,28,14)}px`,`--creative-eyebrow-size:${n(c.eyebrow_size,7,18,10)}px`,`--creative-delay:${n(c.animation_delay_ms,0,5000,80)}ms`];
    for(const field of ['headline','text','eyebrow']){
      const color=String(c[`${field}_color`]||'').trim();
      if(/^#[0-9a-f]{6}$/i.test(color))vars.push(`--creative-${field}-color:${color}`);
    }
    if(c.overlay)vars.push(`--creative-overlay:${String(c.overlay)}`);
    return `style="${escapeHtml(vars.join(';'))}"`;
  }
  function bannerCreativeClasses(c={}){
    const mode=String(c.mode||c.creative_mode||'native').toLowerCase()==='ads'?'ads':'native';
    const pos=String(c.text_position||'left-center').replace(/[^a-z0-9_-]/gi,'');
    const effect=String(c.effect||'fade-up').replace(/[^a-z0-9_-]/gi,'');
    return ` creative-${mode} creative-pos-${pos} creative-effect-${effect}`;
  }
  async function loadEditablePresentationConfig(){
    try{
      const [tiers,banners,theme,siteContent]=await Promise.all([getJSON('/config/membership-tiers.json',{timeoutMs:3000}),getJSON('/config/banners.json',{timeoutMs:3000}),getJSON('/config/site-theme.json',{timeoutMs:3000}),getJSON('/config/site-content.json',{timeoutMs:3000})]);
      state.presentationConfig={tiers,banners,theme,siteContent}; state.siteContent=siteContent;
      Object.entries(tiers?.tiers||{}).forEach(([id,data])=>{if(!state.ui?.plans?.[id])return;const p=state.ui.plans[id];['label','eyebrow','card_title','description','short_description','cta_label','invite_only'].forEach(k=>{if(data[k]!==undefined)p[k]=data[k];});const u=safeExternalUrl(data.url||'');if(u)p.url=u;else if(data.url==='')p.url='';});
      const hero=banners?.main_banner||{};if(state.ui){const liveHero=state.ui.hero_banner||{};state.ui.hero_banner={...liveHero,rotation_seconds:liveHero.rotation_seconds??hero.rotation_seconds??6,auto_rotate:liveHero.auto_rotate??hero.auto_rotate??true,show_dots:liveHero.show_dots??hero.show_dots??true,pause_on_hover:liveHero.pause_on_hover??hero.pause_on_hover??true,slot_count:liveHero.slot_count??(Array.isArray(hero.slides)?Math.min(5,hero.slides.filter(x=>x?.enabled!==false).length):1)};}
      (hero.slides||[]).slice(0,5).forEach((row,i)=>{const item=state.ui?.elements?.[`HERO_BANNER_${i+1}`];if(item){item.content={...row,...(item.content||{})};}});
      const bg=theme?.background||{};const style=document.documentElement.style;style.setProperty('--blinq-page-bg',`url("${String(bg.image||bg.fallback||'')}")`);style.setProperty('--blinq-page-bg-fallback',`url("${String(bg.fallback||'')}")`);style.setProperty('--blinq-page-bg-position',String(bg.position||'center top'));style.setProperty('--blinq-page-bg-size',String(bg.size||'cover'));style.setProperty('--blinq-page-bg-opacity',String(bg.enabled===false?0:(Number(bg.opacity)||0.2)));style.setProperty('--blinq-page-bg-overlay',String(bg.overlay||'linear-gradient(rgba(0,9,13,.8),rgba(0,9,13,.95))'));if(theme?.login?.background_image)style.setProperty('--blinq-login-bg',`url("${String(theme.login.background_image)}")`);if(theme?.login?.card_width)style.setProperty('--blinq-login-width',`${Number(theme.login.card_width)}px`);if(theme?.login?.logo_width)style.setProperty('--blinq-login-logo-width',`${Number(theme.login.logo_width)}px`);
    }catch{}
  }
  function applyManagedPageBackground(){
    const hero=state.ui?.elements?.HERO_BANNER_1?.content||{};
    const theme=state.presentationConfig?.theme?.background||{};
    const configured=String(hero.site_background_url||theme.image||theme.fallback||'').trim();
    // Upgrade only the former built-in dashboard asset; respect custom admin uploads.
    const bg=configured==='/assets/blinq_background.webp'?'/assets/blinq_page_background.webp':configured;
    if(hero.site_background_url==='/assets/blinq_background.webp')hero.site_background_url=bg;
    const fallback=String(theme.fallback||bg||'/assets/blinq_page_background.webp').trim();
    const style=document.documentElement.style;
    if(bg)style.setProperty('--blinq-page-bg',`url("${bg.replaceAll('\"','')}")`);
    if(fallback)style.setProperty('--blinq-page-bg-fallback',`url("${fallback.replaceAll('\"','')}")`);
  }

  async function loadUiConfig() {
    let runtimeConfigSnapshot=null;
    const fallbackUi={schema:2,navigation:{learn:[]},plans:{},elements:{},admin:{draft_storage_key:'blinq_admin_ui_config_v1'}};
    // Fetch independent release/runtime resources concurrently. A single slow
    // optional endpoint must not serialize several timeout windows and hold an
    // authenticated user behind presentation configuration.
    const [uiResult,telegramResult,runtimeResult,linksResult]=await Promise.allSettled([
      getJSON('/ui-config.json?v=7360&p=61',{timeoutMs:3000}),
      getJSON('/config/telegram-groups.json?v=7360&p=61',{timeoutMs:3000}),
      getJSON('/api/v1/ui-config',{timeoutMs:3500}),
      getJSON('/membership-links.json',{timeoutMs:3000})
    ]);
    state.uiSource=uiResult.status==='fulfilled'&&uiResult.value&&typeof uiResult.value==='object'?uiResult.value:fallbackUi;
    const telegramConfig=telegramResult.status==='fulfilled'?telegramResult.value:null;
    if(telegramConfig&&typeof telegramConfig==='object')state.uiSource.telegram_groups=telegramConfig;
    state.ui=clone(state.uiSource);

    const runtime=runtimeResult.status==='fulfilled'?runtimeResult.value:null;
    if(runtime?.configured&&runtime?.config?.schema===2){
      runtimeConfigSnapshot=runtime.config;
      state.ui=mergeConfig(state.uiSource,runtime.config); state.runtimeConfigLoaded=true;
      if(String(runtime.config.ui_revision||'')!==String(state.uiSource.ui_revision||'')){
        // Merge the new release schema around the already-published settings.
        // User-managed order, hero images/links and rotation must survive an application update.
        state.ui.ui_revision=state.uiSource.ui_revision;
        state.ui.dashboard=mergeConfig(state.uiSource.dashboard||{},runtime.config.dashboard||{});
        if(['6.7.0','6.7.3','6.7.4','6.7.5','6.7.6','6.7.7'].includes(String(state.uiSource.ui_revision||''))){
          const primeTab=state.ui.dashboard?.daily_hub?.tabs?.prime;if(primeTab)primeTab.enabled=false;
          const primeSection=state.ui.dashboard?.sections?.prime;if(primeSection){primeSection.dashboard_enabled=false;primeSection.sidebar_enabled=false;}
        }
        state.ui.dashboard.user_switches=false;
        state.ui.dashboard.show_disabled_strip=false;
        state.ui.hero_banner=mergeConfig(state.uiSource.hero_banner||{enabled:true,slot_count:1,rotation_seconds:10,auto_rotate:true,show_dots:true,pause_on_hover:true},runtime.config.hero_banner||{});
        // Admin-published hero text and assets remain authoritative across releases.
      }
    }

    const rawLinks=linksResult.status==='fulfilled'?linksResult.value:null;
    const catalog=rawLinks?.plans&&typeof rawLinks.plans==='object'?rawLinks.plans:rawLinks;
    const aliases={pro_plus:'elite',premium_telegram:'legend'};
    const fields=['enabled','label','eyebrow','description','note','card_title','cta_label','invite_only','show_price','order'];
    Object.entries(catalog||{}).forEach(([rawId,row])=>{
      const id=aliases[String(rawId||'').toLowerCase()]||String(rawId||'').toLowerCase();
      if(!state.ui?.plans?.[id])return;
      const plan=state.ui.plans[id];
      const data=(typeof row==='string')?{url:row}:((row&&typeof row==='object')?row:{});
      const url=safeExternalUrl(data.payment_url||data.url||data.link);if(url)plan.url=url;
      const invite=safeExternalUrl(data.invite_url||data.telegram_url);if(invite)plan.invite_url=invite;
      fields.forEach(key=>{if(data[key]!==undefined)plan[key]=data[key];});
      if(data.title!==undefined)plan.card_title=data.title;if(data.button_text!==undefined)plan.cta_label=data.button_text;
    });
    await loadEditablePresentationConfig();
    // Static membership JSON files are release fallbacks only. Admin-published plan
    // settings are authoritative and must survive reloads without editing JSON.
    if(runtimeConfigSnapshot?.plans&&typeof runtimeConfigSnapshot.plans==='object')state.ui.plans=mergeConfig(state.ui.plans||{},runtimeConfigSnapshot.plans);
    // r24 product invariant: ROOKIE is always the permanent free base tier.
    // Older published configs may still contain the former 30-day/trial values;
    // normalize them client-side before the next Admin publish.
    state.ui.plans=state.ui.plans||{};
    state.ui.plans.trial={...(state.ui.plans.trial||{}),enabled:false,trial_hours:0,duration_days:null,inherits:'rookie'};
    state.ui.plans.rookie={...(state.ui.plans.rookie||{}),enabled:true,duration_days:null,unlimited:true,lifetime:false};
    const goatPlan=state.ui.plans.goat||{},goatDays=Number(goatPlan.duration_days);
    state.ui.plans.goat={...goatPlan,lifetime:false,unlimited:false,duration_days:Number.isFinite(goatDays)&&goatDays>0?Math.trunc(goatDays):Math.max(1,Number(state.uiSource?.plans?.goat?.duration_days)||365)};
    state.ui.account_inactivity=mergeConfig({enabled:true,inactive_days:30,warning_days:7,notify_admin:true,notify_user:true,auto_expire_rookie:true},state.ui.account_inactivity||{});
    // r27: restore PRIME as the public Short Odds category. Older published
    // runtime configs stored it as globally disabled; migrate that state once.
    const loadedPatch=String(state.ui?.ui_patch||'');
    const loadedPatchNumber=Number((loadedPatch.match(/r(\d+)$/)||[])[1]||0);
    if(loadedPatchNumber<27){const primeTab=state.ui?.dashboard?.daily_hub?.tabs?.prime;if(primeTab)primeTab.enabled=true;}
    if(loadedPatchNumber<33){
      const rookiePrime=state.ui?.dashboard?.daily_hub?.tabs?.prime?.plans?.rookie;
      if(rookiePrime)rookiePrime.selection_mode='stable_random';
    }
    applyAccessContractV1(state.ui);
    state.ui.ui_patch='736-r61';
    applyV6514AdminCleanup();
    state.dashboardVisibility=null;
    renderAllUiContent();
  }

  function applyAccessContractV1(target=state.ui){
    if(!target||typeof target!=='object')return;
    const revision=Number(target.access_contract_revision||0);
    if(revision>=1)return;
    const results=target.elements?.SIDEBAR_RESULTS?.access;
    if(results&&typeof results==='object')Object.assign(results,{trial:'locked',expired:'locked',rookie:'locked',pro:'locked',elite:'locked',legend:'active',goat:'active'});
    const tabs=target.dashboard?.daily_hub?.tabs||{};
    const normalize=(tab,plan,visible,{selection='first',display='active',blur=true,seeAll=false}={})=>{
      const rule=tabs?.[tab]?.plans?.[plan];if(!rule)return;
      Object.assign(rule,{visible_rows:visible,blur_remaining:blur,tab_enabled:display!=='hidden',see_all:seeAll,selection_mode:selection,display_state:display,row_overrides:{}});
    };
    ['daily','prime','value'].forEach(tab=>normalize(tab,'rookie',1,{selection:'stable_random'}));
    ['ace','double_faults','doubles','games','sets'].forEach(tab=>normalize(tab,'rookie',0));
    normalize('see_all','rookie',0,{display:'blurred'});
    ['daily','prime','value'].forEach(tab=>normalize(tab,'pro',3));
    ['ace','double_faults','doubles','games','sets'].forEach(tab=>normalize(tab,'pro',0));
    normalize('see_all','pro',0,{display:'blurred'});
    ['elite','legend','goat'].forEach(plan=>['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'].forEach(tab=>normalize(tab,plan,'ALL',{blur:false,seeAll:true})));
    target.notifications=target.notifications||{};
    target.notifications.live_min_level='elite';
    target.notifications.default_min_level='elite';
    target.notifications.default_levels=['elite','legend','goat'];
    target.access_contract_revision=1;
  }

  function applyV6514AdminCleanup(){
    if(!state.ui)return;
    applyAccessContractV1(state.ui);
    state.ui.rss={enabled:false,refresh_minutes:60,max_age_hours:48,max_items:0,sources:[]};
    state.ui.ad_fallbacks=state.ui.ad_fallbacks||{};
    state.ui.ad_fallbacks.rss_enabled=false;
    state.ui.ad_fallbacks.priority=(state.ui.ad_fallbacks.priority||['active_advertisement','blinq_internal']).filter(x=>x!=='rss_news');
    // Fresh asset paths make old browser-cached avatar artwork impossible to reuse.
    const clean=state.uiSource?.assets?.account_avatars;
    if(clean)state.ui.assets={...(state.ui.assets||{}),account_avatars:clone(clean)};
    Object.values(state.ui.plans||{}).forEach(plan=>{if(plan&&typeof plan==='object')delete plan.marketing_avatar;});
    // 6.6.8: add the consolidated Daily Hub tabs even when an older runtime
    // config is still published. Existing plan rules remain untouched.
    const sourceTabs=state.uiSource?.dashboard?.daily_hub?.tabs||{},liveHub=state.ui.dashboard?.daily_hub;
    if(liveHub){liveHub.tabs=liveHub.tabs||{};['prime','top','doubles','double_faults','sets'].forEach(tab=>{if(!liveHub.tabs[tab]&&sourceTabs[tab])liveHub.tabs[tab]=clone(sourceTabs[tab]);});}
    // r24 membership invariant: ROOKIE is the always-on free tier. Run this
    // cleanup here as well so an older local Admin draft cannot reintroduce the
    // former 30-day/trial behaviour after loadAdminDraft().
    state.ui.plans=state.ui.plans||{};
    state.ui.plans.trial={...(state.ui.plans.trial||{}),enabled:false,trial_hours:0,duration_days:null,inherits:'rookie'};
    state.ui.plans.rookie={...(state.ui.plans.rookie||{}),enabled:true,duration_days:null,unlimited:true,lifetime:false};
    const goatPlan=state.ui.plans.goat||{},goatDays=Number(goatPlan.duration_days);
    state.ui.plans.goat={...goatPlan,lifetime:false,unlimited:false,duration_days:Number.isFinite(goatDays)&&goatDays>0?Math.trunc(goatDays):Math.max(1,Number(state.uiSource?.plans?.goat?.duration_days)||365)};
    state.ui.account_inactivity=mergeConfig({enabled:true,inactive_days:30,warning_days:7,notify_admin:true,notify_user:true,auto_expire_rookie:true},state.ui.account_inactivity||{});

    // r23 visual cleanup: purge retired header/content promo systems from both
    // repository defaults and previously published runtime configurations.
    delete state.ui.content_rows; delete state.ui.header_cta; delete state.ui.creative_specs;
    if(state.ui.dashboard){delete state.ui.dashboard.show_header_feature_strip;delete state.ui.dashboard.snapshot_cards;}
    delete state.ui.elements?.PREDICTION_TOOLBAR; delete state.ui.elements?.SIDEBAR_PREDICTIONS;
    Object.entries(state.ui.elements||{}).forEach(([id,item])=>{
      if(['header_slot','large_banner'].includes(String(item?.kind||''))){delete state.ui.elements[id];return;}
      if(item?.kind==='hero_banner'){delete item.access;delete item.click_access;}
    });
  }

  function loadAdminDraft(){
    if(!isAdminAccount() || state.draftLoaded) return;
    state.draftLoaded=true;
    try{
      const saved=JSON.parse(localStorage.getItem(draftKey())||'null');
      if(saved?.schema===2 && saved?.elements && saved?.plans){
        if(String(saved.ui_revision||'')===String(state.uiSource?.ui_revision||'')){state.ui=mergeConfig(state.uiSource,saved);applyV6514AdminCleanup();}
        else localStorage.removeItem(draftKey());
      }
    }catch{}
  }

  function dashboardSectionConfig(key){
    const base=dashboardSectionFallback[key]||{};
    const configured=state.ui?.dashboard?.sections?.[key]||{};
    return {...base,...configured,plans:{...(configured.plans||{})}};
  }
  function dashboardPlanKey(){const p=accountPlan();return p==='admin'?'goat':p;}
  function dashboardPlanEntitlement(key,plan=dashboardPlanKey()){
    if(accountPlan()==='admin'&&!state.previewPlan)return {visible_picks:'ALL',blur_remaining:false,see_all:true};
    // Production authorization is server-owned. Never let public/runtime UI config
    // widen the data access granted by /api/v1/feed. Admin preview intentionally
    // keeps using the local matrix because it is only a visual simulation.
    if(!state.previewPlan){
      const server=state.feed?.entitlements?.sections?.[key];
      if(server&&typeof server==='object')return {...server};
    }
    const section=dashboardSectionConfig(key);const normalized=plan==='trial'?'rookie':plan;
    return section.plans?.[plan]||section.plans?.[normalized]||section.plans?.rookie||{visible_picks:'ALL',blur_remaining:false,see_all:true};
  }
  function sectionPlanOrder(key,plan=dashboardPlanKey()){
    const cfg=dashboardSectionConfig(key),normalized=plan==='trial'?'rookie':plan,ent=cfg.plans?.[plan]||cfg.plans?.[normalized]||{};
    const raw=Number(ent.order);return Number.isFinite(raw)&&raw>0?raw:Number(cfg.dashboard_order||99);
  }
  function orderedDashboardKeys(plan=dashboardPlanKey()){
    return [...dashboardPickSectionKeys].sort((a,b)=>sectionPlanOrder(a,plan)-sectionPlanOrder(b,plan)||Number(dashboardSectionConfig(a).dashboard_order||99)-Number(dashboardSectionConfig(b).dashboard_order||99));
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
    const section=dashboardSectionConfig(key);const plans=membershipHierarchy
      .filter(id=>state.ui?.plans?.[id]?.enabled!==false)
      .sort((a,b)=>Number(state.ui?.plans?.[a]?.order||99)-Number(state.ui?.plans?.[b]?.order||99));
    for(const plan of plans){const ent=section.plans?.[plan]||{};if(forSeeAll){if(ent.see_all)return plan;continue;}const raw=ent.visible_picks;if(String(raw).toUpperCase()==='ALL'||Number(raw)>index)return plan;}
    return 'goat';
  }
  function publicPlanLabel(plan, fallback=''){
    const id=String(plan||'').trim().toLowerCase();
    if(id==='rookie')return 'FREE';
    const raw=String(fallback||state.ui?.plans?.[id]?.card_title||state.ui?.plans?.[id]?.label||id.toUpperCase());
    return raw.replace(/^BlinQ\s+/i,'')||id.toUpperCase();
  }
  function upgradePlanLabel(plan){if(String(plan||'').toLowerCase()==='rookie')return 'FREE';return state.ui?.plans?.[plan]?.label||String(plan||'PRO').toUpperCase();}
  function dashboardSectionKeyForSidebarElement(elementId){return dashboardSectionKeys.find(key=>dashboardSectionConfig(key).sidebar_element===elementId)||'';}
  function dashboardSectionKeyForPanelId(panelId){return dashboardSectionKeys.find(key=>dashboardSectionConfig(key).panel_id===panelId)||'';}
  function sectionSeeAllNode(key){if(key==='prime')return $('primeSeeAllCard');return document.querySelector(`[data-route="${key}"][class~="section-see-all-card"]`);}
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
    if($('overviewTitle'))$('overviewTitle').textContent=lcopy('Tennis. A clearer perspective.','Tenis pod drobnohľadom.','Tenis pod drobnohledem.');
    if($('overviewDescription'))$('overviewDescription').textContent=lcopy('Predictions and model projections, all in one place.','Predikcie a modelové projekcie na jednom mieste.','Predikce a modelové projekce na jednom místě.');
    const prefs=dashboardVisibilityState(),max=Math.max(1,Number(state.ui?.dashboard?.visible_slots)||4);
    const orderedKeys=orderedDashboardKeys();const configured=orderedKeys.filter(key=>{const cfg=dashboardSectionConfig(key);return prefs[key]&&cfg.sidebar_enabled!==false&&elementAccess(cfg.sidebar_element)!=='hidden';}).slice(0,max);
    const countFor=key=>marketRows(key).length;
    let active=[...configured];
    if(state.ui?.dashboard?.auto_replace_empty_sections!==false){
      const replacements=orderedKeys.filter(key=>{const cfg=dashboardSectionConfig(key);return !active.includes(key)&&cfg.sidebar_enabled!==false&&elementAccess(cfg.sidebar_element)!=='hidden'&&countFor(key)>0;});
      active=active.map(key=>countFor(key)>0?key:(replacements.shift()||key));
    }
    // 6.5.50: the homepage is intentionally a single Daily Intelligence surface.
    // Keep legacy panel nodes only as compatibility hooks for old route/render code; never expose them on Overview.
    dashboardPickSectionKeys.forEach(key=>{
      const cfg=dashboardSectionConfig(key),panel=$(cfg.panel_id);if(!panel)return;
      panel.hidden=true; panel.setAttribute('aria-hidden','true');
    });
    {const cfg=dashboardSectionConfig('results'),panel=$(cfg.panel_id);if(panel)panel.hidden=true;}
    dashboardSectionKeys.forEach(key=>{
      const see=sectionSeeAllNode(key),ent=dashboardPlanEntitlement(key);if(!see)return;
      see.hidden=false;see.classList.toggle('section-see-all-locked',!ent.see_all);see.dataset.dashboardSection=key;
      const b=see.querySelector('b');
      if(ent.see_all){see.dataset.route=key;see.href=`#${key}`;delete see.dataset.upgradePlan;if(b)b.textContent='See more →';}
      else{delete see.dataset.route;see.href='#';see.dataset.upgradePlan=firstUnlockPlan(key,0,true);if(b)b.textContent=`${lcopy('Available with','Dostupné s','Dostupné s')} ${upgradePlanLabel(see.dataset.upgradePlan).replace(/^BlinQ\s+/i,'')} →`;}
    });
    renderDashboardSectionToggles();
  }
  
  function lockedPickCard(key,index){
    const plan=firstUnlockPlan(key,index,false),label=upgradePlanLabel(plan),section=dashboardSectionConfig(key);
    return `<article class="prediction-card dashboard-locked-card access-locked" data-upgrade-plan="${escapeHtml(plan)}" data-upgrade-section="${escapeHtml(section.label||key)}"><div class="locked-ghost"><span></span><i>VS</i><span></span></div><div class="locked-pick-copy"><b aria-hidden="true">⌑</b><strong>Uzamknutý pick</strong><small>Dostupné od ${escapeHtml(label.replace(/^BlinQ\s+/i,''))}</small><button type="button" class="btn btn-primary" data-upgrade-plan="${escapeHtml(plan)}" data-upgrade-section="${escapeHtml(section.label||key)}" data-upgrade-explicit="1">Upgrade →</button></div></article>`;
  }
  function translateSignalLabel(label){
    const raw=String(label||'Model signal');
    const legacy={'Celková výkonnosť':'Overall performance','Sila na povrchu':'Surface strength','Aktuálna forma':'Recent form','Vzájomné zápasy':'Head to head','Výkonnosť':'Performance','Forma':'Recent form'};
    const canonical=legacy[raw]||raw; return publicText(canonical);
  }

  function renderNavigation(){
    const referenceNav=document.querySelector('.reference-navigation');
    const predictionRoutes=new Set(['predictions','prime','top_daily','value','doubles','ace','sg']);
    const modelRoutes=new Set(['model_data','methodology','how_blinq_works']);
    const referenceRoute=predictionRoutes.has(state.route)?'predictions':state.route==='results'?'results':modelRoutes.has(state.route)?'model_data':state.route==='account'?'account':'';
    const resultsLocked=!resultsAccessAllowed();
    const resultsPlan=resultsLocked?firstResultsUnlockPlan():'';
    const decorateResultsAccess=node=>{
      if(!node)return;
      node.classList.toggle('access-nav-locked',resultsLocked);
      if(resultsLocked){
        node.dataset.upgradePlan=resultsPlan;
        node.dataset.upgradeSection=lcopy('Results','Výsledky','Výsledky');
        node.dataset.upgradeExplicit='1';
        node.setAttribute('aria-label',`${lcopy('Results','Výsledky','Výsledky')} · ${accessHintDetails(resultsPlan,'').title}`);
      }else{
        delete node.dataset.upgradePlan;
        delete node.dataset.upgradeSection;
        delete node.dataset.upgradeExplicit;
        node.removeAttribute('aria-label');
      }
    };
    if(referenceNav){
      referenceNav.querySelectorAll('[data-route]').forEach(node=>{
        const active=Boolean(referenceRoute)&&node.dataset.route===referenceRoute;
        node.classList.toggle('active',active);
        if(active)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');
      });
      decorateResultsAccess(referenceNav.querySelector('[data-route="results"]'));
    }
    document.querySelectorAll('#mobileTabs [data-route="results"]').forEach(decorateResultsAccess);
    const profileAdmin=$('profileAdminLink');if(profileAdmin)profileAdmin.hidden=!isAdminAccount();
  }

  function safeLink(value, fallback='#predictions'){
    const text=String(value||'').trim();
    if(!text)return fallback;
    if(text.startsWith('#'))return text;
    if(text.startsWith('/')&&!text.startsWith('//'))return text;
    if(/^https:\/\//i.test(text)){try{const parsed=new URL(text);if(parsed.protocol==='https:'&&parsed.host&&!parsed.username&&!parsed.password)return parsed.href;}catch{}}
    return fallback;
  }
  function isExternalLink(value){ return /^https:\/\//i.test(String(value||'')); }
  function safeExternalUrl(value){
    const text=String(value||'').trim();
    if(!text||!/^https:\/\//i.test(text))return '';
    try{const parsed=new URL(text);return parsed.protocol==='https:'&&parsed.host&&!parsed.username&&!parsed.password?parsed.href:'';}catch{return '';}
  }
  function shortModelVersion(value){
    const text=String(value||'').trim();
    if(!text)return '';
    const match=text.match(/^(v?\d+(?:[._-]\d+){0,3})/i);
    return (match?.[1]||text.split(/[+\s]/)[0]||text).slice(0,18);
  }
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
  function resolvedBannerContent(item,index=0){
    const content=item?.content||{};
    const ad=content.type==='advertisement'||content.sponsored===true;
    if(!contentActive(content))return fallbackContent({...item,content},index);
    if(content.type==='rss')return fallbackContent({...item,content:{...content,ad_hidden_fallback:'rss'}},index);
    return content;
  }
  function marketingAvatarUrl(planId){
    const id=String(planId||'').toLowerCase();
    const entry=state.ui?.assets?.account_avatars?.[id]||{};
    // v6.5.16: membership artwork is image-only. Plan labels are rendered beside
    // the avatar and never baked/overlaid into the circular artwork.
    return avatarAssetSrc(entry.marketing||entry.default||entry.w||entry.m||'');
  }

  function bannerAttrs(item,content){
    const slot=String(item.id||'');
    const campaign=String(content?.campaign_id||slot);
    const advertiser=String(content?.advertiser_id||'unassigned');
    return `data-banner-slot="${escapeHtml(slot)}" data-campaign-id="${escapeHtml(campaign)}" data-advertiser-id="${escapeHtml(advertiser)}"`;
  }
  function heroConfig(){
    return state.ui?.hero_banner||{};
  }
  function heroItems(){
    const cfg=heroConfig();
    const requested=Math.max(0,Math.min(5,Number(cfg.slot_count??1)||0));
    if(cfg.enabled===false||!requested)return [];
    return elementList('hero_banner','hero').slice(0,requested).filter(item=>item?.content?.enabled!==false);
  }
  function heroImageHtml(content,index=0){
    const desktop=safeLink(content?.image_url,'');
    const mobile=safeLink(content?.mobile_image_url,'');
    if(!desktop||desktop.startsWith('#'))return '';
    const fit=['cover','contain'].includes(String(content?.image_fit||'cover'))?String(content.image_fit||'cover'):'cover';
    const position=['center','left','right','top','bottom'].includes(String(content?.image_position||'center'))?String(content.image_position||'center'):'center';
    const first=Number(index)===0;
    const img=`<img class="hero-slide-image fit-${escapeHtml(fit)} pos-${escapeHtml(position)}" src="${escapeHtml(desktop)}" alt="" loading="${first?'eager':'lazy'}" decoding="async"${first?' fetchpriority="high"':''}>`;
    return mobile&&!mobile.startsWith('#')?`<picture class="hero-slide-picture"><source media="(max-width: 900px)" srcset="${escapeHtml(mobile)}">${img}</picture>`:img;
  }
  function heroSlideHtml(item,index){
    const rawContent=resolvedBannerContent(item,index),c={...rawContent,eyebrow:publicText(rawContent.eyebrow||''),headline:publicText(rawContent.headline||''),accent_text:publicText(rawContent.accent_text||''),text:publicText(rawContent.text||''),button_text:publicText(rawContent.button_text||'')},route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#predictions'),external=isExternalLink(href);
    const theme=String(c.theme||'violet').replace(/[^a-z0-9_-]/gi,'');
    const showCopy=c.show_copy!==false;
    const sponsored=c.sponsored?'<span class="sponsored-label hero-sponsored">SPONSORED</span>':'';
    const image=heroImageHtml(c,index);
    const art=image?'':`<div class="dashboard-hero-ball" aria-hidden="true"><i></i><b></b></div>`;
    // Do not render the obsolete, uneditable accent_text from saved banner revisions.
    const title=String(c.headline||'').trim();
    const titleHtml=title?`<h2><strong>${escapeHtml(title)}</strong></h2>`:'';
    const heroEyebrow=Object.prototype.hasOwnProperty.call(c,'eyebrow')?String(c.eyebrow||'').trim():'BLINQ';
    const subtitle=String(c.text||'').trim();
    const copy=showCopy?`<div class="dashboard-hero-copy">${heroEyebrow?`<small>${escapeHtml(heroEyebrow)}</small>`:''}${titleHtml}${subtitle?`<p>${escapeHtml(subtitle)}</p>`:''}${c.button_text?`<b class="hero-slide-cta">${escapeHtml(c.button_text)} →</b>`:''}</div>`:'';
    return `<a class="dashboard-hero hero-slide theme-${escapeHtml(theme)}${bannerCreativeClasses(c)}${index===state.heroIndex?' is-active':''}${showCopy?'':' hero-image-only'}" ${bannerCreativeStyle(c)} href="${escapeHtml(href)}" ${external?'target="_blank" rel="noopener"':''} ${route&&!external?`data-route="${escapeHtml(route)}"`:''} data-hero-index="${index}" data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)} aria-hidden="${index===state.heroIndex?'false':'true'}">${sponsored}${image}${copy}${art}</a>`;
  }
  function clearHeroRotation(){
    if(state.heroTimer){clearInterval(state.heroTimer);state.heroTimer=null;}
  }
  function setHeroSlide(index,restart=false){
    const host=$('dashboardHero'),slides=[...(host?.querySelectorAll('.hero-slide')||[])];
    if(!slides.length)return;
    state.heroIndex=((Number(index)||0)%slides.length+slides.length)%slides.length;
    slides.forEach((slide,i)=>{const active=i===state.heroIndex;slide.classList.toggle('is-active',active);slide.setAttribute('aria-hidden',active?'false':'true');slide.tabIndex=active?0:-1;});
    [...host.querySelectorAll('[data-hero-dot]')].forEach((dot,i)=>{const active=i===state.heroIndex;dot.classList.toggle('is-active',active);dot.setAttribute('aria-current',active?'true':'false');});
    if(restart)startHeroRotation();
  }
  function startHeroRotation(){
    clearHeroRotation();
    const cfg=heroConfig(),slides=heroItems();
    if(cfg.auto_rotate===false||slides.length<2||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const seconds=Math.max(3,Math.min(300,Number(cfg.rotation_seconds)||10));
    state.heroTimer=setInterval(()=>{if(state.heroPaused||document.hidden||state.route!=='predictions')return;setHeroSlide(state.heroIndex+1,false);},seconds*1000);
  }
  function renderHeroBanner(){
    const host=$('dashboardHero');if(!host)return;
    clearHeroRotation();
    const cfg=heroConfig(),items=heroItems();
    if(!items.length){host.hidden=true;host.innerHTML='';return;}
    host.hidden=false;
    state.heroIndex=Math.max(0,Math.min(state.heroIndex,items.length-1));
    host.innerHTML=items.map((item,index)=>heroSlideHtml(item,index)).join('')+(cfg.show_dots!==false&&items.length>1?`<div class="hero-dots" aria-label="Hlavný banner slides">${items.map((_,index)=>`<button type="button" data-hero-dot="${index}" class="${index===state.heroIndex?'is-active':''}" aria-label="Show banner ${index+1}" aria-current="${index===state.heroIndex?'true':'false'}"></button>`).join('')}</div>`:'');
    host.onmouseenter=()=>{if(cfg.pause_on_hover!==false)state.heroPaused=true;};
    host.onmouseleave=()=>{state.heroPaused=false;};
    host.querySelectorAll('[data-hero-dot]').forEach(dot=>dot.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();setHeroSlide(Number(dot.dataset.heroDot)||0,true);}));
    setHeroSlide(state.heroIndex,false);
    installBannerTracking(host);
    startHeroRotation();
  }


  function visitorId(){
    const key='blinq_banner_visitor_v1'; let value=localStorage.getItem(key);
    if(!value){const secure=(window.crypto&&typeof window.crypto.randomUUID==='function')?window.crypto.randomUUID():'';value=secure||`${Date.now()}-${Math.random().toString(36).slice(2)}`;localStorage.setItem(key,value);} return value;
  }
  function trackBanner(node,eventType){
    if(!node?.dataset?.bannerSlot||!analyticsConsentAllowed())return;
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
    const rssSlots=elementList('hero_banner','hero').some(item=>item.content?.type==='rss');
    const adSlots=elementList('hero_banner','hero').some(item=>item.content?.type==='advertisement'||item.content?.sponsored===true);
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
      node.classList.remove('ui-state-active','ui-state-locked','ui-state-blurred','ui-state-hidden','access-locked');
      node.classList.add(`ui-state-${mode}`); node.dataset.uiState=mode;
      node.setAttribute('aria-disabled',mode==='active'?'false':'true');
      if(mode!=='active'){
        node.classList.add('access-locked');
        if(!node.dataset.upgradePlan){
          const sectionKey=dashboardSectionKeyForSidebarElement(id)||'top_daily';
          node.dataset.upgradePlan=id==='SIDEBAR_RESULTS'?firstResultsUnlockPlan():firstUnlockPlan(sectionKey,0,true);
          node.dataset.upgradeSection=node.textContent?.trim().slice(0,70)||dashboardSectionConfig(sectionKey).label||'BlinQ';
          node.dataset.accessAutoLock='1';
        }
        const required=String(upgradePlanLabel(node.dataset.upgradePlan||'pro')||node.dataset.upgradePlan||'PRO').replace(/^BlinQ\s+/i,'').toUpperCase();
        node.dataset.uiStateLabel=uiCopyTemplate('access.requires',lcopy(`Requires ${required}`,`Vyžaduje ${required}`,`Vyžaduje ${required}`),{plan:required});
      }else{node.dataset.uiStateLabel='';if(node.dataset.accessAutoLock==='1'){delete node.dataset.upgradePlan;delete node.dataset.upgradeSection;delete node.dataset.accessAutoLock;}}
    });
  }
  function refreshTopPlanCta(){
    const button=$('topUpgradeButton'),label=$('topUpgradeLabel');if(!button||!label)return;
    const plan=accountPlan();
    if(plan==='goat'){button.hidden=true;return;}
    const current=membershipHierarchy.indexOf(plan);
    const next=current>=0&&current<membershipHierarchy.length-1?membershipHierarchy[current+1]:'pro';
    button.hidden=false;button.dataset.upgradePlan=next;button.dataset.upgradeSection='BlinQ Membership';
    label.textContent=lcopy('Upgrade','Upgrade','Upgrade');
  }
  function updateLanguageLinks(){
    document.querySelectorAll('#footerLanguages [data-lang],#authLanguages [data-lang]').forEach(link=>{const lang=link.dataset.lang||'sk';link.href=link.closest('#authLanguages')?`?lang=${encodeURIComponent(lang)}`:`?lang=${encodeURIComponent(lang)}#${encodeURIComponent(state.route||'predictions')}`;link.classList.toggle('active',lang===locale);});
  }
  const cookieConsentKey='blinq_cookie_consent_v1';
  function cookieConsentValue(){try{return localStorage.getItem(cookieConsentKey)||'';}catch{return '';}}
  function analyticsConsentAllowed(){return cookieConsentValue()==='analytics';}
  function saveCookieConsent(value){try{localStorage.setItem(cookieConsentKey,value);}catch{}renderCookieConsent(false);}
  function renderCookieConsent(force=false){
    const host=$('cookieConsent');if(!host)return;
    if(state.route==='admin'){host.hidden=true;return;}
    const copy=state.siteContent?.cookie_banner?.[contentLocale?.()||locale]||state.siteContent?.cookie_banner?.sk||{};
    const saved=cookieConsentValue();
    host.hidden=Boolean(saved)&&!force;
    if($('cookieConsentTitle'))$('cookieConsentTitle').textContent=copy.title||'Súkromie a cookies';
    if($('cookieConsentText'))$('cookieConsentText').textContent=copy.text||'';
    if($('cookieEssentialOnly'))$('cookieEssentialOnly').textContent=copy.essential||'Iba nevyhnutné';
    if($('cookieAcceptAnalytics'))$('cookieAcceptAnalytics').textContent=copy.accept||'Povoliť analytiku';
  }
  function showPublicContentDialog(route){
    const dialog=$('publicContentDialog'),host=$('publicContentDialogContent');if(!dialog||!host)return;
    host.innerHTML=renderSiteContentPage(route)||'<section class="content-page"><p>Obsah nie je dostupný.</p></section>';
    
    if(!dialog.open)dialog.showModal();
  }
  function telegramPlanAllowed(minPlan){
    const required=String(minPlan||'rookie').toLowerCase(),current=accountPlan();
    if(current==='admin')return true;
    const ci=membershipHierarchy.indexOf(current),ri=membershipHierarchy.indexOf(required);
    return ci>=0&&ri>=0&&ci>=ri;
  }
  function renderTelegramGroupsPanel(){
    const host=$('telegramGroupsPanel');if(!host)return;
    const cfg=state.ui?.telegram_groups||{},groups=Array.isArray(cfg.groups)?cfg.groups.filter(row=>row&&row.enabled!==false):[];
    if(cfg.enabled===false||!groups.length){host.hidden=true;host.innerHTML='';return;}
    const cards=groups.map((group,index)=>{
      const minPlan=membershipHierarchy.includes(String(group.min_plan||'rookie').toLowerCase())?String(group.min_plan).toLowerCase():'rookie';
      const allowed=telegramPlanAllowed(minPlan),url=safeExternalUrl(group.url||'');
      const title=publicText(String(group.title||`Telegram ${index+1}`)),description=publicText(String(group.description||'')),cta=publicText(String(group.cta||'Otvoriť Telegram'));
      const accessBadge=minPlan==='rookie'?'ROOKIE':String(upgradePlanLabel(minPlan)||minPlan).replace(/^BlinQ\s+/i,'').toUpperCase();
      const defaultBadge=minPlan==='rookie'?'KOMUNITA':accessBadge;
      const badge=publicText(Object.prototype.hasOwnProperty.call(group,'badge')?String(group.badge||'').trim():defaultBadge);
      const action=allowed?(url?`<a class="tg-group-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(cta)} <span>↗</span></a>`:`<span class="tg-group-cta is-disabled">${escapeHtml(publicText('Doplň odkaz v Admin → Telegram'))}</span>`):`<button class="tg-group-cta is-locked" type="button" data-upgrade-plan="${escapeHtml(minPlan)}" data-upgrade-section="${escapeHtml(title)}">${escapeHtml(lcopy(`Requires ${accessBadge}`,`Vyžaduje ${accessBadge}`,`Vyžaduje ${accessBadge}`))} <span>→</span></button>`;
      return `<article class="tg-group-card${allowed?'':' is-locked'}"><div class="tg-group-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M20.6 4.1 3.9 10.5c-1.14.46-1.13 1.1-.2 1.39l4.28 1.34 1.64 5.05c.2.56.1.78.69.78.46 0 .66-.21.92-.46l2.08-2.03 4.33 3.2c.8.44 1.37.21 1.57-.74l2.84-13.39c.29-1.17-.45-1.7-1.45-1.54Z"></path></svg></div><div class="tg-group-copy">${badge?`<small>${escapeHtml(badge)}</small>`:''}<strong>${escapeHtml(title)}</strong><p>${escapeHtml(description)}</p></div>${action}</article>`;
    }).join('');
    const panelEyebrow=publicText(Object.prototype.hasOwnProperty.call(cfg,'eyebrow')?String(cfg.eyebrow||'').trim():'BLINQ COMMUNITY');
    host.hidden=false;host.innerHTML=`<div class="tg-panel-head"><div>${panelEyebrow?`<small>${escapeHtml(panelEyebrow)}</small>`:''}<h2>${escapeHtml(publicText(String(cfg.title||'Telegram skupiny')))}</h2><p>${escapeHtml(publicText(String(cfg.description||'')))}</p></div></div><div class="tg-group-grid">${cards}</div>`;
  }
  function renderAllUiContent(){ applyEditableUiCopy(); if(state.bannerObserver){state.bannerObserver.disconnect();state.bannerObserver=null;}state.bannerTimers=new WeakMap();renderNavigation(); wireDashboardSearch(); applyManagedPageBackground(); renderHeroBanner(); renderMarketSections(); renderDashboardResultsPreview(); renderDashboardComposition(); renderDashboardKpis(); renderTelegramGroupsPanel(); refreshTopPlanCta(); updateLanguageLinks(); applyAccessStates(); renderInsightBell(); renderSystemFooterStatus(); translatePublicDom(document.body); }

  function auth(mode='login'){
    feedGeneration++;
    $('appShell').hidden=true;
    state.authMode=mode; $('authMessage').textContent=''; if($('resendVerification'))$('resendVerification').hidden=true;
    $('authDialog').dataset.mode=mode;
    $('nameLabel').hidden=mode!=='signup'; $('emailLabel').hidden=mode==='recovery'; $('passwordLabel').hidden=mode==='reset'; if($('authLegalConsentLabel'))$('authLegalConsentLabel').hidden=mode!=='signup'; if(mode!=='signup'&&$('authLegalConsent'))$('authLegalConsent').checked=false;
    $('authEmail').required=mode!=='recovery'; $('authPassword').required=mode!=='reset'; $('authName').required=mode==='signup';
    // Never apply the new-account password policy to sign-in. Older Firebase
    // accounts may legitimately have a 6- or 7-character password; a static
    // minlength=8 made the browser block the submit event before our handler
    // could call Firebase, which looked like a broken login button.
    $('authPassword').minLength=(mode==='signup'||mode==='recovery')?8:0;
    $('authPassword').autocomplete=mode==='login'?'current-password':'new-password';
    const authFallback={login:'Sign in to your analytics workspace',signup:'Get access',reset:'Restore your access',recovery:'Set a new password'}[mode];
    const authCopyKey={login:'auth.login_title',signup:'auth.signup_title',reset:'auth.reset_title',recovery:'auth.recovery_title'}[mode];
    if(mode==='login'){
      $('authTitle').textContent=uiCopy('auth.login_title',lcopy('Sign in to BlinQ','Prihlásenie do BlinQ','Přihlášení do BlinQ'));
      $('authSubtitle').textContent=uiCopy('auth.login_subtitle',publicText(authFallback));$('authSubtitle').hidden=false;
    }else{
      $('authTitle').textContent=uiCopy(authCopyKey,publicText(authFallback));
      $('authSubtitle').textContent='';$('authSubtitle').hidden=true;
    }
    $('authSubmit').textContent=publicText({login:'Sign in',signup:'Create account',reset:'Send recovery link',recovery:'Save password'}[mode]);
    $('switchSignup').textContent=publicText(mode==='login'?'Create account':'Back to sign in'); $('switchReset').hidden=mode!=='login';
    $('authSubmit').disabled=!state.authEnabled;
    if(!state.authEnabled)$('authMessage').textContent=publicText('Authentication is temporarily unavailable.');else $('authMessage').textContent='';
    $('appShell').hidden=true; translatePublicDom(document.body);
    if(!$('authDialog').open) $('authDialog').showModal();
  }

  async function handleAuthSubmit(event){
    event.preventDefault();
    const button=$('authSubmit'),message=$('authMessage'),passwordInput=$('authPassword'),emailInput=$('authEmail');
    const email=emailInput.value.trim().toLowerCase(), password=passwordInput.value;
    emailInput.value=email;
    if(!email && state.authMode!=='recovery'){message.textContent=publicText('Enter your email address.');emailInput.focus();return;}
    if(state.authMode!=='recovery'&&!emailInput.checkValidity()){message.textContent=publicText('Enter a valid email address.');emailInput.focus();return;}
    const domain=email.split('@')[1]||'';
    const domainFix={
      'gmail.con':'gmail.com','gmail.comr':'gmail.com','gmail.co':'gmail.com',
      'gmai.com':'gmail.com','gmial.com':'gmail.com','outlook.con':'outlook.com'
    }[domain];
    if(state.authMode!=='recovery'&&domainFix){message.textContent=`Skontroluj e-mail: doména ${domain} vyzerá ako preklep. Myslel si ${domainFix}?`;emailInput.focus();return;}
    if(['login','signup','recovery'].includes(state.authMode)&&!password){message.textContent=publicText('Enter your password.');passwordInput.focus();return;}
    if(['signup','recovery'].includes(state.authMode)&&password.length<8){message.textContent=publicText('Choose a password with at least eight characters.');passwordInput.focus();return;}
    if(state.authMode==='signup'){const nick=$('authName').value.trim();if(!/^@?[A-Za-z0-9_]{5,32}$/.test(nick)){message.textContent='Telegram nickname musí mať 5–32 znakov: písmená, čísla alebo _.';$('authName').focus();return;}if(!$('authLegalConsent')?.checked){message.textContent='Pre vytvorenie účtu potvrď Podmienky používania a Ochranu súkromia.';$('authLegalConsent')?.focus();return;}}
    button.disabled=true; button.dataset.busy='1'; message.textContent=publicText('Working…');
    try{
      const authStatus=await BlinqAuth.ensureReady();
      state.authEnabled=Boolean(authStatus?.enabled);
      if(state.authMode==='reset'){ await BlinqAuth.reset(email); $('authMessage').textContent=publicText('If the account exists, check your email for the recovery link.'); return; }
      if(state.authMode==='recovery') await BlinqAuth.update({password});
      else if(state.authMode==='signup'){
        const result=await BlinqAuth.signUp(email,password,$('authName').value.trim(),{version:String(state.siteContent?.updated_at||'2026-09-16'),locale:contentLocale()});
        if(result?.verification_required){
          auth('login');$('authEmail').value=email;$('authPassword').value='';
          if(result.email_delivery_failed){
            $('authMessage').textContent=lcopy(
              'Your account was created, but the verification email could not be sent. Use “Send verification email again”.',
              'Účet bol vytvorený, ale overovací e-mail sa nepodarilo odoslať. Použi „Poslať overovací e-mail znova“.',
              'Účet byl vytvořen, ale ověřovací e-mail se nepodařilo odeslat. Použij „Poslat ověřovací e-mail znovu“.'
            );
            if($('resendVerification'))$('resendVerification').hidden=false;
          }else{
            $('authMessage').textContent=publicText('Verification email sent. Open the link in your inbox, then sign in.');
          }
          return;
        }
      } else await BlinqAuth.signIn(email,password);
      // Keep the modal visible while the workspace is being authorized. The
      // feed loader closes it only after a successful authenticated response.
      // This avoids the old close/reopen flash and guarantees that API errors
      // stay visible to the user instead of looking like a dead login button.
      $('authPassword').value='';
      await loadFeed();
    } catch(error){
      const code=String(error.code||'').toLowerCase();
      const verification=code==='email_not_verified';
      const suspended=code==='account_suspended';
      $('authMessage').textContent=verification
        ?publicText('Your email is not verified yet. Open the verification link or resend the email.')
        :suspended
          ?publicText('This BlinQ account is suspended. Contact us via the official BlinQ Telegram channel if you believe this is a mistake.')
          :publicText(error.message||'Sign-in failed. Please try again.');
      if($('resendVerification'))$('resendVerification').hidden=!verification;
      if(!$('authDialog').open)$('authDialog').showModal();
    }
    finally{ button.dataset.busy='0'; button.disabled=!state.authEnabled; }
  }

  function normalize(row){
    const player1=row?.player1||{},player2=row?.player2||{};
    const rawP1=player1?.probability,rawP2=player2?.probability;
    const p1=rawP1==null||rawP1===''?null:Number(rawP1),p2=rawP2==null||rawP2===''?null:Number(rawP2);
    const p1Known=Number.isFinite(p1),p2Known=Number.isFinite(p2);
    const inferredWinner=p1Known&&p2Known?(p1>=p2?player1?.id:player2?.id):'';
    const winnerId=String(row?.winner_id || inferredWinner || '');
    const winner=winnerId===String(player1?.id)?player1:winnerId===String(player2?.id)?player2:null;
    const probability=p1Known&&p2Known?Math.max(p1,p2):p1Known?p1:p2Known?p2:null;
    const betting=row?.betting&&typeof row.betting==='object'?row.betting:{};
    return {id:row?.event_id||row?.id,date:row?.scheduled_at,tour:String(row?.tour||'').toUpperCase(),tournament:row?.tournament||'Tournament',surface:row?.surface||'unknown',round:row?.round||'',p1:player1?.name||'Player 1',p2:player2?.name||'Player 2',p1Id:player1?.id,p2Id:player2?.id,p1Prob:p1,p2Prob:p2,p1Rank:player1?.rank??null,p2Rank:player2?.rank??null,p1PrevRank:player1?.previous_rank??null,p2PrevRank:player2?.previous_rank??null,p1BestRank:player1?.best_rank??null,p2BestRank:player2?.best_rank??null,p1RankingPoints:player1?.ranking_points??null,p2RankingPoints:player2?.ranking_points??null,p1Country:player1?.country_code||'',p2Country:player2?.country_code||'',p1Photo:playerPhotoSource(row,player1,'player1'),p2Photo:playerPhotoSource(row,player2,'player2'),pick:winner?.name||'—',pickId:winnerId,probability,confidence:Number.isFinite(probability)?confidenceBand(probability):'unknown',signals:Array.isArray(row?.signals)?row.signals:[],quality:row?.quality&&typeof row.quality==='object'?row.quality:{},dataDepth:Number(row?.data_depth),odds:firstFinite(betting.odds,row?.odds),edge:firstFinite(betting.edge,row?.edge),expectedValue:firstFinite(betting.expected_value,row?.expected_value),bettingDay:betting.betting_day||'',model:row?.model_version||state.feed?.model?.version||'',raw:row};
  }

  function populateSelect(id,values,label){ const select=$(id),selected=select.value; select.innerHTML=`<option value="">${label}</option>`; [...values].filter(Boolean).sort().forEach(value=>{const opt=document.createElement('option');opt.value=value;opt.textContent=String(value).replaceAll('_',' ');select.appendChild(opt)}); if([...select.options].some(o=>o.value===selected)) select.value=selected; }
  function populateFilters(){ const rows=(state.feed.upcoming||[]).map(normalize); populateSelect('tournamentFilter',new Set(rows.map(x=>x.tournament)),publicText('All Tournaments')); populateSelect('surfaceFilter',new Set(rows.map(x=>x.surface)),publicText('All Surfaces')); }
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
  function marketProbability(row){const raw=row?.blinq_probability??row?.probability??row?.win_probability??row?.model_probability??row?.confidence_probability;const value=Number(raw);return Number.isFinite(value)?(value>1?value/100:value):null;}
  function surfaceSampleLabel(row){const q=row?.quality||{},s1=Number(q?.player1?.surface_matches),s2=Number(q?.player2?.surface_matches);return Number.isFinite(s1)&&Number.isFinite(s2)?`${Math.min(s1,s2)}+`:'—';}
  function dataDepthMetric(row){const depth=Number(row?.data_depth);return Number.isFinite(depth)?`${Math.round(Math.max(0,Math.min(1,depth))*100)}%`:'—';}
  function explicitTournamentCountry(row){
    const raw=row?.tournament_country_code||row?.tournament_country||row?.venue_country_code||row?.venue_country||row?.competition_country_code||row?.competition_country||row?.location?.country_code||row?.location?.country||'';
    return normalizeCountryCode(raw);
  }
  function motivationContext(row,side){
    const player=row?.['player'+side]||{};
    const presentation=player?.presentation&&typeof player.presentation==='object'?player.presentation:{};
    const context=presentation?.context&&typeof presentation.context==='object'?presentation.context:{};
    const round=String(row?.round||row?.round_name||'').toLowerCase();
    const level=String(row?.tournament_level||row?.level||row?.competition||row?.category_name||row?.category||row?.tour||'').toLowerCase();
    const playerCountry=normalizeCountryCode(player?.country_code||player?.country_code2||player?.country_code3||player?.country?.alpha2||player?.country?.alpha3||'');
    const tournamentCountry=explicitTournamentCountry(row);
    const recent=recentFormData(player,'recent_form');
    const surface=recentFormData(player,'surface_form');
    const currentRank=Number(player?.rank??player?.ranking??player?.current_rank);
    const previousRank=Number(player?.previous_rank??player?.previousRank);
    const rest=Number(context?.rest_days),load3=Number(context?.matches_3d),load7=Number(context?.matches_7d),travel=Number(context?.travel_km),altitude=Number(context?.altitude_change_m);
    const overallElo=Number(context?.overall_elo),surfaceElo=Number(context?.surface_elo);
    const signals=[];
    let motivation=0;
    if(/qualification final|qualifying final|final qualification/.test(round)){motivation+=2;signals.push({key:'stakes',label:lcopy('Stakes','Dôležitosť','Důležitost'),value:lcopy('High','Vysoká','Vysoká'),tone:'positive',note:lcopy('Qualification final','Finále kvalifikácie','Finále kvalifikace')});}
    else if(/final/.test(round)&&!/semi/.test(round)){motivation+=2;signals.push({key:'stakes',label:lcopy('Stakes','Dôležitosť','Důležitost'),value:lcopy('High','Vysoká','Vysoká'),tone:'positive',note:lcopy('Final','Finále','Finále')});}
    else if(/semi|quarter|qf\b/.test(round)){motivation+=1;signals.push({key:'stakes',label:lcopy('Stakes','Dôležitosť','Důležitost'),value:lcopy('Elevated','Zvýšená','Zvýšená'),tone:'positive',note:lcopy('Late round','Pokročilé kolo','Pokročilé kolo')});}
    else signals.push({key:'stakes',label:lcopy('Stakes','Dôležitosť','Důležitost'),value:lcopy('Normal','Bežná','Běžná'),tone:'neutral',note:''});
    if(/grand slam|masters|1000/.test(level)){motivation+=1;signals.push({key:'tier',label:lcopy('Event tier','Úroveň','Úroveň'),value:lcopy('Premium','Top turnaj','Top turnaj'),tone:'positive',note:''});}
    if(playerCountry&&tournamentCountry&&playerCountry===tournamentCountry){motivation+=1;signals.push({key:'home',label:lcopy('Home factor','Domáce prostredie','Domácí prostředí'),value:lcopy('Yes','Áno','Ano'),tone:'positive',note:''});}
    if(Number.isFinite(rest)){
      const tone=rest<1?'negative':rest<2?'warning':rest>28?'warning':'positive';
      const value=rest<1?lcopy('< 1 day','< 1 deň','< 1 den'):rest>28?lcopy('Long layoff','Dlhšia pauza','Delší pauza'):`${rest.toFixed(rest<10?1:0)} d`;
      signals.push({key:'rest',label:lcopy('Rest','Oddych','Odpočinek'),value,tone,note:''});
    }
    if(Number.isFinite(load3)||Number.isFinite(load7)){
      const l3=Number.isFinite(load3)?load3:0,l7=Number.isFinite(load7)?load7:0;
      const tone=l3>=3||l7>=5?'negative':l3>=2||l7>=4?'warning':'positive';
      signals.push({key:'load',label:lcopy('Workload','Zaťaženie','Zátěž'),value:`${l3}/3d · ${l7}/7d`,tone,note:''});
    }
    if(Number.isFinite(travel)) signals.push({key:'travel',label:lcopy('Travel','Presun','Přesun'),value:travel<50?lcopy('Local','Lokálny','Lokální'):`${Math.round(travel)} km`,tone:travel>5000?'negative':travel>2500?'warning':'neutral',note:''});
    if(Number.isFinite(altitude)) signals.push({key:'altitude',label:lcopy('Altitude shift','Zmena výšky','Změna výšky'),value:`${Math.round(altitude)} m`,tone:altitude>1500?'warning':'neutral',note:''});
    if(recent.winPct!=null) signals.push({key:'form',label:lcopy('Momentum','Momentum','Momentum'),value:`${Math.round(recent.winPct*100)}%`,tone:recent.winPct>=.65?'positive':recent.winPct<=.4?'negative':'neutral',note:lcopy('recent form','posledná forma','poslední forma')});
    if(surface.winPct!=null) signals.push({key:'surface',label:lcopy('Surface form','Forma na povrchu','Forma na povrchu'),value:`${Math.round(surface.winPct*100)}%`,tone:surface.winPct>=.65?'positive':surface.winPct<=.4?'negative':'neutral',note:''});
    if(Number.isFinite(overallElo)&&Number.isFinite(surfaceElo)){const delta=surfaceElo-overallElo;signals.push({key:'fit',label:lcopy('Surface fit','Povrchový fit','Povrchový fit'),value:`${delta>=0?'+':''}${Math.round(delta)}`,tone:delta>35?'positive':delta<-35?'warning':'neutral',note:''});}
    const known=signals.filter(item=>item.key!=='stakes').length;
    return {motivation,label:motivation>=3?lcopy('High','Vysoká','Vysoká'):motivation>=1?lcopy('Elevated','Zvýšená','Zvýšená'):lcopy('Neutral','Neutrálna','Neutrální'),signals,known};
  }
  function renderMotivationPanel(row){
    const match=normalize(row),m1=motivationContext(row,1),m2=motivationContext(row,2);
    const card=(name,m)=>`<article class="motivation-card context-card"><header><div><small>${escapeHtml(lcopy('PRE-MATCH CONTEXT','PREDZÁPASOVÝ KONTEXT','PŘEDZÁPASOVÝ KONTEXT'))}</small><strong>${escapeHtml(name)}</strong></div><b class="motivation-score ${m.motivation>=1?'is-positive':''}">${escapeHtml(m.label)}</b></header><div class="context-signal-grid">${m.signals.slice(0,8).map(item=>`<span class="context-signal tone-${escapeHtml(item.tone||'neutral')}"><small>${escapeHtml(item.label)}</small><strong>${escapeHtml(item.value)}</strong>${item.note?`<em>${escapeHtml(item.note)}</em>`:''}</span>`).join('')}</div></article>`;
    return `<section class="rail-motivation rail-context"><div class="rail-section-title"><div><h3>${escapeHtml(lcopy('Motivation & readiness','Motivácia & pripravenosť','Motivace & připravenost'))}</h3></div></div><div class="motivation-grid">${card(match.p1,m1)}${card(match.p2,m2)}</div><p class="motivation-note">${escapeHtml(lcopy('Motivation reflects observable stakes and home context. Rest, workload, travel, altitude and form are shown separately; no psychological state is inferred.','Motivácia vychádza iba z pozorovateľnej dôležitosti zápasu a domáceho prostredia. Oddych, zaťaženie, presun, výška a forma sú zobrazené samostatne; psychický stav neodhadujeme.','Motivace vychází pouze z pozorovatelné důležitosti zápasu a domácího prostředí. Odpočinek, zátěž, přesun, výška a forma jsou zobrazeny samostatně; psychický stav neodhadujeme.'))}</p></section>`;
  }
  function dashboardDailyRows(){
    const rows=dailyHubRows('daily');
    return Array.isArray(rows)?rows:[];
  }
  function renderDashboardKpis(){
    const host=$('dashboardKpis');if(!host)return;
    const rows=dashboardDailyRows();
    // A published bet may occur in both TOP / SHORT ODDS and again in SEE ALL.
    // Read the server's unique total from all eight actual markets, never
    // count SEE ALL as a ninth category and never use only visible TOP rows.
    const suppliedTotal=Number(state.feed?.entitlements?.daily_pick_count);
    const totalToday=Number.isSafeInteger(suppliedTotal)&&suppliedTotal>=0
      ?suppliedTotal
      :Math.max(dailyHubRows('see_all').length,
        ['daily','prime','value','ace','double_faults','doubles','games','sets']
          .reduce((sum,tab)=>sum+Math.max(0,Number(dailyHubEntitlement(tab)?.total)||0),0));
    const odds=rows.map(r=>Number(r?.odds??r?.betting?.odds)).filter(Number.isFinite);
    const perf=state.feed?.performance||{};
    const dashboardBest=state.feed?.dashboard_model_success||{};
    const performanceWindows=state.feed?.performance_windows||{};
    const performanceSummary=state.feed?.performance_window_summary||{};
    const bestDays=Number(performanceSummary?.best_days);
    const bestWindow=Number.isFinite(bestDays)?performanceWindows?.[String(bestDays)]||{}:{};
    const bestModel=bestWindow?.model||{};
    const accuracy=Number(dashboardBest?.accuracy??bestModel?.accuracy??perf?.accuracy);
    const avgOdds=odds.length?odds.reduce((a,b)=>a+b,0)/odds.length:null;
    const icons={
      board:'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="#35efa0" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 20V11M10 20V6M15 20v-8M20 20V3"/></svg>',
      target:'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="#35efa0" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/><path d="M17 7l3-3M17 4h3v3"/></svg>',
      chart:'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="#35efa0" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18l5-5 4 3 7-9"/><path d="M15 7h5v5"/></svg>'
    };
    const cards=[
      [icons.board,lcopy('TODAY PREDICTIONS','DNEŠNÉ PREDIKCIE','DNEŠNÍ PREDIKCE'),String(totalToday),'',''],
      [icons.target,lcopy('MODEL SUCCESS','MODELOVÁ ÚSPEŠNOSŤ','ÚSPĚŠNOST MODELU'),Number.isFinite(accuracy)?pct(accuracy):'—','',''],
      [icons.chart,lcopy('AVERAGE ODDS','PRIEMERNÝ KURZ','PRŮMĚRNÝ KURZ'),avgOdds==null?'—':avgOdds.toFixed(2),'','']
    ];
    host.innerHTML=cards.map(([icon,label,value,note,trend])=>`<article class="dashboard-kpi"><span>${icon}</span><div><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}${trend?`<em class="kpi-trend">↗ ${escapeHtml(trend)}</em>`:''}</strong>${note?`<p>${escapeHtml(note)}</p>`:''}</div></article>`).join('');
  }
  function highlightRow(){
    return dashboardDailyRows()[0]||dailyHubRows('top')[0]||dailyHubRows('value')[0]||null;
  }
  function findRowByEventId(id){
    const target=String(id||'');
    for(const tab of ['daily','prime','top','value','ace','double_faults','games','sets','doubles']){
      const row=(dailyHubRows(tab)||[]).find(item=>eventKey(item)===target);
      if(row)return {row,tab};
    }
    return null;
  }

  function notificationReadIds(){
    return new Set((state.insights||[]).filter(item=>item?.read).map(item=>String(item?.id||'')).filter(Boolean));
  }
  function notificationAudienceConfig(){
    const cfg=state.ui?.notifications||{};
    const rawLive=String(cfg.live_min_level||cfg.default_min_level||'elite').toLowerCase();
    const rawInfo=String(cfg.info_min_level||'rookie').toLowerCase();
    const liveMin=membershipHierarchy.includes(rawLive)?rawLive:'elite';
    const infoMin=membershipHierarchy.includes(rawInfo)?rawInfo:'rookie';
    const editable=Array.isArray(cfg.editable_levels)?cfg.editable_levels.filter(level=>membershipHierarchy.includes(String(level))):[...membershipHierarchy];
    const infoDefault=Array.isArray(cfg.info_default_levels)?cfg.info_default_levels.filter(level=>membershipHierarchy.includes(String(level))):membershipLevelsFrom(infoMin);
    return {enabled:cfg.enabled!==false,one_way:cfg.one_way!==false,live_min_level:liveMin,info_min_level:infoMin,default_min_level:liveMin,default_levels:Array.isArray(cfg.default_levels)?cfg.default_levels:membershipLevelsFrom(liveMin),info_default_levels:infoDefault.length?infoDefault:membershipLevelsFrom(infoMin),editable_levels:editable.length?editable:[...membershipHierarchy]};
  }
  function membershipLevelsFrom(minPlan='rookie'){
    const normalized=membershipHierarchy.includes(String(minPlan||'').toLowerCase())?String(minPlan).toLowerCase():'rookie';
    const index=Math.max(0,membershipHierarchy.indexOf(normalized));return membershipHierarchy.slice(index);
  }
  function membershipAtLeast(plan,minPlan='rookie'){
    if(String(plan||'').toLowerCase()==='admin')return true;
    const current=membershipHierarchy.indexOf(String(plan||'').toLowerCase()),required=membershipHierarchy.indexOf(String(minPlan||'').toLowerCase());
    return current>=0&&required>=0&&current>=required;
  }
  function matchDetailAccessConfig(){
    const base={plans:{trial:true,expired:false,rookie:true,pro:true,elite:true,legend:true,goat:true},sections:{overview:'rookie',statistics:'pro',radar:'elite',history:'legend'}};
    const cfg=state.ui?.dashboard?.match_detail||{};
    return mergeConfig(base,cfg);
  }
  function matchDetailPlanAllowed(plan=accountPlan()){
    if(String(plan||'').toLowerCase()==='admin')return true;
    const normalized=String(plan||'').toLowerCase()==='trial'?'rookie':String(plan||'').toLowerCase();
    const plans=matchDetailAccessConfig().plans||{};
    return plans[normalized]!==false;
  }
  function firstMatchDetailUnlockPlan(plan=accountPlan()){
    const current=String(plan||'').toLowerCase()==='trial'?'rookie':String(plan||'').toLowerCase();
    const start=Math.max(0,membershipHierarchy.indexOf(current));
    const plans=matchDetailAccessConfig().plans||{};
    for(let i=start;i<membershipHierarchy.length;i++){if(plans[membershipHierarchy[i]]!==false)return membershipHierarchy[i];}
    for(const id of membershipHierarchy){if(plans[id]!==false)return id;}
    return 'goat';
  }
  function matchDetailSectionMinimum(section){
    const raw=String(matchDetailAccessConfig()?.sections?.[section]||'rookie').toLowerCase();
    return membershipHierarchy.includes(raw)?raw:'rookie';
  }
  function matchDetailSectionAllowed(section,plan=accountPlan()){
    return matchDetailPlanAllowed(plan)&&membershipAtLeast(plan,matchDetailSectionMinimum(section));
  }
  function matchDetailLockHtml(section,label){
    const minPlan=matchDetailSectionMinimum(section);
    const required=String(upgradePlanLabel(minPlan)||minPlan).replace(/^BlinQ\s+/i,'').toUpperCase();
    return `<div class="match-detail-lock-card" data-upgrade-plan="${escapeHtml(minPlan)}" data-upgrade-section="${escapeHtml(label)}"><span class="match-detail-lock-icon" aria-hidden="true">🔒</span><div><small>${escapeHtml(lcopy('LOCKED SECTION','UZAMKNUTÁ SEKCIA','UZAMČENÁ SEKCE'))}</small><strong>${escapeHtml(label)}</strong><p>${escapeHtml(lcopy(`Available from ${required}`,`Dostupné od: ${required}`,`Dostupné od: ${required}`))}</p></div></div>`;
  }
  function hubMatchDetailButtonHtml(){
    if(matchDetailPlanAllowed())return `<button class="hub-detail" type="button" data-hub-detail aria-label="Detail"><span>${escapeHtml(lcopy('Detail','Detail','Detail'))}</span></button>`;
    const minPlan=firstMatchDetailUnlockPlan();
    const required=String(upgradePlanLabel(minPlan)||minPlan).replace(/^BlinQ\s+/i,'').toUpperCase();
    return `<button class="hub-detail is-locked" type="button" data-detail-locked data-upgrade-plan="${escapeHtml(minPlan)}" data-upgrade-section="${escapeHtml(lcopy('Match detail','Detail zápasu','Detail zápasu'))}" aria-label="${escapeHtml(lcopy(`Match detail available from ${required}`,`Detail zápasu dostupný od ${required}`,`Detail zápasu dostupný od ${required}`))}" title="${escapeHtml(lcopy(`Available from ${required}`,`Dostupné od ${required}`,`Dostupné od ${required}`))}"><span>${escapeHtml(lcopy('Detail','Detail','Detail'))}</span><i aria-hidden="true"><svg viewBox="0 0 20 20"><rect x="4" y="8" width="12" height="9" rx="2"/><path d="M6.5 8V5a3.5 3.5 0 0 1 7 0v3"/></svg></i></button>`;
  }
  function renderSystemFooterStatus(){
    const host=$('footerSystemStatus'),time=$('footerLastUpdate');if(!host||!time)return;
    const heartbeat=state.liveRadarHeartbeat||state.userLiveRadarStatus||{};
    const raw=heartbeat?.scanned_at||heartbeat?.updated_at||state.feed?.generated_at||'';
    const parsed=Date.parse(raw);
    time.textContent=Number.isFinite(parsed)?lcopy(`Model update: ${fmtTime(raw)}`,`Aktualizácia modelu: ${fmtTime(raw)}`,`Aktualizace modelu: ${fmtTime(raw)}`):lcopy('Model update: —','Aktualizácia modelu: —','Aktualizace modelu: —');
    const fresh=heartbeat?.fresh===true||(Number.isFinite(parsed)&&Date.now()-parsed<=180000);
    host.classList.toggle('is-stale',!fresh);
  }
  function insightTypeLabel(type){return ({info:'Info',insight:'Premium Info',alert:'LIVE · COMEBACK',live_watch:'LIVE · WATCH',set2:'LIVE · 2. SET',vip:'Premium Info'})[String(type||'').toLowerCase()]||'Insight';}
  function insightAudienceText(levels){
    const list=[...new Set((Array.isArray(levels)?levels:[]).map(v=>String(v).toLowerCase()).filter(v=>membershipHierarchy.includes(v)))].sort((a,b)=>membershipHierarchy.indexOf(a)-membershipHierarchy.indexOf(b));
    for(const level of membershipHierarchy){const suffix=membershipLevelsFrom(level);if(list.length===suffix.length&&suffix.every((v,i)=>list[i]===v)){const label=publicPlanLabel(level,state.ui?.plans?.[level]?.label||level).toUpperCase();return level==='goat'?label:`${label}+`;}}
    return list.map(v=>publicPlanLabel(v,state.ui?.plans?.[v]?.label||v).toUpperCase()).join(' · ')||'—';
  }
  function isLiveInsight(item){return ['alert','live_watch','set2'].includes(String(item?.type||'').toLowerCase());}
  function liveRadarSet2Stats(radar={}){
    const rows=Array.isArray(radar?.candidates)?radar.candidates:(Array.isArray(radar?.candidate_items)?radar.candidate_items:[]);
    const priced=Number.isFinite(Number(radar?.set2_priced))?Number(radar.set2_priced):rows.filter(row=>Number(row?.second_set_odds)>1).length;
    const candidates=Number.isFinite(Number(radar?.set2_candidates))?Number(radar.set2_candidates):rows.length;
    let eligible=Number(radar?.set2_eligible);
    if(!Number.isFinite(eligible)){
      const th=radar?.set2_push_thresholds||{},minSamples=Math.max(1,Number(th.min_samples)||10),minEdge=Math.max(0,Number(th.min_edge)||0),minEv=Math.max(0,Number(th.min_ev)||0),qualities=new Set(Array.isArray(th.accepted_quality)?th.accepted_quality.map(x=>String(x).toLowerCase()):['medium','high']);
      eligible=rows.filter(row=>qualities.has(String(row?.second_set_quality||'').toLowerCase())&&Number(row?.second_set_samples)>=minSamples&&Number(row?.second_set_odds)>1&&Number(row?.second_set_edge)>minEdge&&Number(row?.second_set_ev)>minEv).length;
    }
    return {candidates,priced,eligible:Math.max(0,eligible)};
  }
  function renderInsightBell(){
    const bell=$('insightBell'),badge=$('insightUnread'),shortcut=$('insightShortcut'),shortcutLabel=$('insightShortcutLabel'),shortcutCount=$('insightShortcutCount');if(!bell||!badge)return;
    const plan=accountPlan(),notificationCfg=notificationAudienceConfig(),liveMin=notificationCfg.live_min_level;
    const eligible=notificationCfg.enabled&&['rookie','pro','elite','legend','goat','admin'].includes(plan);
    const infoEligible=eligible;
    const liveEligible=eligible&&membershipAtLeast(plan,liveMin);
    const liveAccessLabel=String(upgradePlanLabel(liveMin)||liveMin).replace(/^BlinQ\s+/i,'').toUpperCase();
    bell.hidden=!eligible;
    bell.classList.remove('is-access-locked');
    delete bell.dataset.upgradePlan;delete bell.dataset.upgradeSection;bell.setAttribute('aria-label','BlinQ Info');
    const radar=state.userLiveRadarStatus||{},watching=liveEligible&&Number(radar.candidates)>0,confirmed=liveEligible&&Number(radar.signals)>0;
    if(shortcut){
      shortcut.hidden=!eligible;
      shortcut.classList.toggle('is-live-enabled',liveEligible);
      shortcut.classList.toggle('is-live-watching',watching&&!confirmed);
      shortcut.classList.toggle('is-live-confirmed',confirmed);
      shortcut.classList.toggle('is-access-locked',eligible&&!liveEligible);
      if(eligible&&!liveEligible){shortcut.dataset.upgradePlan=liveMin;shortcut.dataset.upgradeSection='Comeback LIVE';shortcut.setAttribute('aria-label',`Comeback LIVE · dostupné od ${liveAccessLabel}`);shortcut.title=lcopy(`Available from ${liveAccessLabel}`,`Dostupné od ${liveAccessLabel}`,`Dostupné od ${liveAccessLabel}`);}
      else{delete shortcut.dataset.upgradePlan;delete shortcut.dataset.upgradeSection;shortcut.setAttribute('aria-label','Comeback LIVE Radar');shortcut.removeAttribute('title');}
      shortcut.setAttribute('aria-expanded',state.insightDrawerOpen&&state.insightChannel==='live'?'true':'false');
    }
    if(shortcutCount){const n=confirmed?Number(radar.signals)||0:watching?Number(radar.candidates)||0:0;shortcutCount.textContent=String(n);shortcutCount.hidden=!n||!liveEligible;}
    if(shortcutLabel){shortcutLabel.textContent=liveEligible?(confirmed?'CONFIRMED':watching?'WATCH':'RADAR'):'RADAR';shortcutLabel.hidden=false;}
    const infoUnread=state.insights.filter(item=>!item.read&&!isLiveInsight(item)).length;
    badge.textContent=infoUnread>99?'99+':String(infoUnread);badge.hidden=!infoUnread||!infoEligible;
    bell.classList.toggle('has-unread',infoUnread>0);bell.setAttribute('aria-expanded',state.insightDrawerOpen&&state.insightChannel==='info'?'true':'false');
  }
  function insightTypeIcon(type){
    return ({info:'i',insight:'✦',alert:'!',live_watch:'◉',set2:'②',vip:'◆'})[String(type||'').toLowerCase()]||'✦';
  }
  function renderInsightDrawer(){
    const drawer=$('insightDrawer'),list=$('insightDrawerList'),status=$('insightDrawerStatus'),toolbar=$('insightDrawerToolbar');if(!drawer||!list||!status)return;
    const channel=state.insightChannel==='live'?'live':'info';
    const filter=state.insightFilter||'all';
    const liveTab=['set2','results'].includes(state.liveRadarTab)?state.liveRadarTab:'comeback';
    const channelRows=state.insights.filter(item=>channel==='live'?isLiveInsight(item):!isLiveInsight(item)).filter(item=>channel!=='live'||liveTab==='results'?false:(liveTab==='set2'?String(item?.type||'').toLowerCase()==='set2':String(item?.type||'').toLowerCase()!=='set2'));
    const rows=channelRows.filter(item=>filter==='unread'?!item.read:filter==='pinned'?Boolean(item.pinned):true);
    const channelUnread=channelRows.filter(item=>!item.read).length;
    const title=$('insightDrawerTitle'),eyebrow=$('insightDrawerEyebrow');
    if(title)title.textContent=channel==='live'?'LIVE Radar':'BlinQ Info';
    if(eyebrow)eyebrow.textContent=channel==='live'?'BLINQ LIVE':'BLINQ INFO';
    drawer.dataset.channel=channel;
    if(state.insightsLoading) status.innerHTML=`<span class="insight-status-dot is-loading"></span><strong>${escapeHtml(lcopy('Loading private feed…','Načítavam súkromný feed…','Načítám soukromý feed…'))}</strong>`;
    else if(state.insightsStorageUnavailable) status.innerHTML=`<span class="insight-status-dot is-offline"></span><strong>${escapeHtml(lcopy('Private feed is temporarily unavailable.','Súkromný feed je dočasne nedostupný.','Soukromý feed je dočasně nedostupný.'))}</strong>`;
    else status.innerHTML=`<span class="insight-status-dot"></span><strong>${channelUnread} ${escapeHtml(lcopy('unread','neprečítaných','nepřečtených'))}</strong><span>${channelRows.length} ${escapeHtml(channel==='live'?lcopy('live updates','LIVE správ','LIVE zpráv'):lcopy('messages','správ','zpráv'))}</span>`;
    if(toolbar){
      const tabs=channel==='live'?[['all',lcopy('All','Všetky','Všechny')],['unread',lcopy('Unread','Neprečítané','Nepřečtené')]]:[['all',lcopy('All','Všetky','Všechny')],['unread',lcopy('Unread','Neprečítané','Nepřečtené')],['pinned',lcopy('Pinned','Pripnuté','Připnuté')]];
      toolbar.innerHTML=`<div class="insight-filter-tabs">${tabs.map(([id,label])=>`<button type="button" data-insight-filter="${id}" class="${filter===id?'is-active':''}">${escapeHtml(label)}${id==='unread'&&channelUnread?` <b>${channelUnread}</b>`:''}</button>`).join('')}</div>${channelUnread?`<button class="insight-read-all" type="button" data-insight-read-all>${escapeHtml(lcopy('Mark all read','Prečítať všetko','Přečíst vše'))}</button>`:''}`;
    }
    const plan=accountPlan();
    const liveEligible=membershipAtLeast(plan,notificationAudienceConfig().live_min_level);
    const radar=state.userLiveRadarStatus||{};
    const candidateNames=Array.isArray(radar.candidate_items)?radar.candidate_items.map(x=>x?.favorite).filter(Boolean).slice(0,2):[];
    const radarMode=Number(radar.signals)>0?'is-confirmed':Number(radar.candidates)>0?'is-watching':'';
    const radarStrip=channel==='live'&&liveEligible?`<div class="insight-live-strip ${radar.error?'is-error':radar.ok?'is-ok':''} ${radarMode}"><span class="insight-live-dot"></span><div><strong>Comeback LIVE Radar</strong><small>${escapeHtml(state.userLiveRadarLoading?lcopy('Checking live matches…','Kontrolujem live zápasy…','Kontroluji live zápasy…'):radar.error?lcopy('LIVE status is temporarily unavailable.','LIVE stav je dočasne nedostupný.','LIVE stav je dočasně nedostupný.'):radar.scanned_at?`${Number(radar.live_events)||0} live · ${Number(radar.candidates)||0} WATCH · ${Number(radar.signals)||0} potvrdené${candidateNames.length?' · '+candidateNames.join(', '):''}`:lcopy('Automatic monitoring is active.','Automatické sledovanie je aktívne.','Automatické sledování je aktivní.'))}</small></div></div>`:'';
    const set2Stats=liveRadarSet2Stats(radar);
    const radarCandidateCards=channel==='live'&&liveEligible&&Array.isArray(radar.candidate_items)?radar.candidate_items.slice(0,3).map(item=>{
      const stage=String(item?.stage||'watch'),p=Number(item?.second_set_probability),odds=Number(item?.second_set_odds),edge=Number(item?.second_set_edge),ev=Number(item?.second_set_ev),samples=Number(item?.second_set_samples);
      const quality=String(item?.second_set_quality||'').toUpperCase();
      const status=stage==='second_set_won'||stage==='break_lead'?lcopy('COMEBACK CONFIRMED','COMEBACK POTVRDENÝ','COMEBACK POTVRZENÝ'):lcopy('COMEBACK WATCH','COMEBACK WATCH','COMEBACK WATCH');
      if(state.liveRadarTab==='set2'){
        const set2=[];if(Number.isFinite(p))set2.push(`${lcopy('P(win set 2)','P(výhra 2. setu)','P(výhra 2. setu)')} ${pct(p)}`);if(Number.isFinite(odds))set2.push(`${lcopy('live odds','live kurz','live kurz')} ${odds.toFixed(2)}`);
        const depth=[quality,Number.isFinite(samples)&&samples>0?`${Math.trunc(samples)} samples`:null].filter(Boolean).join(' · ');
        return `<article class="live-radar-candidate is-set2"><header><div><small>${escapeHtml(lcopy('SET 2 MODEL · independent support signal','MODEL 2. SETU · samostatný podporný signál','MODEL 2. SETU · samostatný podporný signál'))}</small><strong>${escapeHtml(String(item?.favorite||'—'))} <span>vs</span> ${escapeHtml(String(item?.opponent||'—'))}</strong></div><b>${escapeHtml(String(item?.second_set||'—'))}</b></header><div class="live-radar-status-grid"><span class="set2-model"><small>${escapeHtml(lcopy('Projection','Projekcia','Projekce'))}</small><strong>${escapeHtml(set2.length?set2.join(' · '):lcopy('Projection only — no live market','Len projekcia — bez live marketu','Pouze projekce — bez live marketu'))}</strong></span><span><small>DATA DEPTH</small><strong>${escapeHtml(depth||'—')}</strong></span></div></article>`;
      }
      return `<article class="live-radar-candidate"><header><div><small>${escapeHtml(status)}</small><strong>${escapeHtml(String(item?.favorite||'—'))} <span>vs</span> ${escapeHtml(String(item?.opponent||'—'))}</strong></div><b>${escapeHtml(String(item?.second_set||'—'))}</b></header><div class="live-radar-status-grid"><span><small>${escapeHtml(lcopy('Comeback status','Comeback stav','Comeback stav'))}</small><strong>${escapeHtml(String(item?.first_set||'—'))} → ${escapeHtml(String(item?.second_set||'—'))}</strong></span><span><small>${escapeHtml(lcopy('Signal','Signál','Signál'))}</small><strong>${escapeHtml(stage==='second_set_won'?lcopy('Won set 2','Vyhral 2. set','Vyhrál 2. set'):stage==='break_lead'?lcopy('Break lead in set 2','Break náskok v 2. sete','Break náskok ve 2. setu'):lcopy('Watching after lost set 1','Sledujeme po prehratom 1. sete','Sledujeme po prohraném 1. setu'))}</strong></span></div></article>`;
    }).join(''):'';
    const radarResults=Array.isArray(radar.results)?radar.results:[];
    const radarResultCards=channel==='live'&&liveEligible&&liveTab==='results'?radarResults.map(item=>{
      const kind=String(item?.kind||'')==='set2'?'2. SET':'COMEBACK';
      const outcome=String(item?.outcome||'').toLowerCase();
      const outcomeLabel=outcome==='win'?lcopy('WIN','VÝHRA','VÝHRA'):outcome==='loss'?lcopy('LOSS','PREHRA','PREHRA'):resultVoidLabel(item?.reason);
      const title=String(item?.title||'').replace(/^Comeback LIVE\s*·\s*/i,'').replace(/^2\. set LIVE\s*·\s*/i,'')||'—';
      const when=item?.settled_at?fmtDate(item.settled_at)+' · '+fmtTime(item.settled_at):'';
      return `<article class="live-radar-candidate is-result is-${escapeHtml(outcome)}"><header><div><small>${escapeHtml(kind)} · ${escapeHtml(outcomeLabel)}</small><strong>${escapeHtml(title)}</strong></div><b>${escapeHtml(outcomeLabel)}</b></header>${when?`<div class="live-radar-result-time">${escapeHtml(when)}</div>`:''}</article>`;
    }).join(''):'';
    const radarTabs=channel==='live'&&liveEligible?`<div class="live-radar-tabs"><button type="button" data-live-radar-tab="comeback" class="${liveTab==='comeback'?'is-active':''}">Comeback</button><button type="button" data-live-radar-tab="set2" class="${liveTab==='set2'?'is-active':''}">2. set</button><button type="button" data-live-radar-tab="results" class="${liveTab==='results'?'is-active':''}">${escapeHtml(lcopy('Results','Výsledky','Výsledky'))}</button></div>`:'';
    const set2Strip=channel==='live'&&liveEligible&&liveTab==='set2'?`<div class="insight-live-strip set2-summary ${set2Stats.eligible>0?'is-confirmed':set2Stats.priced>0?'is-watching':''}"><span class="insight-live-dot"></span><div><strong>${escapeHtml(lcopy('Set 2 model','Model 2. setu','Model 2. setu'))}</strong><small>${escapeHtml(`${set2Stats.candidates} ${lcopy('candidates','kandidátov','kandidátů')} · ${set2Stats.priced} ${lcopy('with live price','s LIVE kurzom','s LIVE kurzem')} · ${set2Stats.eligible} ${lcopy('value signals','value signálov','value signálů')}`)}</small></div></div>`:'';
    const radarPanel=radarTabs+(liveTab==='results'?radarResultCards:liveTab==='set2'?set2Strip+radarCandidateCards:radarStrip+radarCandidateCards);
    if(state.insightsLoading){list.innerHTML=radarPanel+'<div class="insight-feed-empty insight-feed-loading"><span></span><strong>Načítavam…</strong></div>';return;}
    if(channel==='live'&&liveTab==='results'){
      if(radarResults.length){list.innerHTML=radarPanel;return;}
      list.innerHTML=radarTabs+`<div class="insight-feed-empty"><i>✓</i><strong>${escapeHtml(lcopy('No evaluated LIVE signals yet.','Zatiaľ nie sú vyhodnotené žiadne LIVE signály.','Zatím nejsou vyhodnocené žádné LIVE signály.'))}</strong><p>${escapeHtml(lcopy('Only confirmed comeback signals and confirmed Set-2 signals appear here after settlement.','Sem sa po dohraní zapíšu iba potvrdené comeback signály a potvrdené signály 2. setu.','Sem se po dohrání zapíšou pouze potvrzené comeback signály a potvrzené signály 2. setu.'))}</p></div>`;return;
    }
    if(state.insightsStorageUnavailable){
      const liveCopy=uiCopy('private_feed.history_unavailable',lcopy('Alert history is temporarily unavailable. LIVE radar continues to work.','História upozornení je dočasne nedostupná. LIVE radar ďalej funguje.','Historie upozornění je dočasně nedostupná. LIVE radar dále funguje.'));
      const infoCopy=uiCopy('private_feed.info_unavailable',lcopy('Premium Info needs persistent storage. Messages will return automatically when storage is restored.','Premium Info potrebuje trvalé úložisko. Po obnovení sa správy zobrazia automaticky.','Premium Info potřebuje trvalé úložiště. Po obnovení se zprávy zobrazí automaticky.'));
      if(channel==='live'){list.innerHTML=radarPanel+`<div class="insight-storage-note"><i>i</i><span>${escapeHtml(liveCopy)}</span></div>`;}
      else{list.innerHTML=`<div class="insight-feed-empty insight-feed-offline"><i>!</i><strong>${escapeHtml(uiCopy('private_feed.info_title_offline',lcopy('Premium Info temporarily unavailable','Premium Info je dočasne nedostupné','Premium Info je dočasně nedostupné')))}</strong><p>${escapeHtml(infoCopy)}</p></div>`;}
      return;
    }
    if(!rows.length){const set2Empty=channel==='live'&&state.liveRadarTab==='set2';const msg=filter==='unread'?lcopy('You have read everything.','Všetko máš prečítané.','Všechno máš přečtené.'):filter==='pinned'?lcopy('No pinned messages yet.','Zatiaľ nemáš pripnuté správy.','Zatím nemáš připnuté zprávy.'):set2Empty?lcopy('No eligible set-2 candidate is active right now.','Momentálne nie je aktívny žiadny kvalifikovaný kandidát pre 2. set.','Momentálně není aktivní žádný kvalifikovaný kandidát pro 2. set.'):channel==='live'?lcopy('No LIVE signal is active right now.','Momentálne nie je aktívny žiadny LIVE signál.','Momentálně není aktivní žádný LIVE signál.'):lcopy('No messages for your membership yet.','Pre tvoju úroveň zatiaľ nie sú žiadne správy.','Pro tvoji úroveň zatím nejsou žádné zprávy.');const emptyDetail=set2Empty?lcopy('The set-2 radar waits for an eligible Short Odds candidate after a lost first set; a real live set-2 price is shown when the provider offers it.','Radar 2. setu čaká na kvalifikovaného Short Odds kandidáta po prehratom 1. sete; reálny LIVE kurz na 2. set zobrazí, keď ho provider ponúkne.','Radar 2. setu čeká na kvalifikovaného Short Odds kandidáta po prohraném 1. setu; reálný LIVE kurz na 2. set zobrazí, když ho provider nabídne.'):channel==='live'?lcopy('WATCH candidates and confirmed comeback signals will appear here.','WATCH kandidáti a potvrdené comeback signály sa zobrazia tu.','WATCH kandidáti a potvrzené comeback signály se zobrazí zde.'):lcopy('Important BlinQ updates and private member notes will appear here.','Dôležité BlinQ informácie a súkromné správy pre členov sa zobrazia tu.','Důležité BlinQ informace a soukromé zprávy pro členy se zobrazí zde.');list.innerHTML=radarPanel+`<div class="insight-feed-empty"><i>✦</i><strong>${escapeHtml(msg)}</strong><p>${escapeHtml(emptyDetail)}</p></div>`;return;}
    list.innerHTML=radarPanel+rows.map(item=>`<article class="insight-feed-item ${item.read?'is-read':'is-unread'} priority-${escapeHtml(item.priority||'normal')}" data-insight-id="${escapeHtml(item.id)}"><div class="insight-feed-icon type-${escapeHtml(item.type||'insight')}">${escapeHtml(insightTypeIcon(item.type))}</div><div class="insight-feed-content"><header><div><span>${escapeHtml(insightTypeLabel(item.type))}</span>${item.pinned?'<b>PRIPNUTÉ</b>':''}${!item.read?'<em>NEW</em>':''}</div><time>${escapeHtml(item.created_at?fmtDate(item.created_at)+' · '+fmtTime(item.created_at):'')}</time></header><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p><footer><small>${escapeHtml(insightAudienceText(item.levels))}</small>${item.match_id?`<button type="button" data-insight-match="${escapeHtml(item.match_id)}">${escapeHtml(item.link_label||lcopy('Open match','Otvoriť zápas','Otevřít zápas'))}<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 5 5 5-5 5"></path></svg></button>`:item.link?`<a href="${escapeHtml(item.link)}" ${isExternalLink(item.link)?'target="_blank" rel="noopener"':''}>${escapeHtml(item.link_label||lcopy('Open','Otvoriť','Otevřít'))}<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 5 5 5-5 5"></path></svg></a>`:''}</footer></div></article>`).join('');
  }
  async function loadInsights(force=false){
    const generation=feedGeneration;
    const plan=accountPlan();
    if(!['rookie','pro','elite','legend','goat','admin'].includes(plan)){state.insights=[];state.insightsUnread=0;state.insightsStorageUnavailable=false;renderInsightBell();return;}
    if(state.insightsLoading||(!force&&state.insights.length))return;
    const previousUnread=Math.max(0,Number(state.insightsUnread)||0);state.insightsLoading=true;renderInsightDrawer();
    try{
      const data=await BlinqAuth.insights();
      if(generation!==feedGeneration)return;
      state.insights=Array.isArray(data?.items)?data.items:[];state.insightsUnread=Number(data?.unread)||0;state.insightsStorageUnavailable=Boolean(data?.storage_unavailable);state.liveRadarHeartbeat=data?.live_radar_status&&typeof data.live_radar_status==='object'?data.live_radar_status:state.liveRadarHeartbeat;if(force&&state.insightsUnread>previousUnread){const newest=state.insights.find(item=>!item.read);showStatus(newest?`${insightTypeLabel(newest.type)} · ${newest.title}`:'Nová BlinQ správa');}
    }catch{
      if(generation!==feedGeneration)return;
      state.insights=[];state.insightsUnread=0;state.insightsStorageUnavailable=true;
    }finally{
      if(generation===feedGeneration){state.insightsLoading=false;renderInsightBell();renderInsightDrawer();renderSystemFooterStatus();}
    }
  }
  async function refreshPrivateUpdates(force=false){
    const generation=feedGeneration;
    if(state.privateUpdatesBusy||document.hidden||$('appShell')?.hidden)return;const plan=accountPlan();if(!['rookie','pro','elite','legend','goat','admin'].includes(plan))return;const now=Date.now();if(!force&&now-Number(state.privateUpdatesLastPoll||0)<25000)return;state.privateUpdatesBusy=true;state.privateUpdatesLastPoll=now;
    try{await loadInsights(true);if(generation!==feedGeneration)return;if(membershipAtLeast(plan,notificationAudienceConfig().live_min_level))await loadUserLiveRadarStatus(false);}
    finally{if(generation===feedGeneration)state.privateUpdatesBusy=false;}
  }
  async function loadUserLiveRadarStatus(force=false){
    const generation=feedGeneration;
    const plan=accountPlan();if(!membershipAtLeast(plan,notificationAudienceConfig().live_min_level)||state.userLiveRadarLoading)return;
    const scanned=Date.parse(state.userLiveRadarStatus?.scanned_at||'');
    if(!force&&Number.isFinite(scanned)&&Date.now()-scanned<55000)return;
    state.userLiveRadarLoading=true;renderInsightDrawer();
    try{const data=await BlinqAuth.liveRadar();if(generation!==feedGeneration)return;state.userLiveRadarStatus={...data,ok:true};if(state.userLiveRadarStatus?.scanned_at)state.liveRadarHeartbeat={...(state.liveRadarHeartbeat||{}),scanned_at:state.userLiveRadarStatus.scanned_at,fresh:true};}
    catch(error){if(generation!==feedGeneration)return;state.userLiveRadarStatus={error:error.message||'live_unavailable'};}
    finally{if(generation===feedGeneration){state.userLiveRadarLoading=false;renderInsightBell();renderInsightDrawer();renderSystemFooterStatus();}}
  }
  function setInsightDrawer(open,channel=null){
    const drawer=$('insightDrawer'),backdrop=$('insightBackdrop');if(!drawer||!backdrop)return;
    if(channel&&channel!==state.insightChannel){state.insightChannel=channel==='live'?'live':'info';state.insightFilter='all';}
    state.insightDrawerOpen=Boolean(open);drawer.hidden=!state.insightDrawerOpen;backdrop.hidden=!state.insightDrawerOpen;document.body.classList.toggle('insight-open',state.insightDrawerOpen);
    renderInsightBell();renderInsightDrawer();
    if(state.insightDrawerOpen){loadInsights(true);if(state.insightChannel==='live')loadUserLiveRadarStatus(true);}
  }
  function toggleInsightChannel(channel){
    const same=state.insightDrawerOpen&&state.insightChannel===channel;setInsightDrawer(!same,channel);
  }
  async function markInsightRead(id){
    const generation=feedGeneration;
    const item=state.insights.find(row=>String(row.id)===String(id));if(!item||item.read)return;
    item.read=true;state.insightsUnread=Math.max(0,state.insightsUnread-1);renderInsightBell();renderInsightDrawer();
    try{await BlinqAuth.markInsightRead(id);}
    catch{if(generation!==feedGeneration)return;item.read=false;state.insightsUnread+=1;renderInsightBell();renderInsightDrawer();}
  }
  function publicFormLabel(row,pickId=''){
    const signals=Array.isArray(row?.signals)?row.signals:[];let support=0,counter=0,seen=0;const target=String(pickId||row?.betting?.selection_id||row?.selection_id||'');
    for(const signal of signals){const label=String(signal?.label||signal?.name||signal?.type||'').toLowerCase();if(!/(recent|form|momentum)/.test(label))continue;seen++;const favours=String(signal?.player_id??signal?.favours_player_id??'');if(target&&favours){if(favours===target)support++;else counter++;}}
    if(!seen)return '—';if(support>counter)return lcopy('Strong','Silná','Silná');if(counter>support)return lcopy('Mixed','Zmiešaná','Smíšená');return lcopy('Stable','Stabilná','Stabilní');
  }
  function closeMarketLabel(row){
    const market=row?.match_winner_market||{},o1=Number(market?.player1_odds),o2=Number(market?.player2_odds);if(!Number.isFinite(o1)||!Number.isFinite(o2)||o1<=1||o2<=1)return '—';const diff=Math.abs(o1-o2)/((o1+o2)/2);return diff<=.15?lcopy('Balanced','Vyrovnaný','Vyrovnaný'):`${Math.round(diff*100)}%`;
  }
  function apiMarketLine(row){
    const candidates=[row?.line,row?.market_line,row?.betting_line,row?.bookmaker_line,row?.over_under_line,row?.total_line,row?.threshold,row?.betting?.line,row?.betting?.market_line,row?.market?.line];
    for(const candidate of candidates){const value=Number(candidate);if(Number.isFinite(value)&&value>=0)return value;}
    return null;
  }
  function aceMarketName(row){
    const raw=String(row?.market||row?.market_type||'').toLowerCase();
    return raw.includes('double')||raw.includes('fault')?lcopy('Double Faults','Dvojchyby','Dvojchyby'):'Aces';
  }
  function aceProjectionScopeLabel(row){
    const scope=String(row?.projection_scope||'player').toLowerCase();
    return scope==='total'?lcopy('MATCH TOTAL','SPOLU ZÁPAS','CELKEM ZÁPAS'):lcopy('PLAYER','HRÁČ','HRÁČ');
  }
  function aceProjectionTypeLabel(row){
    return `${aceProjectionScopeLabel(row)} · ${aceMarketName(row).toUpperCase()}`;
  }
  function aceLineSide(row){
    const raw=String(row?.side||row?.prediction_side||row?.betting?.side||row?.selection_side||'').trim().toLowerCase();
    if(raw==='over'||raw==='o')return 'Over';
    if(raw==='under'||raw==='u')return 'Under';
    return '';
  }
  function aceHasApiLine(row){return Number.isFinite(apiMarketLine(row));}
  function projectionDirectionLabel(row){
    const raw=String(row?.side||row?.prediction_side||row?.betting?.side||row?.selection_side||row?.projection_direction||'').trim().toLowerCase();
    if(['over','o','high','higher','above'].includes(raw))return 'Over';
    if(['under','u','low','lower','below'].includes(raw))return 'Under';
    const line=apiMarketLine(row),projection=Number(row?.projection);
    if(Number.isFinite(line)&&Number.isFinite(projection)&&projection!==line)return projection>line?'Over':'Under';
    return '';
  }
  function selectionLineFromText(row){
    const text=String(row?.selection||row?.pick||'');
    const match=text.match(/(?:over|under|nad|pod|o|u)\s*([0-9]+(?:[.,][0-9]+)?)/i);
    if(!match)return null;const value=Number(match[1].replace(',','.'));return Number.isFinite(value)?value:null;
  }
  function projectionReferenceLine(row,sourceTab=''){
    const direct=apiMarketLine(row);if(Number.isFinite(direct))return direct;
    const parsed=selectionLineFromText(row);if(Number.isFinite(parsed))return parsed;
    if(sourceTab==='games'){const ref=Number(row?.reference_projection??row?.baseline_projection);if(Number.isFinite(ref))return ref;}
    return null;
  }
  function setsTotalProjectionValue(row){
    const projection=Number(row?.projection),unit=String(row?.projection_unit||'').trim().toLowerCase();
    if(Number.isFinite(projection)&&unit==='sets')return projection;
    // Legacy SG v3 stored direction confidence (0–1) in `projection`. For BO3
    // results/picks, convert that confidence into an expected TOTAL set count so
    // old rows do not render as nonsensical "0.9 Sets".
    if(Number.isFinite(projection)&&unit==='probability'&&projection>=0&&projection<=1){
      const selection=String(row?.selection||row?.pick||'').trim().toLowerCase();
      const line=selectionLineFromText(row),bestOf=Number(row?.best_of)||(Number.isFinite(line)&&Math.abs(line-2.5)<0.01?3:Number.isFinite(line)&&Math.abs(line-3.5)<0.01?5:NaN);
      const over=/\bover\b/.test(selection),under=/\bunder\b/.test(selection);
      if(bestOf===3&&(over||under)){
        const longProbability=over?projection:1-projection;
        return Math.max(2,Math.min(3,2+longProbability));
      }
    }
    return null;
  }
  function projectionPickText(row,sourceTab=''){
    const market=sourceTab||String(row?.market||row?.projection_metric||'').toLowerCase();
    if(market==='sets')return String(row?.selection||row?.pick||'—');
    if(market==='games'){
      const side=projectionDirectionLabel(row),line=projectionReferenceLine(row,'games');
      if(side&&Number.isFinite(line))return `${side} ${line.toFixed(1)} Games`;
      return String(row?.selection||row?.pick||'—').replace(/^High\s+Total\s+Games$/i,'Over total games').replace(/^Low\s+Total\s+Games$/i,'Under total games');
    }
    if(market==='ace'||market==='double_faults'||market==='aces'){
      const subject=String(row?.projection_subject||modelPickName(row)||'').trim();
      const side=projectionDirectionLabel(row),line=projectionReferenceLine(row,market);
      const unit=market==='double_faults'||String(row?.market||'').toLowerCase()==='double_faults'?lcopy('Double Faults','Dvojchyby','Dvojchyby'):lcopy('Aces','Aces','Aces');
      if(side&&Number.isFinite(line))return `${subject?subject+' · ':''}${side} ${line.toFixed(1)} ${unit}`;
      if(Number.isFinite(line))return `${subject?subject+' · ':''}${line.toFixed(1)} ${unit}`;
      return subject||String(row?.selection||row?.pick||'—');
    }
    return modelPickName(row);
  }


  function dailyHubConfig(){
    return state.ui?.dashboard?.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};
  }
  function previewStableRandomSlots(tab,total,count){
    const pool=Math.min(Math.max(0,total),10),wanted=Math.min(Math.max(0,count),pool);
    const dateKey=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()-6*3600*1000));
    const seed=`${state.previewPlan||accountPlan()}|${dateKey}|${tab}`;
    const hash=text=>{let h=2166136261;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;};
    return new Set(Array.from({length:pool},(_,i)=>[hash(`${seed}|${i}`),i]).sort((a,b)=>a[0]-b[0]).slice(0,wanted).map(item=>item[1]));
  }
  function previewDailyHubEntitlement(tab){
    const plan=accountPlan(),cfg=dailyHubConfig(),tabCfg=cfg?.tabs?.[tab]||{};
    const normalized=plan==='trial'?'rookie':plan;
    const rule=tabCfg?.plans?.[plan]||tabCfg?.plans?.[normalized]||tabCfg?.plans?.rookie||{};
    const rows=dailyHubRows(tab),total=rows.length;
    const display=String(rule.display_state||((rule.tab_enabled===false)?'hidden':'active')).toLowerCase();
    const enabled=tabCfg.enabled!==false&&rule.tab_enabled!==false&&display!=='hidden';
    let visible=rule.visible_rows??'ALL';
    if(display==='blurred')visible=0;
    const all=String(visible).toUpperCase()==='ALL';
    const visibleCount=all?total:Math.max(0,Math.min(total,Number(visible)||0));
    const blur=display==='blurred'||rule.blur_remaining!==false;
    const overrides=rule.row_overrides&&typeof rule.row_overrides==='object'?rule.row_overrides:{};
    const randomSlots=String(rule.selection_mode||'first')==='stable_random'&&!all?previewStableRandomSlots(tab,total,visibleCount):null;
    const slot_states=rows.map((_,i)=>{const pos=String(i+1);let state=all||(randomSlots?randomSlots.has(i):i<visibleCount)?'active':(blur?'blurred':'hidden');const override=String(overrides[pos]||'').toLowerCase();if(['active','blurred','hidden'].includes(override))state=override;return state;});
    const returned=slot_states.filter(v=>v==='active').length;
    return {visible_picks:visible,blur_remaining:blur,enabled,see_all:Boolean(rule.see_all),total,returned,locked_count:Math.max(0,total-returned),selection_mode:String(rule.selection_mode||'first'),display_state:display,slot_states,row_overrides:overrides};
  }
  function dailyHubRuleForPlan(tab,plan=accountPlan()){
    const cfg=dailyHubConfig()?.tabs?.[tab]||{},normalized=plan==='trial'?'rookie':plan;
    return cfg?.plans?.[plan]||cfg?.plans?.[normalized]||cfg?.plans?.rookie||{};
  }
  function firstDailyHubUnlockPlan(tab,index=0,forSeeAll=false){
    const cfg=dailyHubConfig()?.tabs?.[tab]||{};
    const plans=membershipHierarchy.filter(id=>state.ui?.plans?.[id]?.enabled!==false);
    // A blurred random slot must never tell an active FREE user to buy FREE.
    // The next unlock tier must be strictly above the actual membership.
    const currentIndex=state.previewPlan?-1:membershipHierarchy.indexOf(accountPlan());
    for(const plan of plans){
      if(currentIndex>=0&&membershipHierarchy.indexOf(plan)<=currentIndex)continue;
      const rule=cfg?.plans?.[plan]||{};const display=String(rule.display_state||((rule.tab_enabled===false)?'hidden':'active')).toLowerCase();
      if(cfg.enabled===false||rule.tab_enabled===false||display==='hidden'||display==='blurred')continue;
      // SEE ALL itself is governed by its own panel access. For normal tabs,
      // an expand/"celá ponuka" request additionally requires see_all=true.
      if(forSeeAll){if(tab==='see_all'||rule.see_all===true)return plan;continue;}
      const override=String(rule?.row_overrides?.[String(index+1)]||'').toLowerCase();
      if(override==='active')return plan;
      if(override==='blurred'||override==='hidden')continue;
      const raw=rule.visible_rows??'ALL';if(String(raw).toUpperCase()==='ALL'||Number(raw)>index)return plan;
    }
    return 'goat';
  }
  function dailyHubEntitlement(tab){
    // ADMIN is unrestricted outside explicit Admin preview mode. Ignore any
    // stale membership slot states that may have been cached before login.
    if(accountPlan()==='admin'&&!state.previewPlan){
      if(tab==='see_all'){
        const daily=state.feed?.entitlements?.sections?.daily||{};
        const value=state.feed?.entitlements?.sections?.value||{};
        const total=Math.max(0,Number(daily.total)||dailyHubRows('daily').length)+Math.max(0,Number(value.total)||dailyHubRows('value').length);
        return {visible_picks:'ALL',blur_remaining:false,enabled:true,see_all:true,total,returned:total,locked_count:0,slot_states:[]};
      }
      const key=tab==='calendar'?'daily':tab==='daily'?'daily':tab==='ace'?'ace':tab==='double_faults'?'double_faults':tab==='games'?'games':tab==='sets'?'sets':tab;
      const server=state.feed?.entitlements?.sections?.[key]||{};
      const rows=dailyHubRows(tab);
      const total=Math.max(Number(server.total)||0,rows.length);
      return {...server,visible_picks:'ALL',blur_remaining:false,enabled:server.enabled!==false,see_all:true,total,returned:rows.length,locked_count:0,slot_states:[]};
    }
    if(tab==='see_all')return previewDailyHubEntitlement(tab);
    if(state.previewPlan&&isAdminAccount())return previewDailyHubEntitlement(tab);
    const key=tab==='calendar'?'daily':tab==='daily'?'daily':tab==='ace'?'ace':tab==='double_faults'?'double_faults':tab==='games'?'games':tab==='sets'?'sets':tab;
    return state.feed?.entitlements?.sections?.[key]||{visible_picks:'ALL',blur_remaining:false,enabled:true,total:0,returned:0};
  }
  function dailyPickIdentity(row){
    return `${row?.event_id||row?.id||row?.match_id||''}::${String(row?.market||row?.projection_metric||row?.betting?.market||'match_winner').toLowerCase()}::${row?.pick||row?.selection||row?.prediction||row?.selection_id||row?.betting?.selection_id||''}`;
  }
  function mergedPrimeRows(){
    const out=[],seen=new Set();
    [...marketRows('prime'),...marketRows('top_daily'),...(Array.isArray(state.feed?.daily_picks)?state.feed.daily_picks:[])].forEach(row=>{
      const id=dailyPickIdentity(row); if(!id||seen.has(id))return; seen.add(id); out.push(row);
    });
    return out;
  }
  function valuePickIds(){ return new Set((marketRows('value')||[]).map(dailyPickIdentity)); }
  function offerSurfaceEligible(row){return String(row?.surface||row?.court_surface||'').trim().toLowerCase()!=='unknown'&&Boolean(String(row?.surface||row?.court_surface||'').trim());}
  function modelPickName(row){ const p1=row?.player1||{},p2=row?.player2||{};const winner=String(row?.winner_id||row?.pick_id||row?.selection_id||'');return row?.pick||row?.selection||row?.prediction||(winner&&String(p1?.id)===winner?p1?.name:winner&&String(p2?.id)===winner?p2?.name:'—')||'—'; }
  function leanSeeAllRows(){
    const rows=[],seen=new Set();
    const add=row=>{const id=dailyPickIdentity(row);if(!row||!id||seen.has(id))return;seen.add(id);rows.push(row);};
    (marketRows('prime')||[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'prime'}));
    (marketRows('value')||[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'value'}));
    (Array.isArray(state.feed?.daily_picks)?state.feed.daily_picks:[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'daily'}));
    (marketRows('ace')||[]).filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()==='aces').forEach(row=>add({...row,_hub_source:'ace'}));
    (marketRows('ace')||[]).filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()==='double_faults').forEach(row=>add({...row,_hub_source:'double_faults'}));
    (marketRows('doubles')||[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'doubles'}));
    (marketRows('sg')||[]).filter(offerSurfaceEligible).forEach(row=>{const market=String(row?.market||'').toLowerCase();if(market==='games'||market==='sets')add({...row,_hub_source:market});});
    return rows.sort((a,b)=>(marketProbability(b)||0)-(marketProbability(a)||0));
  }
  function dailyHubRows(tab){
    if(tab==='daily'){
      // `daily_picks` is already server-authorized; never re-merge legacy arrays client-side.
      // Do not re-merge the legacy prime/top arrays here or a low tier could receive extra rows.
      return (Array.isArray(state.feed?.daily_picks)?state.feed.daily_picks:[]).filter(offerSurfaceEligible);
    }
    if(tab==='prime')return marketRows('prime').filter(offerSurfaceEligible);
    if(tab==='value')return marketRows('value').filter(offerSurfaceEligible);
    if(tab==='ace')return marketRows('ace').filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()==='aces');
    if(tab==='double_faults')return marketRows('ace').filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()==='double_faults');
    if(tab==='doubles')return marketRows('doubles').filter(offerSurfaceEligible);
    if(tab==='games'||tab==='sets')return marketRows('sg').filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()===tab);
    if(tab==='see_all')return leanSeeAllRows();
    return [];
  }

  function dashboardFilteredRows(rows){
    const source=Array.isArray(rows)?rows:[];
    const query=String(state.dashboardSearch||'').trim().toLocaleLowerCase();
    const selectedTournament=String(state.dailyHubTournament||'').trim();
    // A tournament selection can survive a tab switch. Only apply it when the
    // selected tournament exists in the current source; otherwise the next
    // render would appear empty until the select control resets itself.
    const tournamentActive=selectedTournament&&source.some(row=>String(row?.tournament||row?.competition||'').trim()===selectedTournament);
    if(!query&&!tournamentActive)return source;
    return source.filter(row=>{
      if(tournamentActive&&String(row?.tournament||row?.competition||'').trim()!==selectedTournament)return false;
      if(!query)return true;
      const p1=row?.player1||{},p2=row?.player2||{};
      const searchable=[
        p1.name,row?.player1_name,p2.name,row?.player2_name,
        row?.tournament,row?.competition,row?.tour,row?.surface,
        p1.country_code,p1.country_code2,p1.country_code3,p1.country?.name,
        p2.country_code,p2.country_code2,p2.country_code3,p2.country?.name,
        row?.tournament_country_code,row?.country_code,row?.venue_country_code,
        row?.country,row?.venue_country
      ].filter(value=>value!==undefined&&value!==null).join(' ').toLocaleLowerCase();
      return searchable.includes(query);
    });
  }
  function dailyHubTabLabel(tab){
    return {daily:'TOP',prime:'SHORT ODDS',value:'VALUE',ace:'ACES',double_faults:'DVOJCHYBY',doubles:'DOUBLES',games:'GAMES',sets:'SETS',see_all:'SEE ALL'}[tab]||String(tab||'').toUpperCase();
  }
  function dailyHubIsComingSoon(tab){return false;}
  function dailyHubColumns(tab){
    if(dailyHubIsComingSoon(tab))return [''];
    const time=lcopy('TIME','ČAS','ČAS'),tournament=lcopy('TOURNAMENT','TURNAJ','TURNAJ'),match=lcopy('MATCH','ZÁPAS','ZÁPAS'),prediction=lcopy('PREDICTION','PREDIKCIA','PREDIKCE'),odds=lcopy('ODDS','KURZ','KURZ'),projection=lcopy('PROJECTION','PROJEKCIA','PROJEKCE'),confidence=lcopy('CONFIDENCE','ISTOTA','JISTOTA');
    if(tab==='see_all')return ['#',time,tournament,match,prediction,odds,lcopy('MODEL','MODEL','MODEL'),''];
    if(tab==='value')return ['#',time,tournament,match,prediction,odds,'BLINQ %',''];
    if(tab==='ace'||tab==='double_faults')return ['#',time,tournament,match,prediction,odds,projection,confidence];
    if(tab==='doubles')return ['#',time,tournament,match,prediction,odds,'BLINQ %',''];
    if(tab==='games'||tab==='sets')return ['#',time,tournament,match,prediction,odds,projection,confidence];
    return ['#',time,tournament,match,prediction,odds,'BLINQ %',''];
  }
  function dailyHubColumnKeys(tab){
    if(tab==='value')return ['rank','time','tournament','match','pick','number','confidence','action'];
    if(tab==='ace'||tab==='double_faults'||tab==='games'||tab==='sets')return ['rank','time','tournament','match','pick','number','number','confidence'];
    if(tab==='doubles')return ['rank','time','tournament','match','pick','number','confidence','action'];
    return ['rank','time','tournament','match','pick','number','confidence','action'];
  }
  function hubDataDepthLabel(row){
    const depth=Number(row?.data_depth??row?.dataDepth);
    if(Number.isFinite(depth))return `DATA DEPTH · ${Math.round(Math.max(0,Math.min(1,depth))*100)}%`;
    const samples=row?.projection_samples&&typeof row.projection_samples==='object'?row.projection_samples:{};
    const a=Number(samples.player1),b=Number(samples.player2);
    if(Number.isFinite(a)&&Number.isFinite(b)&&a>0&&b>0)return `DATA DEPTH · ${Math.trunc(a)}/${Math.trunc(b)}`;
    const q=row?.quality||{},qa=Number(q?.player1?.matches),qb=Number(q?.player2?.matches);
    if(Number.isFinite(qa)&&Number.isFinite(qb)&&qa>0&&qb>0)return `DATA DEPTH · ${Math.trunc(qa)}/${Math.trunc(qb)}`;
    return '';
  }
  function hubConfidenceHtml(value,row=null){
    const depth=hubDataDepthLabel(row);
    const n=Number(value);if(!Number.isFinite(n))return `<span class="hub-confidence is-empty"><strong>—</strong>${depth?`<small class="hub-data-depth">${escapeHtml(depth)}</small>`:''}</span>`;
    const normalized=n<=1?n:n/100,p=Math.max(0,Math.min(100,normalized*100));
    return `<span class="hub-confidence"><strong>${escapeHtml(pct(n))}</strong><i aria-hidden="true"><b style="width:${p.toFixed(1)}%"></b></i>${depth?`<small class="hub-data-depth" title="${escapeHtml(lcopy('Usable historical sample behind this prediction','Použiteľná historická vzorka za touto predikciou','Použitelný historický vzorek za touto predikcí'))}">${escapeHtml(depth)}</small>`:''}</span>`;
  }
  function hubPredictionHtml(sourceTab,text,subLabel=''){
    const label=subLabel||({daily:'TOP',prime:'SHORT ODDS',value:'VALUE',ace:'ACES',double_faults:'DVOJCHYBY',doubles:'DOUBLES',games:'GAMES',sets:'SETS'}[sourceTab]||String(sourceTab||'').toUpperCase());
    return `<span class="hub-pick-stack"><small>${escapeHtml(label)}</small><strong title="${escapeHtml(text)}">${escapeHtml(text)}</strong></span>`;
  }
  function hubNumberHtml(value,label=''){
    return `<span class="hub-number-stack"><strong>${escapeHtml(value)}</strong>${label?`<small>${escapeHtml(label)}</small>`:''}</span>`;
  }
  function hubSeeAllProjectionHtml(value,label,confidence,row){
    const n=Number(confidence),confidenceText=Number.isFinite(n)?pct(n):'—',depth=hubDataDepthLabel(row);
    return `<span class="hub-seeall-model"><span class="hub-number-stack"><strong>${escapeHtml(value)}</strong><small>${escapeHtml(label)}</small></span><span class="hub-seeall-confidence"><strong>${escapeHtml(confidenceText)}</strong>${depth?`<small>${escapeHtml(depth)}</small>`:''}</span></span>`;
  }
  function safeNum(value){ const n=Number(value); return Number.isFinite(n)?n:null; }
  function clampValue(value,min=0,max=100){ const n=Number(value); if(!Number.isFinite(n)) return min; return Math.max(min,Math.min(max,n)); }
  function firstFinite(...values){
    for(const value of values){
      if(value===null||value===undefined||value===''||typeof value==='boolean') continue;
      const n=Number(value);
      if(Number.isFinite(n)) return n;
    }
    return null;
  }
  function eventKey(row){ return String(row?.event_id||row?.id||''); }
  function candidatePathValues(obj,path){
    if(!obj||!path) return [];
    const parts=String(path).split('.');
    let list=[obj];
    for(const part of parts){
      const next=[];
      for(const item of list){
        if(!item||typeof item!=='object') continue;
        if(Array.isArray(item)){
          for(const entry of item){ if(entry&&typeof entry==='object'&&part in entry) next.push(entry[part]); }
        }else if(part in item) next.push(item[part]);
      }
      list=next;
      if(!list.length) break;
    }
    return list;
  }
  function readFirstValue(obj,paths=[]){
    for(const key of paths){
      for(const value of candidatePathValues(obj,key)){
        if(value!==undefined&&value!==null&&value!=='') return value;
      }
    }
    return null;
  }
  function tournamentDisplayMeta(row){
    const rawName=String(row?.tournament||row?.competition_name||row?.competition||row?.tour||'Turnaj').trim();
    const explicitCity=String(row?.venue_city||row?.tournament_city||row?.location?.city||'').trim();
    const explicitCountryName=String(row?.venue_country||row?.tournament_country||row?.location?.country||row?.country_name||'').trim();
    const countryCode=explicitTournamentCountry(row);
    // Location is rendered only when the API/provider exposes it explicitly.
    // Never infer a venue from the tournament title or a draw/group suffix.
    const location=[explicitCity,explicitCountryName].filter(Boolean).filter((v,i,a)=>a.indexOf(v)===i).join(', ');
    return {name:rawName||'Turnaj',location,countryCode};
  }
  function tournamentIdentityHtml(row,compact=false){
    const meta=tournamentDisplayMeta(row);
    const location=meta.location?`<small class="tournament-location">${flagIconHtml(meta.countryCode,true)}<span>${escapeHtml(meta.location)}</span></small>`:'';
    return `<span class="tournament-identity${compact?' is-compact':''}">${tournamentVisual(row)}<span class="tournament-identity-copy"><strong title="${escapeHtml(meta.name)}">${escapeHtml(meta.name)}</strong>${location}</span></span>`;
  }

  function tournamentFallbackBadge(row){
    const tour=String(row?.tour||row?.category||'').trim().toUpperCase();
    const competition=String(row?.competition||row?.tournament_level||row?.level||row?.category_name||'').trim().toUpperCase();
    const tournament=String(row?.tournament||row?.competition_name||'').trim().toUpperCase();
    const raw=`${tour} ${competition} ${tournament}`.replace(/\s+/g,' ').trim();
    let family='TENNIS',asset='/assets/tournament-fallbacks/tennis.svg';
    if(/US OPEN/.test(raw)){family='US OPEN';asset='/assets/tournament-fallbacks/us-open.svg';}
    else if(/WIMBLEDON/.test(raw)){family='WIMBLEDON';asset='/assets/tournament-fallbacks/wimbledon.svg';}
    else if(/ROLAND GARROS|FRENCH OPEN/.test(raw)){family='ROLAND GARROS';asset='/assets/tournament-fallbacks/roland-garros.svg';}
    else if(/AUSTRALIAN OPEN/.test(raw)){family='AUSTRALIAN OPEN';asset='/assets/tournament-fallbacks/australian-open.svg';}
    else if(/GRAND SLAM|\bSLAM\b/.test(raw)){family='GRAND SLAM';asset='/assets/tournament-fallbacks/grand-slam.svg';}
    else if(/DAVIS CUP|BILLIE JEAN KING|FED CUP|UNITED CUP|LAVER CUP|HOPMAN CUP/.test(raw)){family='TEAM CUP';asset='/assets/tournament-fallbacks/team-cup.svg';}
    else if(/OLYMPIC|OLYMPIJSK|OLYMPIÁD/.test(raw)){family='TEAM EVENT';asset='/assets/tournament-fallbacks/team-event.svg';}
    else if(/\bUTR\b|UNIVERSAL TENNIS/.test(raw)){family='UTR';asset='/assets/tournament-fallbacks/utr.svg';}
    else if(/CHALLENGER|\bCH\b/.test(raw)){family='CHALLENGER';asset='/assets/tournament-fallbacks/challenger.svg';}
    else if(/MASTERS\s*1000|ATP\s*1000/.test(raw)){family='ATP';asset='/assets/tournament-fallbacks/masters-1000.svg';}
    else if(/ATP\s*500/.test(raw)){family='ATP';asset='/assets/tournament-fallbacks/atp-500.svg';}
    else if(/ATP\s*250/.test(raw)){family='ATP';asset='/assets/tournament-fallbacks/atp-250.svg';}
    else if(/WTA\s*1000/.test(raw)){family='WTA';asset='/assets/tournament-fallbacks/wta-1000.svg';}
    else if(/WTA\s*500/.test(raw)){family='WTA';asset='/assets/tournament-fallbacks/wta-500.svg';}
    else if(/WTA\s*250/.test(raw)){family='WTA';asset='/assets/tournament-fallbacks/wta-250.svg';}
    else if(/WTA\s*125/.test(raw)){family='WTA';asset='/assets/tournament-fallbacks/wta-125.svg';}
    else if(tour.includes('ITF')||/\bITF\b|\b[MW](?:15|25|35|50|75|100)\b/.test(raw)){family='ITF';asset='/assets/tournament-fallbacks/itf.svg';}
    else if(tour.includes('WTA')){family='WTA';asset='/assets/tournament-fallbacks/wta.svg';}
    else if(tour.includes('ATP')){family='ATP';asset='/assets/tournament-fallbacks/atp.svg';}
    return {top:family,asset};
  }
  function tournamentFallbackHtml(row){
    const badge=tournamentFallbackBadge(row);
    return '<span class="hub-logo-code single"><img class="hub-type-logo" src="'+escapeHtml(badge.asset)+'" alt="'+escapeHtml(badge.top)+'" loading="lazy"></span>';
  }
  function tournamentVisual(row){
    const tournamentId=String(row?.tournament_logo_id||row?.tournament_id||row?.tournamentId||row?.unique_tournament_id||row?.uniqueTournament?.id||'').trim();
    const explicit=safePhotoUrl(row?.tournament_logo_url||row?.competition_logo_url||row?.competition_logo||row?.tournament_logo||'');
    const logo=explicit; // r40: cached release asset only; never spend provider quota from a public render
    const fallback=tournamentFallbackHtml(row);
    if(logo) return '<span class="hub-tournament-logo has-image"><img data-tournament-logo src="'+escapeHtml(logo)+'" alt="" loading="lazy"><span class="hub-logo-fallback">'+fallback+'</span></span>';
    return '<span class="hub-tournament-logo hub-tournament-badge logo-failed">'+fallback+'</span>';
  }
  function smallAvatar(photo,name,tour,gender=''){
    return playerAvatarHtml(photo,name,tour,gender,'hub-avatar');
  }
  function hubPlayerMeta(player,tour){
    const name=player?.name||'—';
    const rank=firstFinite(player?.rank,player?.ranking,player?.current_rank);
    const country=player?.country_code||player?.country_code2||player?.country_code3||player?.country?.alpha2||player?.country?.alpha3||'';
    const photo=playerPhotoSource(null,player,'');
    const rankText=rank!=null&&rank>0?'#'+Math.trunc(rank):'—';
    const tourText=String(tour||'').toUpperCase();
    return '<span class="hub-player">'+smallAvatar(photo,name,tour,player?.gender||player?.sex||'')+'<span class="hub-player-copy"><b>'+escapeHtml(name)+'</b><small class="hub-player-meta">'+flagIconHtml(country,true)+'<span class="hub-rank">'+escapeHtml(rankText)+'</span><span class="hub-tour">'+escapeHtml(tourText)+'</span></small></span></span>';
  }
  function dailyHubTournament(row){
    const display=tournamentDisplayMeta(row);
    const country=display.countryCode||row?.tournament_country_code||row?.country_code||row?.venue_country_code||'';
    const tour=String(row?.tour||'').trim().toUpperCase();
    const round=String(row?.round||row?.round_name||'').trim();
    const surface=surfaceShortName(row?.surface||'');
    const meta=[tour,round,surface&&surface!=='Surface'?surface:''].filter(Boolean);
    const location=display.location?`<span class="hub-tournament-location">${flagIconHtml(country,true)}${escapeHtml(display.location)}</span>`:'';
    return `<span class="hub-tournament hub-tournament-pro">${tournamentVisual(row)}<span class="hub-tournament-copy"><b title="${escapeHtml(display.name)}">${escapeHtml(display.name)}</b><small>${meta.map(value=>`<span>${escapeHtml(value)}</span>`).join('')}</small>${location}</span></span>`;
  }
  function dailyHubMatch(row){
    const p1=row?.player1||{},p2=row?.player2||{};
    const n1=String(p1.name||row?.player1_name||'—'),n2=String(p2.name||row?.player2_name||'—');
    const c1=p1.country_code||p1.country_code2||p1.country_code3||row?.player1_country_code||row?.p1_country_code||'';
    const c2=p2.country_code||p2.country_code2||p2.country_code3||row?.player2_country_code||row?.p2_country_code||'';
    const r1=firstFinite(p1.rank,p1.ranking,p1.current_rank,row?.player1_rank,row?.p1_rank),r2=firstFinite(p2.rank,p2.ranking,p2.current_rank,row?.player2_rank,row?.p2_rank);
    const photoFor=(player,side)=>playerPhotoSource(row,player,side);
    const selected=String(row?.pick||row?.selection||row?.prediction||'').trim().toLocaleLowerCase();
    const line=(player,side,name,country,rank)=>`<span class="hub-match-player${selected&&selected===String(name).toLocaleLowerCase()?' is-pick':''}"><span class="hub-match-player-main">${smallAvatar(photoFor(player,side),name,row?.tour,player?.gender||player?.sex||'')}${flagIconHtml(country,true)}<b title="${escapeHtml(name)}">${escapeHtml(name)}</b></span>${Number.isFinite(Number(rank))&&Number(rank)>0?`<small>#${Math.trunc(Number(rank))}</small>`:''}</span>`;
    return `<span class="hub-match hub-match-pro">${line(p1,'player1',n1,c1,r1)}<i class="hub-match-divider" aria-hidden="true"></i>${line(p2,'player2',n2,c2,r2)}</span>`;
  }
  function recentFormData(source,key){
    const presentation=source?.presentation&&typeof source.presentation==='object'?source.presentation:{};
    const value=presentation?.[key]&&typeof presentation[key]==='object'?presentation[key]:{};
    const matches=Number(value?.matches),wins=Number(value?.wins),winPct=Number(value?.win_pct);
    const sequence=Array.isArray(value?.sequence)?value.sequence.filter(v=>v==='W'||v==='L').slice(-10):[];
    return {
      matches:Number.isFinite(matches)?matches:null,
      wins:Number.isFinite(wins)?wins:null,
      winPct:Number.isFinite(winPct)?winPct:null,
      sequence
    };
  }
  function formSummaryDisplay(form,label='Form'){
    if(form.matches==null||form.matches<=0||form.winPct==null)return '—';
    return `${label} L${Math.round(form.matches)} = ${Math.round(form.winPct*100)}%`;
  }
  function rankMovement(current,previous){
    const now=Number(current),prior=Number(previous);
    if(!Number.isFinite(now)||!Number.isFinite(prior)||now<=0||prior<=0||now===prior)return '';
    const delta=prior-now;
    return `${delta>0?'↑':'↓'}${Math.abs(Math.trunc(delta))}`;
  }
  function surfaceShortName(value){
    const text=String(value||'').toLowerCase();
    if(text.includes('clay'))return 'Clay';
    if(text.includes('grass'))return 'Grass';
    if(text.includes('hard'))return 'Hard';
    if(text.includes('carpet'))return 'Carpet';
    return value&&value!=='unknown'?String(value).replaceAll('_',' '):'Surface';
  }
  function formSequenceHtml(form){
    if(!form.sequence.length)return '<span class="form-empty">—</span>';
    return form.sequence.map(v=>'<i class="form-dot '+(v==='W'?'win':'loss')+'">'+v+'</i>').join('');
  }
  function presentationMetric(source, keys, scale=1){
    const presentation=source?.presentation&&typeof source.presentation==='object'?source.presentation:{};
    for(const key of keys){
      const raw=readFirstValue(presentation,[key]) ?? readFirstValue(source,[key]);
      const value=Number(raw);
      if(Number.isFinite(value)) return value*scale;
    }
    return null;
  }
  function formatPctMetric(value){
    if(!Number.isFinite(Number(value))) return '—';
    const n=Number(value); const pctValue=Math.abs(n)<=1?n*100:n;
    return pctValue.toFixed(pctValue<10?1:0)+'%';
  }
  function dataCoverageInfo(row){
    const depth=Number(row?.data_depth);
    const pctValue=Number.isFinite(depth)?Math.round(Math.max(0,Math.min(1,depth))*100):null;
    const label=pctValue==null?'—':pctValue>=85?lcopy('High coverage','Vysoké pokrytie','Vysoké pokrytí'):pctValue>=65?lcopy('Good coverage','Dobré pokrytie','Dobré pokrytí'):lcopy('Limited coverage','Obmedzené pokrytie','Omezené pokrytí');
    return {pct:pctValue,label};
  }
  function playerInsightStats(row,side){
    const match=normalize(row);
    const source=row?.['player'+side]||{};
    const quality=row?.quality?.['player'+side]||{};
    const presentation=source?.presentation&&typeof source.presentation==='object'?source.presentation:{};
    const probability=side===1?firstFinite(match.p1Prob,source.probability):firstFinite(match.p2Prob,source.probability);
    const rank=side===1?match.p1Rank:match.p2Rank;
    const surfaceSample=firstFinite(presentation?.surface_history_matches,quality?.surface_matches,source?.surface_matches,readFirstValue(source,['surface.history_count','surface_matches']));
    const overallSample=firstFinite(presentation?.history_matches,quality?.matches,source?.matches,readFirstValue(source,['history.matches','matches_played']));
    const overallForm=recentFormData(source,'recent_form');
    const surfaceForm=recentFormData(source,'surface_form');
    const probabilityPct=probability!=null&&Number.isFinite(Number(probability))?Number(probability)*(Number(probability)<=1?100:1):null;
    // Radar is a visual comparison index. 50% match probability is neutral (zero edge).
    const probabilityScore=probabilityPct!=null?clampValue((probabilityPct-50)*2,0,100):null;
    const rankScore=Number.isFinite(Number(rank))&&Number(rank)>0?clampValue(100-(Math.min(Number(rank),250)/250)*100,4,99):null;
    const surfaceScore=surfaceSample!=null?clampValue((Number(surfaceSample)/20)*100,4,100):null;
    const experienceScore=overallSample!=null?clampValue((Number(overallSample)/50)*100,4,100):null;
    const formScore=overallForm.winPct!=null?clampValue(overallForm.winPct*100,0,100):null;
    return {
      probability: probabilityScore, rawProbability: probabilityPct,
      rank:Number.isFinite(Number(rank))&&Number(rank)>0?Number(rank):null, rankScore,
      surfaceSample,overallSample,surfaceScore,experienceScore,form:formScore,
      overallForm,surfaceForm,
      h2hWins:Number.isFinite(Number(presentation?.h2h_wins))?Number(presentation.h2h_wins):null,
      h2hLosses:Number.isFinite(Number(presentation?.h2h_losses))?Number(presentation.h2h_losses):null,
      h2hMatches:Number.isFinite(Number(presentation?.h2h_matches))?Number(presentation.h2h_matches):null,
      serveDisplay:formatPctMetric(presentationMetric(source,['serve_win_pct','serve.win_pct','serve_quality'])),
      returnDisplay:formatPctMetric(presentationMetric(source,['return_win_pct','return.win_pct','return_quality'])),
      aceDisplay:(()=>{const v=presentationMetric(source,['aces_per_match','ace_rate']);return Number.isFinite(v)?v.toFixed(1):'—';})(),
      formDisplay:formSummaryDisplay(overallForm),
      netDisplay:'—',
      probabilityDisplay: probabilityPct!=null?probabilityPct.toFixed(1)+'%':'—',
      rankDisplay: Number.isFinite(Number(rank))&&Number(rank)>0?'#'+Math.trunc(Number(rank)):'—',
      surfaceDisplay: surfaceSample!=null?String(Math.round(surfaceSample)):'—',
      historyDisplay: overallSample!=null?String(Math.round(overallSample)):'—',
      overallFormDisplay:formSummaryDisplay(overallForm,'Form'),
      surfaceFormDisplay:formSummaryDisplay(surfaceForm,surfaceShortName(row?.surface||match.surface))
    };
  }
  function radarPoints(values,cx,cy,radius){
    const total=values.length||1;
    return values.map((value,index)=>{const angle=-Math.PI/2+(Math.PI*2*index/total);const r=radius*(clampValue(value,0,100)/100);return [cx+Math.cos(angle)*r,cy+Math.sin(angle)*r];});
  }
  function svgPointString(points){ return points.map(([x,y])=>x.toFixed(1)+','+y.toFixed(1)).join(' '); }
  function renderRadarComparison(row){
    const match=normalize(row),stats1=playerInsightStats(row,1),stats2=playerInsightStats(row,2);
    const candidates=[
      [lcopy('BlinQ edge','BlinQ edge','BlinQ edge'),stats1.probability,stats2.probability],
      [lcopy('Ranking','Rebríček','Žebříček'),stats1.rankScore,stats2.rankScore],
      [lcopy('Form','Forma','Forma'),stats1.form,stats2.form],
      [surfaceShortName(row?.surface||match.surface)+' '+lcopy('form','forma','forma'),stats1.surfaceForm.winPct!=null?stats1.surfaceForm.winPct*100:null,stats2.surfaceForm.winPct!=null?stats2.surfaceForm.winPct*100:null],
      [lcopy('Surface sample','Povrchová vzorka','Povrchový vzorek'),stats1.surfaceScore,stats2.surfaceScore]
    ];
    let metrics=candidates.filter(([,a,b])=>Number.isFinite(a)&&Number.isFinite(b));
    metrics=metrics.slice(0,6);
    if(metrics.length<3){
      return '<div class="insight-radar-head"><div><h3>'+escapeHtml(lcopy('Player radar','Radar hráčov','Radar hráčů'))+'</h3></div></div><div class="radar-unavailable">'+escapeHtml(lcopy('Not enough comparable API data for a radar yet.','Zatiaľ nie je dosť porovnateľných API dát pre radar.','Zatím není dost porovnatelných API dat pro radar.'))+'</div>';
    }
    const labels=metrics.map(m=>m[0]),p1=metrics.map(m=>m[1]),p2=metrics.map(m=>m[2]);
    const cx=170,cy=168,radius=112,levels=5;
    const grids=[];
    for(let level=1;level<=levels;level++){
      const r=radius*(level/levels);
      const points=Array.from({length:labels.length},(_,index)=>{const angle=-Math.PI/2+(Math.PI*2*index/labels.length);return [cx+Math.cos(angle)*r,cy+Math.sin(angle)*r];});
      grids.push('<polygon points="'+svgPointString(points)+'" class="insight-radar-grid"></polygon>');
    }
    const axes=labels.map((label,index)=>{const angle=-Math.PI/2+(Math.PI*2*index/labels.length);const x=cx+Math.cos(angle)*radius;const y=cy+Math.sin(angle)*radius;const lx=cx+Math.cos(angle)*(radius+24);const ly=cy+Math.sin(angle)*(radius+24);return '<g><line x1="'+cx+'" y1="'+cy+'" x2="'+x.toFixed(1)+'" y2="'+y.toFixed(1)+'" class="insight-radar-axis"></line><text x="'+lx.toFixed(1)+'" y="'+ly.toFixed(1)+'" class="insight-radar-label">'+escapeHtml(label)+'</text></g>';}).join('');
    const p1Polygon=svgPointString(radarPoints(p1,cx,cy,radius));
    const p2Polygon=svgPointString(radarPoints(p2,cx,cy,radius));
    return '<div class="insight-radar-head"><div><h3>'+escapeHtml(lcopy('Player radar','Radar hráčov','Radar hráčů'))+'</h3></div><div class="insight-radar-legend"><span><i class="legend-dot player-1"></i>'+escapeHtml(match.p1)+'</span><span><i class="legend-dot player-2"></i>'+escapeHtml(match.p2)+'</span></div></div><svg class="insight-radar-svg" viewBox="0 0 340 340" role="img" aria-label="Player comparison radar chart">'+grids.join('')+axes+'<polygon points="'+p2Polygon+'" class="insight-radar-area player-2"></polygon><polygon points="'+p1Polygon+'" class="insight-radar-area player-1"></polygon></svg>';
  }
  function insightSummaryCards(row,tab){
    const match=normalize(row),stats1=playerInsightStats(row,1),stats2=playerInsightStats(row,2);const probability=marketProbability(row);const line=apiMarketLine(row),odds=Number(row?.odds??row?.betting?.odds),ev=Number(row?.expected_value??row?.betting?.expected_value);
    const lineValue=tab==='ace'||tab==='double_faults'||tab==='games'?(Number.isFinite(line)?line.toFixed(1):'—'):(Number.isFinite(odds)?odds.toFixed(2):'—');
    const marketLabel=tab==='value'?lcopy('Close market','Trh','Trh'):tab==='ace'?lcopy('Aces line','Hranica es','Hranica es'):tab==='double_faults'?lcopy('Double faults line','Hranica dvojchýb','Hranice dvojchyb'):tab==='games'?lcopy('Games line','Hranica gemov','Hranice gemů'):lcopy('Odds','Kurz','Kurz');
    const coverage=dataCoverageInfo(row);
    const cards=[
      ['BlinQ pick',match.pick],
      ['BlinQ %',probability==null?'—':pct(probability)],
      [marketLabel,lineValue],
      [lcopy('Data coverage','Pokrytie dát','Pokrytí dat'),coverage.pct==null?'—':coverage.pct+'% · '+coverage.label],
      [lcopy('Rankings','Rebríček','Žebříček'),(Number.isFinite(Number(match.p1Rank))?'#'+Math.trunc(Number(match.p1Rank)):'—')+' vs '+(Number.isFinite(Number(match.p2Rank))?'#'+Math.trunc(Number(match.p2Rank)):'—')],
      [lcopy('Surface sample','Povrchová vzorka','Povrchový vzorek'),(stats1.surfaceSample!=null?Math.round(stats1.surfaceSample):'—')+' vs '+(stats2.surfaceSample!=null?Math.round(stats2.surfaceSample):'—')]
    ];
    return '<div class="insight-summary-grid">'+cards.map(([label,value])=>'<div class="insight-summary-card"><small>'+escapeHtml(label)+'</small><strong>'+escapeHtml(String(value))+'</strong></div>').join('')+'</div>';
  }
  function insightPlayerCard(row,side){
    const match=normalize(row);
    const name=side===1?match.p1:match.p2,country=side===1?match.p1Country:match.p2Country,rank=side===1?match.p1Rank:match.p2Rank,photo=side===1?match.p1Photo:match.p2Photo;
    const previousRank=side===1?match.p1PrevRank:match.p2PrevRank;
    const bestRank=side===1?match.p1BestRank:match.p2BestRank;
    const rankingPoints=side===1?match.p1RankingPoints:match.p2RankingPoints;
    const stats=playerInsightStats(row,side),picked=String(match.pick||'').toLowerCase()===String(name).toLowerCase();
    const tour=String(row?.tour||match.tour||'').toUpperCase();
    const h2h=stats.h2hWins!=null&&stats.h2hLosses!=null?`${stats.h2hWins}–${stats.h2hLosses}${stats.h2hMatches?` · L${Math.round(stats.h2hMatches)}`:''}`:'—';
    const surfaceLabel=surfaceShortName(row?.surface||match.surface);
    const metrics=[
      ['BlinQ %',stats.probabilityDisplay],
      [lcopy('Rank','Rank','Rank'),stats.rankDisplay+(tour?' '+tour:'')],
      [lcopy('Form','Forma','Forma'),stats.overallFormDisplay],
      [surfaceLabel,stats.surfaceFormDisplay],
      ['H2H',h2h]
    ];
    if(Number.isFinite(Number(bestRank))&&Number(bestRank)>0) metrics.push([lcopy('Career high','Career high','Career high'),'#'+Math.trunc(Number(bestRank))]);
    if(Number.isFinite(Number(rankingPoints))&&Number(rankingPoints)>0) metrics.push([lcopy('Points','Body','Body'),Math.trunc(Number(rankingPoints)).toLocaleString()]);
    return '<article class="insight-player-card'+(picked?' picked':'')+'">'+(picked?'<span class="insight-picked-badge">BLINQ PICK</span>':'')+'<div class="insight-player-head">'+smallAvatar(photo,name,row?.tour||'')+'<div><h4>'+escapeHtml(name)+'</h4><p class="insight-player-rankline">'+playerMetaHtml(rank,country,tour)+'</p></div></div><div class="insight-player-metrics">'+metrics.map(([label,value])=>'<span><small>'+escapeHtml(label)+'</small><strong>'+escapeHtml(value)+'</strong></span>').join('')+'</div></article>';
  }

  function renderDailyHubInsight(){
    const host=$('dailyHubInsightBoard'),main=$('dailyHubInsightMain');
    if(!host||!main) return;
    const rows=dailyHubRows(state.dailyHubTab)||[];
    const selectedId=state.dailyHubSelected?.[state.dailyHubTab]||'';
    const row=rows.find(item=>eventKey(item)===selectedId)||rows[0]||null;
    host.hidden=!row;
    if(!row){
      main.innerHTML='<div class="state-card">V tejto kategórii zatiaľ nie sú dáta pre match intelligence.</div>';
      return;
    }
    state.dailyHubSelected[state.dailyHubTab]=eventKey(row);
    const match=normalize(row),probability=marketProbability(row),s1=playerInsightStats(row,1),s2=playerInsightStats(row,2);
    const quick=[
      [lcopy('BlinQ probability','BlinQ pravdepodobnosť','BlinQ pravděpodobnost'),s1.probabilityDisplay,s2.probabilityDisplay],
      [lcopy('Ranking','Rebríček','Žebříček'),s1.rankDisplay,s2.rankDisplay],
      [lcopy('Surface sample','Povrchová vzorka','Povrchový vzorek'),s1.surfaceDisplay,s2.surfaceDisplay],
      [lcopy('History sample','Historická vzorka','Historický vzorek'),s1.historyDisplay,s2.historyDisplay]
    ];
    main.innerHTML='<div class="insight-main-head"><div><small>'+escapeHtml(String(row?.tour||match.tour||'').toUpperCase()+' · '+String(row?.round||match.round||'').toUpperCase())+'</small><h3>'+escapeHtml(match.p1)+' <span>vs</span> '+escapeHtml(match.p2)+'</h3><p>'+escapeHtml((row?.tournament||row?.competition||match.tournament)+' · '+String(match.surface||'').replaceAll('_',' ').toUpperCase()+' · '+fmtDate(match.date)+' · '+fmtTime(match.date))+'</p></div><div class="insight-main-score"><small>BlinQ</small><strong>'+escapeHtml(probability==null?'—':pct(probability))+'</strong><span class="confidence '+escapeHtml(match.confidence)+'">'+escapeHtml(confidenceLabel(match.confidence))+'</span></div></div>'+insightSummaryCards(row,state.dailyHubTab)+'<div class="insight-versus-grid">'+insightPlayerCard(row,1)+insightPlayerCard(row,2)+'</div><div class="insight-inline-footer"><div class="insight-compare-list">'+quick.map(([label,a,b])=>'<div class="insight-compare-row"><span>'+escapeHtml(label)+'</span><strong>'+escapeHtml(String(a))+'</strong><b>'+escapeHtml(String(b))+'</b></div>').join('')+'</div><button class="btn btn-ghost insight-modal-cta" type="button" id="dailyHubInsightOpen">'+escapeHtml(lcopy('Open comparison + radar','Otvoriť porovnanie + radar','Otevřít porovnání + radar'))+'</button></div>';
    const open=$('dailyHubInsightOpen'); if(open) open.onclick=()=>openMatch(match,state.dailyHubTab,row);
  }
  function aceProjectionDetailData(row){
    const p1=row?.player1||{},p2=row?.player2||{};
    const p1Name=String(p1?.name||row?.player1_name||'Player 1');
    const p2Name=String(p2?.name||row?.player2_name||'Player 2');
    const selectedId=String(row?.selection_id||row?.pick_id||'');
    const selectedName=String(row?.pick||row?.selection||'').trim();
    const projection=Number(row?.projection),opponentProjection=Number(row?.opponent_projection),gap=Number(row?.projection_gap),confidence=Number(row?.projection_confidence);
    const samples=row?.projection_samples&&typeof row.projection_samples==='object'?row.projection_samples:{};
    const p1Samples=Number(samples.player1),p2Samples=Number(samples.player2),p1Surface=Number(samples.player1_surface),p2Surface=Number(samples.player2_surface);
    const market=aceMarketName(row),projectionType=aceProjectionTypeLabel(row),line=apiMarketLine(row),side=aceLineSide(row);
    const selectedIsP1=selectedId&&String(p1?.id||'')===selectedId || (!selectedId&&selectedName&&selectedName.toLowerCase()===p1Name.toLowerCase());
    const selectedIsP2=selectedId&&String(p2?.id||'')===selectedId || (!selectedId&&selectedName&&selectedName.toLowerCase()===p2Name.toLowerCase());
    const opponentName=selectedIsP1?p2Name:selectedIsP2?p1Name:'';
    const useful=Number.isFinite(projection)&&projection>0 && Number.isFinite(confidence)&&confidence>0;
    return {useful,p1Name,p2Name,selectedName:projectionPickText(row,String(row?.market||'').toLowerCase())||selectedName||'—',opponentName,projection,opponentProjection,gap,confidence,p1Samples,p2Samples,p1Surface,p2Surface,market,line,side};
  }
  function aceProjectionDetailAvailable(row){return aceProjectionDetailData(row).useful;}
  function aceProjectionDetailHtml(row){
    const d=aceProjectionDetailData(row),match=normalize(row);
    if(!d.useful)return '';
    const metric=(label,value,wide=false)=>value===null||value===undefined||value===''?'' : `<div class="ace-detail-metric${wide?' wide':''}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(String(value))}</strong></div>`;
    const metrics=[];
    metrics.push(metric(d.market,lcopy('Projection','Projekcia','Projekce')+' '+d.projection.toFixed(2),true));
    if(Number.isFinite(d.opponentProjection)&&d.opponentProjection>0)metrics.push(metric(lcopy('Opponent projection','Projekcia súpera','Projekce soupeře'),d.opponentProjection.toFixed(2)));
    if(Number.isFinite(d.gap)&&d.gap>0)metrics.push(metric(lcopy('Projection gap','Rozdiel projekcie','Rozdíl projekce'),'+'+d.gap.toFixed(2)));
    if(Number.isFinite(d.confidence)&&d.confidence>0)metrics.push(metric(lcopy('Model confidence','Istota modelu','Jistota modelu'),pct(d.confidence)));
    if(Number.isFinite(d.line)&&d.line>0)metrics.push(metric(lcopy('Market line','Hranica trhu','Hranice trhu'),`${d.side?d.side+' ':''}${d.line.toFixed(1)}`));
    if(Number.isFinite(d.p1Samples)&&d.p1Samples>0)metrics.push(metric(d.p1Name+' · '+lcopy('sample','vzorka','vzorek'),Math.trunc(d.p1Samples)));
    if(Number.isFinite(d.p2Samples)&&d.p2Samples>0)metrics.push(metric(d.p2Name+' · '+lcopy('sample','vzorka','vzorek'),Math.trunc(d.p2Samples)));
    const surfaceParts=[];
    if(Number.isFinite(d.p1Surface)&&d.p1Surface>0)surfaceParts.push(`${d.p1Name} ${Math.trunc(d.p1Surface)}`);
    if(Number.isFinite(d.p2Surface)&&d.p2Surface>0)surfaceParts.push(`${d.p2Name} ${Math.trunc(d.p2Surface)}`);
    if(surfaceParts.length)metrics.push(metric(lcopy('Surface samples','Vzorka na povrchu','Vzorek na povrchu'),surfaceParts.join(' · '),true));
    return `<div class="match-detail-shell ace-detail-shell"><header class="match-detail-head"><div><div class="dialog-eyebrow">${escapeHtml(d.market.toUpperCase())} · ${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}</div><h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2></div></header><div class="ace-detail-pick"><div><small>${escapeHtml(d.market)}</small><strong>${escapeHtml(d.selectedName)}</strong></div><div class="ace-detail-main"><b>${escapeHtml(d.projection.toFixed(2))}</b><small>${escapeHtml(lcopy('projection','projekcia','projekce'))}</small></div></div><div class="ace-detail-grid">${metrics.filter(Boolean).join('')}</div><p class="ace-detail-note">${escapeHtml(lcopy('Only verified Aces / Double Faults projection data are shown here. Missing serve or return statistics are intentionally hidden.','Zobrazujeme iba overené projekčné dáta pre esá a dvojchyby. Chýbajúce štatistiky podania alebo returnu zámerne nezobrazujeme.','Zobrazujeme pouze ověřená projekční data pro esa a dvojchyby. Chybějící statistiky podání nebo returnu záměrně nezobrazujeme.'))}</p><div class="dialog-meta"><span>${escapeHtml(String(match.surface||'').replaceAll('_',' '))}</span><span>${fmtDate(match.date)} · ${fmtTime(match.date)}</span><span>${escapeHtml(String(row?.projection_source||'historical_event_statistics').replaceAll('_',' '))}</span></div></div>`;
  }
  function openAceProjection(row){
    if(!aceProjectionDetailAvailable(row))return;
    const dialog=$('matchDialog'),content=$('dialogContent');if(!dialog||!content)return;
    content.innerHTML=aceProjectionDetailHtml(row);
    dialog.classList.remove('sg-projection-dialog');dialog.classList.add('ace-projection-dialog');
    if(!dialog.open)dialog.showModal();
  }
  function sgProjectionDetailData(row,sourceTab=''){
    const match=normalize(row),samples=row?.projection_samples&&typeof row.projection_samples==='object'?row.projection_samples:{};
    const market=String(sourceTab||row?.market||'').toLowerCase()==='sets'?'sets':'games';
    const rawProjection=Number(row?.projection),projection=market==='sets'?setsTotalProjectionValue(row):rawProjection;
    const parsedLine=selectionLineFromText(row),baseline=market==='sets'&&Number.isFinite(parsedLine)?parsedLine:Number(row?.reference_projection??row?.baseline_projection);
    const storedGap=Number(row?.projection_gap),gap=market==='sets'&&Number.isFinite(projection)&&Number.isFinite(baseline)?Math.abs(projection-baseline):storedGap;
    const confidence=Number(row?.projection_confidence),depth=Number(row?.data_depth);
    return {match,market,projection,baseline,gap,confidence,depth,bestOf:Number(row?.best_of),samples,selection:projectionPickText(row,market),source:String(row?.projection_source||'historical_structured_scores')};
  }
  function sgProjectionDetailHtml(row,sourceTab=''){
    const d=sgProjectionDetailData(row,sourceTab),isSets=d.market==='sets';
    const projectionText=Number.isFinite(d.projection)?(isSets?`${d.projection.toFixed(2)} Sets`:`${d.projection.toFixed(1)} Games`):'—';
    const baselineText=Number.isFinite(d.baseline)?(isSets?`${d.baseline.toFixed(1)} Sets`:`${d.baseline.toFixed(1)} Games`):'—';
    const gapText=Number.isFinite(d.gap)?(isSets?`${d.gap.toFixed(2)} Sets`:`${d.gap.toFixed(1)} Games`):'—';
    const depthText=Number.isFinite(d.depth)?`${Math.round(Math.max(0,Math.min(1,d.depth))*100)}%`:'—';
    const p1=Number(d.samples.player1),p2=Number(d.samples.player2),s1=Number(d.samples.player1_surface),s2=Number(d.samples.player2_surface);
    const sample=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)?`${Math.trunc(a)} / ${Math.trunc(b)}`:'—';
    const why=isSets
      ?lcopy(`The model compares how often both players' historical matches extend beyond the reference set length and shrinks sparse evidence toward neutral.`,`Model porovnáva, ako často sa historické zápasy oboch hráčov predĺžia nad referenčnú dĺžku setov a pri malej vzorke výsledok konzervatívne približuje k neutrálu.`,`Model porovnává, jak často se historické zápasy obou hráčů prodlužují nad referenční délku setů a při malém vzorku výsledek konzervativně přibližuje k neutrálu.`)
      :lcopy(`The projection is built from structured historical total-games scores for both players, adjusted by sample depth and surface evidence.`,`Projekcia vychádza zo štruktúrovaných historických počtov gemov oboch hráčov a zohľadňuje hĺbku vzorky aj dáta na povrchu.`,`Projekce vychází ze strukturovaných historických počtů gemů obou hráčů a zohledňuje hloubku vzorku i data na povrchu.`);
    return `<div class="match-detail-shell sg-detail-shell" data-detail-market="${escapeHtml(d.market)}"><header class="match-detail-head"><div><div class="dialog-eyebrow">${isSets?'SETS':'GAMES'} · ${escapeHtml(d.match.tour)} · ${escapeHtml(d.match.tournament)}</div><h2>${escapeHtml(d.match.p1)} <span>vs</span> ${escapeHtml(d.match.p2)}</h2></div></header><div class="sg-detail-hero"><div><small>${escapeHtml(lcopy('Model projection','Modelová projekcia','Modelová projekce'))}</small><strong>${escapeHtml(d.selection)}</strong></div><div><b>${escapeHtml(projectionText)}</b><small>${escapeHtml(isSets?lcopy('projected total sets','projekcia setov','projekce setů'):lcopy('projected total games','projekcia gemov','projekce gemů'))}</small></div></div><div class="sg-detail-grid"><article><small>${escapeHtml(lcopy('Reference','Referencia','Reference'))}</small><strong>${escapeHtml(baselineText)}</strong></article><article><small>${escapeHtml(lcopy('Projection gap','Rozdiel projekcie','Rozdíl projekce'))}</small><strong>${escapeHtml(gapText)}</strong></article><article><small>${escapeHtml(lcopy('Model confidence','Istota modelu','Jistota modelu'))}</small><strong>${Number.isFinite(d.confidence)?escapeHtml(pct(d.confidence)):'—'}</strong></article><article class="data-depth"><small>DATA DEPTH</small><strong>${escapeHtml(depthText)}</strong></article><article><small>${escapeHtml(lcopy('History samples P1 / P2','Historická vzorka P1 / P2','Historický vzorek P1 / P2'))}</small><strong>${escapeHtml(sample(p1,p2))}</strong></article><article><small>${escapeHtml(lcopy('Surface samples P1 / P2','Vzorka na povrchu P1 / P2','Vzorek na povrchu P1 / P2'))}</small><strong>${escapeHtml(sample(s1,s2))}</strong></article></div><p class="ace-detail-note">${escapeHtml(lcopy('This is a model projection, not an odds-backed betting market. Market odds are shown only when a real provider market exists.','Ide o modelovú projekciu, nie o predikciu podloženú kurzovým marketom. Kurz zobrazujeme iba vtedy, keď existuje reálny market od providera.','Jde o modelovou projekci, ne o predikci podloženou kurzovým marketem. Kurz zobrazujeme pouze tehdy, když existuje reálný market od providera.'))}</p><div class="dialog-meta"><span>${escapeHtml(String(d.match.surface||'').replaceAll('_',' '))}</span><span>${fmtDate(d.match.date)} · ${fmtTime(d.match.date)}</span>${Number.isFinite(d.bestOf)?`<span>BO${Math.trunc(d.bestOf)}</span>`:''}<span>${escapeHtml(d.source.replaceAll('_',' '))}</span></div></div>`;
  }
  function openSgProjection(row,sourceTab=''){
    const dialog=$('matchDialog'),content=$('dialogContent');if(!dialog||!content)return;
    content.innerHTML=sgProjectionDetailHtml(row,sourceTab);
    dialog.classList.remove('ace-projection-dialog');dialog.classList.add('sg-projection-dialog');
    if(!dialog.open)dialog.showModal();
  }
  function projectionOddsHtml(row){
    // Only prices attached to this selection are eligible; never use model
    // confidence, projected totals, or the match-winner market as a price.
    const odds=[row?.odds,row?.betting?.odds].map(value=>firstFinite(value)).find(value=>Number.isFinite(value)&&value>1);
    if(Number.isFinite(odds))return hubNumberHtml(odds.toFixed(2),lcopy('odds','kurz','kurz'));
    const reason=lcopy('Market odds unavailable','Trhový kurz nie je dostupný','Tržní kurz není dostupný');
    return `<span title="${escapeHtml(reason)}">${hubNumberHtml('N/A',reason)}</span>`;
  }
  function dailyHubRow(row,tab,active=false,index=0){
    const sourceTab=tab==='see_all'?String(row?._hub_source||''):tab;
    const scheduled=row?.scheduled_at||row?.date;
    const tournament=dailyHubTournament(row),key=escapeHtml(eventKey(row));
    const startsAt=Date.parse(String(scheduled||''));
    const started=Number.isFinite(startsAt)&&startsAt<=Date.now();
    // Daily offers keep only the yellow STARTED marker. Settlement is visible
    // exclusively in Results, not on the homepage or SEE ALL.
    const classes=[active?'hub-row-active':'',started?'hub-row-started':''].filter(Boolean).join(' ');
    const rowClass=classes?` class="${classes}"`:'';
    const timeHtml=started
      ?`<span class="hub-time-stack"><strong>${escapeHtml(fmtTime(scheduled))}</strong><small>${escapeHtml(fmtCompactDate(scheduled))}</small><em class="hub-offer-status is-started">${escapeHtml(lcopy('STARTED','ZAČATÉ','ZAHÁJENO'))}</em></span>`
      :timeDateHtml(scheduled);
    const leading=`<td class="hub-rank">${index+1}</td><td class="hub-time">${timeHtml}</td><td class="hub-tournament-cell">${tournament}</td><td class="hub-match-cell">${dailyHubMatch(row)}</td>`;
    if(sourceTab==='games'||sourceTab==='sets'){
      const confidence=Number(row?.projection_confidence),rawProjection=Number(row?.projection),projection=sourceTab==='sets'?setsTotalProjectionValue(row):rawProjection,pick=projectionPickText(row,sourceTab);
      const projectionText=Number.isFinite(projection)?(sourceTab==='sets'?projection.toFixed(2):projection.toFixed(1)):'—';
      const projectionUnit=sourceTab==='sets'?lcopy('projected sets','projekcia setov','projekce setů'):lcopy('projected games','projekcia gemov','projekce gemů');
      const oddsHtml=projectionOddsHtml(row);
      if(tab==='see_all'){
        return `<tr${rowClass} data-hub-event="${key}" data-hub-market="${escapeHtml(sourceTab)}">${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick,lcopy('Model prediction','Modelová predikcia','Modelová predikce'))}</td><td class="hub-odds hub-number-cell">${oddsHtml}</td><td class="hub-seeall-model-cell">${hubSeeAllProjectionHtml(projectionText,projectionUnit,confidence,row)}</td><td class="hub-action-cell hub-optional-action"><span class="hub-projection-badge">MODEL</span></td></tr>`;
      }
      return `<tr${rowClass} data-hub-event="${key}" data-hub-market="${escapeHtml(sourceTab)}">${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick,lcopy('Model prediction','Modelová predikcia','Modelová predikce'))}</td><td class="hub-odds hub-number-cell">${oddsHtml}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(projectionText,projectionUnit)}</td><td class="hub-confidence-cell">${hubConfidenceHtml(confidence,row)}</td></tr>`;
    }
    if(sourceTab==='ace'||sourceTab==='double_faults'){
      const confidence=Number(row?.projection_confidence),projection=Number(row?.projection),pick=projectionPickText(row,sourceTab),market=aceMarketName(row);
      const action=aceProjectionDetailAvailable(row)?`<button class="hub-detail hub-projection-detail" type="button" data-ace-projection aria-label="${escapeHtml(lcopy('Aces projection','Projekcia Aces','Projekce Aces'))}">${escapeHtml(lcopy('Detail','Detail','Detail'))}</button>`:'';
      const odds=firstFinite(row?.odds,row?.betting?.odds),projectionText=Number.isFinite(projection)?projection.toFixed(2):'—',projectionUnit=lcopy('projection','projekcia','projekce');
      if(tab==='see_all'){
        return `<tr${rowClass} data-hub-event="${key}" data-hub-market="${escapeHtml(sourceTab)}">${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick,market||(sourceTab==='double_faults'?'DVOJCHYBY':'ACES'))}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(Number.isFinite(odds)&&odds>1?odds.toFixed(2):'—',lcopy('odds','kurz','kurz'))}</td><td class="hub-seeall-model-cell">${hubSeeAllProjectionHtml(projectionText,projectionUnit,confidence,row)}</td><td class="hub-action-cell hub-optional-action">${action}</td></tr>`;
      }
      return `<tr${rowClass} data-hub-event="${key}" data-hub-market="${escapeHtml(sourceTab)}">${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick,market||(sourceTab==='double_faults'?'DVOJCHYBY':'ACES'))}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(Number.isFinite(odds)&&odds>1?odds.toFixed(2):'—',lcopy('odds','kurz','kurz'))}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(projectionText,projectionUnit)}</td><td class="hub-confidence-cell">${hubConfidenceHtml(confidence,row)}</td></tr>`;
    }
    const probability=marketProbability(row),odds=Number(row?.odds??row?.betting?.odds),pick=modelPickName(row);
    const base=`${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick)}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(Number.isFinite(odds)?odds.toFixed(2):'—',lcopy('odds','kurz','kurz'))}</td><td class="hub-confidence-cell">${hubConfidenceHtml(probability,row)}</td>`;
    if(tab==='value'){
      return `<tr${rowClass} data-hub-event="${key}">${base}<td class="hub-action-cell">${hubMatchDetailButtonHtml()}</td></tr>`;
    }
    return `<tr${rowClass} data-hub-event="${key}">${base}<td class="hub-action-cell">${hubMatchDetailButtonHtml()}</td></tr>`;
  }

  function dailyHubLockedRow(tab,index,requiredPlan='pro'){
    const colspan=Math.max(1,dailyHubColumns(tab).length),required=String(upgradePlanLabel(requiredPlan)||requiredPlan).replace(/^BlinQ\s+/i,'').toUpperCase();
    if(tab==='see_all')return `<tr class="hub-row-locked hub-row-seeall access-locked" data-upgrade-plan="${escapeHtml(requiredPlan)}" data-upgrade-section="SEE ALL"><td colspan="${colspan}"><span>◆</span><div><em>${escapeHtml(uiCopyTemplate('access.requires',`Vyžaduje ${required}`,{plan:required}))}</em><b>SEE ALL</b><small>Rozšírený kvalifikovaný výber podľa nastavenej úrovne prístupu.</small></div></td></tr>`;
    return `<tr class="hub-row-locked access-locked" data-upgrade-plan="${escapeHtml(requiredPlan)}" data-upgrade-section="${escapeHtml(dailyHubTabLabel(tab))}"><td colspan="${colspan}"><span>🔒</span><div><em>${escapeHtml(uiCopyTemplate('access.requires',`Vyžaduje ${required}`,{plan:required}))}</em><b>${escapeHtml(uiCopy('access.locked_row',lcopy('Next pick is locked','Ďalší pick je zamknutý','Další tip je zamčený')))}</b><small>${escapeHtml(uiCopy('access.locked_row_body',lcopy('A higher tier unlocks more rows and prediction detail.','Vyššia úroveň odomkne ďalšie riadky a detail predikcie.','Vyšší úroveň odemkne další řádky a detail predikce.')))}</small></div></td></tr>`;
  }
  function renderDailyHub(){
    const host=$('dailyHub'); if(!host)return; wireDailyHub();
    const cfg=dailyHubConfig(); host.hidden=cfg.enabled===false; if(host.hidden)return;
    const tabs=['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'];
    if(!tabs.includes(state.dailyHubTab))state.dailyHubTab='daily';
    const plan=accountPlan();
    const visibleTabs=tabs.filter(tab=>dailyHubEntitlement(tab).enabled!==false);
    if(!visibleTabs.includes(state.dailyHubTab))state.dailyHubTab=visibleTabs[0]||'daily';
    $('dailyHubTabs').innerHTML=visibleTabs.map(tab=>{
      const ent=dailyHubEntitlement(tab),coming=dailyHubIsComingSoon(tab);
      let count='';
      if(coming)count='<em>COMING SOON</em>';
      else {const total=Number(ent.total);const rows=dailyHubRows(tab);const n=Number.isFinite(total)?total:rows.length;count=n?`<b>${n}</b>`:'';}
      const entitledButUnavailable=!state.previewPlan&&membershipHierarchy.includes(plan)&&ent.enabled!==false&&String(ent.display_state||'active').toLowerCase()==='active'&&(String(ent.visible_picks||'').toUpperCase()==='ALL'||Number(ent.visible_picks)>0)&&Number(ent.total||0)>0&&Number(ent.returned||0)===0;
      const locked=!entitledButUnavailable&&!coming&&ent.enabled!==false&&Number(ent.returned||0)===0&&(Number(ent.locked_count||0)>0||String(ent.display_state||'').toLowerCase()==='blurred'||(Array.isArray(ent.slot_states)&&ent.slot_states.some(value=>value==='blurred')));
      const requiredPlan=locked?firstDailyHubUnlockPlan(tab,0,tab==='see_all'):'';
      const requiredLabel=requiredPlan?String(upgradePlanLabel(requiredPlan)||requiredPlan).replace(/^BlinQ\s+/i,'').toUpperCase():'';
      const accessAttrs=locked?` data-upgrade-plan="${escapeHtml(requiredPlan)}" data-upgrade-section="${escapeHtml(dailyHubTabLabel(tab))}" title="${escapeHtml(lcopy(`Available from ${requiredLabel}`,`Dostupné od ${requiredLabel}`,`Dostupné od ${requiredLabel}`))}"`:'';
      return `<button type="button" role="tab" aria-selected="${tab===state.dailyHubTab?'true':'false'}" class="daily-hub-tab${tab===state.dailyHubTab?' active':''}${coming?' is-coming':''}${locked?' is-locked':''}" data-daily-hub-tab="${tab}"${accessAttrs}><span class="daily-hub-tab-copy"><span>${escapeHtml(dailyHubTabLabel(tab))}</span></span>${locked?'<i class="hub-tab-lock" aria-hidden="true"><svg viewBox="0 0 20 20"><rect x="4" y="8" width="12" height="9" rx="2"/><path d="M6.5 8V5a3.5 3.5 0 0 1 7 0v3"/></svg></i>':''}${count}</button>`;
    }).join('');
    const tab=state.dailyHubTab; host.dataset.tab=tab; host.dataset.plan=plan;
    const empty=$('dailyHubEmpty'),head=$('dailyHubHead'),body=$('dailyHubBody'),expand=$('dailyHubExpand');
    const tournamentSelect=$('dailyHubTournamentFilter');
    if(dailyHubIsComingSoon(tab)){
      head.innerHTML=''; body.innerHTML='';
      if(empty){empty.hidden=false;empty.innerHTML=`<div class="coming-soon-board"><span>${escapeHtml(dailyHubTabLabel(tab))}</span><strong>COMING SOON</strong><p>Modul je pripravený v rozhraní. Dáta zapojíme po validácii modelu.</p></div>`;}
      if(expand)expand.hidden=true;if(tournamentSelect)tournamentSelect.parentElement.hidden=true;
      return;
    }
    if(tournamentSelect)tournamentSelect.parentElement.hidden=false;
    const sourceRows=dailyHubRows(tab),rows=dashboardFilteredRows(sourceRows),ent=dailyHubEntitlement(tab);
    const includedButUnavailable=!state.previewPlan&&membershipHierarchy.includes(plan)&&ent.enabled!==false&&String(ent.display_state||'active').toLowerCase()==='active'&&(String(ent.visible_picks||'').toUpperCase()==='ALL'||Number(ent.visible_picks)>0)&&Number(ent.total||0)>0&&(Number(ent.returned||0)===0||sourceRows.length===0);
    const preview=Math.max(1,Number(cfg.preview_rows)||10);
    const allCount=tab==='see_all'?Math.max(Number(ent.total)||0,rows.length):Math.max(Number(ent.total)||0,rows.length);
    const canExpand=ent.see_all===true&&allCount>preview;
    let limit=(state.dailyHubExpanded&&canExpand)?allCount:preview;
    // Stable-random FREE rows stay at their ORIGINAL server slot (e.g. #8).
    // Only one authorized row is returned, but its slot may be anywhere in
    // the first ten. Never truncate the rendering window to rows.length=1.
    const slotCount=Array.isArray(ent.slot_states)?ent.slot_states.length:0;
    limit=Math.min(limit,Math.max(rows.length,Number(ent.returned)||0,slotCount));
    const columnKeys=dailyHubColumnKeys(tab);
    head.innerHTML=`<tr>${dailyHubColumns(tab).map((c,i)=>`<th class="hub-head-${escapeHtml(columnKeys[i]||'generic')}">${escapeHtml(c)}</th>`).join('')}</tr>`;
    const out=[];
    {
      const slotStates=Array.isArray(ent.slot_states)?ent.slot_states:[];let dataIndex=0;
      if(slotStates.length&&!includedButUnavailable){
        // Server-authorized rows carry their original source slot. Search,
        // surface and tournament filters must never compact slot 7 into slot 2.
        const bySlot=new Map(),unmapped=[];
        rows.forEach(row=>{
          const raw=Number(row?._access_slot);
          if(Number.isInteger(raw)&&raw>=0&&!bySlot.has(raw))bySlot.set(raw,row);
          else unmapped.push(row);
        });
        slotStates.slice(0,limit).forEach((slotState,slotIndex)=>{
          if(slotState==='hidden')return;
          if(slotState==='blurred')out.push(dailyHubLockedRow(tab,slotIndex,firstDailyHubUnlockPlan(tab,slotIndex,false)));
          else {
            const row=bySlot.get(slotIndex)??unmapped[dataIndex++];
            if(row)out.push(dailyHubRow(row,tab,false,slotIndex));
          }
        });
      }else if(!includedButUnavailable)for(let i=0;i<limit;i++){if(i<rows.length)out.push(dailyHubRow(rows[i],tab,false,i));}
      const nextIndex=Math.max(slotStates.length,rows.length);
      if(!out.length&&ent.blur_remaining!==false&&!includedButUnavailable)out.push(dailyHubLockedRow(tab,0,firstDailyHubUnlockPlan(tab,0,false)));
      else if(out.length&&(Number(ent.total)||0)>nextIndex&&ent.blur_remaining!==false)out.push(dailyHubLockedRow(tab,nextIndex,firstDailyHubUnlockPlan(tab,nextIndex,false)));
    }
    body.innerHTML=out.join('');
    // r28: semantic cell labels let the same server-rendered table become a
    // compact card layout on phones without duplicating business logic.
    const mobileLabels=dailyHubColumns(tab);
    body.querySelectorAll('tr:not(.hub-row-locked)').forEach(row=>{
      [...row.children].forEach((cell,i)=>{cell.dataset.label=mobileLabels[i]||'';});
    });
    if(empty){empty.hidden=Boolean(out.length);empty.textContent=includedButUnavailable?lcopy('Your included pick is temporarily unavailable in the current offer.','Tvoj zahrnutý tip momentálne nie je dostupný v aktuálnej ponuke.','Tvůj zahrnutý tip momentálně není dostupný v aktuální nabídce.'):lcopy('No predictions are available in this category yet.','V tejto kategórii zatiaľ nie sú dostupné predikcie.','V této kategorii zatím nejsou dostupné predikce.');}
    const first=rows[0]||sourceRows[0];const raw=first?.scheduled_at||first?.date||first?.start_time||first?.start_at||'';const d=raw?new Date(raw):new Date();const dateText=Number.isNaN(d.getTime())?lcopy('Today','Dnes','Dnes'):new Intl.DateTimeFormat(locale==='en'?'en-GB':locale==='cz'?'cs-CZ':'sk-SK',{weekday:'short',day:'numeric',month:'numeric'}).format(d);
    if($('dailyHubMetaDate'))$('dailyHubMetaDate').textContent=dateText;if($('dailyHubToolbarDate'))$('dailyHubToolbarDate').textContent=dateText;
    if(tournamentSelect){
      const options=[...new Set(sourceRows.map(row=>String(row?.tournament||row?.competition||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));const current=String(state.dailyHubTournament||'');
      tournamentSelect.innerHTML=`<option value="">${escapeHtml(lcopy('All tournaments','Všetky turnaje','Všechny turnaje'))}</option>`+options.map(name=>`<option value="${escapeHtml(name)}"${name===current?' selected':''}>${escapeHtml(name)}</option>`).join('');if(current&&!options.includes(current)){state.dailyHubTournament='';tournamentSelect.value='';}
    }
    if(expand){const hasMore=allCount>preview;expand.hidden=!hasMore;expand.dataset.locked=ent.see_all===true?'0':'1';expand.setAttribute('aria-expanded',state.dailyHubExpanded?'true':'false');expand.title=state.dailyHubExpanded?lcopy('Show first 10','Zobraziť prvých 10','Zobrazit prvních 10'):lcopy('Show all rows','Zobraziť všetky riadky','Zobrazit všechny řádky');}
  }


  function marketPreviewCard(row,key,index=0,locked=false,compact=false){
    if(locked)return lockedPickCard(key,index);
    const p1=row?.player1||{},p2=row?.player2||{};const probability=marketProbability(row);let pick=row?.pick||row?.selection||row?.prediction||'—';const odds=Number(row?.odds);
    const projection=Number(row?.projection),opponentProjection=Number(row?.opponent_projection),projectionGap=Number(row?.projection_gap),projectionConfidence=Number(row?.projection_confidence);const samples=row?.projection_samples||{};const projectionOnly=row?.price_status==='projection_only'&&Number.isFinite(projection);
    let badge='',mainValue='—',confidenceClass='low',pickLabel=publicText(key==='prime'?'Short Odds Prediction':key==='value'?'Value Prediction':key==='ace'?'Ace / DF Prediction':key==='sg'?'Set / Game Prediction':'TOP Prediction'),note='',metrics=[];
    if(projectionOnly){
      const projectionMarket=String(row?.market||row?.projection_metric||'').toLowerCase();
      const projectionTab=projectionMarket==='aces'?'ace':projectionMarket;
      if(['ace','double_faults','games','sets'].includes(projectionTab))pick=projectionPickText(row,projectionTab);
      const marketLabel=row?.market_type||String(row?.market||'Projection').replaceAll('_',' ');const sampleText=Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${publicText('Data')} ${samples.player1}/${samples.player2}`:'';const unit=String(row?.projection_unit||'count');const reference=Number(row?.reference_projection??row?.baseline_projection);
      if(key==='sg'&&projectionTab==='sets'){
        const totalSets=setsTotalProjectionValue(row),line=selectionLineFromText(row),setGap=Number.isFinite(totalSets)&&Number.isFinite(line)?Math.abs(totalSets-line):NaN;
        mainValue=Number.isFinite(totalSets)?`${totalSets.toFixed(2)}<small> Sets</small>`:'—';
        metrics=[[lcopy('Line','Hranica','Hranice'),Number.isFinite(line)?`${line.toFixed(1)} Sets`:'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(setGap)?`${setGap.toFixed(2)} Sets`:'—'],[lcopy('Confidence','Istota','Jistota'),Number.isFinite(projectionConfidence)?pct(projectionConfidence):'—']];pickLabel=lcopy('Sets projection','Projekcia setov','Projekce setů');
      }
      else if(key==='sg'&&unit==='games'){mainValue=`${projection.toFixed(1)}<small> Games</small>`;metrics=[[lcopy('Baseline','Základ','Základ'),Number.isFinite(reference)?reference.toFixed(1):'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${projectionGap.toFixed(1)}`:'—'],[lcopy('Confidence','Istota','Jistota'),Number.isFinite(projectionConfidence)?pct(projectionConfidence):'—']];pickLabel=lcopy('Games projection','Projekcia hier','Projekce her');}
      else{
        const line=apiMarketLine(row),side=aceLineSide(row),marketName=aceMarketName(row);
        const unit=marketName;
        mainValue=`${projection.toFixed(1)}<small>${escapeHtml(unit)}</small>`;
        metrics=[[lcopy('Line','Hranica','Hranice'),Number.isFinite(line)?`${side?side+' ':''}${line.toFixed(1)}`:'—'],[lcopy('Opponent','Súper','Soupeř'),Number.isFinite(opponentProjection)?opponentProjection.toFixed(1):'—'],[lcopy('Difference','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${projectionGap>=0?'+':''}${projectionGap.toFixed(1)}`:'—'],[lcopy('Data','Dáta','Data'),Number.isFinite(projectionConfidence)?`${Math.round(projectionConfidence*100)}/100`:'—']];
        pickLabel=lcopy('Prediction','Predikcia','Predikce');
      }
      badge=lcopy('PREDICTION','PREDIKCIA','PREDIKCE');confidenceClass=Number.isFinite(projectionConfidence)?confidenceBand(projectionConfidence):'medium';note=[marketLabel,sampleText].filter(Boolean).join(' · ');
    }else{
      const selectionId=String(row?.betting?.selection_id||row?.selection_id||'');
      if(key==='prime'||key==='top_daily'){metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),dataDepthMetric(row)],[publicText('Surface'),surfaceSampleLabel(row)],[lcopy('Form','Forma','Forma'),publicFormLabel(row,selectionId)]];}
      else if(key==='value'){metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),dataDepthMetric(row)],[lcopy('Market','Trh','Trh'),closeMarketLabel(row)],[publicText('Surface'),surfaceSampleLabel(row)]];}
      else{metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),dataDepthMetric(row)],[publicText('Surface'),surfaceSampleLabel(row)]];}
      badge=probability==null?publicText('MODEL'):confidenceLabel(confidenceBand(probability));mainValue=probability==null?'—':pct(probability);confidenceClass=probability==null?'low':confidenceBand(probability);
    }
    const p1Photo=playerPhotoSource(row,p1,'player1'),p2Photo=playerPhotoSource(row,p2,'player2');const avatar=(photo,name,gender='')=>playerAvatarHtml(photo,name,row?.tour,gender,'player-avatar');const p1Name=p1.name||row?.player1_name||'Player 1',p2Name=p2.name||row?.player2_name||'Player 2';
    const metricHtml=metrics.map(([label,value])=>{const raw=String(value??'');const tone=raw.trim().startsWith('+')?' metric-positive':raw.trim().startsWith('-')?' metric-negative':'';return `<span class="card-metric${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(raw)}</strong></span>`}).join('');
    const footer=`<div class="card-metrics-bar match-kpi-bar">${metricHtml}</div><div class="card-link-row"><button class="card-more-link" type="button" data-route="${escapeHtml(key)}">${escapeHtml(publicText('See more →'))}</button></div>`;
    const optionalNote=note&&!compact?`<div class="market-card-note">${escapeHtml(note)}</div>`:'';
    const tournamentMeta=tournamentDisplayMeta(row);
    return `<article class="prediction-card featured market-card match-card-v3${projectionOnly?' projection-card':''}${compact?' dashboard-preview-card':''}"><div class="card-meta match-card-meta"><span class="tour match-card-tournament">${tournamentVisual(row)}<span class="match-card-tournament-copy"><b>${escapeHtml(tournamentMeta.name)}</b>${tournamentMeta.location?`<small>${escapeHtml(tournamentMeta.location)}</small>`:''}</span></span><span class="time">${timeDateHtml(row?.scheduled_at||row?.date,'card-time-stack')}</span><span class="surface">${escapeHtml(String(row?.surface||key).replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row match-players-row"><div class="player">${avatar(p1Photo,p1Name,p1?.gender||p1?.sex||'')}<strong class="player-name">${escapeHtml(p1Name)}</strong><small class="player-rank">${playerMetaHtml(p1.rank,p1.country_code,row?.tour)}</small></div><div class="vs match-vs">VS</div><div class="player">${avatar(p2Photo,p2Name,p2?.gender||p2?.sex||'')}<strong class="player-name">${escapeHtml(p2Name)}</strong><small class="player-rank">${playerMetaHtml(p2.rank,p2.country_code,row?.tour)}</small></div></div><div class="pick-row match-pick-row"><div class="pick-copy"><small>${escapeHtml(pickLabel)}</small><strong class="pick-name">${escapeHtml(pick)}</strong></div><div class="pick-score"><div class="probability">${mainValue}</div><span class="confidence ${confidenceClass}">${escapeHtml(badge)}</span></div></div>${optionalNote}${footer}</article>`;
  }

  function renderMarketSection(key,hostId,emptyText){
    const host=$(hostId);if(!host)return;
    const sourceRows=marketRows(key),rows=key==='ace'?sourceRows.filter(aceHasApiLine):sourceRows,ent=dashboardPlanEntitlement(key);
    const serverTotal=Number(ent?.total);
    const total=key==='ace'?rows.length:(Number.isFinite(serverTotal)?Math.max(rows.length,serverTotal):rows.length);
    const previewMax=dashboardPreviewLimit(key,total||1),previewCount=Math.min(total,previewMax);
    const perPage=dashboardCardsPerPanel(),pageCount=Math.max(1,Math.ceil(previewCount/perPage));
    state.marketPage[key]=Math.min(Number(state.marketPage[key]||0),pageCount-1);
    const start=state.marketPage[key]*perPage,end=Math.min(previewCount,start+perPage),unlocked=rows.length;
    const cards=[];
    for(let absoluteIndex=start;absoluteIndex<end;absoluteIndex++){
      if(absoluteIndex<rows.length)cards.push(marketPreviewCard(rows[absoluteIndex],key,absoluteIndex,false,true));
      else cards.push(lockedPickCard(key,absoluteIndex));
    }
    host.innerHTML=cards.length?cards.join(''):`<div class="state-card market-empty">${escapeHtml(emptyText)}</div>`;
    host.style.setProperty('--visible-cards',String(Math.max(1,cards.length)));
    window.BlinqUI.pager(host,state.marketPage[key],pageCount);
    const count=$(key==='top_daily'?'topDailyCount':`${key}Count`);if(count)count.textContent=locale==='en'?`${rows.length} ${rows.length===1?'prediction':'predictions'}`:`${rows.length} ${locale==='cz'?'predikcí':'predikcií'}`;
    const seeCount=$(key==='top_daily'?'topDailySeeAllCardCount':`${key}SeeAllCardCount`);if(seeCount)seeCount.textContent=publicText(`${rows.length} published`);
    const shell=host.closest('.market-carousel-shell');if(shell){const prev=shell.querySelector('[data-market-prev]'),next=shell.querySelector('[data-market-next]');if(prev){prev.hidden=pageCount<=1;prev.disabled=state.marketPage[key]<=0;}if(next){next.hidden=pageCount<=1;next.disabled=state.marketPage[key]>=pageCount-1;}}
  }
  function renderMarketSections(){renderMarketSection('top_daily','topDailyGrid',publicText('No TOP predictions available yet. New qualifying predictions appear automatically.'));renderMarketSection('value','valueGrid',publicText('No Value predictions available yet. We are waiting for qualifying opportunities.'));renderMarketSection('doubles','doublesGrid',publicText('No Doubles predictions have been published yet.'));renderMarketSection('ace','aceGrid',lcopy('No Aces / Double Faults predictions with an API market line are available yet.','Zatiaľ nie sú dostupné predikcie pre esá / dvojchyby s hranicou z API.','Zatím nejsou dostupné predikce pro esa / dvojchyby s hranicí z API.'));renderMarketSection('sg','sgGrid',publicText('No Sets / Games predictions available yet. New projections appear automatically.'));translatePublicDom(document.body);}

  function signalMeta(signal,m){ const id=String(signal?.player_id ?? signal?.favours_player_id ?? ''); const favours=id===String(m.pickId); const label=translateSignalLabel(signal?.label||signal?.factor||'Model signal'); return {label,favours}; }
  function renderSignal(signal,m){ const s=signalMeta(signal,m); return `<div class="signal-row"><span>${escapeHtml(s.label)}</span><div class="signal-meter"><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i></i><i></i></div></div>`; }
  function setPlayerIdentity(box,name,rank,country,photo,tour){
    const avatar=box.querySelector('.player-avatar');
    applyPlayerAvatarHost(avatar,photo,name,tour);
    box.querySelector('.player-name').textContent=name;box.querySelector('.player-rank').innerHTML=playerMetaHtml(rank,country,tour);
  }
  function dataDepthLabel(m){const q=m.quality||{},a=q.player1||{},b=q.player2||{};const values=[a.matches,b.matches,a.surface_matches,b.surface_matches].map(Number);if(values.every(Number.isFinite))return `${publicText('History')} ${values[0]} / ${values[1]} · ${publicText('Surface')} ${values[2]} / ${values[3]}`;if(Number.isFinite(m.dataDepth))return `${publicText('Data depth')} ${Math.round(m.dataDepth*100)}%`;return '';}
  function renderCard(m, slotIndex=0){
    const template=$('predictionTemplate').content.cloneNode(true),card=template.querySelector('.prediction-card');
    card.dataset.id=m.id;card.dataset.uiElement=slotIndex<8?`TOP_PICK_${slotIndex+1}`:'TOP_PICK_MORE';card.classList.add('featured','dashboard-preview-card');
    card.querySelector('.tour').textContent=`${m.tour} ${m.tournament}${m.round?` · ${m.round}`:''}`;card.querySelector('.time').innerHTML=timeDateHtml(m.date,'card-time-stack');card.querySelector('.surface').textContent=String(m.surface).replaceAll('_',' ').toUpperCase();
    setPlayerIdentity(card.querySelector('.player-a'),m.p1,m.p1Rank,m.p1Country,m.p1Photo,m.tour);setPlayerIdentity(card.querySelector('.player-b'),m.p2,m.p2Rank,m.p2Country,m.p2Photo,m.tour);
    const depth=card.querySelector('.data-depth-row');if(depth){const label=dataDepthLabel(m);depth.textContent=label;depth.hidden=!label;}
    card.querySelector('.pick-name').textContent=m.pick;card.querySelector('.probability').textContent=pct(m.probability);
    const conf=card.querySelector('.confidence');conf.textContent=confidenceLabel(m.confidence);conf.classList.add(m.confidence);
    const bettingRow=card.querySelector('.betting-row');if(bettingRow){bettingRow.hidden=false;const oddsNode=card.querySelector('.betting-odds'),dataNode=card.querySelector('.betting-data'),surfaceNode=card.querySelector('.betting-surface'),formNode=card.querySelector('.betting-form');if(oddsNode)oddsNode.innerHTML=`<small>${escapeHtml(publicText('Odds'))}</small><strong>${Number.isFinite(m.odds)&&m.odds>1?m.odds.toFixed(2):'—'}</strong>`;if(dataNode)dataNode.innerHTML=`<small>${escapeHtml(lcopy('Data','Dáta','Data'))}</small><strong>${escapeHtml(dataDepthMetric(m.raw||m))}</strong>`;if(surfaceNode)surfaceNode.innerHTML=`<small>${escapeHtml(publicText('Surface'))}</small><strong>${escapeHtml(surfaceSampleLabel(m.raw||m))}</strong>`;if(formNode)formNode.innerHTML=`<small>${escapeHtml(lcopy('Form','Forma','Forma'))}</small><strong>${escapeHtml(publicFormLabel(m.raw||m,m.pickId))}</strong>`;}
    // Dashboard is intentionally a lightweight preview. Full section pages contain 3–5 picks.
    const signals=card.querySelector('.signals');if(signals){signals.hidden=true;signals.innerHTML='';}
    const analysis=card.querySelector('.analysis-link');if(analysis){analysis.hidden=false;analysis.dataset.route='prime';analysis.textContent=publicText('See more →');analysis.onclick=null;}
    return template;
  }


  function renderDots(pageCount){ const host=$('carouselDots'); if(!host)return; host.innerHTML=''; if(pageCount<=1)return; for(let i=0;i<pageCount;i++){const b=document.createElement('button');b.type='button';b.className=i===state.page?'active':'';b.setAttribute('aria-label',`Show Short Odds page ${i+1}`);b.onclick=()=>{state.page=i;renderPredictions()};host.appendChild(b)} }
  function renderPredictions(){
    const allRows=rankedPredictions(),ent=dashboardPlanEntitlement('prime'),serverTotal=Number(ent?.total),total=Number.isFinite(serverTotal)?Math.max(allRows.length,serverTotal):allRows.length,limit=dashboardPreviewLimit('prime',total||1),previewCount=Math.min(total,limit),grid=$('predictionGrid'),size=dashboardCardsPerPanel();if(!grid)return;
    $('matchCount').textContent=total;const primeSeeCount=$('primeSeeAllCardCount');if(primeSeeCount)primeSeeCount.textContent=publicText(`${total} published`);
    const pageCount=Math.max(1,Math.ceil(previewCount/size));state.page=Math.min(state.page,pageCount-1);const start=state.page*size,end=Math.min(previewCount,start+size);
    grid.classList.remove('show-all');grid.innerHTML='';
    if(!previewCount)grid.innerHTML='<div class="state-card">No Short Odds predictions available yet. This board updates automatically when new predictions qualify.</div>';
    else for(let absoluteIndex=start;absoluteIndex<end;absoluteIndex++){const m=allRows[absoluteIndex];if(m)grid.appendChild(renderCard(m,Number.isInteger(m.accessIndex)?m.accessIndex:absoluteIndex));else grid.insertAdjacentHTML('beforeend',lockedPickCard('prime',absoluteIndex));}
    grid.style.setProperty('--visible-cards',String(Math.max(1,end-start)));window.BlinqUI.pager(grid,state.page,pageCount);
    $('prevPick').hidden=pageCount<=1;$('nextPick').hidden=pageCount<=1;$('prevPick').disabled=state.page<=0;$('nextPick').disabled=state.page>=pageCount-1;renderDots(pageCount);renderDashboardComposition();applyAccessStates(grid);translatePublicDom(grid);
  }

  function winnerWhyBlinqHtml(){ return ''; }

  function renderMatchStatsPanel(row){
    const match=normalize(row),s1=playerInsightStats(row,1),s2=playerInsightStats(row,2);
    const h2h1=s1.h2hWins!=null&&s1.h2hLosses!=null?`${s1.h2hWins}–${s1.h2hLosses}`:'—';
    const h2h2=s2.h2hWins!=null&&s2.h2hLosses!=null?`${s2.h2hWins}–${s2.h2hLosses}`:'—';
    const rows=[
      [lcopy('BlinQ probability','BlinQ pravdepodobnosť','BlinQ pravděpodobnost'),s1.probabilityDisplay,s2.probabilityDisplay],
      [lcopy('Ranking','Rebríček','Žebříček'),s1.rankDisplay,s2.rankDisplay],
      [lcopy('Recent form','Aktuálna forma','Aktuální forma'),s1.overallFormDisplay,s2.overallFormDisplay],
      [surfaceShortName(row?.surface||match.surface)+' '+lcopy('form','forma','forma'),s1.surfaceFormDisplay,s2.surfaceFormDisplay],
      [lcopy('Surface matches','Zápasy na povrchu','Zápasy na povrchu'),s1.surfaceDisplay,s2.surfaceDisplay],
      [lcopy('History sample','Historická vzorka','Historický vzorek'),s1.historyDisplay,s2.historyDisplay],
      ['H2H',h2h1,h2h2],
      [lcopy('1st serve points','Body po 1. podaní','Body po 1. podání'),s1.serveDisplay,s2.serveDisplay],
      [lcopy('Return points','Body na returne','Body na returnu'),s1.returnDisplay,s2.returnDisplay]
    ];
    const missingDisplay=value=>{const text=String(value??'').trim();if(!text||text==='—')return true;const numeric=Number(text.replace('%','').replace(',','.'));return Number.isFinite(numeric)&&numeric===0;};
    const visibleRows=rows.filter(([,a,b])=>!(missingDisplay(a)&&missingDisplay(b)));
    return `<div class="match-stat-table winner-stat-table"><div class="match-stat-head"><span>${escapeHtml(lcopy('Winner factor','Faktor víťaza','Faktor vítěze'))}</span><strong>${escapeHtml(match.p1)}</strong><b>${escapeHtml(match.p2)}</b></div>${visibleRows.map(([label,a,b])=>`<div class="match-stat-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(a))}</strong><b>${escapeHtml(String(b))}</b></div>`).join('')}</div>`;
  }
  function renderMatchHistoryPanel(row){
    const match=normalize(row),s1=playerInsightStats(row,1),s2=playerInsightStats(row,2);
    const cards=(side,name,stats)=>`<article class="match-history-card"><div class="match-history-title"><span>${side}</span><strong>${escapeHtml(name)}</strong></div><div class="match-history-grid"><span><small>${escapeHtml(lcopy('Ranking','Rebríček','Žebříček'))}</small><b>${escapeHtml(stats.rankDisplay)}</b></span><span><small>${escapeHtml(lcopy('Surface matches','Zápasy na povrchu','Zápasy na povrchu'))}</small><b>${escapeHtml(stats.surfaceDisplay)}</b></span><span><small>${escapeHtml(lcopy('History sample','História','Historie'))}</small><b>${escapeHtml(stats.historyDisplay)}</b></span><span><small>BlinQ %</small><b>${escapeHtml(stats.probabilityDisplay)}</b></span></div></article>`;
    return `<div class="match-history-wrap">${cards('P1',match.p1,s1)}${cards('P2',match.p2,s2)}</div>`;
  }
  function mergeLiveMatchIntelligence(row,payload){
    if(!row||!payload||typeof payload!=='object')return row;
    [1,2].forEach(side=>{
      const source=payload['player'+side];
      if(!source||typeof source!=='object')return;
      const player=row['player'+side]||(row['player'+side]={});
      if(source.rank!=null&&Number(source.rank)>0)player.rank=Number(source.rank);
      if(source.previous_rank!=null&&Number(source.previous_rank)>0)player.previous_rank=Number(source.previous_rank);
      if(source.best_rank!=null&&Number(source.best_rank)>0)player.best_rank=Number(source.best_rank);
      if(source.ranking_points!=null&&Number(source.ranking_points)>0)player.ranking_points=Number(source.ranking_points);
      if(source.country_code)player.country_code=String(source.country_code).toUpperCase();
      if(source.presentation&&typeof source.presentation==='object')player.presentation={...(player.presentation||{}),...source.presentation};
    });
    row.__liveIntelligenceLoaded=true;
    row.__liveIntelligenceSource=payload.source||'tennisapi';
    return row;
  }
  function requestLiveMatchIntelligence(row,tab){
    if(!row||row.__liveIntelligenceLoaded||typeof BlinqAuth?.matchIntelligence!=='function')return;
    const p1=String(row?.player1?.id||''),p2=String(row?.player2?.id||'');
    if(!/^\d{1,12}$/.test(p1)||!/^\d{1,12}$/.test(p2))return;
    row.__liveIntelligenceLoading=true;
    BlinqAuth.matchIntelligence(p1,p2,row?.surface||'',row?.custom_id||row?.customId||'',row?.event_id||row?.id||'').then(payload=>{
      mergeLiveMatchIntelligence(row,payload);
      row.__liveIntelligenceLoading=false;
      const dialog=$('matchDialog');
      if(dialog?.open)openMatch(normalize(row),tab,row,true);
    }).catch(()=>{
      row.__liveIntelligenceLoading=false;
      row.__liveIntelligenceFailed=true;
      const note=$('matchIntelligenceStatus');
      if(note)note.textContent=lcopy('Extra live analytics are temporarily unavailable.','Doplnkové analytické dáta sú dočasne nedostupné.','Doplňková analytická data jsou dočasně nedostupná.');
    });
  }
  function matchDetailHtml(m,tab='daily',rowOverride=null){
    const row=rowOverride||m?.raw||m;
    const match=rowOverride?normalize(rowOverride):m;
    const signalRows=Array.isArray(match.signals)&&match.signals.length?match.signals.map(s=>{const meta=signalMeta(s,match);const favoursId=String(s?.player_id??s?.favours_player_id??'');const favours=favoursId===String(match.p1Id)?match.p1:favoursId===String(match.p2Id)?match.p2:'—';return `<div class="dialog-signal"><span>${escapeHtml(meta.label)}</span><strong>${escapeHtml(favours)}</strong><small>${meta.favours?'supports pick':'counter-signal'}</small></div>`;}).join(''):'<p class="signal-empty">No secondary signals are available.</p>';
    const labels={
      overview:lcopy('Overview','Prehľad','Přehled'),
      statistics:lcopy('Form & surface','Forma & povrch','Forma & povrch'),
      radar:lcopy('Winner model','Model víťaza','Model vítěze'),
      history:lcopy('History / H2H','História / H2H','Historie / H2H')
    };
    const overview=`<div class="match-detail-overview">${winnerWhyBlinqHtml(row,tab)}<div class="dialog-duel-grid">${insightPlayerCard(row,1)}${insightPlayerCard(row,2)}</div><div class="match-overview-context">${renderMotivationPanel(row)}</div></div>`;
    const statistics=matchDetailSectionAllowed('statistics')?`<div class="match-detail-statistics">${renderMatchStatsPanel(row)}</div>`:matchDetailLockHtml('statistics',labels.statistics);
    const radar=matchDetailSectionAllowed('radar')?`<div class="match-detail-radar"><div class="dialog-section dialog-radar-wrap">${renderRadarComparison(row)}</div><div class="dialog-section match-model-signals"><h3>${escapeHtml(lcopy('Winner model signals','Signály modelu víťaza','Signály modelu vítěze'))}</h3>${signalRows}</div></div>`:matchDetailLockHtml('radar',labels.radar);
    const history=matchDetailSectionAllowed('history')?`<div class="match-detail-history">${renderMatchHistoryPanel(row)}</div>`:matchDetailLockHtml('history',labels.history);
    const tabButton=(id,label)=>{
      const locked=id!=='overview'&&!matchDetailSectionAllowed(id);
      const minPlan=locked?matchDetailSectionMinimum(id):'';
      const required=locked?String(upgradePlanLabel(minPlan)||minPlan).replace(/^BlinQ\s+/i,'').toUpperCase():'';
      return `<button type="button" class="${id==='overview'?'active ':''}${locked?'is-locked':''}" data-match-tab="${escapeHtml(id)}"${locked?` data-match-locked="1" data-upgrade-plan="${escapeHtml(minPlan)}" data-upgrade-section="${escapeHtml(label)}"`:''}><span>${locked?'🔒 ':''}${escapeHtml(label)}</span>${locked?`<small>${escapeHtml(required)}</small>`:''}</button>`;
    };
    return `<div class="match-detail-shell"><header class="match-detail-head"><div><div class="dialog-eyebrow">${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}</div><h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2></div><button class="match-popout-button" type="button" data-match-popout><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 16 16 8M10 8h6v6"/></svg>${escapeHtml(lcopy('Open in new window','Otvoriť v novom okne','Otevřít v novém okně'))}</button></header><div class="dialog-pick match-detail-pick"><div><small>BlinQ Prediction</small><strong>${escapeHtml(match.pick)}</strong></div><div class="dialog-prob">${marketProbability(row)==null?'—':pct(marketProbability(row))}<small>${escapeHtml(lcopy('win probability','šanca na výhru','šance na výhru'))}</small></div></div><nav class="match-detail-tabs" role="tablist">${tabButton('overview',labels.overview)}${tabButton('statistics',labels.statistics)}${tabButton('radar',labels.radar)}${tabButton('history',labels.history)}</nav><section class="match-detail-panel active" data-match-panel="overview">${overview}</section><section class="match-detail-panel" data-match-panel="statistics" hidden>${statistics}</section><section class="match-detail-panel" data-match-panel="radar" hidden>${radar}</section><section class="match-detail-panel" data-match-panel="history" hidden>${history}</section>${row?.__liveIntelligenceLoading?`<div id="matchIntelligenceStatus" class="match-intelligence-status is-loading">${escapeHtml(lcopy('Loading live player analytics…','Načítavam analytické dáta hráčov…','Načítám analytická data hráčů…'))}</div>`:row?.__liveIntelligenceFailed?`<div id="matchIntelligenceStatus" class="match-intelligence-status is-error">${escapeHtml(lcopy('Extra live analytics are temporarily unavailable.','Doplnkové analytické dáta sú dočasne nedostupné.','Doplňková analytická data jsou dočasně nedostupná.'))}</div>`:''}</div>`;
  }
  function openMatchPopout(){
    const source=$('dialogContent');if(!source)return;
    const w=window.open('','blinq_match_detail','popup=yes,width=980,height=900,resizable=yes,scrollbars=yes');if(!w){showStatus(lcopy('Popup was blocked by the browser.','Prehliadač zablokoval nové okno.','Prohlížeč zablokoval nové okno.'));return;}
    const base=`${location.origin}/`;
    // Keep the popup under the production CSP: behavior lives in an external
    // same-origin script instead of an inline <script>. The popup runtime also
    // reinstalls image fallback handling because DOM event listeners are not
    // copied with innerHTML.
    w.document.open();w.document.write(`<!doctype html><html lang="${escapeHtml(locale)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><base href="${escapeHtml(base)}"><title>BlinQ · ${escapeHtml(lcopy('Match detail','Detail zápasu','Detail zápasu'))}</title><link rel="stylesheet" href="/blinq-app.css?v=7360&p=61"><script defer src="/match-popout.js?v=7360&p=61"><\/script></head><body id="blinqPremium" class="blinq-detail-popout"><main class="match-popout-shell">${source.innerHTML}</main></body></html>`);w.document.close();w.focus();
  }
  function openMatch(m,tab='daily',rowOverride=null,skipLiveHydration=false){
    if(!matchDetailPlanAllowed()){const required=firstMatchDetailUnlockPlan();showUpgradePrompt(required,lcopy('Match detail','Detail zápasu','Detail zápasu'),true);return;}
    const row=rowOverride||m?.raw||m;
    const shouldHydrate=!skipLiveHydration&&!row?.__liveIntelligenceLoaded&&!row?.__liveIntelligenceLoading;
    if(shouldHydrate)row.__liveIntelligenceLoading=true;
    $('dialogContent').innerHTML=matchDetailHtml(m,tab,rowOverride);
    const dialog=$('matchDialog');
    dialog.classList.remove('ace-projection-dialog','sg-projection-dialog');
    dialog.querySelectorAll('[data-match-tab]').forEach(button=>button.addEventListener('click',()=>{
      const id=button.dataset.matchTab;
      dialog.querySelectorAll('[data-match-tab]').forEach(node=>{node.classList.toggle('active',node===button);node.setAttribute('aria-selected',node===button?'true':'false');});
      dialog.querySelectorAll('[data-match-panel]').forEach(panel=>{const active=panel.dataset.matchPanel===id;panel.hidden=!active;panel.classList.toggle('active',active);});
    }));
    dialog.querySelector('[data-match-popout]')?.addEventListener('click',openMatchPopout);
    if(!dialog.open)dialog.showModal();
    if(shouldHydrate)requestLiveMatchIntelligence(row,tab);
  }


  const routeMetaEn={
    predictions:['TENNIS INTELLIGENCE','Dashboard','Daily predictions, model signals and current BlinQ intelligence.'],prime:['SHORT ODDS','Short Odds','Short-priced favourite selections with strong model probability and data quality.'],top_daily:['CONFIDENCE FIRST','TOP','Strongest daily predictions ranked by model probability and data quality.'],value:['VALUE','Value','Predictions selected for stronger model value with probability, price and data-quality context.'],doubles:['DOUBLES','Doubles','Separate doubles model and team-pair intelligence.'],ace:['ACES + DOUBLE FAULTS','Aces','Top Aces and Double Faults market selections.'],sg:['SETS + GAMES','Sets / Games','Top Sets and Games market selections.'],results:['SETTLED PREDICTIONS','Results','Settled predictions, hit rate, ROI, units and related performance statistics.'],account:['BLINQ MEMBERS','Account','Profile, security, membership and access.'],admin:['BLINQ CONTROL','Admin centrum','Správa modelu, publikovania, prístupov, účtov a obsahu BlinQ.'],how_blinq_works:['LEARN','How BlinQ Works','How the BlinQ workflow turns point-in-time tennis data into probabilities.'],methodology:['LEARN','Methodology','The principles used to keep predictions point-in-time and auditable.'],model_data:['LEARN','Model & Data','What the published feed exposes about data and model state.'],faq:['LEARN','FAQ','Common questions about probabilities, results and model output.'],responsible_use:['LEARN','Responsible Use','Use probabilities as information, never as guarantees.'],terms:['LEGAL','Terms of Use','Rules for using the BlinQ service.'],privacy:['LEGAL','Privacy','How BlinQ works with account and service data.'],cookies:['LEGAL','Cookies','Browser storage, essential functionality and analytics preferences.']
  };
  const routeMetaSk={
    predictions:['TENISOVÁ ANALYTIKA','Prehľad','Denné predikcie, kľúčové modelové signály a aktuálna BlinQ analytika.'],prime:['SHORT ODDS','Short Odds','Predikcie favoritov s nižším kurzom a silnou modelovou pravdepodobnosťou.'],top_daily:['NAJSILNEJŠIE SIGNÁLY','TOP','Najsilnejšie denné predikcie zoradené podľa pravdepodobnosti modelu a kvality dát.'],value:['MODEL VALUE','Value','Predikcie so zvýšenou modelovou hodnotou a priaznivým pomerom rizika a ceny.'],doubles:['ŠTVORHRA','Štvorhra','Samostatný model štvorhry a inteligencia dvojíc/tímov.'],ace:['ESÁ + DVOJCHYBY','Esá','Najlepšie projekcie pre esá a dvojchyby.'],sg:['SETY + HRY','Sety / hry','Najlepšie projekcie pre sety a počet hier.'],results:['VYHODNOTENÉ PREDIKCIE','Výsledky','Vyhodnotené predikcie, úspešnosť, ROI, jednotky a súvisiace štatistiky výkonu.'],account:['BLINQ ČLENSTVO','Účet','Profil, zabezpečenie, členstvo a prístup.'],how_blinq_works:['INFO','Ako funguje BlinQ','Ako BlinQ mení point-in-time tenisové dáta na pravdepodobnosti.'],methodology:['INFO','Metodika','Princípy, ktoré udržujú predikcie point-in-time a auditovateľné.'],model_data:['INFO','Model a dáta','Čo publikovaný feed ukazuje o dátach a stave modelu.'],faq:['INFO','FAQ','Najčastejšie otázky o pravdepodobnostiach, výsledkoch a výstupe modelu.'],responsible_use:['INFO','Zodpovedné používanie','Pravdepodobnosti používaj ako informáciu, nikdy nie ako záruku.'],terms:['LEGAL','Podmienky používania','Pravidlá používania služby BlinQ.'],privacy:['LEGAL','Ochrana súkromia','Ako BlinQ pracuje s údajmi používateľov.'],cookies:['LEGAL','Cookies','Nevyhnutné úložisko, preferencie a analytika.']
  };
  const routeMetaCz={
    predictions:['TENISOVÁ ANALYTIKA','Přehled','Denní predikce, klíčové modelové signály a aktuální BlinQ analytika.'],prime:['SHORT ODDS','Short Odds','Predikce favoritů s nižším kurzem a silnou modelovou pravděpodobností.'],top_daily:['NEJSILNĚJŠÍ SIGNÁLY','TOP','Nejsilnější denní predikce seřazené podle pravděpodobnosti modelu a kvality dat.'],value:['MODEL VALUE','Value','Predikce se zvýšenou modelovou hodnotou a příznivým poměrem rizika a ceny.'],doubles:['ČTYŘHRA','Čtyřhra','Samostatný model čtyřhry a inteligence dvojic/týmů.'],ace:['ESA + DVOJCHYBY','Esa','Nejlepší projekce pro esa a dvojchyby.'],sg:['SETY + HRY','Sety / hry','Nejlepší projekce pro sety a počet her.'],results:['VYHODNOCENÉ PREDIKCE','Výsledky','Vyhodnocené predikce, úspěšnost, ROI, jednotky a související statistiky výkonu.'],account:['BLINQ ČLENSTVÍ','Účet','Profil, zabezpečení, členství a přístup.'],how_blinq_works:['INFO','Jak funguje BlinQ','Jak BlinQ mění point-in-time tenisová data na pravděpodobnosti.'],methodology:['INFO','Metodika','Principy, které udržují predikce point-in-time a auditovatelné.'],model_data:['INFO','Model a data','Co publikovaný feed ukazuje o datech a stavu modelu.'],faq:['INFO','FAQ','Nejčastější otázky o pravděpodobnostech, výsledcích a výstupu modelu.'],responsible_use:['INFO','Zodpovědné používání','Pravděpodobnosti používej jako informaci, nikdy ne jako záruku.'],terms:['LEGAL','Podmínky používání','Pravidla používání služby BlinQ.'],privacy:['LEGAL','Ochrana soukromí','Jak BlinQ pracuje s údaji uživatelů.'],cookies:['LEGAL','Cookies','Nezbytné úložiště, preference a analytika.']
  };
  const routeMeta=locale==='sk'?{...routeMetaEn,...routeMetaSk}:locale==='cz'?{...routeMetaEn,...routeMetaCz}:routeMetaEn;

  function wireDashboardSearch(){
    const input=$('dashboardSearch');if(!input||input.dataset.wired==='1')return;input.dataset.wired='1';
    input.addEventListener('input',()=>{state.dashboardSearch=input.value||'';state.dailyHubExpanded=false;renderDailyHub();});
    input.addEventListener('keydown',event=>{if(event.key==='Escape'){input.value='';state.dashboardSearch='';renderDailyHub();input.blur();}});
  }

  function wireDailyHub(){
    const hub=$('dailyHub');
    if(!hub) return;
    // Assign handlers to the current host node rather than relying on a one-time
    // addEventListener guard. Some runtime redraws can replace/re-hydrate the host
    // while preserving data attributes, leaving a visually live panel without its
    // old listener. Reassigning the properties is idempotent and keeps every redraw clickable.
    hub.dataset.wired='1';
    hub.onchange=event=>{
      if(event.target?.id==='dailyHubTournamentFilter'){state.dailyHubTournament=event.target.value||'';state.dailyHubExpanded=false;renderDailyHub();return;}
    };
    hub.onclick=event=>{
      const target=event.target instanceof Element?event.target:null;
      if(!target)return;
      const tab=target.closest('[data-daily-hub-tab]');
      if(tab){ if(tab.dataset.upgradePlan){showAccessHint(tab,tab.dataset.upgradePlan,tab.dataset.upgradeSection||'SEE ALL',true);return;} state.dailyHubTab=tab.dataset.dailyHubTab; state.dailyHubExpanded=false; renderDailyHub(); return; }
      const detailLock=target.closest('[data-detail-locked]');
      if(detailLock){showAccessHint(detailLock,detailLock.dataset.upgradePlan||firstMatchDetailUnlockPlan(),detailLock.dataset.upgradeSection||lcopy('Match detail','Detail zápasu','Detail zápasu'),true);return;}
      if(target.closest('#dailyHubExpand')){ const ent=dailyHubEntitlement(state.dailyHubTab); if(ent.see_all!==true){ const expand=target.closest('#dailyHubExpand');const plan=state.dailyHubTab==='board'?'legend':firstDailyHubUnlockPlan(state.dailyHubTab,0,true);const label=state.dailyHubTab==='board'?'BlinQ Board':lcopy('Full daily offer','Celá denná ponuka','Celá denní nabídka');showAccessHint(expand,plan,label,true); return; } state.dailyHubExpanded=!state.dailyHubExpanded; renderDailyHub(); return; }
      const row=target.closest('tr[data-hub-event]');
      if(row){
        const key=String(row.dataset.hubEvent||'');
        let current=dailyHubRows(state.dailyHubTab).find(r=>eventKey(r)===key);
        if(!current){const found=findRowByEventId(key);current=found?.row||null;}
        if(!current){
          const pools=[state.feed?.upcoming,state.feed?.daily_picks,state.feed?.board_upcoming,state.feed?.board_results];
          current=pools.flatMap(items=>Array.isArray(items)?items:[]).find(r=>eventKey(r)===key)||null;
        }
        if(current){
          const sourceTab=state.dailyHubTab==='see_all'?String(current?._hub_source||''):state.dailyHubTab;
          if(sourceTab==='ace'||sourceTab==='double_faults'){
            if(aceProjectionDetailAvailable(current))openAceProjection(current);
            return;
          }
          if(sourceTab==='games'||sourceTab==='sets'){
            openSgProjection(current,sourceTab);
            return;
          }
          openMatch(normalize(current),sourceTab||state.dailyHubTab,current);
        }
      }
    };
  }

  function setRoute(route,push=true){ if(!routeMeta[route]) route='predictions'; if(route==='results'&&!resultsAccessAllowed()){const source=document.querySelector('.reference-navigation [data-route="results"]')||document.querySelector('#mobileTabs [data-route="results"]')||document.body;const plan=firstResultsUnlockPlan();showAccessHint(source,plan,lcopy('Results','Výsledky','Výsledky'),true);if(location.hash==='#results')history.replaceState(null,'','#predictions');route='predictions';} if(route==='admin'&&!isAdminAccount()) route='predictions'; document.body.classList.toggle('blinq-home',route==='predictions'); document.body.classList.toggle('blinq-admin',route==='admin'); document.body.classList.toggle('blinq-route',route!=='predictions'&&route!=='admin'); const section=dashboardSectionKeys.includes(route)?dashboardSectionConfig(route):null; if(section&&route!=='predictions'&&route!=='results'&&elementAccess(section.sidebar_element)!=='active'&&state.route!=='admin'){const source=document.querySelector(`[data-route="${CSS.escape(route)}"]`)||document.body;showAccessHint(source,firstUnlockPlan(route,0,true),section.label||route,true);route='predictions';} if(route==='admin') state.previewPlan=null; const routeChanged=state.route!==route;state.route=route;renderCookieConsent(false);if(routeChanged)state.page=0;const meta=routeMeta[route]; const overview=route==='predictions'; const routeHeading=$('routeHeading'); if(routeHeading) routeHeading.hidden=overview; const pageEyebrow=$('pageEyebrow'),pageSubtitle=$('pageSubtitle'); if(pageEyebrow){pageEyebrow.textContent=meta[0];pageEyebrow.hidden=route==='results';} $('pageTitle').textContent=meta[1]; if(pageSubtitle){pageSubtitle.textContent=meta[2];pageSubtitle.hidden=route==='results';} const topbar=document.querySelector('.dashboard-topbar'); if(topbar) topbar.classList.toggle('overview-mode',overview); $('predictionsView').hidden=!overview; $('routePanel').hidden=overview; renderNavigation(); if(overview){renderPredictions();renderMarketSections();renderDailyHub();renderDashboardResultsPreview();applyAccessStates();} else renderRoute(route); if(push&&location.hash!==`#${route}`) history.pushState(null,'',`#${route}`); window.BlinqUI.routeChanged(route,push); updateLanguageLinks(); document.title=`${meta[1]} · BlinQ`; if(route!=='admin')translatePublicDom(document.body); }

  function metricCards(items){ return `<div class="metric-cards">${items.map(([label,value,note])=>`<div class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note||'')}</span></div>`).join('')}</div>`; }
  function issuedMarketPublications(row){
    return (Array.isArray(row?.market_publications)?row.market_publications:[]).filter(p=>p&&p.issued_at&&p.result&&!p.excluded_reason);
  }
  const publicResultSections=new Set(['top_daily','prime','value','doubles','ace','double_faults','sets','games']);
  const publicResultMarkets=new Set(['aces','double_faults']);
  function isPublicResultPublication(publication){
    if(!publication||typeof publication!=='object')return false;
    const section=String(publication.section||'').trim().toLowerCase();
    const market=String(publication.market||'').trim().toLowerCase();
    return publicResultSections.has(section)||publicResultMarkets.has(market);
  }
  function publicResultPublications(row){
    return issuedMarketPublications(row).filter(isPublicResultPublication);
  }
  function resultTags(row){
    const tags=[];
    issuedMarketPublications(row).forEach(p=>{
      const section=String(p.section||'');
      const market=String(p.market||'');
      if(section&&!tags.includes(section))tags.push(section);
      if(market==='aces'&&!tags.includes('ace'))tags.push('ace');
      if(market==='double_faults'&&!tags.includes('double_faults'))tags.push('double_faults');
    });
    return tags;
  }
  function isProjectionPublication(publication){return ['aces','double_faults','sets','games'].includes(String(publication?.market||publication?.projection_metric||'').toLowerCase())||['projection_only','priced_projection'].includes(String(publication?.price_status||'').toLowerCase());}
  function publicationMatchesResultCategory(publication,category='all'){
    if(category==='all')return true;
    if(category==='sg')return ['sets','games'].includes(String(publication?.section||''));
    if(category==='ace')return String(publication?.market||'')==='aces';
    if(category==='double_faults')return String(publication?.market||'')==='double_faults';
    return String(publication?.section||'')===category;
  }
  function normalizeResultPlayerName(value){
    return String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-zA-Z0-9]+/g,' ').trim().toLowerCase();
  }
  function resultPickIdentity(publication,row){
    const p1=row?.player1||{},p2=row?.player2||{};
    const p1Id=String(p1?.id||''),p2Id=String(p2?.id||'');
    const ids=[publication?.selection_id,publication?.pick_id,publication?.winner_id].map(v=>String(v||'')).filter(Boolean);
    let sideById='';
    for(const id of ids){if(p1Id&&id===p1Id){sideById='p1';break;}if(p2Id&&id===p2Id){sideById='p2';break;}}
    const text=String(publication?.selection||publication?.pick||publication?.prediction||'').trim();
    const nt=normalizeResultPlayerName(text),n1=normalizeResultPlayerName(p1?.name),n2=normalizeResultPlayerName(p2?.name);
    const sideByText=nt&&n1&&nt===n1?'p1':nt&&n2&&nt===n2?'p2':'';
    const side=sideById||sideByText||'';
    const conflict=Boolean(sideById&&sideByText&&sideById!==sideByText);
    const name=side==='p1'?String(p1?.name||text||'—'):side==='p2'?String(p2?.name||text||'—'):(text||'—');
    return {side,name,conflict,selectionId:ids[0]||'',rawText:text};
  }
  function projectionResultTypeLabel(publication){
    const metric=String(publication?.projection_metric||publication?.market||'').toLowerCase();
    return ({
      aces:lcopy('ACES','ACES','ACES'),
      double_faults:lcopy('DOUBLE FAULTS','DVOJCHYBY','DVOJCHYBY'),
      sets:lcopy('SETS','SETY','SETY'),
      games:lcopy('GAMES','GAMY','GEMY'),
    })[metric]||String(metric||'PROJECTION').replaceAll('_',' ').toUpperCase();
  }
  function projectionResultSelectionText(publication,fallback='—'){
    const metric=String(publication?.projection_metric||publication?.market||'').toLowerCase();
    const selection=String(publication?.selection||fallback||'—').trim();
    if(metric==='games'){
      const direction=String(publication?.projection_direction||'').toLowerCase();
      const line=Number(publication?.reference_projection);
      const side=['high','over'].includes(direction)?lcopy('Over','Over','Over'):['low','under'].includes(direction)?lcopy('Under','Under','Under'):'';
      if(side&&Number.isFinite(line))return `${side} ${line.toFixed(1)} ${lcopy('Games','Games','Games')}`;
      return selection.replace(/^High\s+Total\s+Games$/i,lcopy('Over total games','Over total games','Over total games')).replace(/^Low\s+Total\s+Games$/i,lcopy('Under total games','Under total games','Under total games'));
    }
    if(metric==='sets')return selection;
    const line=Number(publication?.market_line??publication?.line??publication?.threshold);
    if((metric==='aces'||metric==='double_faults')&&Number.isFinite(line)){
      const projected=Number(publication?.projection),side=Number.isFinite(projected)?(projected>=line?'Over':'Under'):'';
      const unit=metric==='aces'?'Aces':lcopy('Double Faults','Dvojchyby','Dvojchyby');
      if(side)return `${selection&&selection!=='—'?selection+' · ':''}${side} ${line.toFixed(1)} ${unit}`;
    }
    return selection;
  }
  function projectionResultUnitLabel(publication){
    const metric=String(publication?.projection_metric||publication?.market||'').toLowerCase();
    return ({aces:'Aces',double_faults:lcopy('Double Faults','Dvojchyby','Dvojchyby'),sets:lcopy('Sets','Sety','Sety'),games:lcopy('Games','Games','Gemy')})[metric]||'';
  }
  function projectionResultNumber(value,publication,digits=1){
    const numberValue=Number(value);if(!Number.isFinite(numberValue))return '—';
    const unit=projectionResultUnitLabel(publication);const rendered=numberValue.toFixed(Number.isInteger(numberValue)?0:digits);
    return unit?`${rendered} ${unit}`:rendered;
  }
  function projectionResultProjectionText(publication){
    const metric=String(publication?.projection_metric||publication?.market||'').toLowerCase();
    if(metric==='sets'){
      const totalSets=setsTotalProjectionValue(publication);
      if(Number.isFinite(totalSets))return `${totalSets.toFixed(2)} ${lcopy('Sets','Sety','Sety')}`;
    }
    return projectionResultNumber(publication?.projection,publication,1);
  }
  function projectionResultActualText(publication){
    const result=publication?.result||{},actual=Number(result?.actual_count),opponent=Number(result?.opponent_actual_count);
    if(!Number.isFinite(actual))return '—';
    const metric=String(publication?.projection_metric||publication?.market||'').toLowerCase();
    const primary=projectionResultNumber(actual,publication,1);
    if(['aces','double_faults'].includes(metric)&&Number.isFinite(opponent)){
      return `${primary} · ${lcopy('opponent','súper','soupeř')} ${projectionResultNumber(opponent,publication,1)}`;
    }
    return primary;
  }
  function resultCategoryLabel(value){const en=({all:'All published',prime:'Short Odds',top_daily:'TOP',value:'Value',doubles:'Doubles',ace:'Aces',aces:'Aces',double_faults:'Double Faults',sg:'Sets & Games',sets:'Sets',games:'Games',model:'Model'})[value]||String(value||'').replaceAll('_',' ');if(locale==='sk')return ({'All published':'Všetky publikované','TOP':'TOP','Doubles':'Štvorhra','Aces':'Esá','Double Faults':'Dvojchyby','Sets & Games':'Sety a gamy','Sets':'Sety','Games':'Gamy','Model':'Model'})[en]||en;if(locale==='cz')return ({'All published':'Všechny publikované','TOP':'TOP','Doubles':'Čtyřhra','Aces':'Esa','Double Faults':'Dvojchyby','Sets & Games':'Sety a gamy','Sets':'Sety','Games':'Gamy','Model':'Model'})[en]||en;return en;}
  function resultPublication(row,category='all'){
    const pubs=publicResultPublications(row);
    const filtered=['prime','top_daily','value','doubles','ace','double_faults','sg','sets','games'].includes(category)?pubs.filter(p=>publicationMatchesResultCategory(p,category)):pubs;
    return filtered.sort((a,b)=>new Date(a.issued_at)-new Date(b.issued_at))[0]||null;
  }
  function publicationOutcome(publication){
    const result=publication?.result||{};
    const raw=String(result?.status||result?.outcome||result?.settlement||result?.result||'').trim().toLowerCase();
    const reason=String(result?.reason||result?.void_reason||result?.settlement_reason||'').trim();
    const isVoid=result?.void===true||result?.is_void===true||['void','push','cancelled','canceled','postponed','walkover','walk over','w/o','retired','ret','abandoned','interrupted','suspended','no_action'].includes(raw);
    if(isVoid)return {kind:'void',reason:reason||raw||'void'};
    if(result?.correct===true)return {kind:'win',reason:''};
    if(result?.correct===false)return {kind:'loss',reason:''};
    return {kind:'pending',reason:''};
  }
  function resultVoidLabel(reason=''){
    const value=String(reason||'').trim().toLowerCase();
    if(value.includes('retir')||value.includes('incomplete')||value==='ret')return lcopy('RETIREMENT','SKREČ','SKREČ');
    // W/O, cancellations and other non-played results have one public label.
    // Only a verified in-progress retirement stays separate as SKREČ.
    return 'VOID';
  }
  function filteredResults(){
    const filters=state.resultsFilters||{},now=Date.now(),windowDays=Number(filters.window);
    const from=String(filters.dateFrom||'').trim(),to=String(filters.dateTo||'').trim();
    const fromTs=from?new Date(`${from}T00:00:00`).getTime():null;
    const toTs=to?new Date(`${to}T23:59:59.999`).getTime():null;
    return (state.feed.results||[]).filter(row=>{
      if(filters.tour&&String(row?.tour||'').toUpperCase()!==filters.tour)return false;
      // "All surfaces" really means all settled published rows. Unknown/missing
      // surface metadata must never hide a valid historical result.
      if(filters.surface){const raw=String(row?.surface||'').toLowerCase();const mapped=raw==='indoor_hard'?'hard':raw;if(mapped!==filters.surface)return false;}
      const ts=new Date(row?.scheduled_at||0).getTime();
      if(filters.window==='custom'){
        if(fromTs!==null&&(!Number.isFinite(ts)||ts<fromTs))return false;
        if(toTs!==null&&(!Number.isFinite(ts)||ts>toTs))return false;
      }else if(Number.isFinite(windowDays)&&windowDays>0){if(!Number.isFinite(ts)||ts<now-windowDays*86400000)return false;}
      const category=filters.category||'all';
      const pubs=publicResultPublications(row);
      if(!pubs.length)return false;
      if(category!=='all'&&!pubs.some(p=>publicationMatchesResultCategory(p,category)&&publicationOutcome(p).kind!=='pending'))return false;
      return pubs.some(p=>publicationOutcome(p).kind!=='pending');
    });
  }
  function resultsHistoryHours(){
    const raw=state.feed?.entitlements?.results_history_hours;
    if(raw===null||raw===undefined||raw==='ALL')return null;
    const n=Number(raw);if(Number.isFinite(n)&&n>0)return n;
    const plan=accountPlan();return plan==='rookie'?24:plan==='pro'?48:null;
  }
  function resultsAccessAllowed(plan=accountPlan()){
    if(String(plan||'').toLowerCase()==='admin')return true;
    return elementAccess('SIDEBAR_RESULTS',plan)==='active';
  }
  function firstResultsUnlockPlan(){
    for(const id of membershipHierarchy){if(state.ui?.plans?.[id]?.enabled!==false&&elementAccess('SIDEBAR_RESULTS',id)==='active')return id;}
    return 'goat';
  }
  function resultsLockedCard(){
    const minPlan=firstResultsUnlockPlan();
    const required=String(upgradePlanLabel(minPlan)||minPlan).replace(/^BlinQ\s+/i,'').toUpperCase();
    return `<div class="results-access-lock" data-upgrade-plan="${escapeHtml(minPlan)}" data-upgrade-section="${escapeHtml(lcopy('Results','Výsledky','Výsledky'))}"><span aria-hidden="true">🔒</span><div><small>${escapeHtml(lcopy('LOCKED SECTION','UZAMKNUTÁ SEKCIA','UZAMČENÁ SEKCE'))}</small><strong>${escapeHtml(lcopy('Results','Výsledky','Výsledky'))}</strong><p>${escapeHtml(lcopy(`Available from ${required}`,`Dostupné od: ${required}`,`Dostupné od: ${required}`))}</p></div></div>`;
  }
  function renderResultsFilters(){
    const rows=state.feed.results||[],filters=state.resultsFilters||{},hours=resultsHistoryHours();
    const tours=[...new Set(rows.map(r=>String(r?.tour||'').toUpperCase()).filter(Boolean))].sort();
    const surfaces=[...new Set(rows.map(r=>{const v=String(r?.surface||'').toLowerCase();return v==='indoor_hard'?'hard':v;}).filter(v=>v&&v!=='unknown'))].sort();
    const option=(value,label,selected)=>`<option value="${escapeHtml(value)}"${value===selected?' selected':''}>${escapeHtml(label)}</option>`;
    if(hours){state.resultsFilters.window=String(hours/24);state.resultsFilters.dateFrom='';state.resultsFilters.dateTo='';}
    const fixedDays=hours?hours/24:null;
    const fixedLabel=hours?(hours===24?lcopy('Last 24 hours','Posledných 24 hodín','Posledních 24 hodin'):hours===48?lcopy('Last 48 hours','Posledných 48 hodín','Posledních 48 hodin'):lcopy(`Last ${fixedDays} days`,`Posledných ${fixedDays} dní`,`Posledních ${fixedDays} dní`)):'';
    const periodOptions=hours?[[String(fixedDays),fixedLabel]]:[['all',publicText('All time')],['1',publicText('24 hours')],['3',lcopy('3 days','3 dni','3 dny')],['7',publicText('7 days')],['10',lcopy('10 days','10 dní','10 dní')],['14',lcopy('14 days','14 dní','14 dní')],['30',publicText('30 days')],['90',publicText('90 days')],['custom',lcopy('Custom range','Vlastné obdobie','Vlastní období')]];
    return `<div class="results-filter-bar results-filter-bar-v683">
      <label class="results-filter-field"><span>${escapeHtml(publicText('Category'))}</span><span class="select-shell"><select id="resultsCategory">${['all','top_daily','prime','value','ace','double_faults','sets','games','doubles'].map(v=>option(v,resultCategoryLabel(v),filters.category||'all')).join('')}</select><i aria-hidden="true"></i></span></label>
      <label class="results-filter-field"><span>${escapeHtml(publicText('Tour'))}</span><span class="select-shell"><select id="resultsTour">${option('',publicText('All Tours'),filters.tour||'')}${tours.map(v=>option(v,v,filters.tour||'')).join('')}</select><i aria-hidden="true"></i></span></label>
      <label class="results-filter-field"><span>${escapeHtml(publicText('Surface'))}</span><span class="select-shell"><select id="resultsSurface">${option('',publicText('All Surfaces'),filters.surface||'')}${surfaces.map(v=>option(v,v.replaceAll('_',' '),filters.surface||'')).join('')}</select><i aria-hidden="true"></i></span></label>
      <label class="results-filter-field"><span>${escapeHtml(publicText('Period'))}</span><span class="select-shell"><select id="resultsWindow" ${hours?'disabled':''}>${periodOptions.map(([v,l])=>option(v,l,filters.window||periodOptions[0][0])).join('')}</select><i aria-hidden="true"></i></span></label>
      ${hours?'':`<label class="results-filter-field results-date-field"><span>${escapeHtml(lcopy('From','Od','Od'))}</span><span class="date-shell"><input id="resultsDateFrom" type="date" value="${escapeHtml(filters.dateFrom||'')}"><i aria-hidden="true"></i></span></label><label class="results-filter-field results-date-field"><span>${escapeHtml(lcopy('To','Do','Do'))}</span><span class="date-shell"><input id="resultsDateTo" type="date" value="${escapeHtml(filters.dateTo||'')}"><i aria-hidden="true"></i></span></label>`}
    </div>`;
  }
  function canonicalResultPublicationKey(row,publication,index=0){
    // Old ledgers may contain the same public bet under more than one lifecycle
    // key (for example before/after betting-day identity was introduced). Results
    // are a semantic view: one event + market/projection + selection = one row.
    const eventId=String(row?.event_id||row?.id||row?.match_id||'').trim();
    const market=String(publication?.market||'match_winner').trim().toLowerCase();
    const scope=String(publication?.projection_scope||'').trim().toLowerCase();
    const metric=String(publication?.projection_metric||'').trim().toLowerCase();
    const selection=String(publication?.selection_id||publication?.selection||'').trim().toLowerCase();
    if(eventId&&selection)return `${eventId}::${market}::${scope}::${metric}::${selection}`;
    const p1=String(row?.player1?.id||row?.player1?.name||'').trim().toLowerCase();
    const p2=String(row?.player2?.id||row?.player2?.name||'').trim().toLowerCase();
    const players=[p1,p2].filter(Boolean).sort().join('::');
    const scheduled=String(row?.scheduled_at||'').trim();
    if((scheduled||players)&&selection)return `${scheduled}::${players}::${market}::${scope}::${metric}::${selection}`;
    return String(publication?.selection_key||publication?.publication_key||`${scheduled}::${players}::${publication?.section||''}::${selection||index}`);
  }
  function settledPublishedEntries(rows,category='all'){
    const specific=['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category);
    const unique=new Map();
    (rows||[]).forEach(row=>{
      const pubs=publicResultPublications(row).filter(p=>!specific&&category!=='sg'?true:publicationMatchesResultCategory(p,category)).filter(p=>publicationOutcome(p).kind!=='pending');
      pubs.forEach((publication,index)=>{
        const key=canonicalResultPublicationKey(row,publication,index);
        const current=unique.get(key);
        if(!current||new Date(publication.issued_at)<new Date(current.publication.issued_at))unique.set(key,{row,publication});
      });
    });
    return [...unique.values()].sort((a,b)=>new Date(b.row?.scheduled_at||0)-new Date(a.row?.scheduled_at||0));
  }
  function localResultMetrics(rows,category){
    const entries=settledPublishedEntries(rows,category);
    const pubs=entries.map(entry=>entry.publication);
    const graded=pubs.filter(p=>publicationOutcome(p).kind==='win'||publicationOutcome(p).kind==='loss');
    const wins=graded.filter(p=>publicationOutcome(p).kind==='win').length;
    const voids=pubs.filter(p=>publicationOutcome(p).kind==='void').length;
    const profit=graded.reduce((sum,p)=>sum+Number(p.result?.profit_units||0),0);
    const stake=graded.reduce((sum,p)=>sum+Number(p.result?.staked_units||0),0);
    const odds=graded.filter(p=>p.odds!=null).map(p=>Number(p.odds)).filter(v=>Number.isFinite(v)&&v>1);
    const sample=graded.length;
    return {wins,losses:Math.max(0,sample-wins),voids,sample,hit:sample?wins/sample:null,avgOdds:odds.length?odds.reduce((a,b)=>a+b,0)/odds.length:null,roi:stake?profit/stake:null,profit,oddsSample:odds.length};
  }
  function renderResults(){
    const rows=filteredResults(),category=state.resultsFilters?.category||'all',entries=settledPublishedEntries(rows,category);
    if(!entries.length){state.resultsPage=0;return '<div class="state-card">Zatiaľ nie sú dostupné vyhodnotené publikované predikcie/projekcie pre tento filter.</div>';}
    const allowedSizes=[50,100],pageSize=allowedSizes.includes(Number(state.resultsPageSize))?Number(state.resultsPageSize):50;
    state.resultsPageSize=pageSize;
    const pages=Math.max(1,Math.ceil(entries.length/pageSize));
    state.resultsPage=Math.max(0,Math.min(Number(state.resultsPage)||0,pages-1));
    const startIndex=state.resultsPage*pageSize,endIndex=Math.min(entries.length,startIndex+pageSize);
    const body=entries.slice(startIndex,endIndex).map(({row:r,publication})=>{
      const p1=r.player1||{},p2=r.player2||{},outcome=publicationOutcome(publication),projection=isProjectionPublication(publication);
      const pickIdentity=resultPickIdentity(publication,r);
      const pickName=projection?(publication?.selection||pickIdentity.name||'—'):pickIdentity.name;
      const probability=publication?.model_probability==null?NaN:Number(publication?.model_probability);
      const odds=publication?.odds==null?NaN:Number(publication?.odds),rawUnits=publication?.result?.profit_units==null?NaN:Number(publication?.result?.profit_units),units=outcome.kind==='void'?0:rawUnits;
      const projectionMarket=String(publication?.market||publication?.projection_metric||'').toLowerCase();
      const tag=projection?({aces:'ace',double_faults:'double_faults',sets:'sets',games:'games'}[projectionMarket]||String(publication?.section||'projection')):String(publication?.section||'');
      const tags=`<span class="result-tag ${escapeHtml(tag)}">${escapeHtml(projection?projectionResultTypeLabel(publication):resultCategoryLabel(tag||'all'))}</span>`;
      const voidLabel=resultVoidLabel(outcome.reason);
      const resultHtml=outcome.kind==='win'
        ?`<b class="correct">✓ ${escapeHtml(lcopy('WIN','VÝHRA','VÝHRA'))}</b>`
        :outcome.kind==='loss'
          ?`<b class="wrong">× ${escapeHtml(lcopy('LOSS','PREHRA','PREHRA'))}</b>`
          :`<b class="${voidLabel==='SKREČ'?'retired':'void'}">○ ${escapeHtml(voidLabel)}</b>`;
      const p1Name=p1.name||'Player 1',p2Name=p2.name||'Player 2';
      const p1Photo=playerPhotoSource(r,p1,'player1');
      const p2Photo=playerPhotoSource(r,p2,'player2');
      const marketName=String(publication?.market||'').toLowerCase();
      const selectable=!projection&&(marketName==='match_winner'||!marketName);
      const p1Selected=selectable&&pickIdentity.side==='p1';
      const p2Selected=selectable&&pickIdentity.side==='p2';
      const p1Class=p1Selected?' is-pick':p2Selected?' is-opponent':'';
      const p2Class=p2Selected?' is-pick':p1Selected?' is-opponent':'';
      const tipBadge='<i class="results-pick-mark" aria-label="Predikovaný hráč">TIP</i>';
      const match=`<div class="results-match-player${p1Class}">${smallAvatar(p1Photo,p1Name,r?.tour,p1?.gender||p1?.sex||'')}${flagIconHtml(p1.country_code||p1.country_code2||p1.country_code3,true)}<strong>${escapeHtml(p1Name)}</strong>${p1Selected?tipBadge:''}</div><div class="results-match-sub"><span class="results-vs">vs</span><span class="results-opponent${p2Class}">${smallAvatar(p2Photo,p2Name,r?.tour,p2?.gender||p2?.sex||'')}${flagIconHtml(p2.country_code||p2.country_code2||p2.country_code3,true)}<strong>${escapeHtml(p2Name)}</strong>${p2Selected?tipBadge:''}</span></div>`;
      const tournamentCell=tournamentIdentityHtml(r);
      if(projection){
        const depth=Number(publication?.data_depth??publication?.result?.data_depth),displayPick=projectionResultSelectionText(publication,pickName),projectionText=projectionResultProjectionText(publication),actualText=projectionResultActualText(publication);
        const projectionOdds=publication?.odds==null?NaN:Number(publication?.odds),projectionUnits=publication?.result?.profit_units==null?NaN:Number(publication?.result?.profit_units);
        const depthText=Number.isFinite(depth)?pct(depth):'—';
        const unitsText=outcome.kind==='void'?'0.00u':Number.isFinite(projectionUnits)&&Number(publication?.result?.staked_units)>0?`${projectionUnits>0?'+':''}${projectionUnits.toFixed(2)}u`:'—';
        const outcomeDetail=actualText&&actualText!=='—'?`<span class="results-actual">${escapeHtml(actualText)}</span>`:'';
        return `<tr><td>${escapeHtml(fmtDate(r.scheduled_at))}<small>${escapeHtml(fmtTime(r.scheduled_at))}</small></td><td>${tags}</td><td>${tournamentCell}</td><td>${match}</td><td><strong>${escapeHtml(displayPick)}</strong></td><td>${escapeHtml(projectionText)}</td><td>${Number.isFinite(projectionOdds)&&projectionOdds>1?projectionOdds.toFixed(2):'—'}</td><td><span class="results-outcome-stack">${resultHtml}${outcomeDetail}</span></td><td><span class="results-units-depth"><b class="${Number.isFinite(projectionUnits)&&projectionUnits>0?'correct':Number.isFinite(projectionUnits)&&projectionUnits<0?'wrong':'void'}">${escapeHtml(unitsText)}</b><small>${escapeHtml(depthText)}</small></span></td></tr>`;
      }
      return `<tr><td>${escapeHtml(fmtDate(r.scheduled_at))}<small>${escapeHtml(fmtTime(r.scheduled_at))}</small></td><td>${tags}</td><td>${tournamentCell}</td><td>${match}</td><td><strong>${escapeHtml(pickName)}</strong></td><td>${Number.isFinite(probability)?pct(probability):'—'}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td><td>${resultHtml}</td><td class="${outcome.kind==='void'?'void':Number.isFinite(units)&&units>=0?'correct':'wrong'}">${outcome.kind==='void'?'0.00u':Number.isFinite(units)?`${units>0?'+':''}${units.toFixed(2)}u`:'—'}</td></tr>`;
    }).join('');
    const pager=`<div class="results-pagination"><div class="results-pagination-meta"><strong>${startIndex+1}–${endIndex}</strong><span>z ${entries.length}</span></div><label><span>Riadkov</span><select id="resultsPageSize">${allowedSizes.map(size=>`<option value="${size}"${size===pageSize?' selected':''}>${size}</option>`).join('')}</select></label><div class="results-pagination-nav"><button type="button" id="resultsPrevPage" ${state.resultsPage<=0?'disabled':''}>←</button><span>Strana <strong>${state.resultsPage+1}</strong> / ${pages}</span><button type="button" id="resultsNextPage" ${state.resultsPage>=pages-1?'disabled':''}>→</button></div></div>`;
    const head='<tr><th>Dátum</th><th>Kategória</th><th>Turnaj</th><th>Zápas</th><th>Predikcia</th><th>Model / BlinQ %</th><th>Kurz</th><th>Výsledok</th><th>Jednotky / DATA DEPTH</th></tr>';
    return `<div class="admin-table-wrap results-table-wrap"><table class="admin-analytics-table results-table"><thead>${head}</thead><tbody>${body}</tbody></table></div>${pager}`;
  }

  function wireResultsFilters(){
    const rerender=()=>{state.resultsPage=0;renderRoute('results');};
    [['resultsCategory','category'],['resultsTour','tour'],['resultsSurface','surface']].forEach(([id,key])=>{const el=$(id);if(el)el.onchange=()=>{state.resultsFilters[key]=el.value;rerender();};});
    const period=$('resultsWindow');if(period)period.onchange=()=>{state.resultsFilters.window=period.value||'all';if(state.resultsFilters.window!=='custom'){state.resultsFilters.dateFrom='';state.resultsFilters.dateTo='';}rerender();};
    const from=$('resultsDateFrom'),to=$('resultsDateTo');
    if(from)from.onchange=()=>{state.resultsFilters.dateFrom=from.value||'';if(state.resultsFilters.dateTo&&state.resultsFilters.dateFrom>state.resultsFilters.dateTo)state.resultsFilters.dateTo=state.resultsFilters.dateFrom;state.resultsFilters.window='custom';rerender();};
    if(to)to.onchange=()=>{state.resultsFilters.dateTo=to.value||'';if(state.resultsFilters.dateFrom&&state.resultsFilters.dateTo<state.resultsFilters.dateFrom)state.resultsFilters.dateFrom=state.resultsFilters.dateTo;state.resultsFilters.window='custom';rerender();};
    const clear=$('resultsDateClear');if(clear)clear.onclick=()=>{state.resultsFilters.dateFrom='';state.resultsFilters.dateTo='';state.resultsFilters.window='all';rerender();};
    const size=$('resultsPageSize');if(size)size.onchange=()=>{state.resultsPageSize=[50,100].includes(Number(size.value))?Number(size.value):50;state.resultsPage=0;renderRoute('results');};
    const prev=$('resultsPrevPage'),next=$('resultsNextPage');
    if(prev)prev.onclick=()=>{if(state.resultsPage>0){state.resultsPage-=1;renderRoute('results');window.scrollTo({top:0,behavior:'smooth'});}};
    if(next)next.onclick=()=>{state.resultsPage+=1;renderRoute('results');window.scrollTo({top:0,behavior:'smooth'});};
  }

  function planIsUnlimited(planId,plan=state.ui?.plans?.[planId]||{}){return planId==='rookie'||plan.unlimited===true;}
  function planDefaultExpiry(planId, from=new Date()){
    const plan=state.ui?.plans?.[planId]||{};
    if(plan.lifetime||planIsUnlimited(planId,plan))return null;
    const days=Number(plan.duration_days); if(!Number.isFinite(days)||days<=0)return null;
    return new Date(from.getTime()+days*86400000);
  }
  function planTermLabel(planId){
    const plan=state.ui?.plans?.[planId]||{};
    if(planIsUnlimited(planId,plan))return 'Bez časového obmedzenia';
    if(plan.lifetime)return 'Doživotne';
    const days=Number(plan.duration_days); return Number.isFinite(days)&&days>0?`${days} dní`:'Vlastná platnosť';
  }
  function adminLevelChips(selected,attr='admin-plan-chip',includeExpired=true){
    const ids=includeExpired?accessContexts:membershipHierarchy;
    return `<div class="admin-level-chips">${ids.map(id=>`<button type="button" class="admin-level-chip${id===selected?' active':''}${id==='goat'?' top-tier':''}" data-${attr}="${escapeHtml(id)}"><span>${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</span>${id==='goat'?'<small>TOP</small>':''}</button>`).join('')}</div>`;
  }
  function renderAdminLayout(){
    const levelLabel=accessLabel(state.adminPlan);
    const hub=dailyHubConfig();
    const detailCfg=matchDetailAccessConfig();
    const resultsAccess=elements()?.SIDEBAR_RESULTS?.access||{};
    const resultPlanChecks=membershipHierarchy.map(id=>{const label=String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,'');const enabled=String(resultsAccess?.[id]||'active').toLowerCase()==='active';return `<label class="admin-detail-plan-check"><input type="checkbox" data-admin-results-plan="${escapeHtml(id)}" ${enabled?'checked':''}><span>${escapeHtml(label)}</span></label>`;}).join('');
    const historyCfg=state.ui?.dashboard?.results_history_window||{};
    const historyChoices=[['24h','24H'],['48h','48H'],['3d','3D'],['7d','7D'],['14d','14D'],['30d','30D'],['all','ALL']];
    const resultWindows=membershipHierarchy.map(id=>{const label=String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,'');const current=String(historyCfg[id]||(id==='rookie'?'24h':id==='pro'?'48h':'all')).toLowerCase();return `<label><span>${escapeHtml(label)}</span><select data-admin-results-window="${escapeHtml(id)}">${historyChoices.map(([value,text])=>`<option value="${value}"${value===current?' selected':''}>${text}</option>`).join('')}</select></label>`;}).join('');
    const resultsSettings=`<div class="admin-detail-access-card admin-results-access-card"><header><div><small>VÝSLEDKY</small><h3>Prístup a história podľa levelu</h3><p>Vypnutý level stále uvidí kartu Výsledky so zámkom a informáciou o najnižšom potrebnom leveli. Rozsah histórie nastavíš samostatne.</p></div></header><div class="admin-detail-plan-grid">${resultPlanChecks}</div><div class="admin-results-window-grid"><strong>Dĺžka zobrazenej histórie</strong>${resultWindows}</div><small class="admin-detail-help">Možnosti: 24H · 48H · 3D · 7D · 14D · 30D · ALL. ADMIN má vždy plný prístup.</small></div>`;
    const detailPlanChecks=membershipHierarchy.map(id=>{const label=String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,'');return `<label class="admin-detail-plan-check"><input type="checkbox" data-admin-detail-plan="${escapeHtml(id)}" ${detailCfg?.plans?.[id]!==false?'checked':''}><span>${escapeHtml(label)}</span></label>`;}).join('');
    const detailSectionSelect=(section,label)=>{const current=matchDetailSectionMinimum(section);return `<label><span>${escapeHtml(label)}</span><select data-admin-detail-section="${escapeHtml(section)}">${membershipHierarchy.map(id=>`<option value="${id}"${id===current?' selected':''}>${escapeHtml(String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,''))}</option>`).join('')}</select></label>`;};
    const detailSettings=`<div class="admin-detail-access-card"><header><div><small>DETAIL ZÁPASU</small><h3>Prístup ku karte detailu</h3><p>Jednoducho zapni, ktoré levely môžu otvoriť detail. Vnútri karty môžeš jednotlivé sekcie stupňovať minimálnym levelom.</p></div></header><div class="admin-detail-plan-grid">${detailPlanChecks}</div><div class="admin-detail-section-grid"><strong>Minimálny level pre sekcie</strong>${detailSectionSelect('statistics','Forma & povrch')}${detailSectionSelect('radar','Model víťaza')}${detailSectionSelect('history','História / H2H')}</div><small class="admin-detail-help">Prehľad ostáva základnou sekciou. ADMIN má vždy plný prístup. Neprístupná sekcia sa v detaile zobrazí ako zámok s najnižším potrebným levelom.</small></div>`;
    const rows=['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'].map(tab=>{
      const tc=hub.tabs?.[tab]||{},rule=tc.plans?.[state.adminPlan]||{},globalOn=tc.enabled!==false;
      const visible=String(rule.visible_rows??0).toUpperCase(),display=String(rule.display_state||((rule.tab_enabled!==false)?'active':'hidden'));
      const selection=String(rule.selection_mode||'first'),overrides=rule.row_overrides&&typeof rule.row_overrides==='object'?rule.row_overrides:{};
      const rowOverrides=[1,2,3,4,5,6,7,8,9,10].map(position=>{const mode=String(overrides[position]||'active');return `<label><span>${position}</span><select data-admin-hub-row-state="${position}" data-admin-hub-tab="${tab}"><option value="active"${mode==='active'?' selected':''}>SHOW</option><option value="blurred"${mode==='blurred'?' selected':''}>BLUR</option><option value="hidden"${mode==='hidden'?' selected':''}>HIDE</option></select></label>`;}).join('');
      return `<div class="admin-daily-matrix-row${globalOn?'':' is-global-off'}${display==='hidden'?' is-level-off':''}" data-admin-hub-tab-card="${tab}">
        <div class="admin-daily-category"><strong>${escapeHtml(dailyHubTabLabel(tab))}</strong><small>${globalOn?'Na webe':'Globálne vypnuté'}</small></div>
        <label class="admin-switch-compact"><input type="checkbox" data-admin-hub-global-field="enabled" data-admin-hub-tab="${tab}" ${globalOn?'checked':''}><span>Na webe</span></label>
        <label class="admin-daily-row-count"><span>Prístup pre ${escapeHtml(levelLabel)}</span><select data-admin-hub-field="display_state" data-admin-hub-tab="${tab}" ${!globalOn?'disabled':''}><option value="active"${display==='active'?' selected':''}>ZOBRAZIŤ</option><option value="blurred"${display==='blurred'?' selected':''}>ZAMKNÚŤ</option><option value="hidden"${display==='hidden'?' selected':''}>SKRYŤ</option></select></label>
        <label class="admin-daily-row-count"><span>Odomknuté riadky</span><select data-admin-hub-field="visible_rows" data-admin-hub-tab="${tab}" ${!globalOn||display!=='active'?'disabled':''}>${[0,1,2,3,4,5,6,7,8,9,10,'ALL'].map(v=>`<option value="${v}"${visible===String(v).toUpperCase()?' selected':''}>${String(v).toUpperCase()==='ALL'?'VŠETKY':v}</option>`).join('')}</select></label><label class="admin-daily-row-count"><span>Výber</span><select data-admin-hub-field="selection_mode" data-admin-hub-tab="${tab}" ${!globalOn||display!=='active'?'disabled':''}><option value="first"${selection==='first'?' selected':''}>PRVÉ</option><option value="stable_random"${selection==='stable_random'?' selected':''}>NÁHODNÉ / DEŇ</option></select></label><label class="admin-switch-compact"><input type="checkbox" data-admin-hub-field="blur_remaining" data-admin-hub-tab="${tab}" ${rule.blur_remaining!==false?'checked':''} ${!globalOn||display==='hidden'?'disabled':''}><span>Zamknúť zvyšok</span></label><label class="admin-switch-compact"><input type="checkbox" data-admin-hub-field="see_all" data-admin-hub-tab="${tab}" ${rule.see_all===true?'checked':''} ${!globalOn||display!=='active'?'disabled':''}><span>Celá ponuka</span></label><details class="admin-row-overrides admin-row-advanced"><summary><span>Pokročilé nastavenia</span><small>Ručné pravidlá pre jednotlivé pozície</small></summary><div class="admin-row-advanced-body"><strong>Riadky 1–10 · SHOW / BLUR / HIDE</strong><div>${rowOverrides}</div><small>BLUR a HIDE neposielajú citlivý obsah do prehliadača. Pri NÁHODNÉ / DEŇ zostáva výber stabilný celý deň pre konkrétny účet.</small></div></details>
      </div>`;
    }).join('');
    return `<section class="admin-ux-section admin-daily-settings-v687">
      <div class="admin-admin-guide">
        <div><span>1</span><strong>Vyber úroveň účtu</strong><small>Všetky pravidlá nižšie upravuješ iba pre zvolený level</small></div>
        <div><span>2</span><strong>Nastav dennú ponuku</strong><small>Urči, ktoré karty vidí a koľko riadkov má odomknutých</small></div>
        <div><span>3</span><strong>Publikuj zmeny</strong><small>Až tlačidlo Publikovať prenesie konfiguráciu na live web</small></div>
      </div>
      <div class="admin-level-focus-card">
        <div><small>UPRAVUJEŠ PRÍSTUP PRE</small><strong>${escapeHtml(levelLabel)}</strong><span>Najprv vyber level, potom nastav jeho pravidlá. Globálne vypnutie kategórie ju skryje všetkým.</span></div>
        ${adminLevelChips(state.adminPlan,'admin-plan-chip',true)}
      </div>
      <div class="admin-daily-preset-bar"><div><strong>Rýchle nastavenie pre ${escapeHtml(levelLabel)}</strong><span>Voliteľné. Prepíše iba pravidlá dennej ponuky pre tento level, nie globálne zapnutie kategórií.</span></div><div><button type="button" data-admin-daily-preset="full">Plný prístup</button><button type="button" data-admin-daily-preset="preview3">3 riadky</button><button type="button" data-admin-daily-preset="rookie2">2 náhodné + blur</button><button type="button" data-admin-daily-preset="blurred">Rozmazať panely</button><button type="button" data-admin-daily-preset="hidden">Skryť všetko</button></div></div>
      <div class="admin-daily-matrix-card">
        <header><div><small>DENNÁ PONUKA</small><h3>Čo uvidí ${escapeHtml(levelLabel)}</h3><p>Domovská stránka drží maximálne 10 pozícií. „VŠETKY“ odomkne všetky aktuálne riadky. „Celá ponuka“ dovolí otvoriť rozšírený zoznam.</p></div><button class="btn btn-ghost" type="button" data-admin-action="preview">Náhľad ako ${escapeHtml(levelLabel)}</button></header>
        <div class="admin-daily-matrix-head"><span>Kategória</span><span>Globálne</span><span>Panel</span><span>Riadky</span><span>Výber</span><span>Zvyšok</span></div>
        <div class="admin-daily-matrix">${rows}</div>
        <div class="admin-admin-legend"><span><i class="is-global"></i><b>SHOW</b> = plný obsah</span><span><i class="is-level"></i><b>BLUR</b> = viditeľný premium teaser bez citlivých dát v HTML</span><span><i class="is-lock"></i><b>HIDE</b> = prvok sa pre level nezobrazí</span></div>
      </div>
      ${resultsSettings}
      ${detailSettings}
    </section>`;
  }

  function activeAdminBanners(){
    const count=Math.max(1,Math.min(5,Number(state.ui?.hero_banner?.slot_count)||1));
    return Array.from({length:count},(_,i)=>({
      id:`HERO_BANNER_${i+1}`,
      item:elements()?.[`HERO_BANNER_${i+1}`]||{content:{}}
    }));
  }
  function adminHeroPreviewCard(entry,mode){
    const c=entry.item?.content||{};
    const desktop=safePhotoUrl(c.image_url||'')||'/assets/hero-reference-exact-v680.webp';
    const mobile=safePhotoUrl(c.mobile_image_url||'')||desktop;
    const img=mode==='mobile'?mobile:desktop;
    const eyebrow=Object.prototype.hasOwnProperty.call(c,'eyebrow')?String(c.eyebrow||'').trim():'BLINQ';
    const headline=String(c.headline||'').trim();
    const subtitle=String(c.text||'').trim();
    const copy=c.show_copy===false?'':`<div class="admin-hero-preview-copy">${eyebrow?`<small>${escapeHtml(eyebrow)}</small>`:''}${headline?`<strong>${escapeHtml(headline)}</strong>`:''}${subtitle?`<p>${escapeHtml(subtitle)}</p>`:''}${c.button_text?`<b>${escapeHtml(c.button_text)} →</b>`:''}</div>`;
    return `<div class="lean-admin-preview ${mode}" ${bannerCreativeStyle(c)} data-preview-slot="${escapeHtml(entry.id)}"><img src="${escapeHtml(img)}" alt="" loading="lazy">${copy}</div>`;
  }
  function syncAdminHeroPreview(){
    const stage=document.querySelector('#adminHeroLivePreview');
    if(!stage||state.route!=='admin'||state.adminTab!=='banners')return;
    const entries=activeAdminBanners();
    state.adminPreviewIndex=((state.adminPreviewIndex%entries.length)+entries.length)%entries.length;
    const entry=entries[state.adminPreviewIndex];
    for(const mode of ['desktop','mobile']){
      const host=stage.querySelector(`[data-admin-preview-card="${mode}"]`);
      if(host)host.innerHTML=adminHeroPreviewCard(entry,mode);
    }
    const status=stage.querySelector('[data-admin-preview-status]');
    if(status)status.textContent=`Banner ${state.adminPreviewIndex+1} / ${entries.length} · ${state.adminPreviewPaused?'pozastavené':'živý náhľad'}`;
    const pause=stage.querySelector('[data-admin-preview-pause]');
    if(pause){pause.textContent=state.adminPreviewPaused?'Spustiť':'Pozastaviť';pause.setAttribute('aria-pressed',String(state.adminPreviewPaused));}
    stage.querySelectorAll('[data-admin-preview-dot]').forEach(dot=>{
      const active=Number(dot.dataset.adminPreviewDot)===state.adminPreviewIndex;
      dot.classList.toggle('is-active',active);
      dot.setAttribute('aria-current',String(active));
    });
  }
  function startAdminHeroPreview(){
    if(state.adminPreviewTimer){clearInterval(state.adminPreviewTimer);state.adminPreviewTimer=null;}
    if(state.route!=='admin'||state.adminTab!=='banners'||state.ui?.hero_banner?.auto_rotate===false)return;
    const entries=activeAdminBanners();
    if(entries.length<2||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const seconds=Math.max(3,Math.min(10,Number(state.ui?.hero_banner?.rotation_seconds)||6));
    state.adminPreviewTimer=setInterval(()=>{
      if(document.hidden||state.adminPreviewPaused||state.route!=='admin'||state.adminTab!=='banners')return;
      state.adminPreviewIndex=(state.adminPreviewIndex+1)%activeAdminBanners().length;
      syncAdminHeroPreview();
    },seconds*1000);
  }
  function renderAdminBanners(){
    const heroIds=[1,2,3,4,5].map(i=>`HERO_BANNER_${i}`);
    if(!heroIds.includes(state.selectedElement))state.selectedElement='HERO_BANNER_1';
    const selectedId=state.selectedElement;
    const item=elements()?.[selectedId]||elements()?.HERO_BANNER_1||{};
    const c=item.content=item.content||{};
    const globalHero=state.ui.hero_banner=state.ui.hero_banner||{};
    const activeCount=Math.max(1,Math.min(5,Number(globalHero.slot_count)||1));
    const rotation=Math.max(3,Math.min(10,Number(globalHero.rotation_seconds)||6));
    const entries=activeAdminBanners();
    state.adminPreviewIndex=Math.max(0,Math.min(state.adminPreviewIndex,entries.length-1));
    const previewEntry=entries[state.adminPreviewIndex];
    const hero1=elements()?.HERO_BANNER_1?.content||{};
    const bg=safePhotoUrl(hero1.site_background_url||'')||String(state.presentationConfig?.theme?.background?.image||'/assets/blinq_page_background.webp');
    const effects=['fade-up','fade','slide-down'];
    const tabs=heroIds.map((id,index)=>{
      const slot=elements()?.[id]||{},content=slot.content||{},active=index<activeCount,selected=id===selectedId,ready=Boolean(String(content.image_url||'').trim());
      return `<button type="button" class="admin-hero-tab${selected?' is-selected':''}${active?' is-live':''}${ready?' is-ready':''}" data-admin-element="${id}" aria-pressed="${selected}"><span>0${index+1}</span><strong>Banner ${index+1}</strong><small>${active?'AKTÍVNY':ready?'PRIPRAVENÝ':'NEAKTÍVNY'}</small></button>`;
    }).join('');
    const countOptions=[1,2,3,4,5].map(n=>`<option value="${n}"${n===activeCount?' selected':''}>${n}</option>`).join('');
    const delayOptions=[3,4,5,6,7,8,9,10].map(n=>`<option value="${n}"${n===rotation?' selected':''}>${n} s</option>`).join('');
    const sizes=(values,current,fallback)=>values.map(n=>`<option value="${n}"${n===(Number(current)||fallback)?' selected':''}>${n} px</option>`).join('');
    return `<section class="admin-ux-section lean-admin-banners admin-hero-manager" data-simple-banner="${escapeHtml(selectedId)}">
      <div class="admin-ux-heading"><div><small>BANNERY</small><h2>Hero bannery</h2><p>Nastav text, typografiu, podklady a rotáciu. Živý náhľad beží nezávisle od formulára.</p></div></div>
      <div class="admin-hero-carousel-controls">
        <label><span>Počet aktívnych bannerov</span><select data-admin-hero-count>${countOptions}</select><small>Zvolený počet z piatich pozícií.</small></label>
        <label><span>Interval automatickej zmeny</span><select data-admin-hero-seconds>${delayOptions}</select><small>3 až 10 sekúnd, rovnako ako na webe.</small></label>
        <div class="admin-hero-rotation-status"><i></i><div><strong>${activeCount>1?'Živá rotácia':'Jeden banner'}</strong><small>${activeCount>1?'Náhľad sa prepína, editačný formulár zostáva na vybranom bannere.':'Pridaj druhý aktívny banner pre rotáciu.'}</small></div></div>
      </div>
      <div class="admin-hero-tabs" role="group" aria-label="Vybrať banner na úpravu">${tabs}</div>
      <section class="admin-hero-preview-stage" id="adminHeroLivePreview" aria-label="Živý náhľad carouselu">
        <div class="admin-hero-preview-toolbar"><div><small>ŽIVÝ NÁHĽAD</small><strong data-admin-preview-status>Banner ${state.adminPreviewIndex+1} / ${entries.length} · živý náhľad</strong></div><div class="admin-hero-preview-actions"><button type="button" data-admin-preview-step="-1" aria-label="Predchádzajúci banner">‹</button><button type="button" data-admin-preview-pause aria-pressed="${state.adminPreviewPaused}">${state.adminPreviewPaused?'Spustiť':'Pozastaviť'}</button><button type="button" data-admin-preview-step="1" aria-label="Nasledujúci banner">›</button></div></div>
        <div class="lean-admin-preview-grid"><div><span>Desktop · 1920 × 640</span><div data-admin-preview-card="desktop">${adminHeroPreviewCard(previewEntry,'desktop')}</div></div><div><span>Mobil · 1080 × 720</span><div data-admin-preview-card="mobile">${adminHeroPreviewCard(previewEntry,'mobile')}</div></div></div>
        <div class="admin-hero-preview-dots" aria-label="Pozícia náhľadu">${entries.map((_,i)=>`<button type="button" data-admin-preview-dot="${i}" class="${i===state.adminPreviewIndex?'is-active':''}" aria-current="${i===state.adminPreviewIndex}" aria-label="Zobraziť banner ${i+1}"></button>`).join('')}</div>
      </section>
      <div class="admin-hero-selected-head"><div><small>UPRAVUJEŠ</small><strong>${escapeHtml(item.label||selectedId)}</strong></div><span>${Number(selectedId.split('_').pop())<=activeCount?'V rotácii':'Neaktívny banner'}</span></div>
      <div class="admin-form-section admin-banner-copy-editor"><div class="admin-form-section-title"><strong>Text bannera</strong><span>Prázdne pole zostane skryté. Pôvodný skrytý doplnkový nadpis sa nepoužíva.</span></div><div class="admin-form-grid">
        <label>Popiska <small>(prázdne = skryť)</small><input data-simple-banner-field="eyebrow" value="${escapeHtml(c.eyebrow||'')}"></label>
        <label>Animácia<select data-simple-banner-field="effect">${effects.map(v=>`<option value="${v}"${v===(c.effect||'fade-up')?' selected':''}>${v}</option>`).join('')}</select></label>
        <label class="span-2">Nadpis<input data-simple-banner-field="headline" value="${escapeHtml(c.headline||'')}"></label>
        <label class="span-2">Podnadpis<textarea rows="3" data-simple-banner-field="text">${escapeHtml(c.text||'')}</textarea></label>
        <label>Text tlačidla<input data-simple-banner-field="button_text" value="${escapeHtml(c.button_text||'')}"></label>
        <label>Odkaz<input data-simple-banner-field="link" value="${escapeHtml(c.link||'')}"></label>
      </div></div>
      <div class="admin-form-section admin-banner-typography"><div class="admin-form-section-title"><strong>Veľkosť a farba textu</strong><span>Jednoduchá škála od čiernej po bielu. Platí pre desktop aj mobil, náhľad reaguje hneď.</span></div><div class="admin-banner-type-grid">
        <label><span>Nadpis · veľkosť</span><select data-simple-banner-field="headline_size">${sizes([12,14,16,18,20,24,28,32,36,40,44,48,56,64,72],c.headline_size,36)}</select></label>
        <label><span>Nadpis · farba</span><select data-simple-banner-field="headline_color">${bannerColorOptions(c.headline_color)}</select></label>
        <label><span>Podnadpis · veľkosť</span><select data-simple-banner-field="text_size">${sizes([10,12,14,16,18,20,24,28],c.text_size,14)}</select></label>
        <label><span>Podnadpis · farba</span><select data-simple-banner-field="text_color">${bannerColorOptions(c.text_color)}</select></label>
        <label><span>Popiska · veľkosť</span><select data-simple-banner-field="eyebrow_size">${sizes([8,10,12,14,16,18],c.eyebrow_size,10)}</select></label>
        <label><span>Popiska · farba</span><select data-simple-banner-field="eyebrow_color">${bannerColorOptions(c.eyebrow_color)}</select></label>
      </div></div>
      <div class="admin-form-section admin-banner-image-editor"><div class="admin-form-section-title"><strong>Grafické podklady · Banner ${escapeHtml(selectedId.split('_').pop())}</strong><span>Vlastný desktop a mobilný obrázok bez textu.</span></div><div class="admin-form-grid">
        <label class="span-2">Desktop hero · 1920×640<input data-simple-banner-field="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/hero.webp"></label>
        <label class="span-2">Mobilný hero · 1080×720<input data-simple-banner-field="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="/assets/hero-mobile.webp"></label>
        <label class="admin-toggle-line span-2"><input type="checkbox" data-simple-banner-field="show_copy" ${c.show_copy!==false?'checked':''}><span>Zobraziť text nad obrázkom</span></label>
      </div></div>
      <div class="admin-form-section admin-page-background-editor" data-simple-banner="HERO_BANNER_1"><div class="admin-form-section-title"><strong>Pozadie hlavnej stránky</strong><span>Predvolené je rovnaké zelené tenisové pozadie ako pri prihlásení a loadingu, bez watermarku.</span></div><div class="admin-form-grid">
        <label class="span-2">Background · 1920 × 1080<input data-simple-banner-field="site_background_url" value="${escapeHtml(hero1.site_background_url||bg)}" placeholder="/assets/blinq_page_background.webp"></label>
      </div></div>
      <div class="admin-banner-save-note"><span></span><strong>Zmeny sú zatiaľ iba v koncepte.</strong><small>Po kontrole klikni hore na Publikovať.</small></div>
    </section>`;
  }
  function userDateValue(value){ if(!value)return ''; const d=new Date(value); if(Number.isNaN(d.getTime()))return ''; const pad=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
  function adminTelegramIcon(){
    return `<svg class="admin-tg-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21.5 3.3 18.3 19c-.24 1.11-.88 1.38-1.79.86l-4.87-3.59-2.35 2.26c-.26.26-.48.48-.98.48l.35-4.96 9.02-8.15c.39-.35-.09-.55-.61-.2L5.92 12.72l-4.8-1.5c-1.04-.33-1.06-1.04.22-1.54L20.1 2.45c.87-.32 1.63.2 1.4.85Z"/></svg>`;
  }
  function adminTelegramLabel(user){
    const nick=String(user?.telegram_nick||'').trim();
    return nick?`<span class="admin-tg-nick">${adminTelegramIcon()}<b>${escapeHtml(nick)}</b></span>`:'<span class="admin-tg-missing">Bez TG nicku</span>';
  }
  function adminTgEligible(user){
    if(typeof user?.tg_private_eligible==='boolean')return user.tg_private_eligible;
    return ['active','lifetime'].includes(String(user?.status||'').toLowerCase())&&['elite','legend','goat'].includes(String(user?.plan||'').toLowerCase());
  }
  function adminTgAction(user){
    const explicit=String(user?.tg_private_action||'').toLowerCase();
    if(['add','remove','ok','none'].includes(explicit))return explicit;
    const eligible=adminTgEligible(user),member=Boolean(user?.tg_private_member);
    return eligible&&!member?'add':!eligible&&member?'remove':eligible&&member?'ok':'none';
  }
  function adminTgActionLabel(user){
    const action=adminTgAction(user);
    const labels={add:'PRIDAŤ',remove:'ODSTRÁNIŤ',ok:'OK',none:'—'};
    return `<span class="admin-tg-action is-${action}">${labels[action]}</span>`;
  }
  function adminUserFilterState(){
    const defaults={q:'',plan:'all',status:'all',sort:'email'};
    state.adminUserFilters={...defaults,...(state.adminUserFilters||{})};
    return state.adminUserFilters;
  }
  function adminUserDateMs(value){const ms=value?new Date(value).getTime():NaN;return Number.isFinite(ms)?ms:null;}
  function adminUserMatchesFilters(user){
    const f=adminUserFilterState(),status=String(user?.status||'').toLowerCase(),plan=String(user?.plan||'').toLowerCase(),nick=String(user?.telegram_nick||''),search=`${user?.email||''} ${nick} ${user?.id||''}`.toLowerCase(),q=String(f.q||'').trim().toLowerCase();
    if(q&&!search.includes(q))return false;
    if(f.plan!=='all'&&plan!==f.plan)return false;
    if(f.status!=='all'&&status!==f.status)return false;
    return true;
  }
  function adminSortedUsers(users){
    const list=[...(users||[])],sort=adminUserFilterState().sort;
    const text=(u,k)=>String(u?.[k]||'').toLowerCase();
    list.sort((a,b)=>{
      if(sort==='telegram')return text(a,'telegram_nick').localeCompare(text(b,'telegram_nick'))||text(a,'email').localeCompare(text(b,'email'));
      if(sort==='level')return membershipHierarchy.indexOf(String(b?.plan||''))-membershipHierarchy.indexOf(String(a?.plan||''))||text(a,'email').localeCompare(text(b,'email'));
      if(sort==='expiry'){const av=adminUserDateMs(a?.expires_at)??Number.MAX_SAFE_INTEGER,bv=adminUserDateMs(b?.expires_at)??Number.MAX_SAFE_INTEGER;return av-bv;}
      if(sort==='last-login')return (adminUserDateMs(b?.last_sign_in_at)||0)-(adminUserDateMs(a?.last_sign_in_at)||0);
      return text(a,'email').localeCompare(text(b,'email'));
    });
    return list;
  }
  function adminFilteredUsers(){return adminSortedUsers(Array.isArray(state.adminUsers)?state.adminUsers:[]).filter(adminUserMatchesFilters);}
  function adminApplyUserFilters(){
    const visible=new Set(adminFilteredUsers().map(u=>String(u.id)));
    const list=$('routePanel')?.querySelector('.admin-simple-user-list');
    list?.querySelectorAll('.admin-simple-user-row[data-admin-user]').forEach(row=>{
      row.hidden=!visible.has(String(row.dataset.adminUser));
    });
    const count=$('adminFilteredCount');if(count)count.textContent=String(visible.size);
    const empty=$('adminUserFilterEmpty');if(empty)empty.hidden=visible.size!==0;
  }

  function renderAdminUserEditor(user){
    if(!user)return `<div class="admin-user-empty admin-user-empty-v687"><strong>Vyber používateľa</strong><span>Klikni na účet vľavo. Potom môžeš upraviť e-mail, Telegram nickname, level a platnosť alebo mu poslať obnovu hesla.</span></div>`;
    const self=String(user.id)===String(state.feed?.account?.id),isAdmin=String(user.role||'').toLowerCase()==='admin'||String(user.plan||'').toLowerCase()==='admin',selectedPlan=!isAdmin&&user.plan&&!['expired','admin'].includes(user.plan)?String(user.plan):'',status=String(user.status||'expired').toLowerCase();
    const enabledPlans=membershipHierarchy.filter(id=>state.ui?.plans?.[id]?.enabled!==false);
    const planButtons=enabledPlans.map(id=>{const active=id===selectedPlan;return `<button type="button" class="admin-simple-plan${active?' active':''}${id==='goat'?' top-tier':''}" data-admin-user-plan="${escapeHtml(id)}"><b>${escapeHtml(String(state.ui?.plans?.[id]?.label||id.toUpperCase()).replace(/^BlinQ\s+/i,''))}</b><small>${escapeHtml(planTermLabel(id))}</small></button>`;}).join('');
    const currentExpiry=status==='lifetime'?'Doživotne':selectedPlan==='rookie'?'Bez časového obmedzenia':user.expires_at?`${fmtDate(user.expires_at)} · ${fmtTime(user.expires_at)}`:'Bez platnosti';
    return `<form id="adminUserForm" class="admin-user-editor admin-user-editor-simple">
      <div class="admin-user-simple-head"><div><small>UPRAVIŤ ÚČET</small><h3>${escapeHtml(user.telegram_nick||user.email||'Používateľ')}</h3><p>${escapeHtml(user.email||'')}</p></div><span class="admin-current-access">${escapeHtml(user.plan_label||user.plan||'Bez plánu')} · ${escapeHtml(status)}</span></div>
      <section class="admin-simple-card"><header><div><span>01</span><div><strong>Údaje</strong><small>E-mail a Telegram</small></div></div></header><div class="admin-simple-fields">
        <label>E-mail<input id="adminUserEmail" type="email" required maxlength="254" value="${escapeHtml(user.email||'')}"></label>
        <label><span class="admin-field-label-with-icon">${adminTelegramIcon()} Telegram nickname</span><input id="adminUserTelegram" maxlength="33" value="${escapeHtml(user.telegram_nick||'')}" placeholder="@nickname"></label>
      </div><div class="admin-user-meta-line"><span>E-mail ${user.email_verified?'overený':'neoverený'}</span><span>Vytvorený ${escapeHtml(fmtDate(user.created_at))}</span><span>Posledné prihlásenie ${escapeHtml(fmtDate(user.last_sign_in_at))}</span></div>
      <div class="admin-password-reset-row"><div><strong>Obnova hesla</strong><small>Pošle sa e-mail s linkom</small></div><button class="btn btn-ghost" type="button" data-admin-action="reset-user-password">Poslať link na obnovu hesla</button></div></section>
      ${isAdmin?`<section class="admin-simple-card admin-admin-account-note"><header><div><span>02</span><div><strong>Admin účet</strong><small>Tento interný účet zostáva ADMIN a nepoužíva členský level ani expiráciu</small></div></div></header></section>`:`<section class="admin-simple-card"><header><div><span>02</span><div><strong>Level</strong><small>Prístup a platnosť</small></div></div><b>Teraz: ${escapeHtml(currentExpiry)}</b></header>
        <input id="adminUserPlan" type="hidden" value="${escapeHtml(selectedPlan)}"><div class="admin-simple-plans">${planButtons}</div>
        <div class="admin-simple-expiry"><label>Platnosť do<input id="adminUserExpires" type="datetime-local" value="${escapeHtml(userDateValue(user.expires_at))}" ${selectedPlan==='rookie'?'disabled':''}></label><div class="admin-term-actions"><button type="button" data-admin-action="apply-default-term">Použiť predvolenú dĺžku</button><button type="button" data-admin-action="extend-default-term">Predĺžiť o predvolenú dĺžku</button></div></div>
        <div class="admin-expiry-shortcuts admin-expiry-shortcuts-simple"><span>Rýchlo pridať</span><button type="button" data-admin-expiry-days="30">+30 dní</button><button type="button" data-admin-expiry-days="90">+90 dní</button><button type="button" data-admin-expiry-days="180">+180 dní</button><button type="button" data-admin-expiry-days="365">+365 dní</button></div>
      </section>`}
      <div class="admin-user-savebar admin-user-savebar-simple"><p id="adminUserMessage" class="form-message"></p><button class="btn btn-primary" type="submit">Uložiť účet</button></div>
      ${self?'':`<details class="admin-danger-zone"><summary>Nebezpečná zóna</summary><div><div><strong>Zmazať účet</strong><small>Natrvalo odstráni Firebase účet a jeho profilové údaje</small></div><button type="button" data-admin-action="delete-user">Zmazať účet</button></div></details>`}
    </form>`;
  }
  function renderAdminAccounts(){
    const users=Array.isArray(state.adminUsers)?state.adminUsers:[],f=adminUserFilterState(),sorted=adminSortedUsers(users),filtered=adminFilteredUsers();
    const countActive=users.filter(u=>['active','lifetime'].includes(String(u.status||'').toLowerCase())).length,countSuspended=users.filter(u=>String(u.status||'').toLowerCase()==='suspended').length;
    if(state.adminUsersError&&!state.adminUsersLoading&&!users.length)return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>POUŽÍVATELIA</small><h2>Správa účtov</h2><p>Jednoduchá správa používateľov BlinQ</p></div></div><div class="admin-accounts-unavailable"><span class="admin-accounts-unavailable-icon">!</span><div><strong>Účty sa nenačítali — nejde o nulový počet účtov.</strong><p>${escapeHtml(state.adminUsersError)}</p></div><button class="btn btn-ghost" type="button" data-admin-action="diagnostics">Diagnostika</button></div></section>`;
    const rows=state.adminUsersLoading?'<div class="state-card">Načítavam účty…</div>':sorted.length?sorted.map(user=>{const identity=user.telegram_nick||user.email||'Používateľ',initial=String(identity).replace(/^@/,'').trim().charAt(0).toUpperCase()||'U';return `<button type="button" class="admin-simple-user-row${state.adminSelectedUser?.id===user.id?' selected':''}" data-admin-user="${escapeHtml(user.id)}"><span class="admin-simple-user-identity"><i class="admin-simple-avatar">${escapeHtml(initial)}</i><span class="admin-simple-user-main"><b>${escapeHtml(identity)}</b><small>${escapeHtml(user.telegram_nick?user.email||'—':'Bez Telegram nicku')}</small></span></span><span class="admin-simple-level is-${escapeHtml(String(user.plan||'expired'))}">${escapeHtml(String(user.plan_label||user.plan||'—').replace(/^BlinQ\s+/i,''))}</span><span class="admin-simple-expire">${escapeHtml(user.plan==='rookie'&&user.status==='active'?'Bez limitu':user.status==='lifetime'?'Doživotne':fmtDate(user.expires_at))}</span><span class="admin-simple-state is-${escapeHtml(String(user.status||'expired').toLowerCase())}">${escapeHtml(user.status||'—')}</span><span class="admin-simple-edit">›</span></button>`;}).join(''):'<div class="admin-user-empty">Nie sú načítané žiadne účty</div>';
    const levelOptions=['all',...membershipHierarchy,'admin'].map(v=>`<option value="${v}"${f.plan===v?' selected':''}>${v==='all'?'Všetky levely':v.toUpperCase()}</option>`).join('');
    const statusOptions=['all','active','expired','lifetime','suspended'].map(v=>`<option value="${v}"${f.status===v?' selected':''}>${v==='all'?'Všetky stavy':v.toUpperCase()}</option>`).join('');
    return `<section class="admin-ux-section admin-accounts-simple"><div class="admin-ux-heading"><div><small>POUŽÍVATELIA</small><h2>Správa účtov</h2><p>Nájdi účet, uprav prístup a ulož.</p></div><button class="btn btn-ghost icon-text-btn" type="button" data-admin-action="refresh-users"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15.5 6.2A6 6 0 1 0 16 12"></path><path d="M15.5 2.8v3.8h-3.8"></path></svg><span>Obnoviť</span></button></div>
      ${state.adminUsersWarning?`<div class="admin-note admin-note-warning"><strong>Profilové úložisko je v náhradnom režime</strong><span>Levely fungujú cez Firebase. Niektoré profilové zmeny môžu čakať na dostupné úložisko.</span></div>`:''}
      <div class="admin-simple-stats"><span><b>${users.length}</b> účtov</span><span><b>${countActive}</b> aktívnych</span>${countSuspended?`<span><b>${countSuspended}</b> pozastavených</span>`:''}</div>
      <div class="admin-simple-toolbar"><label class="search-box"><span class="admin-search-icon" aria-hidden="true"><svg viewBox="0 0 20 20"><circle cx="8.5" cy="8.5" r="5"></circle><path d="m12.2 12.2 4 4"></path></svg></span><input id="adminUserSearch" type="search" value="${escapeHtml(f.q)}" placeholder="Hľadať e-mail, Telegram alebo UID"></label><label>Level<select id="adminUserLevelFilter">${levelOptions}</select></label><label>Stav<select id="adminUserStatusFilter">${statusOptions}</select></label><label>Zoradiť<select id="adminUserSort"><option value="email"${f.sort==='email'?' selected':''}>E-mail</option><option value="telegram"${f.sort==='telegram'?' selected':''}>Telegram</option><option value="level"${f.sort==='level'?' selected':''}>Level</option><option value="expiry"${f.sort==='expiry'?' selected':''}>Najbližšia expirácia</option><option value="last-login"${f.sort==='last-login'?' selected':''}>Posledné prihlásenie</option></select></label><span>Zobrazených <b id="adminFilteredCount">${filtered.length}</b></span></div>
      <div class="admin-accounts-split admin-accounts-split-v22${state.adminSelectedUser?' has-selection':' no-selection'}"><div class="admin-simple-user-table"><div class="admin-simple-user-head"><span>Používateľ</span><span>Level</span><span>Platnosť</span><span>Stav</span><span></span></div><div class="admin-simple-user-list">${rows}${!state.adminUsersLoading&&users.length?`<div id="adminUserFilterEmpty" class="admin-filter-empty"${filtered.length?" hidden":""} role="status">Žiadne účty nezodpovedajú zvoleným filtrom.</div>`:""}</div></div><div class="admin-simple-user-editor-wrap">${renderAdminUserEditor(state.adminSelectedUser)}</div></div>
    </section>`;
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

  async function loadAdminInsights(force=false){
    const generation=feedGeneration;
    if(state.adminInsightsLoading||(!force&&Array.isArray(state.adminInsights)))return;
    state.adminInsightsLoading=true;state.adminInsightsError='';rerenderAdmin();
    try{const data=await BlinqAuth.adminInsights();if(generation!==feedGeneration)return;state.adminInsights=Array.isArray(data?.items)?data.items:[];}
    catch(error){if(generation!==feedGeneration)return;state.adminInsights=[];state.adminInsightsError=error.status===503?'INFO/LIVE história nemá trvalé úložisko. Nastav BLINQ_STORAGE_CONNECTION_STRING na existujúci Azure Storage účet (alebo zapni Firestore).':error.message;}
    finally{if(generation===feedGeneration){state.adminInsightsLoading=false;rerenderAdmin();}}
  }
  function adminInsightDraft(){
    const editing=(state.adminInsights||[]).find(row=>String(row.id)===String(state.adminInsightEditingId));
    if(editing)return editing;
    const cfg=notificationAudienceConfig();
    return {title:'',body:'',type:'vip',priority:'normal',levels:[...cfg.info_default_levels],link:'',link_label:'',match_id:'',active:true,pinned:false,active_from:'',active_until:''};
  }
  function adminDatetimeValue(value){const text=String(value||'');return text?text.replace('Z','').slice(0,16):'';}
  function adminAudiencePresetLevels(preset){
    if(preset==='all'||preset==='rookie+')return [...membershipHierarchy];
    if(preset==='live-default')return membershipLevelsFrom(notificationAudienceConfig().live_min_level);
    if(preset==='goat')return ['goat'];
    const min=String(preset||'').replace('+','').toLowerCase();return membershipHierarchy.includes(min)?membershipLevelsFrom(min):[];
  }
  function syncAdminInsightAudienceForType(form,reset=false){
    if(!form)return;const live=String(form.querySelector('#adminInsightType')?.value||'vip')==='alert';const cfg=notificationAudienceConfig(),liveLevels=new Set(membershipLevelsFrom(cfg.live_min_level));
    const nodes=[...form.querySelectorAll('input[name="insight_level"]')];
    nodes.forEach(node=>{node.disabled=live?!liveLevels.has(node.value):false;if(node.disabled)node.checked=false;});
    if(reset){const wanted=new Set(live?[...liveLevels]:notificationAudienceConfig().info_default_levels);nodes.forEach(node=>{node.checked=wanted.has(node.value)&&!node.disabled;});}
    const hint=form.querySelector('[data-insight-audience-hint]');if(hint){const liveLabel=String(upgradePlanLabel(cfg.live_min_level)||cfg.live_min_level).replace(/^BlinQ\s+/i,'').toUpperCase();hint.textContent=live?`LIVE rešpektuje globálne minimum ${liveLabel}. Pre konkrétnu správu môžeš publikum iba zúžiť.`:`INFO publikum určuješ pri každej správe samostatne. VŠETCI zahŕňa FREE, PRO, ELITE, LEGEND aj GOAT.`;}
  }
  function renderAdminInsights(){
    const item=adminInsightDraft(),levels=Array.isArray(item.levels)?item.levels:[];const list=Array.isArray(state.adminInsights)?state.adminInsights:[];
    const notificationCfg=notificationAudienceConfig(),liveMin=notificationCfg.live_min_level,liveLevels=membershipLevelsFrom(liveMin),liveLabel=String(upgradePlanLabel(liveMin)||liveMin).replace(/^BlinQ\s+/i,'').toUpperCase(),infoLabel=String(upgradePlanLabel(infoMin)||infoMin).replace(/^BlinQ\s+/i,'').toUpperCase();
    const itemIsLive=String(item.type||'vip')==='alert';
    const allowed=new Set(notificationCfg.editable_levels||membershipHierarchy);
    const allLevels=membershipHierarchy.filter(level=>allowed.has(level));
    const selectedLevels=new Set(levels.length?levels:(itemIsLive?liveLevels:notificationCfg.info_default_levels));
    const levelChecks=allLevels.map(level=>{const disabled=itemIsLive&&!liveLevels.includes(level);return `<label class="admin-insight-level${disabled?' is-disabled':''}"><input type="checkbox" name="insight_level" value="${level}" ${selectedLevels.has(level)&&!disabled?'checked':''} ${disabled?'disabled':''}><span>${escapeHtml(String(state.ui?.plans?.[level]?.label||level).replace(/^BlinQ\s+/i,''))}</span></label>`;}).join('');
    const rows=list.map(row=>`<article class="admin-insight-row ${row.active===false?'is-inactive':''} priority-${escapeHtml(row.priority||'normal')}"><div><span>${escapeHtml(insightTypeLabel(row.type))}${row.pinned?' · PIN':''}</span><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml(row.body)}</p><small>${escapeHtml(insightAudienceText(row.levels))} · ${escapeHtml(row.created_at?fmtDate(row.created_at)+' '+fmtTime(row.created_at):'')} · ${Number(row.read_count)||0} prečítaní</small></div><div class="admin-insight-row-actions"><button type="button" class="btn btn-ghost" data-admin-action="insight-edit" data-insight-id="${escapeHtml(row.id)}">Upraviť</button><button type="button" class="btn btn-ghost danger" data-admin-action="insight-delete" data-insight-id="${escapeHtml(row.id)}">Zmazať</button></div></article>`).join('');
    const radar=state.adminLiveRadarStatus||{},radarTone=radar.error?' is-error':radar.ok?' is-ok':'',adminSet2=liveRadarSet2Stats(radar);
    const primeEligible=Number(radar.prime_eligible??radar.eligible_prime_pool)||0,primeTotal=Number(radar.prime_total??radar.prime_pool)||0;
    const radarText=state.adminLiveRadarLoading?'Kontrolujem live zápasy…':radar.error?String(radar.error):radar.scanned_at?`Posledný scan ${fmtTime(radar.scanned_at)} · PRIME ${primeEligible}/${primeTotal} · live ${Number(radar.live_events)||0} · kandidáti ${Array.isArray(radar.candidates)?radar.candidates.length:Number(radar.candidates)||0} · signály ${Array.isArray(radar.signals)?radar.signals.length:Number(radar.signals)||0} · 2. set LIVE kurz ${adminSet2.priced} · value ${adminSet2.eligible}${radar.provider_skipped_reason?' · provider preskočený: bez vhodného PRIME':''} · nové ${Number(radar.new_alerts??radar.created)||0}`:'Automatický radar beží na serveri. Tu ho vieš kedykoľvek otestovať ručne.';
    const liveOptions=membershipHierarchy.map(level=>`<option value="${level}"${level===liveMin?' selected':''}>${escapeHtml(String(state.ui?.plans?.[level]?.label||level).replace(/^BlinQ\s+/i,'').toUpperCase())}+</option>`).join('');
    const infoOptions=membershipHierarchy.map(level=>`<option value="${level}"${level===infoMin?' selected':''}>${escapeHtml(String(state.ui?.plans?.[level]?.label||level).replace(/^BlinQ\s+/i,'').toUpperCase())}+</option>`).join('');
    const audiencePresets=[['all','VŠETCI'],['pro+','PRO+'],['elite+','ELITE+'],['legend+','LEGEND+'],['goat','GOAT']].map(([value,label])=>`<button type="button" class="btn btn-ghost" data-admin-action="insight-audience-preset" data-audience-preset="${value}">${label}</button>`).join('');
    return `<section class="admin-ux-section admin-insights-section"><div class="admin-ux-heading"><div><small>SPRÁVY & LIVE</small><h2>Info & Comeback LIVE</h2><p>LIVE má globálne minimum prístupu. INFO má publikum pri každej správe samostatne.</p></div><button type="button" class="btn btn-ghost" data-admin-action="insight-new">Nová správa</button></div>${state.adminInsightsError?`<div class="admin-runtime-note is-error"><strong>Feed nie je dostupný</strong><span>${escapeHtml(state.adminInsightsError)}</span></div>`:''}<div class="admin-notification-access-grid"><div class="admin-live-access-rule"><div><small>PREDVOLENÉ INFO PUBLIKUM</small><strong>Predvolené INFO od ${escapeHtml(infoLabel)}</strong><span>Toto nastaví predvolený rozsah pri novej INFO správe. Konkrétne publikum môžeš potom vybrať ručne vrátane FREE.</span></div><label><span>Predvolene od levelu</span><select id="adminInfoMinLevel">${infoOptions}</select></label><button class="btn btn-primary" type="button" data-admin-action="save-info-access">Uložiť INFO predvoľbu</button></div><div class="admin-live-access-rule"><div><small>PRÍSTUP K LIVE</small><strong>Comeback LIVE od ${escapeHtml(liveLabel)}</strong><span>Automatický radar, ručné LIVE správy aj zámok v headeri používajú toto pravidlo. ADMIN má vždy plný prístup.</span></div><label><span>Minimálny level</span><select id="adminLiveMinLevel">${liveOptions}</select></label><button class="btn btn-primary" type="button" data-admin-action="save-live-access">Uložiť LIVE pravidlo</button></div></div><div class="admin-live-radar-card${radarTone}"><div><small>COMEBACK LIVE RADAR</small><strong>PRIME pool → prehratý 1. set → potvrdený návrat</strong><span>${escapeHtml(radarText)}</span></div><button type="button" class="btn btn-ghost" data-admin-action="live-radar-scan" ${state.adminLiveRadarLoading?'disabled':''}>${state.adminLiveRadarLoading?'Skenujem…':'Scan LIVE teraz'}</button></div><div class="admin-insights-grid"><form id="adminInsightForm" class="admin-insight-composer"><div class="admin-insight-composer-head"><div><small>${item.id?'UPRAVIŤ':'NOVÁ SPRÁVA'}</small><h3>${item.id?escapeHtml(item.title):'Napíš INFO alebo ručné LIVE upozornenie'}</h3></div><span>${escapeHtml(insightAudienceText([...selectedLevels]))}</span></div><label>Nadpis<input id="adminInsightTitle" maxlength="140" required value="${escapeHtml(item.title||'')}"></label><label>Správa<textarea id="adminInsightBody" maxlength="4000" required rows="7">${escapeHtml(item.body||'')}</textarea></label><div class="admin-form-grid"><label>Typ<select id="adminInsightType"><option value="vip"${String(item.type||'vip')==='vip'?' selected':''}>INFO</option><option value="alert"${item.type==='alert'?' selected':''}>LIVE</option></select></label><label>Priorita<select id="adminInsightPriority"><option value="normal"${item.priority==='normal'?' selected':''}>Normal</option><option value="important"${item.priority==='important'?' selected':''}>Important</option><option value="critical"${item.priority==='critical'?' selected':''}>Critical</option></select></label></div><fieldset class="admin-insight-audience"><legend>Publikum</legend><div>${levelChecks}</div><div class="admin-insight-audience-presets">${audiencePresets}<button type="button" class="btn btn-ghost" data-admin-action="insight-audience-preset" data-audience-preset="live-default">LIVE PRAVIDLO</button></div><small data-insight-audience-hint>${itemIsLive?`LIVE rešpektuje globálne minimum ${escapeHtml(liveLabel)}. Pre konkrétnu správu môžeš publikum iba zúžiť.`:`INFO publikum určuješ pri každej správe samostatne. VŠETCI zahŕňa ROOKIE, PRO, ELITE, LEGEND aj GOAT.`}</small></fieldset><div class="admin-form-grid"><label>Event ID / zápas (voliteľné)<input id="adminInsightMatchId" value="${escapeHtml(item.match_id||'')}"></label><label>Text odkazu<input id="adminInsightLinkLabel" maxlength="80" value="${escapeHtml(item.link_label||'')}"></label><label class="span-2">Odkaz (voliteľné)<input id="adminInsightLink" value="${escapeHtml(item.link||'')}"></label><label>Aktívne od<input id="adminInsightFrom" type="datetime-local" value="${escapeHtml(adminDatetimeValue(item.active_from))}"></label><label>Aktívne do<input id="adminInsightUntil" type="datetime-local" value="${escapeHtml(adminDatetimeValue(item.active_until))}"></label></div><div class="admin-insight-flags"><label><input id="adminInsightActive" type="checkbox" ${item.active!==false?'checked':''}> Aktívna</label><label><input id="adminInsightPinned" type="checkbox" ${item.pinned?'checked':''}> Pripnúť hore</label></div><div class="admin-insight-actions"><button class="btn btn-primary" type="submit">${item.id?'Uložiť':'Publikovať'}</button>${item.id?'<button class="btn btn-ghost" type="button" data-admin-action="insight-new">Zrušiť</button>':''}<span id="adminInsightMessage"></span></div></form><div class="admin-insight-list"><div class="admin-subsection-heading"><div><strong>Publikované</strong><span>${state.adminInsightsLoading?'Načítavam…':`${list.length} správ`}</span></div></div>${state.adminInsightsLoading?'<div class="admin-note"><strong>Načítavam…</strong></div>':rows||'<div class="admin-note"><strong>Zatiaľ žiadne správy</strong><span>INFO sa zobrazí iba vybranému publiku; LIVE navyše rešpektuje globálny minimálny level.</span></div>'}</div></div></section>`;
  }
  function auditDiffLabel(item){
    const before=item?.before||{},after=item?.after||{};const changes=[];
    ['plan','status','expires_at','role','tg_private_member'].forEach(key=>{if(String(before[key]??'')!==String(after[key]??''))changes.push(`${key}: ${before[key]??'—'} → ${after[key]??'—'}`);});
    if(item?.action==='account_admin_metadata_update'&&String(before.admin_note||'')!==String(after.admin_note||''))changes.push('interná poznámka upravená');
    return changes.join(' · ')||item?.action||'zmena účtu';
  }
  function systemState(ok,warning=false){return ok?'ok':warning?'warning':'error';}
  function renderAdminSystem(){
    const d=state.adminDiagnostics||{},feed=d.feed||{},provider=d.provider||{},worker=d.live_worker||{},accountHealth=d.account_inactivity||{},accountWorker=accountHealth.worker||{},smtp=accountHealth.smtp||{},accountPolicy=accountHealth.policy||{},ops=d.ops||{},counts=ops.counts||{};
    const storage=d.storage||{},storageServices=storage.services||{},services=d.services||{},assets=d.assets||{};
    const playerImages=assets.player_images||{},tournamentLogos=assets.tournament_logos||{};
    const storageDetail=d.content_storage_ready?`${d.admin_storage||'storage'}${storage.azure_connection_source?' · '+storage.azure_connection_source:''}`:(storage.recommended_setting?`SET ${storage.recommended_setting}`:'unavailable');
    const mediaDetail=item=>`${Number(item.provider_or_proxy_refs||0)}/${Number(item.total||0)} ref · ${Number(item.fallback_needed||0)} fallback`;
    const cards=[
      ['API / AUTH',Boolean(d.accounts_ready),d.auth_provider||'—'],
      ['ADMIN STORAGE',Boolean(d.content_storage_ready),storageDetail],
      ['PLAYER IMAGES',Boolean(playerImages.ok),mediaDetail(playerImages)],
      ['TOURNAMENT LOGOS',Boolean(tournamentLogos.ok),mediaDetail(tournamentLogos)],
      ['INFO STORAGE',Boolean(services.info_storage),services.info_storage?'ONLINE':'NEED STORAGE'],
      ['LIVE DATA',Boolean(services.live_data),services.live_data?'FRESH':(feed.ready?'STALE':'NO FEED')],
      ['LIVE WORKER',Boolean(worker.healthy),worker.healthy?`AUTO · ${Math.max(0,Number(worker.age_seconds)||0)}s`:(worker.configured?'STALE':'TOKEN MISSING')],
      ['ACCOUNT CHECK',accountPolicy.enabled===false||Boolean(accountWorker.healthy),accountPolicy.enabled===false?'OFF':(accountWorker.healthy?`DAILY · ${Number(accountWorker.inactive||0)} inactive · ${Number(accountWorker.subscription_7||0)}/${Number(accountWorker.subscription_3||0)} expiry mail`:(accountWorker.configured?'STALE':'TOKEN MISSING'))],
      ['EMAIL / SMTP',accountPolicy.enabled===false||Boolean(smtp.configured),accountPolicy.enabled===false?'NOT NEEDED':(smtp.configured?(smtp.admin_recipient_configured?`READY · ${Number(smtp.admin_recipient_count||1)} admin`:'ADMIN EMAIL MISSING'):'NOT CONFIGURED')],
      ['DATA PROVIDER',Boolean(provider.configured),provider.configured?'CONFIGURED':'MISSING KEY'],
      ['ERRORS · 24H',Number(counts.error||0)===0,String(counts.error||0)],
    ];
    const events=(ops.items||[]).map(item=>`<tr><td><span class="ops-level is-${escapeHtml(item.level||'info')}">${escapeHtml(String(item.level||'info').toUpperCase())}</span></td><td>${escapeHtml(item.component||'app')}</td><td>${escapeHtml(item.message||'')}</td><td>${escapeHtml(fmtDate(item.occurred_at))} · ${escapeHtml(fmtTime(item.occurred_at))}</td></tr>`).join('');
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>SYSTEM HEALTH</small><h2>Prevádzkový stav</h2><p>Diagnostika iba znovu načíta aktuálny stav API, úložiska, feedu, assetov, LIVE workeru a kontroly neaktívnych účtov. Nič neopravuje a nespúšťa data/enrichment run ani LIVE scan. Nespúšťa ani e-mailovú kontrolu účtov.</p></div><div class="admin-system-actions"><button class="btn btn-ghost" type="button" data-admin-action="copy-diagnostics">Kopírovať diagnostiku</button><button class="btn btn-primary" type="button" data-admin-action="diagnostics">Obnoviť diagnostiku</button></div></div><div class="admin-system-cards">${cards.map(([name,ok,detail])=>`<article class="admin-system-card is-${systemState(ok,false)}"><span></span><small>${name}</small><strong>${ok?'OK':'CHECK'}</strong><em>${escapeHtml(detail)}</em></article>`).join('')}</div><div class="admin-system-details"><div><small>Posledný feed</small><strong>${escapeHtml(feed.generated_at?`${fmtDate(feed.generated_at)} · ${fmtTime(feed.generated_at)}`:'—')}</strong></div><div><small>Model</small><strong>${escapeHtml(feed.model_version||state.feed?.model?.version||'—')}</strong></div><div><small>Upcoming / Results</small><strong>${Number(feed.upcoming||0)} / ${Number(feed.results||0)}</strong></div><div><small>Úložisko</small><strong>${escapeHtml(storageDetail)}</strong></div><div><small>Kontrola</small><strong>${d.checked_at?new Date(Number(d.checked_at)*1000).toLocaleTimeString('sk-SK',{hour:'2-digit',minute:'2-digit'}):'—'}</strong></div></div>${!d.content_storage_ready?`<div class="admin-runtime-note is-error"><strong>Admin konfigurácia, INFO a história LIVE potrebujú trvalé úložisko</strong><span>Nastav jeden spoločný App Setting <code>${escapeHtml(storage.recommended_setting||'BLINQ_STORAGE_CONNECTION_STRING')}</code>. Stačí jeden existujúci Azure Storage účet; nie je potrebné vytvárať ďalší. Rovnaké úložisko používa admin konfigurácia, INFO a LIVE história.</span></div>`:''}${!worker.configured?`<div class="admin-runtime-note is-warning"><strong>Autonómny LIVE worker ešte nemá token</strong><span>Nastav rovnaký <code>BLINQ_LIVE_WORKER_TOKEN</code> v Azure Production environment variables aj v GitHub Actions Secrets a GitHub variable <code>TBT_LIVE_RADAR_ENABLED=true</code>. Až potom bude plánovaný LIVE Radar bežať autonómne.</span></div>`:''}${accountPolicy.enabled!==false&&!accountWorker.configured?`<div class="admin-runtime-note is-warning"><strong>Denná kontrola neaktívnych účtov ešte nemá token</strong><span>Nastav rovnaký <code>BLINQ_ACCOUNT_WORKER_TOKEN</code> v Azure Production environment variables aj v GitHub Actions Secrets a GitHub variable <code>TBT_ACCOUNT_INACTIVITY_ENABLED=true</code>. Kým token chýba, denný lifecycle worker účtov sa nespúšťa.</span></div>`:''}${accountPolicy.enabled!==false&&!smtp.configured?`<div class="admin-runtime-note is-warning"><strong>E-mailové upozornenia ešte nemajú SMTP</strong><span>Bez SMTP sa neposielajú inactivity ani 7/3-dňové subscription upozornenia a ROOKIE sa neoznačí ako EXPIRED. V Azure nastav <code>BLINQ_SMTP_HOST</code>, <code>BLINQ_SMTP_PORT</code>, <code>BLINQ_SMTP_FROM</code>${accountPolicy.notify_admin?' a <code>BLINQ_ADMIN_EMAILS</code>':''}. Ak server vyžaduje prihlásenie, pridaj aj <code>BLINQ_SMTP_USERNAME</code> a <code>BLINQ_SMTP_PASSWORD</code>.</span></div>`:''}<div class="admin-form-section"><div class="admin-form-section-title"><strong>Posledné udalosti</strong><span>Serverové chyby, ktoré zachytil BlinQ prevádzkový journal.</span></div><div class="admin-table-wrap"><table class="admin-analytics-table"><thead><tr><th>Level</th><th>Komponent</th><th>Správa</th><th>Čas</th></tr></thead><tbody>${events||'<tr><td colspan="4">Za posledných 24 hodín nie sú zaznamenané žiadne prevádzkové udalosti.</td></tr>'}</tbody></table></div></div></section>`;
  }
  function renderAdminLevels(){
    const plans=membershipHierarchy.map((id,index)=>{
      const p=state.ui.plans[id]=state.ui.plans[id]||{label:`BlinQ ${id.toUpperCase()}`,enabled:true,order:index+1};
      const mainUrl=String(p.url||'');
      const inviteUrl=String(p.invite_url||'');
      const features=Array.isArray(p.features)?p.features.join('\n'):upgradePlanFeatureList(id).join('\n');
      const unlimited=planIsUnlimited(id,p),duration=unlimited?'':(Number.isFinite(Number(p.duration_days))?String(Number(p.duration_days)):'');
      const external=safeExternalUrl(p.invite_only?(inviteUrl||mainUrl):mainUrl);
      const termMark=unlimited?'∞':String(Number(p.duration_days)||'—');
      const termTitle=unlimited?'FREE · bez časového obmedzenia':'Časovo obmedzený';
      const termHelp=unlimited?'ROOKIE nemá pevnú expiráciu. Voliteľná kontrola neaktivity je nižšie.':'Platnosť nastavuješ počtom dní nižšie.';
      return `<details class="admin-membership-card plan-${escapeHtml(id)}" data-admin-level-plan="${escapeHtml(id)}" ${id==='rookie'?'open':''}><summary><div>${planAvatarPairHtml(id,p)}<span>${planEyebrowHtml(p)}<strong>${escapeHtml(p.label||id.toUpperCase())}</strong><em>${p.enabled===false?'VYPNUTÝ':'AKTÍVNY'}</em></span></div><b>${external?'ODKAZ OK':'BEZ ODKAZU'}</b></summary><div class="admin-membership-card-body"><div class="admin-membership-switches"><label><input type="checkbox" data-admin-level-field="enabled" ${p.enabled!==false?'checked':''} ${id==='rookie'?'disabled':''}><span><strong>Level aktívny</strong><small>Zobrazí sa v členských kartách a upgrade ponuke.</small></span></label><label><input type="checkbox" data-admin-level-field="invite_only" ${p.invite_only?'checked':''}><span><strong>Len na pozvánku</strong><small>Použije pozvánkový odkaz namiesto bežného CTA.</small></span></label><label class="is-static"><span class="admin-membership-static-mark">${escapeHtml(termMark)}</span><span><strong>${escapeHtml(termTitle)}</strong><small>${escapeHtml(termHelp)}</small></span></label></div><div class="admin-membership-fields"><label><span>Názov levelu</span><input data-admin-level-field="label" value="${escapeHtml(p.label||'')}"></label><label><span>Názov karty</span><input data-admin-level-field="card_title" value="${escapeHtml(p.card_title||'')}"></label><label class="span-2"><span>Zelená popiska nad názvom <small>(prázdne = skryť)</small></span><input maxlength="40" data-admin-level-field="eyebrow" value="${escapeHtml(Object.prototype.hasOwnProperty.call(p,'eyebrow')?p.eyebrow:'')}"></label><label class="span-2"><span>Krátky popis</span><input data-admin-level-field="short_description" value="${escapeHtml(p.short_description||p.description||'')}"></label><label class="span-2"><span>Detailný popis</span><textarea rows="3" data-admin-level-field="description">${escapeHtml(p.description||'')}</textarea></label><label><span>Text tlačidla</span><input data-admin-level-field="cta_label" value="${escapeHtml(p.cta_label||'')}"></label><label><span>Úroveň v poradí</span><input value="${escapeHtml(String(index+1))} · ${escapeHtml(id.toUpperCase())}" disabled title="Poradie levelov je pevné: ROOKIE → PRO → ELITE → LEGEND → GOAT"></label><label class="span-2"><span>Hlavný odkaz / platba</span><div class="admin-membership-link-row"><input data-admin-level-field="url" value="${escapeHtml(mainUrl)}" placeholder="https://..."><span>${safeExternalUrl(mainUrl)?`<a href="${escapeHtml(safeExternalUrl(mainUrl))}" target="_blank" rel="noopener">Otestovať ↗</a>`:'<em>Nie je nastavený</em>'}</span></div></label><label class="span-2"><span>Pozvánkový odkaz <small>(iba ak je „Len na pozvánku“)</small></span><div class="admin-membership-link-row"><input data-admin-level-field="invite_url" value="${escapeHtml(inviteUrl)}" placeholder="https://..."><span>${safeExternalUrl(inviteUrl)?`<a href="${escapeHtml(safeExternalUrl(inviteUrl))}" target="_blank" rel="noopener">Otestovať ↗</a>`:'<em>Voliteľné</em>'}</span></div></label><label><span>Predvolená platnosť (dni)</span><input type="number" min="1" max="3650" data-admin-level-field="duration_days" value="${escapeHtml(duration)}" ${unlimited?'disabled':''}></label><label><span>Interná poznámka</span><input data-admin-level-field="note" value="${escapeHtml(p.note||'')}"></label><label class="span-2"><span>Výhody na karte <small>(1 riadok = 1 bod)</small></span><textarea rows="5" data-admin-level-field="features">${escapeHtml(features)}</textarea></label></div><div class="admin-membership-note"><strong>Publikovanie</strong><span>Zmeny sú súčasťou UI konfigurácie. Klikni hore na <b>Publikovať</b>; JSON súbory už nemusíš ručne meniť.</span></div></div></details>`;
    }).join('');
    const inactivity=state.ui.account_inactivity=mergeConfig({enabled:true,inactive_days:30,warning_days:7,notify_admin:true,notify_user:true,auto_expire_rookie:true},state.ui.account_inactivity||{});
    if(inactivity.auto_expire_rookie)inactivity.notify_user=true;
    const inactivityPanel=`<div class="admin-form-section admin-inactivity-policy"><div class="admin-form-section-title"><strong>Kontrola neaktivity účtov</strong><span>ROOKIE zostáva bez pevnej platnosti. Po dlhšej neaktivite sa iba označí ako EXPIRED; Firebase účet sa automaticky nemaže ani nedeaktivuje.</span></div><div class="admin-membership-switches"><label><input type="checkbox" data-admin-inactivity-field="enabled" ${inactivity.enabled!==false?'checked':''}><span><strong>Kontrolovať aktivitu účtu</strong><small>Denný worker používa serverovú aktivitu aj posledné Firebase prihlásenie.</small></span></label><label><input type="checkbox" data-admin-inactivity-field="notify_admin" ${inactivity.notify_admin!==false?'checked':''}><span><strong>Poslať admin súhrn e-mailom</strong><small>Voliteľný prevádzkový súhrn pre administrátora.</small></span></label><label><input type="checkbox" data-admin-inactivity-field="notify_user" ${inactivity.notify_user?'checked':''} ${inactivity.auto_expire_rookie?'disabled':''}><span><strong>Upozorniť používateľa e-mailom</strong><small>${inactivity.auto_expire_rookie?'Povinné pred označením účtu ako EXPIRED.':'Predvolene zapnuté; upozornenie sa odošle pred hranicou neaktivity.'}</small></span></label></div><div class="admin-membership-fields"><label><span>Neaktívny po (dni)</span><input type="number" min="14" max="3650" data-admin-inactivity-field="inactive_days" value="${escapeHtml(String(inactivity.inactive_days||30))}"></label><label><span>Upozorniť vopred (dni)</span><input type="number" min="1" max="365" data-admin-inactivity-field="warning_days" value="${escapeHtml(String(inactivity.warning_days||7))}"></label><div class="span-2 admin-inactivity-danger"><span>Automatické označenie FREE ROOKIE ako EXPIRED</span><label class="admin-inline-check"><input type="checkbox" data-admin-inactivity-field="auto_expire_rookie" ${inactivity.auto_expire_rookie?'checked':''}> Po prekročení limitu označiť dlhodobo neaktívny ROOKIE účet ako EXPIRED</label><small>Bezpečnostné pravidlo: označenie EXPIRED môže nastať až po úspešne odoslanom e-maile používateľovi a po uplynutí celej lehoty „Upozorniť vopred“. Pri 7 dňoch teda nikdy skôr ako 7 dní po reálnom doručení upozornenia.</small></div></div><div class="admin-runtime-note"><strong>Worker potrebuje token a SMTP</strong><span>Rovnaký <code>BLINQ_ACCOUNT_WORKER_TOKEN</code> musí byť v Azure aj GitHub Secrets. SMTP zostáva iba v Azure Environment variables. Bez úspešne odoslaného používateľského upozornenia sa označenie EXPIRED nevykoná.</span></div></div>`;
    return `<section class="admin-ux-section admin-membership-manager"><div class="admin-ux-heading"><div><small>ČLENSTVÁ</small><h2>Levely a upgrade karty</h2><p>Spravuj názvy, popisy, odkazy, dostupnosť a predvolenú platnosť bez ručnej úpravy JSON.</p></div></div><div class="admin-runtime-note"><strong>Prístupové pravidlá zostávajú oddelené</strong><span>Táto sekcia upravuje samotné levely a ich marketingové karty. Čo ktorý level vidí nastavuješ v <b>Zobrazenie</b>; LIVE minimum v <b>Info & LIVE</b>.</span></div><div class="admin-membership-list">${plans}</div>${inactivityPanel}</section>`;
  }

  function renderAdminTelegram(){
    const cfg=state.ui.telegram_groups=state.ui.telegram_groups||{schema:1,enabled:true,eyebrow:'BLINQ COMMUNITY',title:'Telegram skupiny',description:'',groups:[]};
    cfg.groups=Array.isArray(cfg.groups)?cfg.groups:[];
    const optionHtml=current=>membershipHierarchy.map(id=>`<option value="${id}"${id===current?' selected':''}>${escapeHtml(String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,''))}</option>`).join('');
    const rows=cfg.groups.map((group,index)=>`<article class="admin-tg-card" data-tg-index="${index}"><div class="admin-tg-card-head"><div><small>SKUPINA ${index+1}</small><strong>${escapeHtml(group.title||'Telegram skupina')}</strong></div><button class="btn btn-ghost" type="button" data-admin-action="tg-remove" data-tg-index="${index}">Odstrániť</button></div><div class="admin-tg-grid"><label><span>Názov</span><input data-tg-group-field="title" value="${escapeHtml(group.title||'')}"></label><label><span>Min. level</span><select data-tg-group-field="min_plan">${optionHtml(String(group.min_plan||'rookie'))}</select></label><label><span>Popiska nad názvom <small>(prázdne = skryť)</small></span><input data-tg-group-field="badge" value="${escapeHtml(Object.prototype.hasOwnProperty.call(group,'badge')?group.badge:'')}"></label><label class="admin-tg-wide"><span>Popis</span><input data-tg-group-field="description" value="${escapeHtml(group.description||'')}"></label><label><span>Text tlačidla</span><input data-tg-group-field="cta" value="${escapeHtml(group.cta||'')}"></label><label><span>URL</span><input data-tg-group-field="url" value="${escapeHtml(group.url||'')}" placeholder="https://t.me/..."></label><label class="admin-tg-check"><input data-tg-group-field="enabled" type="checkbox" ${group.enabled!==false?'checked':''}> Zobraziť skupinu</label></div></article>`).join('');
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>COMMUNITY</small><h2>Telegram skupiny</h2><p>Panel pod predikciami. Zmeny sa publikujú spolu s ostatnou UI konfiguráciou.</p></div><button class="btn btn-primary" type="button" data-admin-action="tg-add">+ Pridať skupinu</button></div><div class="admin-runtime-note"><strong>Bezpečnostná poznámka</strong><span>Pri súkromnej VIP skupine nevkladaj trvalý tajný invite link. Použi radšej verejný request/contact odkaz alebo bot link.</span></div><div class="admin-form-section admin-tg-panel-settings"><div class="admin-form-section-title"><strong>Panel</strong><span>Defaulty sú v <code>web/config/telegram-groups.json</code>. Admin zmeny sa ukladajú cez existujúce UI storage.</span></div><div class="admin-tg-grid"><label><span>Popiska nad nadpisom <small>(prázdne = skryť)</small></span><input data-tg-field="eyebrow" value="${escapeHtml(Object.prototype.hasOwnProperty.call(cfg,'eyebrow')?cfg.eyebrow:'')}"></label><label><span>Nadpis</span><input data-tg-field="title" value="${escapeHtml(cfg.title||'')}"></label><label class="admin-tg-wide"><span>Popis</span><input data-tg-field="description" value="${escapeHtml(cfg.description||'')}"></label><label class="admin-tg-check"><input data-tg-field="enabled" type="checkbox" ${cfg.enabled!==false?'checked':''}> Zobraziť panel na domovskej stránke</label></div></div><div class="admin-tg-list">${rows||'<div class="admin-note"><strong>Žiadna Telegram skupina</strong><span>Pridaj prvú skupinu tlačidlom hore.</span></div>'}</div></section>`;
  }

  function renderAdminRoute(){
    const tabs=[['accounts','Účty','Prístup · platnosť'],['levels','Členstvá','Levely · odkazy'],['layout','Zobrazenie','Panely · riadky'],['banners','Bannery','Hero · pozadie'],['telegram','Telegram','Skupiny · odkazy'],['insights','Info & LIVE','Správy · radar'],['system','Systém','Diagnostika']];
    const valid=tabs.map(row=>row[0]);if(!valid.includes(state.adminTab))state.adminTab='accounts';
    const renderers={accounts:renderAdminAccounts,levels:renderAdminLevels,layout:renderAdminLayout,banners:renderAdminBanners,telegram:renderAdminTelegram,insights:renderAdminInsights,system:renderAdminSystem};const panel=renderers[state.adminTab]();
    const info={accounts:['Účty','Používatelia, level a platnosť prístupu.'],levels:['Členstvá','Názvy, popisy, odkazy a dostupnosť levelov.'],layout:['Zobrazenie','SHOW / BLUR / HIDE pre panely a jednotlivé riadky.'],banners:['Bannery','Hero carousel, texty, odkazy, mobilný podklad a pozadie.'],telegram:['Telegram','Skupiny, odkazy a minimálna úroveň prístupu.'],insights:['Info & LIVE','Správy podľa levelu a Comeback radar.'],system:['Systém','Úložisko, API, feed a prevádzková diagnostika.']}[state.adminTab];
    let contextual='';
    if(state.adminTab==='accounts')contextual='<div class="admin-account-direct-note"><span></span>Zmeny účtov sa aplikujú okamžite</div>';
    else if(state.adminTab==='insights')contextual='<div class="admin-account-direct-note"><span></span>Správy sa publikujú okamžite</div>';
    else if(state.adminTab==='system')contextual='<div class="admin-account-direct-note"><span></span>Kontrola je len čítacia diagnostika</div>';
    else contextual='<div class="admin-publish-hint"><span>Koncept</span><i></i><b>Live po publikovaní</b></div><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Uložiť koncept</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publikovať</button>';
    const nav=tabs.map(([id,label,hint])=>`<button type="button" class="${state.adminTab===id?'active':''}" data-admin-tab="${id}"><span class="admin-nav-mark"></span><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(hint)}</small></span></button>`).join('');
    return `<div class="admin-console admin-console-v685 admin-console-v687 lean-admin-console"><aside class="admin-side-nav"><div class="admin-side-brand"><span>BLINQ CONTROL</span><strong>Admin</strong><small>Účty · obsah · LIVE</small></div><nav class="admin-tabs admin-tabs-v685" aria-label="Admin navigácia"><div class="admin-nav-group"><span>SPRÁVA</span>${nav}</div></nav><div class="admin-side-foot"><a href="#predictions" data-route="predictions"><svg viewBox="0 0 20 20"><path d="M4 10h12M9 5l-5 5 5 5"></path></svg><span>Späť na web</span></a></div></aside><section class="admin-workarea"><header class="admin-workarea-head admin-control-toolbar"><div><small>ADMIN / ${escapeHtml(state.adminTab.toUpperCase())}</small><h2>${escapeHtml(info[0])}</h2><p>${escapeHtml(info[1])}</p></div><div class="admin-global-actions">${contextual}</div></header><div class="admin-panel admin-panel-v685">${panel}</div></section></div>`;
  }


  function rerenderAdmin(){ if(state.route!=='admin')return; const host=$('routePanel');host.innerHTML=renderAdminRoute();wireAdmin(); }
  function saveDraft(){ applyV6514AdminCleanup(); localStorage.setItem(draftKey(),JSON.stringify(state.ui)); showStatus('Admin koncept bol uložený v tomto prehliadači.'); }
  async function publishUiConfig(){
    if(!state.ui)return;
    showStatus('Publikujem nastavenie…');
    try{
      applyV6514AdminCleanup();
      const result=await BlinqAuth.adminSaveUiConfig(state.ui);
      if(!result?.saved)throw new Error('Server nepotvrdil uloženie konfigurácie.');
      try{localStorage.removeItem(draftKey());}catch{}
      state.runtimeConfigLoaded=true;
      state.uiSource=clone(state.ui);
      showStatus('Nastavenie bolo publikované na live web.');
      renderAllUiContent();
      rerenderAdmin();
    }catch(error){
      const message=error?.status===503?'Admin storage nie je dostupný. Skontroluj Admin → Systém.':(error?.message||'Nastavenie sa nepodarilo publikovať.');
      showStatus(message);
      return false;
    }
  }
  function exportUiConfig(){ const blob=new Blob([JSON.stringify(state.ui,null,2)+'\n'],{type:'application/json'}); const url=URL.createObjectURL(blob); const a=document.createElement('a');a.href=url;a.download='ui-config.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),0); }
  async function loadAdminDiagnostics(force=false){
    const generation=feedGeneration;
    if(state.adminDiagnosticsLoading||(!force&&state.adminDiagnostics))return;
    state.adminDiagnosticsLoading=true;rerenderAdmin();
    try{const data=await BlinqAuth.adminDiagnostics();if(generation!==feedGeneration)return;state.adminDiagnostics=data;}
    catch(error){if(generation!==feedGeneration)return;state.adminDiagnostics={ok:false,error:error.message,status:error.status||0};}
    finally{if(generation===feedGeneration){state.adminDiagnosticsLoading=false;rerenderAdmin();}}
  }
  async function loadAdminUsers(force=false){
    const generation=feedGeneration;
    if(state.adminUsersLoading||(!force&&Array.isArray(state.adminUsers)))return;
    state.adminUsersLoading=true;rerenderAdmin();
    try{
      const all=[];const perPage=200;let page=1;
      let storageWarning='';
      while(page<=25){const data=await BlinqAuth.adminUsers(page,perPage);if(generation!==feedGeneration)return;const batch=Array.isArray(data?.users)?data.users:[];all.push(...batch);if(data?.storage_warning)storageWarning=data.storage_warning;if(batch.length<perPage)break;page+=1;}
      if(generation!==feedGeneration)return;
      state.adminUsersWarning=storageWarning?'Levely, platnosť a prístup fungujú cez Firebase. Doplnkové profilové údaje a audit čakajú na trvalé úložisko; nastav BLINQ_STORAGE_CONNECTION_STRING.':'';
      state.adminUsersError=all.length>=5000?'Zobrazených prvých 5000 účtov. Pre väčší zoznam treba serverové cursor filtrovanie.':'';state.adminUsers=all;
      if(state.adminSelectedUser)state.adminSelectedUser=state.adminUsers.find(x=>x.id===state.adminSelectedUser.id)||null;
    }catch(error){if(generation!==feedGeneration)return;state.adminUsers=[];state.adminUsersWarning='';state.adminUsersError=error.status===503?'Admin API pre účty nie je dostupné. Otvor Diagnostiku pre presný stav Firebase Admin konfigurácie.':error.message;}
    finally{if(generation===feedGeneration){state.adminUsersLoading=false;rerenderAdmin();adminApplyUserFilters();}}
  }

  function setSelectedElement(id){ if(!elements()?.[id])return;state.selectedElement=id;rerenderAdmin(); }
  function setAdminPlanDefaults(planId, force=false){
    const expiry=$('adminUserExpires');if(!expiry)return;
    const plan=state.ui?.plans?.[planId]||{};
    if(!planId){expiry.value='';expiry.disabled=false;return;}
    if(planIsUnlimited(planId,plan)){expiry.value='';expiry.disabled=true;return;}
    expiry.disabled=false;
    const current=expiry.value?new Date(expiry.value).getTime():0;
    if(force||!current||current<=Date.now()){
      const date=planDefaultExpiry(planId);expiry.value=userDateValue(date?.toISOString());
    }
  }
  function adminAddDaysToExpiry(days){
    const expiry=$('adminUserExpires');if(!expiry)return;
    const planId=String($('adminUserPlan')?.value||''),plan=state.ui?.plans?.[planId]||{};
    if(planIsUnlimited(planId,plan)){setAdminPlanDefaults(planId,true);showStatus('ROOKIE je bez časového obmedzenia.');return;}
    const current=expiry.value?new Date(expiry.value).getTime():0,base=Math.max(Date.now(),Number.isFinite(current)?current:0);
    expiry.disabled=false;expiry.value=userDateValue(new Date(base+Math.max(1,Number(days)||1)*86400000).toISOString());
  }
  function adminDefaultPlanDays(){
    const planId=String($('adminUserPlan')?.value||'');const plan=state.ui?.plans?.[planId]||{};return planIsUnlimited(planId,plan)?0:Math.max(1,Number(plan.duration_days)||30);
  }
  function decorateAdminMediaUploads(host){
    if(!host)return;
    const selector=[
      'input[data-simple-banner-field="image_url"]',
      'input[data-simple-banner-field="mobile_image_url"]',
      'input[data-simple-banner-field="site_background_url"]',
      'input[data-simple-banner-field$="_icon_url"]',
    ].join(',');
    host.querySelectorAll(selector).forEach(input=>{
      if(input.dataset.mediaUploadReady==='1')return;
      input.dataset.mediaUploadReady='1';
      const wrap=document.createElement('span');wrap.className='admin-media-upload';
      input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);
      const button=document.createElement('button');button.type='button';button.className='admin-media-upload-button';button.textContent='Nahrať obrázok';
      const picker=document.createElement('input');picker.type='file';picker.accept='image/png,image/jpeg,image/webp,image/gif,image/avif';picker.hidden=true;
      wrap.appendChild(button);wrap.appendChild(picker);
      button.onclick=()=>picker.click();
      picker.onchange=async()=>{
        const file=picker.files?.[0];if(!file)return;
        button.disabled=true;button.textContent='Nahrávam…';
        try{
          const result=await BlinqAuth.adminUploadMedia(file);
          input.value=String(result?.url||'');
          input.dispatchEvent(new Event('change',{bubbles:true}));
          showStatus(`Obrázok bol nahraný · ${Math.max(1,Math.round(Number(result?.size||0)/1024))} kB`);
        }catch(error){showStatus(error.message||'Obrázok sa nepodarilo nahrať.');}
        finally{button.disabled=false;button.textContent='Nahrať obrázok';picker.value='';}
      };
    });
  }
  function wireAdmin(){
    const host=$('routePanel'); if(!host)return;
    decorateAdminMediaUploads(host);
    host.onclick=async event=>{
      const tab=event.target.closest('[data-admin-tab]');if(tab){state.adminTab=tab.dataset.adminTab;rerenderAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='insights')loadAdminInsights();if(state.adminTab==='system')loadAdminDiagnostics(true);return;}
      const tgAction=event.target.closest('[data-admin-action="tg-add"],[data-admin-action="tg-remove"]');if(tgAction){const cfg=state.ui.telegram_groups=state.ui.telegram_groups||{schema:1,enabled:true,groups:[]};cfg.groups=Array.isArray(cfg.groups)?cfg.groups:[];if(tgAction.dataset.adminAction==='tg-add'){cfg.groups.push({id:`group_${Date.now()}`,enabled:true,badge:'KOMUNITA',title:'Telegram skupina',description:'',cta:'Otvoriť Telegram',url:'',min_plan:'rookie'});}else{const index=Number(tgAction.dataset.tgIndex);if(Number.isInteger(index)&&index>=0)cfg.groups.splice(index,1);}renderTelegramGroupsPanel();rerenderAdmin();return;}
      const planChip=event.target.closest('[data-admin-plan-chip]');if(planChip){state.adminPlan=planChip.dataset.adminPlanChip;rerenderAdmin();return;}
      const dailyPreset=event.target.closest('[data-admin-daily-preset]');if(dailyPreset){const preset=dailyPreset.dataset.adminDailyPreset,hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};hub.tabs=hub.tabs||{};['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'].forEach(tab=>{const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc.plans=tc.plans||{};const rule=tc.plans[state.adminPlan]=tc.plans[state.adminPlan]||{};rule.tab_enabled=true;rule.row_overrides={};if(preset==='full'){rule.display_state='active';rule.visible_rows='ALL';rule.selection_mode='first';rule.blur_remaining=false;rule.see_all=true;}else if(preset==='preview3'){rule.display_state='active';rule.visible_rows=3;rule.selection_mode='first';rule.blur_remaining=true;rule.see_all=false;}else if(preset==='rookie2'){rule.display_state='active';rule.visible_rows=tab==='daily'?2:Math.min(1,Number(rule.visible_rows)||1);rule.selection_mode='stable_random';rule.blur_remaining=true;rule.see_all=false;}else if(preset==='blurred'){rule.display_state='blurred';rule.visible_rows=0;rule.blur_remaining=true;rule.see_all=false;}else if(preset==='hidden'){rule.display_state='hidden';rule.visible_rows=0;rule.blur_remaining=false;rule.see_all=false;}if(state.adminPlan==='rookie')tc.plans.trial=clone(rule);});renderAllUiContent();rerenderAdmin();showStatus(`Zobrazenie · ${accessLabel(state.adminPlan)} preset bol nastavený.`);return;}
      const previewStep=event.target.closest('[data-admin-preview-step]');
      if(previewStep){const n=activeAdminBanners().length;state.adminPreviewIndex=(state.adminPreviewIndex+Number(previewStep.dataset.adminPreviewStep)+n)%n;syncAdminHeroPreview();return;}
      const previewDot=event.target.closest('[data-admin-preview-dot]');
      if(previewDot){state.adminPreviewIndex=Number(previewDot.dataset.adminPreviewDot)||0;syncAdminHeroPreview();return;}
      const previewPause=event.target.closest('[data-admin-preview-pause]');
      if(previewPause){state.adminPreviewPaused=!state.adminPreviewPaused;syncAdminHeroPreview();return;}
      const element=event.target.closest('[data-admin-element]');if(element){setSelectedElement(element.dataset.adminElement);return;}
      const userButton=event.target.closest('[data-admin-user]');if(userButton){state.adminSelectedUser=(state.adminUsers||[]).find(x=>String(x.id)===String(userButton.dataset.adminUser))||null;rerenderAdmin();return;}
      const quick=event.target.closest('[data-admin-user-plan]');if(quick){const input=$('adminUserPlan');if(input){input.value=quick.dataset.adminUserPlan;host.querySelectorAll('[data-admin-user-plan]').forEach(btn=>btn.classList.toggle('active',btn===quick));setAdminPlanDefaults(input.value,false);}return;}
      const expiryQuick=event.target.closest('[data-admin-expiry-days]');if(expiryQuick){adminAddDaysToExpiry(Number(expiryQuick.dataset.adminExpiryDays));return;}
      const actionNode=event.target.closest('[data-admin-action]');const action=actionNode?.dataset.adminAction;if(!action)return;
      if(action==='insight-new'){state.adminInsightEditingId='';rerenderAdmin();return;}
      if(action==='insight-edit'){state.adminInsightEditingId=String(actionNode.dataset.insightId||'');rerenderAdmin();return;}
      if(action==='insight-delete'){const id=String(actionNode.dataset.insightId||'');if(!id)return;if(!window.confirm('Naozaj chceš túto správu odstrániť?'))return;try{await BlinqAuth.adminDeleteInsight(id);state.adminInsightEditingId='';state.adminInsights=null;await loadAdminInsights(true);await loadInsights(true);showStatus('Správa bola odstránená.');}catch(error){showStatus(error.message);}return;}
      if(action==='insight-audience-preset'){const form=$('adminInsightForm');if(!form)return;const preset=String(actionNode.dataset.audiencePreset||'all'),wanted=new Set(adminAudiencePresetLevels(preset)),live=String($('adminInsightType')?.value||'vip')==='alert',liveAllowed=new Set(membershipLevelsFrom(notificationAudienceConfig().live_min_level));form.querySelectorAll('input[name="insight_level"]').forEach(node=>{node.checked=wanted.has(node.value)&&(!live||liveAllowed.has(node.value));});return;}
      if(action==='save-info-access'){const value=String($('adminInfoMinLevel')?.value||'rookie').toLowerCase();state.ui.notifications=state.ui.notifications||{};state.ui.notifications.info_min_level=membershipHierarchy.includes(value)?value:'rookie';state.ui.notifications.info_default_levels=membershipLevelsFrom(state.ui.notifications.info_min_level);const saved=await publishUiConfig();if(saved!==false)showStatus(`Predvolené INFO publikum bolo nastavené od ${publicPlanLabel(state.ui.notifications.info_min_level,state.ui?.plans?.[state.ui.notifications.info_min_level]?.label||'')}.`);return;}
      if(action==='save-live-access'){const value=String($('adminLiveMinLevel')?.value||'elite').toLowerCase();state.ui.notifications=state.ui.notifications||{};state.ui.notifications.live_min_level=membershipHierarchy.includes(value)?value:'elite';state.ui.notifications.default_min_level=state.ui.notifications.live_min_level;state.ui.notifications.default_levels=membershipLevelsFrom(state.ui.notifications.live_min_level);const saved=await publishUiConfig();if(saved!==false)showStatus(`LIVE prístup bol nastavený od ${String(upgradePlanLabel(state.ui.notifications.live_min_level)||state.ui.notifications.live_min_level).replace(/^BlinQ\s+/i,'').toUpperCase()}.`);return;}
      if(action==='live-radar-scan'){if(state.adminLiveRadarLoading)return;state.adminLiveRadarLoading=true;state.adminLiveRadarStatus=null;rerenderAdmin();try{const result=await BlinqAuth.adminLiveRadar(true,true);state.adminLiveRadarStatus={...result,ok:true,new_alerts:Number(result?.created)||0};state.adminInsights=null;await loadAdminInsights(true);await loadInsights(true);showStatus(`LIVE Radar: ${Number(result?.signals?.length??result?.signals)||0} signálov · ${Number(result?.created)||0} nových upozornení.`);}catch(error){state.adminLiveRadarStatus={error:error.message||'LIVE Radar sa nepodarilo spustiť.'};showStatus(state.adminLiveRadarStatus.error);}finally{state.adminLiveRadarLoading=false;rerenderAdmin();}return;}
      if(action==='diagnostics'){loadAdminDiagnostics(true);return;}
      if(action==='copy-diagnostics'){
        const d=state.adminDiagnostics||{};
        const safe={release:d.release||'',accounts_ready:Boolean(d.accounts_ready),content_storage_ready:Boolean(d.content_storage_ready),auth_provider:d.auth_provider||'',admin_storage:d.admin_storage||'unavailable',firebase_server_configured:Boolean(d.firebase_server_configured),firebase_admin_users:Boolean(d.firebase_admin_users),storage:{backend:d.storage?.backend||'unavailable',azure_configured:Boolean(d.storage?.azure_configured),azure_available:Boolean(d.storage?.azure_available),azure_connection_source:d.storage?.azure_connection_source||'',firestore_available:Boolean(d.storage?.firestore_available)},assets:d.assets||{},services:d.services||{},media_storage:{configured:Boolean(d.media_storage?.configured),available:Boolean(d.media_storage?.available),container:d.media_storage?.container||''},webpush:{enabled:Boolean(d.webpush?.enabled),keys_configured:Boolean(d.webpush?.keys_configured),storage_available:Boolean(d.webpush?.storage_available),subscriptions:d.webpush?.subscriptions??null},live_worker:{configured:Boolean(d.live_worker?.configured),healthy:Boolean(d.live_worker?.healthy),age_seconds:d.live_worker?.age_seconds??null,scanned_at:d.live_worker?.scanned_at||'',live_events:Number(d.live_worker?.live_events||0),candidates:Number(d.live_worker?.candidates||0),signals:Number(d.live_worker?.signals||0),new_alerts:Number(d.live_worker?.new_alerts||0),last_error:d.live_worker?.last_error||''},problems:Array.isArray(d.problems)?d.problems:[]};
        const value=JSON.stringify(safe,null,2);
        try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(value);else{const ta=document.createElement('textarea');ta.value=value;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();}showStatus('Bezpečná diagnostika bola skopírovaná. Môžeš ju poslať bez kľúčov a tokenov.');}catch{showStatus('Diagnostiku sa nepodarilo skopírovať.');}
        return;
      }
      if(action==='save-draft')saveDraft();
      else if(action==='publish-config')await publishUiConfig();
      else if(action==='export')exportUiConfig();
      else if(action==='reset'){localStorage.removeItem(draftKey());state.ui=clone(state.uiSource);state.selectedElement='HERO_BANNER_1';renderAllUiContent();rerenderAdmin();showStatus('Reset to repository defaults. Publish if you want this reset live.');}
      else if(action==='preview-demo'){state.previewPlan=null;enableDemoBoardPreview();}
      else if(action==='preview'){state.previewPlan=state.adminPlan;renderAllUiContent();setRoute('predictions');showStatus(`Previewing page as ${accessLabel(state.previewPlan)}.`);}
      else if(action==='clear-preview'){state.previewPlan=null;renderAllUiContent();rerenderAdmin();showStatus('Admin preview disabled.');}
      else if(action==='reset-user-password'){const user=state.adminSelectedUser;if(!user)return;const savedEmail=String(user.email||'').trim(),editedEmail=String($('adminUserEmail')?.value||savedEmail).trim();if(!savedEmail){showStatus('Účet nemá uložený e-mail.');return;}if(editedEmail.toLowerCase()!==savedEmail.toLowerCase()){showStatus('Najprv ulož zmenený e-mail a potom pošli link na obnovu hesla.');return;}try{await BlinqAuth.reset(savedEmail);showStatus(`Link na obnovu hesla bol odoslaný na ${savedEmail}.`);}catch(error){showStatus(error.message||'Obnovu hesla sa nepodarilo odoslať.');}}
      else if(action==='apply-default-term'){const plan=String($('adminUserPlan')?.value||'');if(!plan){showStatus('Najprv vyber level.');return;}setAdminPlanDefaults(plan,true);}
      else if(action==='extend-default-term'){const plan=String($('adminUserPlan')?.value||'');if(!plan){showStatus('Najprv vyber level.');return;}const cfg=state.ui?.plans?.[plan]||{};if(planIsUnlimited(plan,cfg)){setAdminPlanDefaults(plan,true);showStatus('ROOKIE je bez časového obmedzenia.');return;}adminAddDaysToExpiry(adminDefaultPlanDays());}
      else if(action==='delete-user'){const user=state.adminSelectedUser;if(!user)return;const confirmation=window.prompt(`Naozaj zmazať účet ${user.email||user.id}?\n\nPre potvrdenie napíš DELETE`);if(confirmation!=='DELETE')return;try{await BlinqAuth.adminDeleteUser(user.id);state.adminUsers=(state.adminUsers||[]).filter(row=>row.id!==user.id);state.adminSelectedUser=null;rerenderAdmin();adminApplyUserFilters();showStatus('Účet bol zmazaný.');}catch(error){showStatus(error.message||'Účet sa nepodarilo zmazať.');}}
      else if(action==='refresh-users')await loadAdminUsers(true);
      else if(action==='reset-user-filters'){state.adminUserFilters={q:'',plan:'all',status:'all',sort:'email'};rerenderAdmin();adminApplyUserFilters();}
      else if(action==='copy-tg-nicks'){const nicks=adminFilteredUsers().map(u=>String(u.telegram_nick||'').trim()).filter(Boolean);const text=nicks.join('\n');if(!text){showStatus('V aktuálnom filtri nie sú žiadne Telegram nicky.');return;}try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);else{const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();}showStatus(`Skopírovaných ${nicks.length} Telegram nickov.`);}catch{showStatus('Telegram nicky sa nepodarilo skopírovať.');}}
    };
    host.onchange=event=>{
      const t=event.target;
      if(t.dataset.tgField){const cfg=state.ui.telegram_groups=state.ui.telegram_groups||{schema:1,enabled:true,groups:[]};cfg[t.dataset.tgField]=t.type==='checkbox'?t.checked:t.value;renderTelegramGroupsPanel();return;}
      if(t.dataset.tgGroupField){const card=t.closest('[data-tg-index]'),index=Number(card?.dataset.tgIndex),cfg=state.ui.telegram_groups=state.ui.telegram_groups||{schema:1,enabled:true,groups:[]},group=Array.isArray(cfg.groups)?cfg.groups[index]:null;if(group){group[t.dataset.tgGroupField]=t.type==='checkbox'?t.checked:t.value;renderTelegramGroupsPanel();}return;}
      const uf=adminUserFilterState();
      if(t.id==='adminUserLevelFilter'){uf.plan=t.value;adminApplyUserFilters();return;}
      if(t.id==='adminUserStatusFilter'){uf.status=t.value;adminApplyUserFilters();return;}
      if(t.id==='adminUserSort'){uf.sort=t.value;rerenderAdmin();adminApplyUserFilters();return;}
      if(t.id==='adminPlanSelect'){state.adminPlan=t.value;rerenderAdmin();return;}
      if(t.dataset.adminHeroCount!==undefined){const count=Math.max(1,Math.min(5,Number(t.value)||1));state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.enabled=true;state.ui.hero_banner.slot_count=count;state.ui.hero_banner.auto_rotate=count>1;state.ui.hero_banner.show_dots=count>1;state.ui.hero_banner.pause_on_hover=true;[1,2,3,4,5].forEach(i=>{const slot=elements()?.[`HERO_BANNER_${i}`];if(slot){slot.content=slot.content||{};slot.content.enabled=i<=count;}});state.heroIndex=0;state.adminPreviewIndex=0;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHeroSeconds!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.rotation_seconds=Math.max(3,Math.min(10,Number(t.value)||6));renderHeroBanner();rerenderAdmin();return;}
      if(t.dataset.adminHeroRotate!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.auto_rotate=t.checked;renderHeroBanner();rerenderAdmin();return;}
      if(t.dataset.adminHeroDots!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.show_dots=t.checked;renderHeroBanner();rerenderAdmin();return;}
      const simpleBanner=t.closest('[data-simple-banner]');
      if(simpleBanner&&t.dataset.simpleBannerField){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id];if(item){item.content=item.content||{};item.content[t.dataset.simpleBannerField]=t.type==='checkbox'?t.checked:/_size$/.test(t.dataset.simpleBannerField)?Number(t.value):t.value;renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.dashboardGlobalField){state.ui.dashboard=state.ui.dashboard||{};let value=t.type==='checkbox'?t.checked:Number(t.value);state.ui.dashboard[t.dataset.dashboardGlobalField]=value;state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHubGlobalField){const tab=t.dataset.adminHubTab,hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};hub.tabs=hub.tabs||{};const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc[t.dataset.adminHubGlobalField]=t.type==='checkbox'?t.checked:t.value;renderAllUiContent();rerenderAdmin();showStatus(`${dailyHubTabLabel(tab)} · ${tc.enabled===false?'vypnuté':'zapnuté'} globálne.`);return;}
      if(t.dataset.adminHubField){const tab=t.dataset.adminHubTab,hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};hub.tabs=hub.tabs||{};const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc.plans=tc.plans||{};const rule=tc.plans[state.adminPlan]=tc.plans[state.adminPlan]||{visible_rows:0,blur_remaining:true,tab_enabled:true,see_all:false,selection_mode:'first',display_state:'active',row_overrides:{}};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.adminHubField==='visible_rows'&&String(value).toUpperCase()!=='ALL')value=Number(value);rule[t.dataset.adminHubField]=value;rule.tab_enabled=rule.display_state!=='hidden';if(state.adminPlan==='rookie')tc.plans.trial=clone(rule);renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHubRowState){const tab=t.dataset.adminHubTab,position=String(t.dataset.adminHubRowState),hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{tabs:{}};hub.tabs=hub.tabs||{};const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc.plans=tc.plans||{};const rule=tc.plans[state.adminPlan]=tc.plans[state.adminPlan]||{};rule.row_overrides=rule.row_overrides&&typeof rule.row_overrides==='object'?rule.row_overrides:{};if(t.value==='active')delete rule.row_overrides[position];else rule.row_overrides[position]=t.value;if(state.adminPlan==='rookie')tc.plans.trial=clone(rule);renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminResultsPlan){const id=String(t.dataset.adminResultsPlan||'').toLowerCase();if(membershipHierarchy.includes(id)){const item=elements()?.SIDEBAR_RESULTS;if(item){item.access=item.access||{};item.access[id]=t.checked?'active':'locked';if(id==='rookie')item.access.trial=t.checked?'active':'locked';showStatus(`Výsledky · ${String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,'')} ${t.checked?'odomknuté':'zamknuté'} · klikni Publikovať.`);renderAllUiContent();rerenderAdmin();}}return;}
      if(t.dataset.adminResultsWindow){const id=String(t.dataset.adminResultsWindow||'').toLowerCase(),value=String(t.value||'all').toLowerCase();if(membershipHierarchy.includes(id)&&['24h','48h','3d','7d','14d','30d','all'].includes(value)){state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.results_history_window=state.ui.dashboard.results_history_window||{};state.ui.dashboard.results_history_window[id]=value;if(id==='rookie')state.ui.dashboard.results_history_window.trial=value;showStatus(`Výsledky · ${String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,'')} · história ${value.toUpperCase()} · klikni Publikovať.`);rerenderAdmin();}return;}
      if(t.dataset.adminDetailPlan){const id=String(t.dataset.adminDetailPlan||'').toLowerCase();if(membershipHierarchy.includes(id)){state.ui.dashboard=state.ui.dashboard||{};const cfg=state.ui.dashboard.match_detail=matchDetailAccessConfig();cfg.plans=cfg.plans||{};cfg.plans[id]=Boolean(t.checked);if(id==='rookie')cfg.plans.trial=Boolean(t.checked);showStatus(`Detail zápasu · ${String(state.ui?.plans?.[id]?.label||id).replace(/^BlinQ\s+/i,'')} ${t.checked?'zapnutý':'vypnutý'} · klikni Publikovať.`);renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.adminDetailSection){const section=String(t.dataset.adminDetailSection||'');const value=String(t.value||'rookie').toLowerCase();if(['statistics','radar','history'].includes(section)&&membershipHierarchy.includes(value)){state.ui.dashboard=state.ui.dashboard||{};const cfg=state.ui.dashboard.match_detail=matchDetailAccessConfig();cfg.sections=cfg.sections||{};cfg.sections[section]=value;showStatus(`Detail zápasu · ${section} od ${String(state.ui?.plans?.[value]?.label||value).replace(/^BlinQ\s+/i,'')} · klikni Publikovať.`);renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.adminInactivityField){const cfg=state.ui.account_inactivity=state.ui.account_inactivity||{enabled:true,inactive_days:30,warning_days:7,notify_admin:true,notify_user:true,auto_expire_rookie:true};const field=t.dataset.adminInactivityField;let value=t.type==='checkbox'?t.checked:Number(t.value);if(field==='inactive_days')value=Math.max(14,Math.min(3650,Number(value)||30));if(field==='warning_days')value=Math.max(1,Math.min(Math.max(1,Number(cfg.inactive_days||30)-1),Number(value)||7));cfg[field]=value;if(field==='auto_expire_rookie'&&value===true){cfg.notify_user=true;rerenderAdmin();}if(field==='notify_user'&&cfg.auto_expire_rookie&&value===false){cfg.notify_user=true;rerenderAdmin();showStatus('E-mail používateľovi je pred označením EXPIRED povinný.');return;}showStatus('Kontrola neaktivity · zmena je v koncepte. Klikni Publikovať.');return;}
      if(t.dataset.adminLevelField){const card=t.closest('[data-admin-level-plan]'),id=String(card?.dataset.adminLevelPlan||'').toLowerCase();if(membershipHierarchy.includes(id)){const p=state.ui.plans[id]=state.ui.plans[id]||{};const field=t.dataset.adminLevelField;let value=t.type==='checkbox'?t.checked:t.value;if(id==='rookie'&&field==='enabled')value=true;if(id==='rookie'&&field==='duration_days')value=null;else if(field==='duration_days'){value=value===''?null:Math.max(1,Math.min(3650,Number(value)||30));if(id==='goat'){p.lifetime=false;p.unlimited=false;}}else if(field==='features')value=String(value||'').split(/\r?\n/).map(x=>x.trim()).filter(Boolean);else if(field==='eyebrow')value=String(value||'').slice(0,40);p[field]=value;showStatus(`${String(p.label||id).replace(/^BlinQ\s+/i,'')} · zmena je v koncepte. Klikni Publikovať.`);}return;}
      if(t.dataset.adminAccess){const item=elements()?.[state.selectedElement];if(item){item.access=item.access||{};item.access[t.dataset.adminAccess]=t.value;if(t.dataset.adminAccess==='rookie')item.access.trial=t.value;rerenderAdmin();}return;}
    };
    // Live copy feedback without replacing the selected editor or interrupting typing.
    host.oninput=event=>{
      const t=event.target,field=t?.dataset?.simpleBannerField;
      if(!field||!['eyebrow','headline','text','button_text'].includes(field))return;
      const wrap=t.closest('[data-simple-banner]'),item=elements()?.[wrap?.dataset?.simpleBanner];
      if(!item)return;
      item.content=item.content||{};
      item.content[field]=t.value;
      syncAdminHeroPreview();
    };
    startAdminHeroPreview();
    const search=$('adminUserSearch');if(search)search.oninput=()=>{adminUserFilterState().q=search.value;adminApplyUserFilters();};
    adminApplyUserFilters();
    const form=$('adminUserForm');if(form)form.onsubmit=async event=>{event.preventDefault();const user=state.adminSelectedUser;if(!user)return;const message=$('adminUserMessage');message.textContent='Ukladám…';try{
      const email=String($('adminUserEmail')?.value||'').trim(),telegram_nick=String($('adminUserTelegram')?.value||'').trim();if(!email)throw new Error('E-mail je povinný.');
      let updated=await BlinqAuth.adminUpdateUserProfile(user.id,{email,telegram_nick});
      const existingAdmin=String(user.role||'').toLowerCase()==='admin'||String(user.plan||'').toLowerCase()==='admin',plan=String($('adminUserPlan')?.value||''),rawExpiry=String($('adminUserExpires')?.value||'');
      let role=existingAdmin?'admin':'user',status='expired',expires_at=null,accessPlan=existingAdmin?'':plan;
      if(existingAdmin){status='active';}
      else if(plan==='rookie'){status='active';expires_at=null;}
      else if(plan){if(!rawExpiry)throw new Error('Pre tento level nastav platnosť do.');expires_at=new Date(rawExpiry).toISOString();status=new Date(expires_at).getTime()>Date.now()?'active':'expired';}
      updated=await BlinqAuth.adminUpdateAccess(user.id,{role,plan:accessPlan,status,expires_at});
      state.adminUsers=(state.adminUsers||[]).map(row=>row.id===updated.id?updated:row);state.adminSelectedUser=updated;message.textContent='Účet bol uložený.';setTimeout(()=>{rerenderAdmin();adminApplyUserFilters();},300);
    }catch(error){message.textContent=error.message||'Účet sa nepodarilo uložiť.';}};

    const insightForm=$('adminInsightForm');if(insightForm){const typeSelect=$('adminInsightType');if(typeSelect)typeSelect.onchange=()=>syncAdminInsightAudienceForType(insightForm,true);syncAdminInsightAudienceForType(insightForm,false);}if(insightForm)insightForm.onsubmit=async event=>{event.preventDefault();const message=$('adminInsightMessage');if(message)message.textContent='Publikujem…';try{const levels=[...insightForm.querySelectorAll('input[name="insight_level"]:checked')].map(node=>node.value);if(!levels.length)throw new Error('Vyber aspoň jeden level.');const payload={title:$('adminInsightTitle').value.trim(),body:$('adminInsightBody').value.trim(),type:$('adminInsightType').value,priority:$('adminInsightPriority').value,levels,link:$('adminInsightLink').value.trim(),link_label:$('adminInsightLinkLabel').value.trim(),match_id:$('adminInsightMatchId').value.trim(),active:Boolean($('adminInsightActive').checked),pinned:Boolean($('adminInsightPinned').checked),active_from:$('adminInsightFrom').value?new Date($('adminInsightFrom').value).toISOString():'',active_until:$('adminInsightUntil').value?new Date($('adminInsightUntil').value).toISOString():''};if(state.adminInsightEditingId)await BlinqAuth.adminUpdateInsight(state.adminInsightEditingId,payload);else await BlinqAuth.adminCreateInsight(payload);state.adminInsightEditingId='';state.adminInsights=null;await loadAdminInsights(true);await loadInsights(true);showStatus('BlinQ Insight bol publikovaný.');}catch(error){if(message)message.textContent=error.message;}};
  }
  function planAvatarHtml(id,p={}){
    const style=String(p.avatar||id||'').toLowerCase(),src=marketingAvatarUrl(style);
    const glyph={rookie:'○',pro:'◇',elite:'✦',goat:'♛',legend:'♛'}[style]||'◇';
    return `<span class="plan-card-avatar plan-${escapeHtml(style)}${src?' has-photo':''}" aria-label="${escapeHtml((p.label||id).toUpperCase())} avatar">${src?`<img src="${escapeHtml(src)}" alt="" loading="lazy">`:`<b aria-hidden="true">${glyph}</b>`}</span>`;
  }
  function planAvatarPairHtml(id,p={}){
    const style=String(p.avatar||id||'').toLowerCase();
    const entry=state.ui?.assets?.account_avatars?.[style]||{};
    const left=avatarAssetSrc(entry.w||entry.default||entry.marketing||'');
    const right=avatarAssetSrc(entry.m||entry.default||entry.marketing||'');
    const unique=[...new Set([left,right].filter(Boolean))];
    if(!unique.length) return planAvatarHtml(id,p);
    return `<span class="plan-avatar-pair plan-${escapeHtml(style)}" aria-hidden="true">${unique.map((src,idx)=>`<span class="plan-avatar-chip${idx===1?' is-back':''}"><img src="${escapeHtml(src)}" alt="" loading="lazy"></span>`).join('')}</span>`;
  }
  function planEyebrowHtml(plan={}){
    const value=Object.prototype.hasOwnProperty.call(plan,'eyebrow')?String(plan.eyebrow??'').trim():'';
    return value?`<small>${escapeHtml(value)}</small>`:'';
  }
  function renderPlanCardsForAccount(){
    const a=state.feed?.account||{},status=String(a.status||'expired').toLowerCase(),current=accountPlan();
    const plans=membershipHierarchy.map(id=>[id,state.ui?.plans?.[id]||{}]);
    return `<div class="account-plan-grid">${plans.map(([id,p])=>{const url=safeExternalUrl(p.url),active=status!=='expired'&&current===id,rookieUnavailable=id==='rookie'&&current!=='rookie'&&status!=='expired',disabled=p.enabled===false,unavailable=!active&&(rookieUnavailable||disabled),restricted=Boolean(p.invite_only||p.verified_only),title=publicPlanLabel(id,p.card_title||p.label||id.toUpperCase()),detail=String(p.description||'').trim();let action='';if(active)action='<span class="membership-current">AKTUÁLNY</span>';else if(unavailable)action=`<span class="membership-unavailable">${escapeHtml(lcopy('Unavailable','Nedostupné','Nedostupné'))}</span>`;else if(id==='rookie'&&status==='expired')action=`<button class="btn btn-primary membership-cta" type="button" data-reactivate-free>${escapeHtml(lcopy('Switch to FREE','Prejsť na FREE','Přejít na FREE'))} →</button>`;else if(restricted){const invite=safeExternalUrl(p.invite_url||p.url);action=invite?`<a class="btn btn-ghost membership-cta invite-only" href="${escapeHtml(invite)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Požiadať o prístup')} →</a>`:`<button class="btn btn-ghost membership-cta invite-only" type="button" data-goat-request>${escapeHtml(p.cta_label||'Požiadať o prístup')}</button>`;}else if(url)action=`<a class="btn btn-primary membership-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Upgrade')} →</a>`;else action=`<button class="btn btn-primary membership-cta" type="button" data-plan-link-missing="${escapeHtml(id)}">${escapeHtml(p.cta_label||'Upgrade')} →</button>`;return `<article class="membership-card plan-${escapeHtml(id)}${active?' current-plan':''}${restricted?' restricted-plan':''}${unavailable?' is-unavailable-plan':''}"${unavailable?' aria-disabled="true"':''}>${planAvatarPairHtml(id,p)}<div class="membership-card-copy">${planEyebrowHtml(p)}<strong>${escapeHtml(title)}</strong>${detail?`<p>${escapeHtml(detail)}</p>`:''}</div>${restricted&&!unavailable?'<span class="membership-badge">INVITE ONLY</span>':''}${action}</article>`}).join('')}</div>`;
  }
  function renderAccountModal(){
    const a=state.feed?.account||{},status=String(a.status||'expired').toLowerCase(),plan=accountPlan(),planCfg=state.ui?.plans?.[plan]||{},planLabel=plan==='rookie'?publicPlanLabel('rookie'):(a.plan_label||planCfg.label||plan);
    const verified=a.email_verified===true;
    const expiry=status==='lifetime'?'Doživotne':a.expires_at?`${remainingLabel(a.expires_at)} zostáva`:(status==='active'?'Bez časového obmedzenia':'Bez aktívneho prístupu');
    const tg=String(a.telegram_nick||'').trim();
    const plans=membershipHierarchy.map(id=>{
      const p=state.ui.plans[id]||{},url=safeExternalUrl(p.url||''),invite=safeExternalUrl(p.invite_url||p.url||''),current=status!=='expired'&&id===plan,rookieUnavailable=id==='rookie'&&plan!=='rookie'&&status!=='expired',disabled=p.enabled===false,unavailable=!current&&(rookieUnavailable||disabled);
      const action=current
        ?'<span class="account-plan-current">AKTUÁLNY</span>'
        :(unavailable?`<span class="account-plan-unavailable">${escapeHtml(lcopy('Unavailable','Nedostupné','Nedostupné'))}</span>`:(id==='rookie'&&status==='expired'?`<button class="account-plan-upgrade account-plan-free" type="button" data-reactivate-free>${escapeHtml(lcopy('Switch to FREE','Prejsť na FREE','Přejít na FREE'))} →</button>`:(p.invite_only?(invite?`<a class="account-plan-upgrade" href="${escapeHtml(invite)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Upgrade')} →</a>`:`<button class="account-plan-upgrade" type="button" data-goat-request>${escapeHtml(p.cta_label||'Upgrade')} →</button>`):(url?`<a class="account-plan-upgrade" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Upgrade')} →</a>`:`<button class="account-plan-upgrade" type="button" data-plan-link-missing="${escapeHtml(id)}">${escapeHtml(p.cta_label||'Upgrade')} →</button>`))));
      const detail=String(p.description||'').trim();
      return `<article class="account-modal-plan plan-${escapeHtml(id)}${current?' is-current':''}${unavailable?' is-unavailable-plan':''}"${unavailable?' aria-disabled="true"':''}>${planAvatarPairHtml(id,p)}<div class="account-modal-plan-copy">${planEyebrowHtml(p)}<strong>${escapeHtml(publicPlanLabel(id,p.card_title||p.label||id.toUpperCase()))}</strong>${detail?`<span>${escapeHtml(detail)}</span>`:''}</div>${action}</article>`;
    }).join('');
    return `<div class="account-modal-head"><div><small>BLINQ ÚČET</small><h2 id="accountDialogTitle">Tvoj BlinQ účet</h2><p>Spravuj profil, prístup a členskú úroveň na jednom mieste.</p></div></div>
      <form id="accountModalProfileForm" class="account-modal-main-card account-modal-main-card-v3">
        <div class="account-modal-access"><div class="account-modal-avatar" id="accountModalAvatar">${escapeHtml(accountAvatarFallback(a))}</div><div class="account-access-copy"><small>AKTUÁLNY PRÍSTUP</small><strong>${escapeHtml(planLabel)}</strong><span class="account-access-status"><i></i>${escapeHtml(status==='lifetime'?'Aktívny · doživotne':status==='active'?'Aktívny':expiry)}</span></div></div>
        <div class="account-profile-facts account-profile-facts-v3"><span class="account-email-fact"><small>Registrovaný e-mail</small><strong>${escapeHtml(a.email||'—')}</strong><b class="account-verified ${verified?'is-verified':'needs-verification'}">${verified?'✓ E-mail overený':'! E-mail neoverený'}</b></span><span><small>Telegram nick</small><strong>${escapeHtml(tg||'Nenastavený')}</strong></span><span><small>Úroveň</small><strong>${escapeHtml(planLabel)}</strong></span><span><small>Platnosť prístupu</small><strong>${escapeHtml(expiry)}</strong></span></div>
        <div class="account-profile-editor"><div class="account-profile-editor-head"><small>UPRAVIŤ PROFIL</small><span>${verified?'Overený účet':'Overenie čaká'}</span></div><label class="account-inline-field account-inline-telegram"><span>${adminTelegramIcon()} Telegram nick</span><input id="accountModalTelegram" maxlength="33" value="${escapeHtml(tg)}" placeholder="@username"></label><div class="account-inline-field account-inline-avatar"><span>Avatar</span><div class="avatar-sex-toggle" role="group" aria-label="Avatar"><button type="button" data-avatar-variant="m" class="${a.avatar_variant==='w'?'':'is-active'}" aria-label="Mužský avatar" aria-pressed="${a.avatar_variant==='w'?'false':'true'}">♂</button><button type="button" data-avatar-variant="w" class="${a.avatar_variant==='w'?'is-active':''}" aria-label="Ženský avatar" aria-pressed="${a.avatar_variant==='w'?'true':'false'}">♀</button></div><input id="accountModalAvatarVariant" type="hidden" value="${a.avatar_variant==='w'?'w':'m'}"></div><button class="btn btn-primary account-profile-save" type="submit">Uložiť profil</button><p id="accountModalMessage" class="form-message account-inline-message"></p></div>
      </form>
      <div class="account-modal-plans"><div class="account-modal-section-title"><div><small>BLINQ ČLENSTVO</small><h3>Vyber si svoju úroveň</h3></div><span>Každá úroveň prináša iný rozsah dát, funkcií a prístupu.</span></div>${plans}</div>`;
  }
  async function reactivateFreeMembership(messageNode=null){
    const node=messageNode||$('accountModalMessage')||$('accountProfileMessage');
    if(node)node.textContent=lcopy('Switching to FREE…','Prepínam na FREE…','Přepínám na FREE…');
    try{
      await BlinqAuth.reactivateFree();
      if(node)node.textContent=lcopy('FREE access is active.','FREE prístup je aktívny.','FREE přístup je aktivní.');
      await loadFeed(false);
      return true;
    }catch(error){if(node)node.textContent=error.message;return false;}
  }
  function openAccountDialog(){
    const d=$('accountDialog'),host=$('accountDialogContent');if(!d||!host)return;host.innerHTML=renderAccountModal();setAccountAvatar($('accountModalAvatar'),state.feed?.account||{});
    const form=$('accountModalProfileForm');if(form)form.onsubmit=async e=>{e.preventDefault();const m=$('accountModalMessage');m.textContent='Ukladám…';try{await BlinqAuth.update({data:{telegram_nick:$('accountModalTelegram').value.trim(),blinq_avatar_variant:$('accountModalAvatarVariant').value}});m.textContent='Profil uložený.';await loadFeed(false);openAccountDialog();}catch(err){m.textContent=err.message;}};
    host.querySelectorAll('[data-avatar-variant]').forEach(button=>button.onclick=()=>{const value=button.dataset.avatarVariant||'m',input=$('accountModalAvatarVariant');if(input)input.value=value;host.querySelectorAll('[data-avatar-variant]').forEach(node=>{const active=node===button;node.classList.toggle('is-active',active);node.setAttribute('aria-pressed',active?'true':'false');});setAccountAvatar($('accountModalAvatar'),{...(state.feed?.account||{}),avatar_variant:value});});
    host.querySelectorAll('[data-plan-link-missing]').forEach(button=>button.onclick=()=>showStatus(`Doplň odkaz pre ${button.dataset.planLinkMissing?.toUpperCase()||'plán'} v Admin → Členstvá.`));
    host.querySelectorAll('[data-reactivate-free]').forEach(button=>button.onclick=async()=>{button.disabled=true;const ok=await reactivateFreeMembership($('accountModalMessage'));button.disabled=false;if(ok)openAccountDialog();});
    const reset=$('accountModalPassword');if(reset)reset.onclick=async()=>{try{await BlinqAuth.reset(state.feed?.account?.email||'');showStatus('E-mail na obnovu hesla bol odoslaný.');}catch(err){showStatus(err.message);}};
    const out=$('accountModalSignOut');if(out)out.onclick=()=>{d.close();signOutCurrentSession();};
    if(!d.open)d.showModal();
  }
  function renderAccountPage(){
    const a=state.feed?.account||{},status=String(a.status||'expired').toLowerCase(),plan=accountPlan(),planLabel=plan==='rookie'?publicPlanLabel('rookie'):(a.plan_label||state.ui?.plans?.[plan]?.label||plan);
    const pushEligible=Boolean(a.is_admin||String(a.role||'').toLowerCase()==='admin'||(membershipHierarchy.includes(plan)&&['trial','active','lifetime'].includes(status)));
    const expiry=status==='lifetime'?publicText('Lifetime access'):a.expires_at?`${remainingLabel(a.expires_at)} ${locale==='cz'?'zbývá':'zostáva'}`:(status==='active'?publicText('Active'):publicText('No active access'));
    const verified=a.email_verified===true;
    return `<section class="account-overview account-overview-v676">
      <article class="account-profile-card account-profile-card-v676"><div class="account-profile-head"><span class="avatar account-page-avatar" id="accountPageAvatar">${escapeHtml(accountAvatarFallback(a))}</span><div><span class="account-card-kicker">BLINQ ÚČET</span><h2>${escapeHtml(a.email||'BlinQ účet')}</h2><p>${escapeHtml(a.telegram_nick||'Telegram prezývka zatiaľ nie je nastavená')}</p></div><span class="account-verified ${verified?'is-verified':'needs-verification'}">${escapeHtml(publicText(verified?'✓ Email verified':'! Email not verified'))}</span></div>
      <form id="accountProfileForm" class="account-profile-form account-profile-form-v676"><label><span class="telegram-label">${adminTelegramIcon()} Telegram</span><input id="accountTelegramNick" maxlength="33" value="${escapeHtml(a.telegram_nick||'')}" placeholder="@username"></label><div class="account-page-avatar-choice"><span>Avatar</span><div class="avatar-sex-toggle" role="group" aria-label="Avatar"><button type="button" data-avatar-page-variant="m" class="${a.avatar_variant==='w'?'':'is-active'}" aria-label="Mužský avatar" aria-pressed="${a.avatar_variant==='w'?'false':'true'}">♂</button><button type="button" data-avatar-page-variant="w" class="${a.avatar_variant==='w'?'is-active':''}" aria-label="Ženský avatar" aria-pressed="${a.avatar_variant==='w'?'true':'false'}">♀</button></div><input id="accountAvatarVariant" type="hidden" value="${a.avatar_variant==='w'?'w':'m'}"></div><button class="btn btn-primary" type="submit">Uložiť profil</button><p class="form-message" id="accountProfileMessage"></p></form></article>
      <article class="account-access-card"><div class="account-access-top"><span class="account-card-kicker">AKTUÁLNY PRÍSTUP</span>${planAvatarHtml(plan,state.ui?.plans?.[plan]||{})}</div><h2>${escapeHtml(planLabel)}</h2><p class="account-access-status">${escapeHtml(status==='trial'?'Rookie Trial':status==='lifetime'?'Doživotný':status==='active'?'Aktívny':'Expirovaný')}</p><div class="account-facts"><span><small>Prístup</small><strong>${escapeHtml(expiry)}</strong></span><span><small>Člen od</small><strong>${escapeHtml(a.created_at?fmtDate(a.created_at):'—')}</strong></span><span><small>Zabezpečenie</small><strong>${verified?'E-mail overený':'Vyžaduje overenie'}</strong></span></div><div class="account-access-actions"><button class="btn btn-ghost" id="accountPasswordReset" type="button">Obnoviť heslo</button><button class="btn btn-ghost account-signout" id="accountSignOut" type="button">Odhlásiť sa</button></div></article>
      <article class="account-push-card${pushEligible?'':' is-locked'}"><div><span class="account-card-kicker">LIVE & INFO PUSH</span><h2>Okamžité upozornenia</h2><p>${pushEligible?'Dostaneš systémovú notifikáciu aj keď BlinQ práve nemáš otvorený.':'INFO push je dostupný pre aktívne členstvo; LIVE sa riadi nastaveným minimálnym levelom.'}</p></div><div class="account-push-actions"><button class="btn ${pushEligible?'btn-primary':'btn-ghost'}" id="accountPushToggle" type="button" ${pushEligible?'':'disabled'}>Skontrolovať push</button><span id="accountPushStatus">${pushEligible?'Kontrolujem stav…':'Dostupné pre aktívne členstvo'}</span></div></article>
    </section><section class="account-membership-page"><div class="account-membership-heading"><div><small>BLINQ ČLENSTVO</small><h2>Plány</h2></div></div>${renderPlanCardsForAccount()}</section>`;
  }
  function base64UrlToUint8Array(value){
    const padding='='.repeat((4-String(value||'').length%4)%4),base64=(String(value||'')+padding).replace(/-/g,'+').replace(/_/g,'/');
    const raw=atob(base64);return Uint8Array.from([...raw].map(ch=>ch.charCodeAt(0)));
  }
  async function localPushSubscription(){
    if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window))return null;
    const registration=await navigator.serviceWorker.getRegistration('/');
    return registration?registration.pushManager.getSubscription():null;
  }
  async function refreshPushControl(){
    const button=$('accountPushToggle'),status=$('accountPushStatus');if(!button||!status||button.disabled)return;
    if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){button.disabled=true;button.textContent='Nepodporované';status.textContent='Tento prehliadač nepodporuje Web Push.';return;}
    try{
      const cfg=await BlinqAuth.pushConfig();state.pushConfig=cfg;
      if(!cfg?.eligible){button.disabled=true;button.textContent='NEDOSTUPNÉ';status.textContent='Vyžaduje aktívne členstvo.';return;}
      if(!cfg?.enabled){button.disabled=true;button.textContent='Čaká na nastavenie';status.textContent='Push server ešte nemá VAPID kľúče.';return;}
      const sub=await localPushSubscription();
      if(sub&&Notification.permission==='granted'){button.dataset.pushEnabled='1';button.textContent='Vypnúť upozornenia';button.classList.remove('btn-primary');button.classList.add('btn-ghost');status.textContent='Push upozornenia sú na tomto zariadení zapnuté.';}
      else{button.dataset.pushEnabled='0';button.textContent='Zapnúť upozornenia';button.classList.add('btn-primary');button.classList.remove('btn-ghost');status.textContent=Notification.permission==='denied'?'Notifikácie sú zablokované v nastavení prehliadača.':'Zapni LIVE a INFO notifikácie pre toto zariadenie.';}
    }catch(error){status.textContent=error.message||'Stav push notifikácií sa nepodarilo načítať.';}
  }
  async function toggleBrowserPush(){
    const button=$('accountPushToggle'),status=$('accountPushStatus');if(!button||state.pushBusy)return;state.pushBusy=true;button.disabled=true;
    try{
      const cfg=state.pushConfig||await BlinqAuth.pushConfig();
      if(!cfg?.enabled)throw new Error('Browser push ešte nie je nakonfigurovaný na serveri.');
      const registration=await navigator.serviceWorker.register('/blinq-sw.js',{scope:'/',updateViaCache:'none'});
      await navigator.serviceWorker.ready;
      let subscription=await registration.pushManager.getSubscription();
      if(button.dataset.pushEnabled==='1'&&subscription){
        await BlinqAuth.pushUnsubscribe(subscription.endpoint);await subscription.unsubscribe();subscription=null;
        status.textContent='Push upozornenia sú vypnuté.';
      }else{
        const permission=await Notification.requestPermission();
        if(permission!=='granted')throw new Error('Povolenie pre notifikácie nebolo udelené.');
        if(!subscription)subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:base64UrlToUint8Array(cfg.public_key)});
        await BlinqAuth.pushSubscribe(subscription.toJSON());
        status.textContent='Push upozornenia sú zapnuté.';
      }
    }catch(error){status.textContent=error.message||'Push notifikácie sa nepodarilo zmeniť.';}
    finally{state.pushBusy=false;button.disabled=false;await refreshPushControl();}
  }
  function wireAccountPage(){
    const a=state.feed?.account||{};setAccountAvatar($('accountPageAvatar'),a);
    const form=$('accountProfileForm');if(form)form.onsubmit=async event=>{event.preventDefault();const message=$('accountProfileMessage');message.textContent=publicText('Saving…');try{await BlinqAuth.update({data:{telegram_nick:$('accountTelegramNick').value.trim(),blinq_avatar_variant:$('accountAvatarVariant').value}});message.textContent=publicText('Profile updated.');await loadFeed(false);}catch(error){message.textContent=error.message;}};
    document.querySelectorAll('[data-avatar-page-variant]').forEach(button=>button.onclick=()=>{const value=button.dataset.avatarPageVariant||'m',input=$('accountAvatarVariant');if(input)input.value=value;document.querySelectorAll('[data-avatar-page-variant]').forEach(node=>{const active=node===button;node.classList.toggle('is-active',active);node.setAttribute('aria-pressed',active?'true':'false');});setAccountAvatar($('accountPageAvatar'),{...a,avatar_variant:value});});
    document.querySelectorAll('[data-plan-link-missing]').forEach(button=>button.onclick=()=>{const message=$('accountProfileMessage');if(message)message.textContent=`Doplň odkaz pre ${button.dataset.planLinkMissing?.toUpperCase()||'plán'} v Admin → Členstvá.`;});
    document.querySelectorAll('[data-reactivate-free]').forEach(button=>button.onclick=async()=>{button.disabled=true;const ok=await reactivateFreeMembership($('accountProfileMessage'));button.disabled=false;if(ok)setRoute('account',false);});
    const reset=$('accountPasswordReset');if(reset)reset.onclick=async()=>{const message=$('accountProfileMessage');message.textContent=publicText('Sending recovery email…');try{await BlinqAuth.reset(a.email);message.textContent=publicText('Password reset email sent.');}catch(error){message.textContent=error.message;}};
    const logout=$('accountSignOut');if(logout)logout.onclick=signOutCurrentSession;
    const pushToggle=$('accountPushToggle');if(pushToggle&&!pushToggle.disabled){pushToggle.onclick=toggleBrowserPush;refreshPushControl();}
    document.querySelectorAll('[data-goat-request]').forEach(button=>button.onclick=()=>{const nick=String(state.feed?.account?.telegram_nick||'').trim();const input=$('accountTelegramNick');const message=$('accountProfileMessage');if(!nick){if(message)message.textContent=lcopy('Add your Telegram nickname first, save the profile, then request GOAT access.','Najprv doplň Telegram prezývku, ulož profil a potom požiadaj o GOAT prístup.','Nejdřív doplň Telegram přezdívku, ulož profil a potom požádej o GOAT přístup.');input?.focus();return;}if(message)message.textContent=lcopy(`GOAT is invite-only. Your Telegram ${nick.startsWith('@')?nick:`@${nick}`} is saved.`,`GOAT je iba na pozvánku. Telegram ${nick.startsWith('@')?nick:`@${nick}`} máš uložený.`,`GOAT je pouze na pozvánku. Telegram ${nick.startsWith('@')?nick:`@${nick}`} máš uložený.`);});
  }
  function primeTableRows(){ return rankedPredictions(); }
  function aceProjectionTable(rows){
    if(!rows.length)return '<div class="state-card">No Aces / Double Faults projections are available yet.</div>';
    const body=rows.map(row=>{const p1=row?.player1?.name||row?.player1_name||'Player 1',p2=row?.player2?.name||row?.player2_name||'Player 2',projection=Number(row?.projection),opponent=Number(row?.opponent_projection),gap=Number(row?.projection_gap),score=Number(row?.projection_confidence),samples=row?.projection_samples||{};return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(aceProjectionTypeLabel(row))}</td><td>${escapeHtml(row?.pick||row?.selection||'—')}</td><td>${Number.isFinite(projection)?projection.toFixed(1):'—'}</td><td>${Number.isFinite(opponent)?opponent.toFixed(1):'—'}</td><td>${Number.isFinite(gap)?`+${gap.toFixed(1)}`:'—'}</td><td>${Number.isFinite(score)?`${Math.round(score*100)}/100`:'—'}</td><td>${Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${samples.player1}/${samples.player2}`:'—'}</td></tr>`}).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Market</th><th>Projection pick</th><th>Proj.</th><th>Opp. proj.</th><th>Gap</th><th>Score</th><th>Data</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">Projection only. No bookmaker odds or ROI are inferred until a verified Aces/DF price source is available.</div>`;
  }
  function sgProjectionTable(rows){
    if(!rows.length)return '<div class="state-card">No Sets / Games projections are available yet.</div>';
    const body=rows.map(row=>{const p1=row?.player1?.name||row?.player1_name||'Player 1',p2=row?.player2?.name||row?.player2_name||'Player 2',projection=Number(row?.projection),reference=Number(row?.reference_projection??row?.baseline_projection),gap=Number(row?.projection_gap),score=Number(row?.projection_confidence),samples=row?.projection_samples||{},unit=String(row?.projection_unit||'');const projectionText=Number.isFinite(projection)?(unit==='probability'?pct(projection):`${projection.toFixed(1)} games`):'—';const referenceText=Number.isFinite(reference)?(unit==='probability'?pct(reference):`${reference.toFixed(1)} games`):'—';const gapText=Number.isFinite(gap)?(unit==='probability'?`${(gap*100).toFixed(1)} pp`:`${gap.toFixed(1)} games`):'—';return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(row?.market_type||String(row?.market||'').replaceAll('_',' '))}</td><td>${escapeHtml(row?.pick||row?.selection||'—')}</td><td>${escapeHtml(projectionText)}</td><td>${escapeHtml(referenceText)}</td><td>${escapeHtml(gapText)}</td><td>${Number.isFinite(score)?`${Math.round(score*100)}/100`:'—'}</td><td>${Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${samples.player1}/${samples.player2}`:'—'}</td></tr>`}).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Market</th><th>Projection pick</th><th>Projection</th><th>Baseline</th><th>Gap</th><th>Score</th><th>Data</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">Projection only. Structured historical set/game scores are used; bookmaker odds and ROI stay blank until that market layer is separately calibrated and validated.</div>`;
  }
  function genericTable(rows,key){
    if(key==='ace'&&rows.some(row=>row?.price_status==='projection_only'))return aceProjectionTable(rows);
    if(key==='sg'&&rows.some(row=>row?.price_status==='projection_only'))return sgProjectionTable(rows);
    if(!rows.length)return '<div class="state-card">No published data are available for this section yet.</div>';
    if(key==='top_daily'){const body=rows.map(row=>{const p1=row?.p1||row?.player1?.name||row?.player1_name||'Player 1',p2=row?.p2||row?.player2?.name||row?.player2_name||'Player 2';const probability=marketProbability(row),depth=Number(row?.data_depth),q=row?.quality||{},s1=Number(q?.player1?.surface_matches),s2=Number(q?.player2?.surface_matches),m1=Number(q?.player1?.matches),m2=Number(q?.player2?.matches),odds=Number(row?.odds),pick=row?.pick||row?.selection||row?.prediction||'—';return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(pick)}</td><td>${probability==null?'—':pct(probability)}</td><td>${Number.isFinite(depth)?pct(depth):'—'}</td><td>${Number.isFinite(s1)&&Number.isFinite(s2)?`${s1}/${s2}`:'—'}</td><td>${Number.isFinite(m1)&&Number.isFinite(m2)?`${m1}/${m2}`:'—'}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td></tr>`}).join('');return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Prediction</th><th>Probability</th><th>Data depth</th><th>Surface sample</th><th>Overall sample</th><th>Odds</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">TOP predictions are confidence-first. Elo, surface Elo, H2H and form are already represented inside model probability.</div>`;}
    const body=rows.map(row=>{
      const p1=row?.p1||row?.player1?.name||row?.player1_name||'Player 1',p2=row?.p2||row?.player2?.name||row?.player2_name||'Player 2';
      const rawProb=row?.probability!=null?Number(row.probability):marketProbability(row); const probability=Number.isFinite(rawProb)?(rawProb>1?rawProb/100:rawProb):null; const pick=row?.pick||row?.selection||row?.prediction||'—';
      const odds=Number(row?.odds);
      return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(pick)}</td><td>${probability==null?'—':pct(probability)}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td></tr>`;
    }).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Prediction</th><th>Probability</th><th>Odds</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }
  function renderDashboardResultsPreview(){
    const host=$('resultsPreviewContent');if(!host)return;
    const rows=(state.feed?.results||[]).filter(row=>typeof row?.result?.correct==='boolean');
    const wins=rows.filter(row=>row.result.correct===true).length,losses=Math.max(0,rows.length-wins),hit=rows.length?wins/rows.length:null;
    const perf=state.feed?.betting_performance?.overall||state.feed?.performance?.betting?.overall||{};
    const roi=Number(perf.roi),units=Number(perf.profit_units);
    host.innerHTML=`<div class="results-preview-metrics"><span><small>${escapeHtml(publicText('Record'))}</small><strong>${wins}-${losses}</strong></span><span><small>${escapeHtml(publicText('Hit rate'))}</small><strong>${hit==null?'—':pct(hit)}</strong></span><span><small>ROI</small><strong>${Number.isFinite(roi)?pct(roi):'—'}</strong></span><span><small>${escapeHtml(publicText('Units'))}</small><strong>${Number.isFinite(units)?`${units>=0?'+':''}${units.toFixed(2)}u`:'—'}</strong></span></div>`;
    const count=$('resultsPreviewCount');if(count)count.textContent=publicText(`${rows.length} settled`);const cardCount=$('resultsSeeAllCardCount');if(cardCount)cardCount.textContent=publicText(`${rows.length} settled`);
  }

  function resultsSummary(){
    const rows=filteredResults(),category=state.resultsFilters?.category||'all',m=localResultMetrics(rows,category),projectionCategory=['ace','double_faults','sg','sets','games'].includes(category);
    if(projectionCategory){
      const typeLabel=category==='ace'?lcopy('ACES','ESÁ','ESA'):category==='double_faults'?lcopy('DOUBLE FAULTS','DVOJCHYBY','DVOJCHYBY'):category==='sets'?lcopy('SETS','SETY','SETY'):category==='games'?lcopy('GAMES','GAMY','GEMY'):lcopy('SETS & GAMES','SETY & GAMY','SETY & GEMY');
      return metricCards([[lcopy('Result','Výsledok','Výsledek'),`${m.wins}-${m.losses}`,lcopy('WIN - LOSS','VÝHRA - PREHRA','VÝHRA - PREHRA')],[publicText('Hit rate'),m.hit==null?'—':pct(m.hit),lcopy('settled projection sample','vyhodnotená vzorka projekcií','vyhodnocený vzorek projekcí')],[lcopy('Projection type','Typ projekcie','Typ projekce'),typeLabel,lcopy('Projection only · no invented odds or ROI','Iba projekcia · bez vymysleného kurzu a ROI','Pouze projekce · bez vymyšleného kurzu a ROI')],[publicText('Sample'),String(m.sample),lcopy('published projections','publikované projekcie','publikované projekce')]]);
    }
    return metricCards([[publicText('Record'),`${m.wins}-${m.losses}`,lcopy('wins - losses','výhry - prehry','výhry - prohry')],[publicText('Hit rate'),m.hit==null?'—':pct(m.hit),lcopy('filtered settled sample','filtrovaná vyhodnotená vzorka','filtrovaný vyhodnocený vzorek')],[publicText('Avg Odds'),m.avgOdds==null?'—':m.avgOdds.toFixed(2),m.oddsSample?lcopy(`${m.oddsSample} odds-backed picks`,`${m.oddsSample} predikcií s kurzom`,`${m.oddsSample} predikcí s kurzem`):publicText('no issued odds')],['ROI',m.roi==null?'—':pct(m.roi),publicText('flat 1u on issued odds')],[publicText('Units'),m.oddsSample?`${m.profit>=0?'+':''}${m.profit.toFixed(2)}u`:'—',publicText('profit · flat 1u stake')],[publicText('Sample'),String(m.sample),publicText('settled published rows')]]);
  }

  function primeDetailCard(m,index=0){
    const photo1=playerPhotoSource(m.raw||{},m.raw?.player1||{},'player1')||safePhotoUrl(m.p1Photo),photo2=playerPhotoSource(m.raw||{},m.raw?.player2||{},'player2')||safePhotoUrl(m.p2Photo);
    const avatar=(src,name)=>playerAvatarHtml(src,name,m.tour,'','player-avatar');
    const metrics=[[publicText('Odds'),Number.isFinite(m.odds)?m.odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),dataDepthMetric(m.raw||{})],[publicText('Surface'),surfaceSampleLabel(m.raw||{})]];
    const metricHtml=metrics.map(([label,value])=>{const raw=String(value);const tone=raw.trim().startsWith('+')?' metric-positive':raw.trim().startsWith('-')?' metric-negative':'';return `<span class="card-metric${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(raw)}</strong></span>`}).join('');
    return `<article class="prediction-card featured detail-pick-card match-card-v3"><div class="card-meta match-card-meta"><span class="tour">${escapeHtml(m.tour)} ${escapeHtml(m.tournament)}</span><span class="time">${timeDateHtml(m.date,'card-time-stack')}</span><span class="surface">${escapeHtml(String(m.surface||'').replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row match-players-row"><div class="player">${avatar(photo1,m.p1)}<strong class="player-name">${escapeHtml(m.p1)}</strong></div><div class="vs match-vs">VS</div><div class="player">${avatar(photo2,m.p2)}<strong class="player-name">${escapeHtml(m.p2)}</strong></div></div><div class="pick-row match-pick-row"><div class="pick-copy"><small>${escapeHtml(lcopy('BlinQ prediction','Naša predikcia','Naše predikce'))}</small><strong class="pick-name">${escapeHtml(m.pick)}</strong></div><div class="pick-score"><div class="probability">${pct(m.probability)}</div><span class="confidence ${escapeHtml(m.confidence)}">${escapeHtml(confidenceLabel(m.confidence))}</span></div></div><div class="card-metrics-bar match-kpi-bar">${metricHtml}</div></article>`;
  }
  function detailCards(rows,key){
    const cap=Math.max(3,Math.min(5,Number(state.ui?.dashboard?.detail_pick_limit)||5));
    const list=(rows||[]).slice(0,cap);
    if(!list.length)return `<div class="state-card">${escapeHtml(publicText('No published predictions are available in this section yet.'))}</div>`;
    const cards=key==='prime'?list.map(primeDetailCard).join(''):list.map((row,index)=>marketPreviewCard(row,key,index,false)).join('');
    return `<div class="detail-picks-grid">${cards}</div><div class="detail-picks-foot"><span>${escapeHtml(publicText(`Showing ${list.length} of ${(rows||[]).length} published pick${(rows||[]).length===1?'':'s'}.`))}</span><button type="button" class="btn btn-ghost" data-route="predictions">${escapeHtml(publicText('← Dashboard'))}</button></div>`;
  }


  function contentLocale(){return ['sk','cz','en'].includes(locale)?locale:'sk';}
  function sitePage(route){
    const lang=contentLocale(), pages=state.siteContent?.pages||{};
    const local=pages?.[lang]?.[route];
    return local&&Object.keys(local).length?local:pages?.sk?.[route]||null;
  }
  function renderSiteContentPage(route){
    const page=sitePage(route);if(!page)return '';
    const updated=state.siteContent?.updated_at||'';
    const sections=(page.sections||[]).map((section,index)=>`<article class="content-section-card"><span class="content-section-index">${String(index+1).padStart(2,'0')}</span><div><h3>${escapeHtml(section.title||'')}</h3><p>${escapeHtml(section.body||'')}</p></div></article>`).join('');
    const faqs=(page.faq||[]).map((item,index)=>`<details class="content-faq" ${index===0?'open':''}><summary><span>${escapeHtml(item.q||'')}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 8 4 4 4-4"></path></svg></summary><p>${escapeHtml(item.a||'')}</p></details>`).join('');
    const operator=state.siteContent?.operator||{};
    const legalMeta=['terms','privacy','cookies'].includes(route)?`<div class="content-meta"><span>${escapeHtml(lcopy('Last updated','Posledná aktualizácia','Poslední aktualizace'))}: <strong>${escapeHtml(updated||'—')}</strong></span>${operator.legal_name&&!String(operator.legal_name).startsWith('DOPLNIŤ')?`<span>${escapeHtml(operator.legal_name)}</span>`:''}</div>`:'';
    const cookieSettings=route==='cookies'?`<div class="cookie-settings-card"><strong>${escapeHtml(lcopy('Cookie preferences','Nastavenia cookies','Nastavení cookies'))}</strong><p>${escapeHtml(lcopy('You can change optional analytics consent at any time.','Súhlas s nepovinnou analytikou môžete kedykoľvek zmeniť.','Souhlas s nepovinnou analytikou můžete kdykoli změnit.'))}</p><div><button class="btn btn-ghost" type="button" data-cookie-choice="essential">${escapeHtml(lcopy('Essential only','Iba nevyhnutné','Pouze nezbytné'))}</button><button class="btn btn-primary" type="button" data-cookie-choice="analytics">${escapeHtml(lcopy('Allow analytics','Povoliť analytiku','Povolit analytiku'))}</button></div></div>`:'';
    return `<section class="content-page"><header class="content-page-hero"><span>${escapeHtml(page.eyebrow||'BLINQ')}</span><h2>${escapeHtml(page.title||'')}</h2><p>${escapeHtml(page.subtitle||'')}</p>${legalMeta}</header>${sections?`<div class="content-section-grid">${sections}</div>`:''}${faqs?`<div class="content-faq-list">${faqs}</div>`:''}${cookieSettings}</section>`;
  }
  function renderRoute(route){
    const host=$('routePanel'),feed=state.feed,p=feed.performance||{},history=feed.history||{},report=feed.model?.report||{}; let body='';
    if(route==='admin'){host.innerHTML=renderAdminRoute();wireAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='system')loadAdminDiagnostics();return;}
    if(route==='prime'){
      const r=state.ui?.market_rules?.prime||{};
      const desc=lcopy(`Accuracy first · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · depth ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · surface ${Number(r.min_surface_matches||5)}+/player · preferred odds ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)}, with model and data-quality guardrails.`,`Presnosť na prvom mieste · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · hĺbka dát ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasov/hráč · preferovaný kurz ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)} · pravidlá modelu a kvality dát zostávajú aktívne.`,`Přesnost na prvním místě · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · hloubka dat ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasů/hráč · preferovaný kurz ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)} · pravidla modelu a kvality dat zůstávají aktivní.`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Short Odds rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(primeTableRows(),'prime')}`;
    }
    else if(route==='top_daily'){
      const r=state.ui?.market_rules?.top_daily||{},day=state.feed?.market_selection?.odds_report?.betting_day||'current';
      const desc=lcopy(`BlinQ publication day ${day} · CORE starts at 68% / 1.50. If fewer than 5 TOP picks remain after Value priority, thresholds relax stepwise only until 5 qualify, with a hard floor of 60% / 1.45. Data-depth and surface guardrails stay active.`,`Publikačný deň BlinQ ${day} · CORE začína na 68 % / 1,50. Ak po priorite Value ostane menej ako 5 TOP pickov, hranice sa uvoľňujú po krokoch iba dovtedy, kým sa nekvalifikuje 5 pickov; absolútne minimum je 60 % / 1,45. Pravidlá hĺbky dát a povrchu zostávajú aktívne.`,`Publikační den BlinQ ${day} · CORE začíná na 68 % / 1,50. Pokud po prioritě Value zůstane méně než 5 TOP picků, hranice se uvolňují po krocích jen do chvíle, kdy se kvalifikuje 5 picků; absolutní minimum je 60 % / 1,45. Pravidla hloubky dat a povrchu zůstávají aktivní.`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('TOP Predictions rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(marketRows('top_daily'),'top_daily')}`;
    }
    else if(route==='value'){
      const r=state.ui?.market_rules?.value||{},tiers=Array.isArray(r.fallback_tiers)?r.fallback_tiers.length:0;
      const desc=lcopy(`Value selection. Primary target: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · odds ${Number(r.min_odds||1.80).toFixed(2)}+. ${tiers?`${tiers} configured fallback tiers may widen market thresholds while preserving model/data guardrails.`:'No fallback tier is configured.'}`,`Value výber. Hlavný cieľ: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · kurz ${Number(r.min_odds||1.80).toFixed(2)}+. ${tiers?`${tiers} nastavených fallback úrovní môže rozšíriť trhové limity, pričom ostávajú zachované pravidlá modelu a dát.`:'Fallback úroveň nie je nastavená.'}`,`Value výběr. Hlavní cíl: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · kurz ${Number(r.min_odds||1.80).toFixed(2)}+. ${tiers?`${tiers} nastavených fallback úrovní může rozšířit tržní limity při zachování pravidel modelu a dat.`:'Fallback úroveň není nastavena.'}`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Value rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(marketRows('value'),'value')}`;
    }
    else if(route==='ace') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Aces / Double Faults'))}</strong><span>${escapeHtml(lcopy(`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time count projections from stored event statistics. Projection score is not a calibrated win probability; odds/ROI stay blank until a verified price source exists.`,`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time projekcií z uložených štatistík zápasov. Skóre projekcie nie je kalibrovaná pravdepodobnosť výhry; kurz/ROI ostávajú prázdne, kým nebude dostupný overený zdroj kurzov.`,`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time projekcí z uložených statistik zápasů. Skóre projekce není kalibrovaná pravděpodobnost výhry; kurz/ROI zůstávají prázdné, dokud nebude dostupný ověřený zdroj kurzů.`))}</span></div>${detailCards(marketRows('ace'),'ace')}`;
    else if(route==='sg') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Sets / Games'))}</strong><span>${escapeHtml(lcopy('Point-in-time projections from structured historical set/game scores. Sets use long-match probability; Games use projected total versus the ATP/WTA best-of baseline. No odds/ROI are inferred yet.','Point-in-time projekcie zo štruktúrovaných historických skóre setov/hier. Sety používajú pravdepodobnosť dlhého zápasu; hry používajú projektovaný celkový počet oproti ATP/WTA baseline. Kurz/ROI sa zatiaľ neodvodzujú.','Point-in-time projekce ze strukturovaných historických skóre setů/her. Sety používají pravděpodobnost dlouhého zápasu; hry používají projektovaný celkový počet oproti ATP/WTA baseline. Kurz/ROI se zatím neodvozují.'))}</span></div>${detailCards(marketRows('sg'),'sg')}`;
    else if(route==='doubles') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Doubles model'))}</strong><span>${escapeHtml(lcopy('Separate pair/team model only. Pair identity, pair history, individual strength, surface form and pair chemistry stay isolated from singles probabilities.','Iba samostatný model dvojíc/tímov. Identita dvojice, spoločná história, individuálna sila, forma na povrchu a súhra zostávajú oddelené od pravdepodobností dvojhry.','Pouze samostatný model dvojic/týmů. Identita dvojice, společná historie, individuální síla, forma na povrchu a souhra zůstávají oddělené od pravděpodobností dvouhry.'))}</span></div>${detailCards(marketRows('doubles'),'doubles')}`;
    else if(route==='results') body=resultsAccessAllowed()?(renderResultsFilters()+resultsSummary()+`<div class="route-sub results-section-head results-section-clean">${renderResults()}</div>`):resultsLockedCard();
    else if(route==='tournaments'){const names=[...new Set((feed.upcoming||[]).map(x=>x.tournament).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):escapeHtml(publicText('No upcoming tournament coverage is currently published.'))}</div>`;}
    else if(route==='players'){const names=[...new Set((feed.upcoming||[]).flatMap(x=>[x.player1?.name,x.player2?.name]).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):escapeHtml(publicText('No upcoming players are currently published.'))}</div>`;}
    else if(route==='stats') body=metricCards([[publicText('Vyhodnotené predikcie'),String(p.n??0),publicText('Published and scored')],[publicText('Accuracy'),p.accuracy!=null?pct(p.accuracy):'—',publicText('Observed results')],['Log loss',number(p.log_loss),publicText('Lower is better')],[publicText('Brier score'),number(p.brier_score),publicText('Probability quality')]])+`<div class="route-sub"><h3>${escapeHtml(publicText('Results'))}</h3>${renderResults()}</div>`;
    else if(route==='model'||route==='backtests'){const h=report.holdout||{},delta=report.delta_vs_elo||{};body=metricCards([[publicText('Model'),String(feed.model?.version||'—'),publicText('Production artifact')],['Holdout n',String(h.n??'—'),publicText('Chronological holdout')],['Holdout úspešnosť',h.accuracy!=null?pct(h.accuracy):'—',publicText('Evaluation report')],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—',publicText('Negative is better')]])+`<div class="route-sub static-copy"><h3>${escapeHtml(publicText('Data window'))}</h3><p>${escapeHtml(history.start?fmtDate(history.start):'—')} → ${escapeHtml(history.end?fmtDate(history.end):'—')} · ${escapeHtml(lcopy(`${history.matches??'—'} historical matches in the current serving metadata.`,`${history.matches??'—'} historických zápasov v aktuálnych metadátach.`,`${history.matches??'—'} historických zápasů v aktuálních metadatech.`))}</p><p>${escapeHtml(lcopy('No result here is presented as a guarantee. Holdout metrics describe a specific historical evaluation period.','Žiadny výsledok tu nie je prezentovaný ako záruka. Holdout metriky opisujú konkrétne historické obdobie vyhodnotenia.','Žádný výsledek zde není prezentován jako záruka. Holdout metriky popisují konkrétní historické období vyhodnocení.'))}</p></div>`;}
    else if(route==='account') body=renderAccountPage();
    else if(['how_blinq_works','methodology','model_data','faq','responsible_use','terms','privacy','cookies'].includes(route)) body=renderSiteContentPage(route);
    else body=`<div class="static-copy"><p>${escapeHtml(lcopy('This section is available in the BlinQ workspace.','Táto sekcia je dostupná v BlinQ.','Tato sekce je dostupná v BlinQ.'))}</p></div>`;
    host.innerHTML=`<div class="route-card route-card-clean">${body}</div>`; if(route!=='admin')translatePublicDom(host); window.BlinqUI.prepareRoute(host); if(route==='results')wireResultsFilters(); if(route==='account')wireAccountPage();  applyAccessStates(host);
  }

  function upgradePlanFacts(planId,plan={}){
    const label=String(plan.label||planId||'').trim()||'BlinQ';
    const access=String(plan.card_title||plan.description||plan.note||'').trim()||label;
    const duration=planIsUnlimited(planId,plan)?lcopy('No time limit','Bez časového obmedzenia','Bez časového omezení'):plan.lifetime?publicText('Lifetime'):Number.isFinite(Number(plan.duration_days))&&Number(plan.duration_days)>0?`${Math.trunc(Number(plan.duration_days))} ${locale==='cz'?'dní':locale==='sk'?'dní':'days'}`:publicText('Active membership');
    return [
      [publicText('Level'),label],
      [publicText('Access'),access],
      [publicText('Validity'),duration],
    ];
  }
  let accessHintTimer=0,accessHintHoverTimer=0,accessHintTarget=null,upgradeReturnTarget=null;
  function accessHintTrigger(node){
    if(node?.closest?.('#accessHint')||$('upgradeDialog')?.open)return null;
    return node?.closest?.('[data-upgrade-plan]:not([data-upgrade-explicit="1"])');
  }
  function accessHintDetails(planId='elite',sectionLabel=''){
    const levelName=String(upgradePlanLabel(planId)||planId).replace(/^BlinQ\s+/i,'').toUpperCase();
    const section=String(sectionLabel||'').trim();
    return {levelName,title:lcopy(`Available from ${levelName}`,`Dostupné od úrovne ${levelName}`,`Dostupné od úrovně ${levelName}`),text:section?lcopy(`Upgrade for full access to ${section}.`,`Upgrade pre plný prístup k ${section}.`,`Upgrade pro plný přístup k ${section}.`):lcopy('Upgrade for full access.','Upgrade pre plný prístup.','Upgrade pro plný přístup.')};
  }
  function hideAccessHint(delay=0){
    clearTimeout(accessHintTimer);clearTimeout(accessHintHoverTimer);
    const run=()=>{const hint=$('accessHint');if(hint)hint.hidden=true;accessHintTarget=null;};
    if(delay)accessHintTimer=setTimeout(run,delay);else run();
  }
  function positionAccessHint(target){
    const hint=$('accessHint');if(!hint||hint.hidden||!target)return;
    const mobile=window.matchMedia('(max-width:720px)').matches;
    hint.classList.toggle('is-mobile',mobile);
    hint.style.left='';hint.style.top='';hint.style.right='';hint.style.bottom='';hint.style.transform='';
    if(mobile){hint.style.left='12px';hint.style.right='12px';hint.style.bottom='calc(12px + env(safe-area-inset-bottom, 0px))';return;}
    const r=target.getBoundingClientRect(),w=Math.min(310,window.innerWidth-24);
    hint.style.width=`${w}px`;
    const left=Math.max(12,Math.min(window.innerWidth-w-12,r.left+r.width/2-w/2));
    hint.style.left=`${left}px`;
    const h=hint.getBoundingClientRect().height,below=r.bottom+9;
    hint.style.top=`${below+h<window.innerHeight-10?below:Math.max(10,r.top-h-9)}px`;
  }
  function showAccessHint(target,planId='elite',sectionLabel='',autoHide=false){
    const hint=$('accessHint'),title=$('accessHintTitle'),text=$('accessHintText'),button=$('accessHintUpgrade');if(!hint||!target||!target.isConnected||hint.contains(target)||$('upgradeDialog')?.open)return;
    clearTimeout(accessHintHoverTimer);
    const d=accessHintDetails(planId,sectionLabel);accessHintTarget=target;
    if(title)title.textContent=d.title;if(text)text.textContent=d.text;
    if(button){button.textContent=`Upgrade na ${d.levelName}`;button.dataset.upgradePlan=planId;button.dataset.upgradeSection=sectionLabel||d.levelName;}
    hint.hidden=false;positionAccessHint(target);
    clearTimeout(accessHintTimer);if(autoHide)accessHintTimer=setTimeout(()=>hideAccessHint(),4300);
  }

  function upgradePlanFeatureList(planId){
    const id=String(planId||'').toLowerCase();
    const managed=state.ui?.plans?.[id]?.features;
    if(Array.isArray(managed)&&managed.length)return managed.map(value=>String(value||'').trim()).filter(Boolean);
    const configured=state.presentationConfig?.tiers?.tiers?.[id]?.features;
    if(Array.isArray(configured)&&configured.length)return configured.map(value=>String(value||'').trim()).filter(Boolean);
    const features={
      pro:[
        lcopy('3 TOP picks per day','3 TOP picky denne','3 TOP tipy denně'),
        lcopy('3 PRIME value picks','3 PRIME value picky','3 PRIME value tipy'),
        lcopy('Full dashboard','Plný dashboard','Plný dashboard'),
        lcopy('Custom notifications','Vlastné upozornenia','Vlastní upozornění')
      ],
      elite:[
        lcopy('Everything in PRO','Všetko z PRO','Vše z PRO'),
        lcopy('VIP group','VIP skupina','VIP skupina'),
        'See All',
        lcopy('Overview + advanced analytics','Overview + pokročilé analýzy','Overview + pokročilé analýzy')
      ],
      legend:[
        lcopy('Everything in ELITE','Všetko z ELITE','Vše z ELITE'),
        lcopy('Results','Výsledky','Výsledky'),
        lcopy('Advanced performance statistics','Pokročilé štatistiky výkonu','Pokročilé statistiky výkonu'),
        lcopy('Long-term analytical view','Dlhodobý analytický prehľad','Dlouhodobý analytický přehled')
      ],
      goat:[
        lcopy('Everything in LEGEND','Všetko z LEGEND','Vše z LEGEND'),
        lcopy('Maximum BlinQ access','Maximum BlinQ','Maximum BlinQ'),
        lcopy('Partner / advertising privileges','Partner / reklamné privilégiá','Partnerská / reklamní privilegia'),
        lcopy('Banner advertising benefit','Výhoda na reklamný banner','Výhoda na reklamní banner')
      ]
    };
    return features[id]||[];
  }
  function renderUpgradeTierCard(id,p,requiredIndex,lockedContext=false,currentIndex=-1){
    const idx=membershipHierarchy.indexOf(id),below=requiredIndex>0&&idx<requiredIndex;
    const url=safeExternalUrl(p?.url||''),label=String(p?.label||id.toUpperCase()),title=p?.card_title||label;
    const short=String(p?.short_description||p?.description||p?.note||'').trim();
    const fullDescription=String(p?.description||p?.note||short).trim();
    const detail=fullDescription&&fullDescription!==short?fullDescription:'';
    const features=upgradePlanFeatureList(id);
    const required=Boolean(lockedContext&&idx===requiredIndex);
    const isCurrent=idx===currentIndex;
    const alreadyOwned=idx<currentIndex;
    const actionLabel=p?.cta_label||lcopy(`Upgrade to ${id.toUpperCase()}`,`Upgrade na ${id.toUpperCase()}`,`Upgrade na ${id.toUpperCase()}`);
    let action='';
    if(isCurrent&&url) action=`<a class="upgrade-tier-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(lcopy(`Extend ${id.toUpperCase()} membership`,`Predĺžiť členstvo ${id.toUpperCase()}`,`Prodloužit členství ${id.toUpperCase()}`))} →</a>`;
    else if(isCurrent) action=`<span class="upgrade-tier-cta is-disabled" aria-disabled="true">${escapeHtml(lcopy('Payment link not configured','Platobný odkaz nie je nastavený','Platební odkaz není nastaven'))}</span>`;
    else if(alreadyOwned) action=`<span class="upgrade-tier-cta is-disabled">${escapeHtml(lcopy('Already included','Už máte zahrnuté','Již máte zahrnuto'))}</span>`;
    else if(lockedContext&&below) action=`<span class="upgrade-tier-cta is-disabled">${escapeHtml(lcopy('Does not unlock this section','Neodomkne túto sekciu','Neodemkne tuto sekci'))}</span>`;
    else if(url) action=`<a class="upgrade-tier-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(actionLabel)} →</a>`;
    else action=`<button class="upgrade-tier-cta" type="button" data-upgrade-account-route="1">${escapeHtml(actionLabel)} →</button>`;
    const note=isCurrent
      ?`<span class="upgrade-tier-note">${escapeHtml(lcopy('Your current level','Vaša aktuálna úroveň','Vaše aktuální úroveň'))}</span>`
      :lockedContext&&below
      ?`<span class="upgrade-tier-note is-warning">${escapeHtml(lcopy('Does not unlock this section','Neodomkne túto sekciu','Neodemkne tuto sekci'))}</span>`
      :required?`<span class="upgrade-tier-note">${escapeHtml(lcopy('Required for this section','Potrebné pre túto sekciu','Potřebné pro tuto sekci'))}</span>`:'';
    const featureHeading=String(p?.note||'').trim();
    return `<article class="upgrade-tier-card plan-${escapeHtml(id)}${required?' is-required':''}${lockedContext&&below?' is-below-required':''}">${note}<div class="upgrade-tier-top">${planAvatarPairHtml(id,p)}<div class="upgrade-tier-copy">${planEyebrowHtml(p)}<strong>${escapeHtml(publicPlanLabel(id,title))}</strong>${short?`<span>${escapeHtml(short)}</span>`:''}</div></div>${detail?`<p class="upgrade-tier-description">${escapeHtml(detail)}</p>`:''}${featureHeading?`<p class="upgrade-feature-heading">${escapeHtml(featureHeading)}</p>`:''}<ul class="upgrade-feature-list">${features.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>${action}</article>`;
  }
  function showUpgradePrompt(planId='pro',sectionLabel='this content',lockedContext=false){
    const dialog=$('upgradeDialog'),host=$('upgradeDialogContent');if(!dialog||!host)return;
    if(dialog.open)return;
    upgradeReturnTarget=$('accessHint')?.contains(document.activeElement)?accessHintTarget:document.activeElement;
    hideAccessHint();
    const a=state.feed?.account||{};
    const requiredId=membershipHierarchy.includes(String(planId||'').toLowerCase())?String(planId).toLowerCase():'pro';
    const requiredIndex=lockedContext?Math.max(1,membershipHierarchy.indexOf(requiredId)):0;
    const requiredName=String(state.ui?.plans?.[requiredId]?.label||upgradePlanLabel(requiredId)||requiredId).replace(/^BlinQ\s+/i,'').toUpperCase();
    const isAdmin=Boolean(a.is_admin||String(a.role||'').toLowerCase()==='admin');
    const rawMembership=String(a.plan||((String(a.status||'').toLowerCase()==='trial')?'rookie':'rookie')).toLowerCase();
    const currentPlan=membershipHierarchy.includes(rawMembership)?rawMembership:'rookie';
    const currentLabel=String(a.plan_label||state.ui?.plans?.[currentPlan]?.label||currentPlan).replace(/^BlinQ\s+/i,'').toUpperCase();
    const accountName=String(a.name||a.telegram_nick||a.email||'BlinQ User');
    const avatar=accountAvatarUrl(a);
    const upgradePlans=['pro','elite','legend','goat'].filter(id=>state.ui?.plans?.[id]?.enabled!==false);
    const section=String(sectionLabel||'').trim();
    const availability=lockedContext
      ?lcopy(`This content requires ${requiredName} or higher.`, `Táto sekcia je dostupná od úrovne ${requiredName} a vyššie.`, `Tato sekce je dostupná od úrovně ${requiredName} a výše.`)
      :uiCopy('upgrade.generic_availability',lcopy('Choose the membership level that fits you best.','Vyber si úroveň, ktorá ti najviac vyhovuje.','Vyber si úroveň, která ti nejvíc vyhovuje.'));
    const badge=lockedContext
      ?uiCopyTemplate('upgrade.requires',lcopy(`Requires ${requiredName}`,`Vyžaduje ${requiredName}`,`Vyžaduje ${requiredName}`),{plan:requiredName})
      :uiCopy('upgrade.generic_badge',lcopy('Membership upgrade','Upgrade členstva','Upgrade členství'));
    const summaryLabel=isAdmin?'ADMIN':(currentLabel||'FREE');
    host.innerHTML=`<div class="upgrade-dialog-head"><div class="upgrade-dialog-intro"><span class="upgrade-dialog-eyebrow">${escapeHtml(uiCopy('upgrade.eyebrow',lcopy('BLINQ MEMBERSHIP','BLINQ ČLENSTVO','BLINQ ČLENSTVÍ')))}</span>${lockedContext?`<span class="upgrade-requires-pill is-required-context">▣ ${escapeHtml(badge)}</span>`:''}<h2 id="upgradeDialogTitle" class="upgrade-dialog-title">${escapeHtml(lcopy('Unlock higher access','Odomknúť ','Odemknout '))}<span class="accent">${escapeHtml(lcopy('higher access','vyšší prístup','vyšší přístup'))}</span></h2><p class="upgrade-dialog-copy"><strong>${escapeHtml(availability)}</strong></p></div><div class="upgrade-account-summary"><span class="upgrade-account-avatar">${avatar?`<img src="${escapeHtml(avatar)}" alt="">`:escapeHtml(accountAvatarFallback(a))}</span><div class="upgrade-account-copy"><small>${escapeHtml(lcopy('Your account','Tvoj účet','Tvůj účet'))}</small><strong>${escapeHtml(accountName)}</strong><b>${escapeHtml(summaryLabel)}</b></div></div></div><div class="upgrade-tier-heading"><div><h3>${escapeHtml(lcopy('Choose your level','Vyber si svoju úroveň','Vyber si svou úroveň'))}</h3></div></div><div class="upgrade-plan-grid">${upgradePlans.map(id=>renderUpgradeTierCard(id,state.ui?.plans?.[id]||{},requiredIndex,lockedContext,membershipHierarchy.indexOf(currentPlan))).join('')}</div>`;
    host.querySelectorAll('[data-upgrade-account-route]').forEach(button=>button.onclick=()=>{if(dialog.open)dialog.close();setRoute('account',true);});
    if(locale!=='en')translatePublicDom(dialog);if(!dialog.open)dialog.showModal();
    $('upgradeDialogClose')?.focus({preventScroll:true});
  }
  function clearPrivateWorkspaceState(){
    state.feed={upcoming:[],results:[],performance:{},history:{},model:null};
    state.insights=[];state.insightsUnread=0;state.insightsLoading=false;state.insightsStorageUnavailable=false;
    state.userLiveRadarStatus=null;state.userLiveRadarLoading=false;state.liveRadarHeartbeat=null;state.privateUpdatesBusy=false;state.privateUpdatesLastPoll=0;
    state.adminUsers=null;state.adminUsersLoading=false;state.adminUsersError='';state.adminUsersWarning='';state.adminSelectedUser=null;
    state.adminDiagnostics=null;state.adminDiagnosticsLoading=false;state.adminInsights=null;state.adminInsightsLoading=false;state.adminInsightsError='';state.adminInsightEditingId='';state.adminLiveRadarStatus=null;state.adminLiveRadarLoading=false;
    state.railMatch=null;state.previewPlan=null;state.demoFeedBackup=null;state.demoMode=false;state.dashboardVisibility=null;state.pushConfig=null;state.pushBusy=false;
    state.route='predictions';state.page=0;state.resultsPage=0;state.dailyHubExpanded=false;state.dashboardSearch='';
    Object.keys(state.marketPage||{}).forEach(key=>{state.marketPage[key]=0;});
    setInsightDrawer(false);closeProfileMenu();
    ['matchDialog','accountDialog','upgradeDialog'].forEach(id=>{const dialog=$(id);if(dialog?.open)dialog.close();});
    const shell=$('appShell');if(shell)shell.hidden=true;
  }
  async function signOutCurrentSession(){
    feedGeneration++;clearPrivateWorkspaceState();feedLoading=false;
    try{await BlinqAuth.signOut();}finally{auth('login');}
  }
  function closeProfileMenu(){const menu=$('profileMenu'),toggle=$('profileMenuToggle');if(menu)menu.hidden=true;if(toggle)toggle.setAttribute('aria-expanded','false');}

  let feedLoading=false,feedGeneration=0,externalSessionTimer=null;
  async function syncExternalSession(){
    feedGeneration++;clearPrivateWorkspaceState();feedLoading=false;
    const generation=feedGeneration;
    let session=null;
    try{session=await BlinqAuth.restore();}catch(error){console.warn('[BlinQ auth] cross-tab session restore failed.',error);}
    if(generation!==feedGeneration)return;
    if(!session){auth('login');return;}
    try{await loadUiConfig();}catch(error){console.warn('[BlinQ UI] cross-tab config refresh failed; using last known config.',error);}
    if(generation!==feedGeneration)return;
    await loadFeed(false).catch(()=>{});
  }
  function handleSessionStorageEvent(event){
    const epochKey=typeof BlinqAuth.sessionEpochKey==='function'?BlinqAuth.sessionEpochKey():'blinq_v4_session_epoch';
    if(event.storageArea!==localStorage||event.key!==epochKey)return;
    clearTimeout(externalSessionTimer);externalSessionTimer=setTimeout(()=>{syncExternalSession().catch(error=>console.warn('[BlinQ auth] cross-tab session sync failed.',error));},40);
  }
  async function loadFeed(showLoading=true){
    if(feedLoading)return;feedLoading=true;const generation=feedGeneration;window.BlinqUI.sync('loading');
    if(showLoading&&state.route==='predictions') $('predictionGrid').innerHTML=`<div class="state-card">${escapeHtml(publicText('Loading current model predictions…'))}</div>`;
    try{
      const feed=(await BlinqAuth.feed())||{};if(generation!==feedGeneration)return;
      state.feed=feed; state.feed.upcoming=Array.isArray(feed?.upcoming)?feed.upcoming:[]; state.feed.results=Array.isArray(feed?.results)?feed.results:[];
      // News/RSS is presentation-only. Never hold an authenticated workspace
      // behind a slow external feed. Render immediately, then refresh the hero
      // only if this session generation is still current when news arrives.
      loadNewsPool().then(()=>{if(generation===feedGeneration&&state.route==='predictions')renderHeroBanner();}).catch(()=>{});
      loadAdminDraft(); renderAllUiContent(); populateFilters();
      const a=feed.account||{};
      $('profileName').textContent=a.name||a.email||publicText('BlinQ User');
      const resolvedPlan=accountPlan();
      const planLabel=resolvedPlan==='rookie'?publicPlanLabel('rookie'):(a.plan_label||state.ui?.plans?.[resolvedPlan]?.label||a.plan||publicText('Member'));
      $('profilePlan').textContent=(a.is_admin||String(a.role||'').toLowerCase()==='admin')?'Admin':planLabel;
      const profileTelegram=$('profileTelegram');if(profileTelegram)profileTelegram.textContent=String(a.telegram_nick||'TG —');
      const profileRegisteredEmail=$('profileRegisteredEmail');if(profileRegisteredEmail)profileRegisteredEmail.textContent=a.email||'—';
      const profileRemaining=$('profileRemaining');if(profileRemaining){const status=String(a.status||'active').toLowerCase();profileRemaining.textContent=status==='lifetime'?publicText('Lifetime'):a.expires_at?remainingLabel(a.expires_at):(status==='active'?publicText('Active'):publicText(status));}
      const planIcon={admin:'♛',rookie:'○',pro:'◇',elite:'✦',goat:'♛',legend:'♛',expired:'○'}[resolvedPlan]||'◇';
      const planIconHost=$('profilePlanIcon');if(planIconHost)planIconHost.textContent=planIcon;
      const member=$('memberStatus');
      if(member){
        const status=String(a.status||'active').toLowerCase();
        member.textContent=locale==='en'?(status==='trial'?`TRIAL · ${remainingLabel(a.expires_at)}`:status==='lifetime'?'LIFETIME':status.toUpperCase()):(status==='trial'?`${locale==='cz'?'ZKOUŠKA':'SKÚŠOBNÉ'} · ${remainingLabel(a.expires_at)}`:status==='lifetime'?(locale==='cz'?'DOŽIVOTNĚ':'DOŽIVOTNE'):publicText(status==='active'?'Active':status));
      }
      const profileButton=$('profileButton');if(profileButton)profileButton.dataset.plan=resolvedPlan;
      setAccountAvatar($('avatar'),a);
      const tooltipName=$('tooltipAccountName'),tooltipEmail=$('tooltipAccountEmail'),tooltipPlan=$('tooltipAccountPlan'),tooltipRemaining=$('tooltipAccountRemaining');
      if(tooltipName)tooltipName.textContent=a.name||a.email||publicText('BlinQ User');
      if(tooltipEmail)tooltipEmail.textContent=a.email||'—';
      if(tooltipPlan)tooltipPlan.textContent=String(a.plan||'').toLowerCase()==='rookie'?publicPlanLabel('rookie'):(a.plan_label||state.ui?.plans?.[String(a.plan||'').toLowerCase()]?.label||a.plan||planLabel||'Member');
      if(tooltipRemaining){const status=String(a.status||'active').toLowerCase();tooltipRemaining.textContent=status==='lifetime'?publicText('Lifetime'):a.expires_at?remainingLabel(a.expires_at):(status==='active'?publicText('Managed manually'):status.toUpperCase());}
      $('updatedAt').textContent=feed.generated_at?fmtTime(feed.generated_at):'—'; $('todayLabel').textContent=fmtToday();
      const fullModelVersion=String(feed?.model?.version||'').trim(),compactModelVersion=shortModelVersion(fullModelVersion);
      const staleNotice=$('staleNotice'); if(staleNotice){staleNotice.hidden=true;staleNotice.textContent='';} $('appShell').hidden=false; if($('authDialog').open)$('authDialog').close();
      if(state.route==='admin'&&!isAdminAccount())state.route='predictions'; setRoute(state.route,false); applyAccessStates();renderDashboardKpis();loadInsights(true);window.BlinqUI.sync(feed.stale?'stale':'ready',feed.generated_at);
    }catch(error){if(generation!==feedGeneration)return;if(error.status===401){BlinqAuth.clear();clearPrivateWorkspaceState();auth('login');$('authMessage').textContent=publicText('Your session could not be authorized. Sign in again.');return;}if(error.status===403&&String(error.code||'').toLowerCase()==='email_not_verified'){clearPrivateWorkspaceState();auth('login');$('authMessage').textContent=publicText('Verify your email before opening BlinQ. You can resend the verification email below.');$('resendVerification').hidden=false;return;}if(error.status===403&&String(error.code||'').toLowerCase()==='account_suspended'){clearPrivateWorkspaceState();auth('login');$('authMessage').textContent=publicText('This BlinQ account is suspended. Contact us via the official BlinQ Telegram channel if you believe this is a mistake.');return;}window.BlinqUI.sync(navigator.onLine?'error':'offline');if(showLoading)showStatus(publicText('Data could not be refreshed. Please try again.'));if($('appShell').hidden){clearPrivateWorkspaceState();auth('login');$('authMessage').textContent=publicText(error.message||'The BlinQ workspace could not be opened. Please try again.');return;}if(state.route==='predictions')renderPredictions();throw error;}finally{if(generation===feedGeneration){feedLoading=false;window.BlinqUI.refreshFinished();}}
  }
  async function refreshWorkspace(showLoading=false){
    try{await loadUiConfig();}
    catch(error){console.warn('[BlinQ UI] runtime UI refresh failed; keeping last known UI config.',error);}
    return loadFeed(showLoading);
  }

  function showStatus(message){const n=$('statusBanner');n.textContent=message;n.hidden=!message;if(message)setTimeout(()=>{n.hidden=true},5000)}

  function setupEvents(){
    $('authDialog').addEventListener('cancel',e=>e.preventDefault()); $('authForm').addEventListener('submit',handleAuthSubmit); $('switchSignup').onclick=()=>auth(state.authMode==='login'?'signup':'login'); $('switchReset').onclick=()=>auth('reset');
    if($('publicContentDialogClose'))$('publicContentDialogClose').onclick=()=>$('publicContentDialog').close();
    if($('publicContentDialog'))$('publicContentDialog').addEventListener('click',e=>{if(e.target===$('publicContentDialog'))$('publicContentDialog').close();});
    document.addEventListener('click',event=>{const open=event.target.closest('[data-public-content]');if(open){event.preventDefault();showPublicContentDialog(open.dataset.publicContent);return;}const choice=event.target.closest('[data-cookie-choice]');if(choice){saveCookieConsent(choice.dataset.cookieChoice==='analytics'?'analytics':'essential');$('publicContentDialog')?.close();}});
    if($('cookieEssentialOnly'))$('cookieEssentialOnly').onclick=()=>saveCookieConsent('essential');
    if($('cookieAcceptAnalytics'))$('cookieAcceptAnalytics').onclick=()=>saveCookieConsent('analytics');
    $('resendVerification').onclick=async()=>{const node=$('authMessage');node.textContent=publicText('Sending verification email…');try{await BlinqAuth.resendVerification();node.textContent=publicText('Verification email sent again. Check your inbox and spam folder.');}catch(error){node.textContent=error.message;}};
    $('authPasswordToggle').onclick=()=>{const input=$('authPassword'),button=$('authPasswordToggle'),show=input.type==='password';input.type=show?'text':'password';button.textContent=publicText(show?'Hide':'Show');button.setAttribute('aria-pressed',show?'true':'false');button.setAttribute('aria-label',publicText(show?'Hide password':'Show password'));};
    $('refreshButton').onclick=()=>refreshWorkspace(true).catch(()=>{});$('syncRefresh').onclick=()=>refreshWorkspace(false).catch(()=>{}); ['tourFilter','tournamentFilter','surfaceFilter','confidenceFilter'].forEach(id=>$(id).addEventListener('change',()=>{state.page=0;state.showAll=false;renderPredictions()})); $('searchInput').addEventListener('input',()=>{state.page=0;state.showAll=false;renderPredictions()}); const headerSearch=$('headerSearchInput'); if(headerSearch)headerSearch.addEventListener('input',()=>{$('searchInput').value=headerSearch.value;state.page=0;state.showAll=false;renderPredictions();renderDailyHub();});
    $('prevPick').onclick=()=>{state.page=Math.max(0,state.page-1);renderPredictions()}; $('nextPick').onclick=()=>{state.page+=1;renderPredictions()}; $('dialogClose').onclick=()=>$('matchDialog').close(); $('matchDialog').addEventListener('click',e=>{if(e.target===$('matchDialog'))$('matchDialog').close()}); const accountDialog=$('accountDialog'); if($('accountDialogClose'))$('accountDialogClose').onclick=()=>accountDialog.close(); if(accountDialog)accountDialog.addEventListener('click',e=>{if(e.target===accountDialog)accountDialog.close()}); $('profileButton').onclick=()=>{closeProfileMenu();openAccountDialog()};
    $('profileMenuToggle').onclick=e=>{e.stopPropagation();const menu=$('profileMenu'),toggle=$('profileMenuToggle'),open=menu.hidden;menu.hidden=!open;toggle.setAttribute('aria-expanded',open?'true':'false');};
    $('headerLogoutButton').onclick=signOutCurrentSession;$('upgradeDialogClose').onclick=()=>$('upgradeDialog').close();$('upgradeDialog').addEventListener('click',e=>{if(e.target===$('upgradeDialog'))$('upgradeDialog').close()});
    if($('insightBell'))$('insightBell').onclick=()=>{const node=$('insightBell');if(node?.dataset.upgradePlan){showAccessHint(node,node.dataset.upgradePlan,node.dataset.upgradeSection||'Premium Info',true);return;}toggleInsightChannel('info');};
    if($('insightShortcut'))$('insightShortcut').onclick=event=>{const node=$('insightShortcut');if(node?.dataset.upgradePlan){showAccessHint(node,node.dataset.upgradePlan,node.dataset.upgradeSection||'Comeback LIVE',true);return;}toggleInsightChannel('live');};
    document.querySelectorAll('[data-open-insights]').forEach(node=>node.addEventListener('click',()=>setInsightDrawer(true,'info')));
    if($('insightDrawerClose'))$('insightDrawerClose').onclick=()=>setInsightDrawer(false);
    if($('insightBackdrop'))$('insightBackdrop').onclick=()=>setInsightDrawer(false);
    if($('insightDrawerToolbar'))$('insightDrawerToolbar').onclick=async event=>{const filter=event.target.closest('[data-insight-filter]');if(filter){state.insightFilter=filter.dataset.insightFilter||'all';renderInsightDrawer();return;}if(event.target.closest('[data-insight-read-all]')){const unread=state.insights.filter(item=>!item.read&&(state.insightChannel==='live'?isLiveInsight(item):!isLiveInsight(item)));for(const item of unread){await markInsightRead(item.id);}renderInsightDrawer();}};
    if($('insightDrawerList'))$('insightDrawerList').onclick=event=>{
      const liveTab=event.target.closest('[data-live-radar-tab]');if(liveTab){const tab=String(liveTab.dataset.liveRadarTab||'');state.liveRadarTab=['set2','results'].includes(tab)?tab:'comeback';state.insightFilter='all';renderInsightDrawer();return;}
      const article=event.target.closest('[data-insight-id]');if(article)markInsightRead(article.dataset.insightId);
      const matchButton=event.target.closest('[data-insight-match]');if(matchButton){const found=findRowByEventId(matchButton.dataset.insightMatch);if(found){setInsightDrawer(false);setRoute('predictions');openMatch(normalize(found.row),found.tab,found.row);}else showStatus(lcopy('This match is not on the current board.','Tento zápas už nie je v aktuálnej ponuke.','Tento zápas už není v aktuální nabídce.'));}
    };
    document.addEventListener('click',e=>{
      if(!e.target.closest('#profileShell'))closeProfileMenu();
      const dashboardToggle=e.target.closest('[data-dashboard-toggle]');if(dashboardToggle&&state.route==='predictions'){e.preventDefault();toggleDashboardSection(dashboardToggle.dataset.dashboardToggle);return;}
      const accessUpgrade=e.target.closest('#accessHintUpgrade');if(accessUpgrade){e.preventDefault();e.stopPropagation();showUpgradePrompt(accessUpgrade.dataset.upgradePlan||'elite',accessUpgrade.dataset.upgradeSection||'BlinQ',true);return;}
      const upgradeTarget=e.target.closest('[data-upgrade-plan]');
      const lockedResultsRoute=Boolean(upgradeTarget?.dataset?.uiElement==='SIDEBAR_RESULTS'&&upgradeTarget?.dataset?.route==='results');
      if(upgradeTarget&&state.route!=='admin'&&!lockedResultsRoute){e.preventDefault();e.stopPropagation();const plan=upgradeTarget.dataset.upgradePlan||'pro',section=upgradeTarget.dataset.upgradeSection||'this content';if(upgradeTarget.dataset.upgradeExplicit==='1')showUpgradePrompt(plan,section);else showAccessHint(upgradeTarget,plan,section,true);return;}
      const restricted=e.target.closest('[data-ui-element].ui-state-locked,[data-ui-element].ui-state-blurred,[data-ui-element].ui-state-hidden');
      const restrictedResultsRoute=Boolean(restricted?.dataset?.uiElement==='SIDEBAR_RESULTS'&&restricted?.dataset?.route==='results');
      if(restricted&&state.route!=='admin'&&!restrictedResultsRoute){e.preventDefault();e.stopPropagation();const plan=firstUnlockPlan(dashboardSectionKeyForSidebarElement(restricted.dataset.uiElement)||'top_daily',0,true);showAccessHint(restricted,plan,restricted.querySelector('span:nth-child(2)')?.textContent||'this content',true);return;}
      const banner=e.target.closest('[data-banner-slot]');if(banner)trackBanner(banner,'click');
      const prev=e.target.closest('[data-market-prev]');if(prev){const key=prev.dataset.marketPrev;state.marketPage[key]=Math.max(0,Number(state.marketPage[key]||0)-1);renderMarketSections();return;}
      const next=e.target.closest('[data-market-next]');if(next){const key=next.dataset.marketNext;state.marketPage[key]=Number(state.marketPage[key]||0)+1;renderMarketSections();return;}
      const target=e.target.closest('[data-route]');if(!target)return;const route=target.dataset.route;if(!routeMeta[route])return;e.preventDefault();if(route==='account'){openAccountDialog();return;}const upgradeDialog=$('upgradeDialog');if(upgradeDialog?.open&&target.closest('#upgradeDialog'))upgradeDialog.close();const matchDialog=$('matchDialog');if(matchDialog?.open&&target.closest('#matchDialog'))matchDialog.close();setRoute(route);
    });
    document.addEventListener('pointerover',e=>{const target=accessHintTrigger(e.target);if(!target||state.route==='admin'||window.matchMedia('(hover: none)').matches)return;if(e.relatedTarget instanceof Node&&target.contains(e.relatedTarget))return;clearTimeout(accessHintTimer);clearTimeout(accessHintHoverTimer);accessHintHoverTimer=setTimeout(()=>showAccessHint(target,target.dataset.upgradePlan||'elite',target.dataset.upgradeSection||'',false),320);});
    document.addEventListener('pointerout',e=>{const target=accessHintTrigger(e.target);if(!target)return;const next=e.relatedTarget;const hint=$('accessHint');if(next instanceof Node&&(target.contains(next)||hint?.contains(next)))return;clearTimeout(accessHintHoverTimer);hideAccessHint(240);});
    const accessHintNode=$('accessHint');
    if(accessHintNode){
      accessHintNode.addEventListener('focusin',()=>{clearTimeout(accessHintTimer);clearTimeout(accessHintHoverTimer);});
      accessHintNode.addEventListener('pointerenter',()=>{clearTimeout(accessHintTimer);clearTimeout(accessHintHoverTimer);});
      accessHintNode.addEventListener('pointerleave',e=>{const next=e.relatedTarget;if(next instanceof Node&&accessHintTarget?.contains?.(next))return;hideAccessHint(220);});
    }
    document.addEventListener('focusin',e=>{const target=accessHintTrigger(e.target);if(target&&state.route!=='admin')showAccessHint(target,target.dataset.upgradePlan||'elite',target.dataset.upgradeSection||'',false);});
    document.addEventListener('focusout',e=>{const hint=$('accessHint'),next=e.relatedTarget;if(next instanceof Node&&(hint?.contains(next)||accessHintTarget?.contains(next)))return;if(accessHintTrigger(e.target)||hint?.contains(e.target))hideAccessHint(180);});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('accessHint')?.hidden){hideAccessHint();}});
    $('upgradeDialog').addEventListener('close',()=>{const target=upgradeReturnTarget;upgradeReturnTarget=null;if(target?.isConnected){target.focus({preventScroll:true});}hideAccessHint();});
    window.addEventListener('scroll',()=>hideAccessHint(),{passive:true});
    window.addEventListener('resize',()=>{if(accessHintTarget&&!$('accessHint')?.hidden)positionAccessHint(accessHintTarget);},{passive:true});
    let resizeTimer,lastCardCapacity=dashboardCardsPerPanel(); window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{const capacity=dashboardCardsPerPanel();if(capacity===lastCardCapacity)return;lastCardCapacity=capacity;if(state.route==='predictions'){state.page=0;Object.keys(state.marketPage||{}).forEach(k=>{state.marketPage[k]=0;});renderPredictions();renderMarketSections();renderDashboardComposition();}},120)});
  }

  function setupLiveRefresh(){
    let lastAttempt=Date.now();
    const refresh=()=>{if(document.hidden||!navigator.onLine||document.activeElement?.matches('input,select,textarea')||$('appShell').hidden||state.route==='admin'||state.demoMode||document.querySelector('dialog[open]')||Date.now()-lastAttempt<60000)return;lastAttempt=Date.now();refreshWorkspace(false).catch(()=>{});};
    const privateRefresh=()=>{if(!document.hidden&&navigator.onLine&&!$('appShell')?.hidden)refreshPrivateUpdates(false).catch(()=>{});};
    setInterval(refresh,5*60*1000);setInterval(privateRefresh,30*1000);
    document.addEventListener('visibilitychange',()=>{refresh();if(!document.hidden)refreshPrivateUpdates(true).catch(()=>{});});
    window.addEventListener('online',()=>{lastAttempt=0;refresh();refreshPrivateUpdates(true).catch(()=>{});});
    window.addEventListener('offline',()=>window.BlinqUI.sync('offline'));
    window.addEventListener('storage',handleSessionStorageEvent);
    window.addEventListener('popstate',()=>{if(!$('appShell').hidden)setRoute(location.hash.slice(1)||'predictions',false);});
    window.addEventListener('hashchange',()=>{const route=location.hash.slice(1)||'predictions';if(!$('appShell').hidden&&route!==state.route)setRoute(route,false);});
  }

  function finishBootSplash(){const splash=$('bootSplash');if(!splash)return;splash.classList.add('is-done');setTimeout(()=>splash.remove(),220);}
  async function boot(){
    setupEvents();window.BlinqUI.init();setupLiveRefresh();
    const hash=location.hash.replace(/^#/,'');if(routeMeta[hash])state.route=hash;

    // Authentication is a core subsystem. Editable UI/content configuration is
    // presentation state and must never be able to disable sign-in or delay the
    // login form behind an Azure storage/CMS cold start.
    const uiReady=loadUiConfig()
      .then(()=>{try{renderCookieConsent(false);}catch(error){console.warn('[BlinQ boot] cookie UI render failed.',error);}return true;})
      .catch(error=>{console.warn('[BlinQ boot] UI config failed; auth remains available.',error);return false;});
    const authReady=BlinqAuth.init()
      .then(cfg=>({cfg,error:null}))
      .catch(error=>({cfg:null,error}));

    try{
      let session=null;
      try{session=await BlinqAuth.restore();}
      catch(error){console.warn('[BlinQ boot] session restore failed; showing sign-in without destroying auth.',error);}

      // Logged-out users see an immediately usable form. The submit action uses
      // BlinqAuth.ensureReady(), so a still-running init cannot create a race.
      if(!session)auth('login');

      const {cfg,error:authError}=await authReady;
      if(cfg){
        state.authEnabled=Boolean(cfg.enabled&&String(cfg.provider||'').toLowerCase()==='firebase');
        if($('authSubmit')?.dataset.busy!=='1')$('authSubmit').disabled=!state.authEnabled;
        if(state.authEnabled&&$('authMessage')?.textContent===publicText('Authentication is temporarily unavailable.'))$('authMessage').textContent='';
      }else{
        state.authEnabled=false;
        if($('authSubmit'))$('authSubmit').disabled=true;
        if(authError)showStatus(authError.message);
        if($('authDialog')?.open)$('authMessage').textContent=publicText(authError?.message||'Authentication is temporarily unavailable.');
        if(!session)return;
      }

      if(cfg?.recovery){auth('recovery');return;}
      if(!session)return;

      // Workspace rendering can use UI configuration, but failure falls back to
      // repository defaults and can never invalidate a Firebase session.
      await uiReady;
      await loadFeed();
    }catch(error){
      showStatus(error?.message||'The BlinQ workspace could not be opened. Please try again.');
      if($('appShell').hidden)auth('login');
    }finally{finishBootSplash();}
  }
  boot();
})();
