(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = { feed: {upcoming:[],results:[],performance:{},history:{},model:null}, ui:null, uiSource:null, route:'predictions', page:0, showAll:false, authMode:'login', authEnabled:false, draftLoaded:false, selectedElement:'HERO_BANNER_1', adminPlan:'rookie', adminPlanId:'rookie', adminBannerPreviewPlan:'rookie', adminTab:'accounts', adminUsers:null, adminUsersLoading:false, adminUsersError:'', adminDiagnostics:null, adminDiagnosticsLoading:false, adminSelectedUser:null, adminUsersWarning:'', adminUserFilters:{q:'',plan:'all',status:'all',sort:'email'}, previewPlan:null, newsPool:[], bannerObserver:null, bannerTimers:new WeakMap(), adminAnalytics:null, adminAnalyticsLoading:false, runtimeConfigLoaded:false, adminCampaignId:null, adminAdvertiserId:null, resultsFilters:{category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:''}, resultsPage:0, resultsPageSize:50, marketPage:{top_daily:0,value:0,doubles:0,ace:0,sg:0}, dashboardVisibility:null, demoFeedBackup:null, demoMode:false, heroIndex:0, heroTimer:null, heroPaused:false, dailyHubTab:'daily', dailyHubExpanded:false, boardMode:'live', dashboardSearch:'', dailyHubTournament:'', dailyHubSelected:{daily:'',prime:'',top:'',value:'',ace:'',games:'',doubles:'',board:''}, railMatch:null, railMatchTab:'overview', railDetailTab:'overview', insights:[], insightsUnread:0, insightsLoading:false, insightsStorageUnavailable:false, insightDrawerOpen:false, insightFilter:'all', insightChannel:'info', liveRadarTab:'comeback', adminInsights:null, adminInsightsLoading:false, adminInsightsError:'', adminInsightEditingId:'', adminLiveRadarStatus:null, adminLiveRadarLoading:false, userLiveRadarStatus:null, userLiveRadarLoading:false, privateUpdatesLastPoll:0, privateUpdatesBusy:false, railPromoIndex:0, railPromoTimer:null, railPromoPaused:false, presentationConfig:null, siteContent:null, adminSupport:null, adminSupportLoading:false, adminSupportError:'', adminSupportStatus:'all', adminPayments:{}, adminAudit:null, adminAuditLoading:false, adminUserAudit:{}, supportSubmitting:false, pushConfig:null, pushBusy:false };
  const pageSize = () => innerWidth >= 1700 ? 6 : innerWidth >= 1450 ? 5 : innerWidth >= 1200 ? 4 : innerWidth >= 900 ? 3 : 1;
  const dashboardCardsPerPanel = () => 1; // v6.5.16: dashboard is a lightweight one-pick preview; See more opens 3–5 picks.
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const pct = value => `${(Number(value || 0) * (Number(value || 0) <= 1 ? 100 : 1)).toFixed(1)}%`;
  const number = (value, digits=3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const fmtTime = value => value ? new Intl.DateTimeFormat(localeTag,{hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : publicText('TBA');
  const fmtDate = value => value ? new Intl.DateTimeFormat(localeTag,{day:'2-digit',month:'short',year:'numeric'}).format(new Date(value)) : '—';
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
    return `<span class="${cls.trim()}" title="${escapeHtml(value)}" aria-label="${escapeHtml(value)}"><img src="${escapeHtml(src)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="country-flag-fallback" hidden>${escapeHtml(value)}</span></span>`;
  }
  function playerMetaHtml(rank,country,tour=''){
    const rankValue=Number(rank),rankText=Number.isFinite(rankValue)&&rankValue>0?`#${Math.trunc(rankValue)}`:'—';
    const tourText=String(tour||'').trim().toUpperCase();
    return `${flagIconHtml(country,true)}<span class="player-rank-number">${escapeHtml(rankText)}</span>${tourText?`<span class="player-rank-tour">${escapeHtml(tourText)}</span>`:''}`;
  }
  const safePhotoUrl = value => { const url=String(value||'').trim(); if(/^\/assets\/[A-Za-z0-9_.\/-]+$/.test(url)&&!url.split('/').includes('..'))return url; if(/^\/api\/v1\/(?:tournament-logo|player-image)\/[0-9]{1,12}$/.test(url))return url; if(/^https:\/\//i.test(url)){try{const parsed=new URL(url);if(parsed.protocol==='https:'&&parsed.host&&!parsed.username&&!parsed.password)return parsed.href;}catch{}} return ''; };
  const safeUiAsset = value => { const url=String(value||'').trim(); if(!/^\/assets\/[A-Za-z0-9_.\/-]+$/.test(url)||url.split('/').includes('..'))return ''; return url; };
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
  const membershipHierarchy = ['rookie','pro','elite','legend','goat'];
  const accessContexts = ['expired',...membershipHierarchy];
  const requestedLocale = String(new URLSearchParams(location.search).get('lang')||'').toLowerCase();
  // v6.5.13: the public site is Slovak-first. Czech and English are optional public mutations.
  // Internal identifiers, API payloads and Admin remain English.
  const locale = ['sk','cz','en'].includes(requestedLocale) ? requestedLocale : 'sk';
  const localeTag = ({sk:'sk-SK',cz:'cs-CZ',en:'en-GB'})[locale] || 'sk-SK';
  document.documentElement.lang = locale==='cz' ? 'cs' : locale;
  const PUBLIC_TRANSLATIONS = {
    sk: {
      'Skip to content':'Preskočiť na obsah','Close navigation':'Zavrieť navigáciu','Open navigation':'Otvoriť navigáciu',
      'Main navigation':'Hlavná navigácia','Quick navigation':'Rýchla navigácia','Language versions':'Jazykové verzie',
      'Dashboard':'Prehľad','Prime Predictions':'Short Odds','Short Odds':'Short Odds','TOP Predictions':'TOP','Value Predictions':'Value','Doubles':'Štvorhra','Ace Predictions':'Esá','S/G Predictions':'Sety / hry','Results':'Výsledky','BTTS Bonus':'BTTS Bonus',
      'Plans':'Plány','Upgrade':'Upgrade','Level':'Úroveň','Remaining':'Zostáva','Account':'Účet','Account & membership':'Účet a členstvo','Profile, access and plans':'Profil, prístup a plány','Sign out':'Odhlásiť sa','End this session':'Ukončiť túto reláciu',
      'Sign in to your analytics workspace':'Prihlás sa do svojho analytického priestoru','Get access':'Získaj prístup','Restore your access':'Obnov svoj prístup','Set a new password':'Nastav nové heslo',
      'Welcome back.':'Vitaj späť.','Sign in to your tennis intelligence workspace.':'Prihlás sa do svojho tenisového analytického priestoru.','Create your BlinQ account.':'Vytvor si účet BlinQ.','Create an account to access your BlinQ workspace.':'Vytvor si účet a získaj prístup do BlinQ.','Restore access.':'Obnov prístup.','We will send a password recovery link to your email.':'Na e-mail ti pošleme odkaz na obnovenie hesla.','Set a new password.':'Nastav nové heslo.','Choose a password with at least eight characters.':'Zvoľ heslo s minimálne ôsmimi znakmi.',
      'Display name':'Zobrazované meno','Email':'E-mail','Password':'Heslo','Enter your email':'Zadaj svoj e-mail','Enter your password':'Zadaj svoje heslo','Show':'Zobraziť','Hide':'Skryť','Show password':'Zobraziť heslo','Hide password':'Skryť heslo','Sign in':'Prihlásiť sa','Create account':'Vytvoriť účet','Back to sign in':'Späť na prihlásenie','Forgot password':'Zabudnuté heslo','Resend verification email':'Poslať overovací e-mail znova','Send recovery link':'Poslať odkaz na obnovu','Save password':'Uložiť heslo','Working…':'Pracujem…','Authentication is temporarily unavailable.':'Prihlasovanie je dočasne nedostupné.',
      'Verification email sent. Open the link in your inbox, then sign in.':'Overovací e-mail bol odoslaný. Otvor odkaz v správe a potom sa prihlás.','Your email is not verified yet. Open the verification link or resend the email.':'Tvoj e-mail ešte nie je overený. Otvor overovací odkaz alebo si pošli e-mail znova.','Verify your email before opening BlinQ. You can resend the verification email below.':'Pred otvorením BlinQ over svoj e-mail. Overovací e-mail si môžeš poslať znova nižšie.','Sending verification email…':'Odosielam overovací e-mail…','Verification email sent again. Check your inbox and spam folder.':'Overovací e-mail bol odoslaný znova. Skontroluj doručenú poštu aj spam.','If the account exists, check your email for the recovery link.':'Ak účet existuje, skontroluj e-mail s odkazom na obnovu.',
      'Your account':'Tvoj účet','YOUR ACCOUNT':'TVOJ ÚČET','CURRENT ACCESS':'AKTUÁLNY PRÍSTUP','Email verified':'E-mail overený','Email not verified':'E-mail nie je overený','Legacy admin · verify email':'Legacy admin · over e-mail','Telegram nick':'Telegram nick','Avatar style':'Typ avatara','Default':'Predvolený','Male':'Muž','Female':'Žena','Save profile':'Uložiť profil','Reset password':'Obnoviť heslo','Saving…':'Ukladám…','Profile updated.':'Profil bol uložený.','Sending recovery email…':'Odosielam e-mail na obnovu…','Password reset email sent.':'E-mail na obnovu hesla bol odoslaný.','BLINQ MEMBERSHIP':'BLINQ ČLENSTVO','Available plans':'Dostupné plány','Choose the access level that fits your workflow. Plans without an active checkout stay visible but cannot be purchased online yet.':'Vyber si úroveň prístupu. Plány bez aktívnej platby zostávajú viditeľné, ale zatiaľ ich nemožno kúpiť online.','Current plan':'Aktuálny plán','CURRENT PLAN':'AKTUÁLNY PLÁN','INVITE ONLY':'LEN NA POZVÁNKU','Invite only':'Len na pozvánku','Request invite':'Požiadať o pozvánku','Open plan':'Otvoriť plán','Lifetime access':'Doživotný prístup','Active':'Aktívne','No active access':'Bez aktívneho prístupu','Rookie Trial':'Rookie skúšobná verzia','Lifetime':'Doživotne','Active membership':'Aktívne členstvo','Expired':'Expirované','Access':'Prístup','Validity':'Platnosť','Member since':'Člen od','Security':'Zabezpečenie','Verified email':'Overený e-mail','Legacy admin access':'Legacy admin prístup','Verification required':'Vyžaduje sa overenie',
      'LIVE · Connecting…':'LIVE · Pripájam…','Auto-refresh on':'Automatické obnovenie zapnuté','Refresh':'Obnoviť','Live · updated':'Live · aktualizované','picks':'predikcií','published':'publikovaných','settled':'vyhodnotených','See more':'Zobraziť viac','See more →':'Zobraziť viac →','Loading Short Odds…':'Načítavam Short Odds…','All Tours':'Všetky okruhy','All Tournaments':'Všetky turnaje','All Surfaces':'Všetky povrchy','All Confidence':'Všetky úrovne istoty',
      'Unlock this pick':'Odomkni túto predikciu','Upgrade to unlock →':'Upgrade pre odomknutie →','Model signal':'Signál modelu','Overall performance':'Celková výkonnosť','Surface strength':'Sila na povrchu','Recent form':'Aktuálna forma','Head to head':'Vzájomné zápasy','Current market snapshot':'Aktuálny stav trhu','Odds':'Kurz','Model edge':'Výhoda modelu','Model signals':'Signály modelu','supports pick':'podporuje predikciu','counter-signal':'protisignál','No secondary signals are available.':'Nie sú dostupné žiadne sekundárne signály.','History':'História','Surface':'Povrch','Data depth':'Hĺbka dát',
      'Category':'Kategória','All published':'Všetky publikované','Tour':'Okruh','Period':'Obdobie','All time':'Celé obdobie','24 hours':'24 hodín','7 days':'7 dní','30 days':'30 dní','90 days':'90 dní','Date':'Dátum','Match':'Zápas','Pick':'Predikcia','Probability':'Pravdepodobnosť','Result':'Výsledok','Units':'Jednotky','WON':'VÝHRA','LOST':'PREHRA','VOID':'VOID','Record':'Bilancia','Hit rate':'Úspešnosť','ROI':'ROI','Vyhodnotené predikcie':'Vyhodnotené predikcie','Observed results':'Pozorované výsledky','Lower is better':'Nižšie je lepšie','Probability quality':'Kvalita pravdepodobnosti',
      'TENNIS INTELLIGENCE':'TENISOVÁ ANALYTIKA','MATCH WINNER':'VÍŤAZ ZÁPASU','CONFIDENCE FIRST':'ISTOTA NA PRVOM MIESTE','VALUE EDGE':'VALUE VÝHODA','SETTLED PREDICTIONS':'VYHODNOTENÉ PREDIKCIE','BLINQ MEMBERS':'BLINQ ČLENSTVO','LEARN':'INFO','How BlinQ Works':'Ako funguje BlinQ','Methodology':'Metodika','Model & Data':'Model a dáta','Responsible Use':'Zodpovedné používanie',
      'Short Odds rule':'Pravidlo Short Odds','TOP Predictions rule':'Pravidlo TOP predikcií','Value rule':'Pravidlo Value','Doubles model':'Model štvorhry','Aces / Double Faults':'Esá / dvojchyby','Sets / Games':'Sety / hry','Projection only.':'Iba projekcia.','No published data are available for this section yet.':'Pre túto sekciu zatiaľ nie sú dostupné publikované dáta.','No Short Odds predictions available yet. This board updates automatically when new predictions qualify.':'Short Odds zatiaľ nie sú dostupné. Prehľad sa automaticky aktualizuje, keď sa kvalifikujú nové predikcie.','No TOP predictions available yet. New qualifying predictions appear automatically.':'TOP predikcie zatiaľ nie sú dostupné. Nové kvalifikované predikcie sa zobrazia automaticky.','No Value predictions available yet. We are waiting for qualifying opportunities.':'Value predikcie zatiaľ nie sú dostupné. Čakáme na kvalifikované príležitosti.','No Doubles predictions have been published yet.':'Predikcie pre štvorhru zatiaľ neboli publikované.','No Ace predictions available yet. New projections appear automatically.':'Predikcie pre esá zatiaľ nie sú dostupné. Nové projekcie sa zobrazia automaticky.','No Sets / Games predictions available yet. New projections appear automatically.':'Predikcie pre sety / hry zatiaľ nie sú dostupné. Nové projekcie sa zobrazia automaticky.','No settled published predictions match these filters yet.':'Týmto filtrom zatiaľ nezodpovedajú žiadne vyhodnotené publikované predikcie.','No upcoming tournament coverage is currently published.':'Momentálne nie je publikované pokrytie nadchádzajúcich turnajov.','No upcoming players are currently published.':'Momentálne nie sú publikovaní žiadni nadchádzajúci hráči.',
      'BlinQ Prediction':'BlinQ predikcia','Prime predictions':'Short Odds','Short Odds predictions':'Short Odds','TOP predictions':'TOP','Value predictions':'Value','Štvorhra':'Štvorhra','Esá':'Esá','Sety / hry':'Sety / hry','Výsledky':'Výsledky',
      'LANGUAGE':'JAZYK','Live model':'Live model','Production feed':'Produkčný feed','This data is provided for informational and analytical purposes only. Powered by BackstageTalks Statistical Engine.':'Tieto dáta slúžia iba na informačné a analytické účely. Powered by BackstageTalks Statistical Engine.',
      'More published predictions':'Viac publikovaných predikcií','Full card details':'Kompletné detaily karty','See all access':'Prístup ku všetkým predikciám','View membership options →':'Zobraziť možnosti členstva →','UNLOCK MORE WITH BLINQ':'ODOMKNI VIAC S BLINQ',
      'COMMUNITY':'KOMUNITA','Join our Telegram Community':'Pridaj sa do Telegram komunity','News · Predictions · Discussions':'Novinky · Predikcie · Diskusie','JOIN':'PRIDAŤ SA','Premium Predictions':'Prémiové predikcie','Higher value. Better decisions.':'Vyššia hodnota. Lepšie rozhodnutia.','OPEN':'OTVORIŤ','RESULTS & STATS':'VÝSLEDKY A ŠTATISTIKY','Track performance':'Sleduj výkonnosť','Transparent. Verified.':'Transparentné. Overené.','VIEW':'ZOBRAZIŤ','Data. Analysis.':'Dáta. Analýza.','Better Decisions.':'Lepšie rozhodnutia.','Advanced tennis intelligence for informed players.':'Pokročilá tenisová analytika pre informované rozhodnutia.','Join the BlinQ':'Pridaj sa do BlinQ','Telegram Community':'Telegram komunity','Track performance.':'Sleduj výkonnosť.','Stay informed.':'Maj prehľad.','Transparent model results and published statistics.':'Transparentné výsledky modelu a publikované štatistiky.','SEE RESULTS':'VÝSLEDKY','BLINQ NEWS':'BLINQ NOVINKY','Updates & releases':'Novinky a aktualizácie','Product news and new features.':'Novinky produktu a nové funkcie.','BLINQ PARTNER':'BLINQ PARTNER','Your campaign.':'Tvoja kampaň.','Your message.':'Tvoja správa.','Assign a campaign, image, link and schedule in Admin.':'V Adminovi nastav kampaň, obrázok, odkaz a časovanie.',
      'Incorrect email or password.':'Nesprávny e-mail alebo heslo.','An account with this email already exists.':'Účet s týmto e-mailom už existuje.','Choose a stronger password with at least eight characters.':'Zvoľ silnejšie heslo s minimálne ôsmimi znakmi.','Enter a valid email address.':'Zadaj platnú e-mailovú adresu.','Too many attempts. Try again later.':'Príliš veľa pokusov. Skús to neskôr.','This account has been disabled.':'Tento účet bol deaktivovaný.','Verify your email before opening the BlinQ workspace.':'Pred otvorením BlinQ over svoj e-mail.','Your session expired. Sign in again.':'Tvoja relácia vypršala. Prihlás sa znova.','Your session is no longer valid. Sign in again.':'Tvoja relácia už nie je platná. Prihlás sa znova.',
      '✓ Email verified':'✓ E-mail overený','! Email not verified':'! E-mail nie je overený','! Legacy admin · verify email':'! Legacy admin · over e-mail','← Dashboard':'← Prehľad','Loading current model predictions…':'Načítavam aktuálne predikcie modelu…','Data could not be refreshed. Please try again.':'Dáta sa nepodarilo obnoviť. Skús to znova.','Published data is older than 12 hours. Check prediction creation times before evaluating them.':'Publikované dáta sú staršie ako 12 hodín. Pred vyhodnotením skontroluj čas vytvorenia predikcií.','Managed manually':'Spravované manuálne','Production feed':'Produkčný feed','Production':'Produkcia','Member':'Člen','BlinQ User':'Používateľ BlinQ',
      'Short Odds Prediction':'Short Odds','Value Prediction':'Value predikcia','Ace / DF Prediction':'Predikcia es / dvojchýb','Set / Game Prediction':'Predikcia setu / hry','TOP Prediction':'TOP predikcia','Sets Projection':'Projekcia setov','Games Projection':'Projekcia hier','Ace / DF Projection':'Predikcia es / dvojchýb','Projection':'Predikcia','Projection only · no odds':'Iba projekcia · bez kurzu','Baseline':'Základ','Gap':'Rozdiel','Score':'Skóre','Opponent proj.':'Projekcia súpera','Data':'Dáta','games':'hier','proj.':'proj.','MODEL':'MODEL','VERY HIGH':'VEĽMI VYSOKÁ','HIGH':'VYSOKÁ','MEDIUM':'STREDNÁ','LOW':'NÍZKA','PROJECTION':'PREDIKCIA',
      'No published predictions are available in this section yet.':'V tejto sekcii zatiaľ nie sú dostupné publikované predikcie.','Both Teams To Score':'Oba tímy dajú gól','The BlinQ BTTS module is prepared, but live football data and published predictions are not connected in this repository yet.':'Modul BlinQ BTTS je pripravený, ale live futbalové dáta a publikované predikcie zatiaľ nie sú v tomto repozitári pripojené.','Data not connected':'Dáta nie sú pripojené','No demo or fabricated predictions are shown.':'Nezobrazujú sa žiadne demo ani vymyslené predikcie.','BETA · FOOTBALL':'BETA · FUTBAL',
      'Entry access to the BlinQ workspace.':'Základný prístup do BlinQ.','Start with BlinQ':'Začni s BlinQ','Core predictions':'Hlavné predikcie','Core predictions + expanded daily board.':'Hlavné predikcie a rozšírený denný prehľad.','Advanced analytics':'Pokročilá analytika','Expanded analytical access for users who follow more matches and context.':'Rozšírený analytický prístup pre používateľov, ktorí sledujú viac zápasov a kontextu.','Maximum public access':'Najvyšší verejný prístup','The highest publicly available BlinQ tier.':'Najvyššia verejne dostupná úroveň BlinQ.','Private all-access':'Súkromný plný prístup','Lifetime access · All BlinQ features. Private top-tier access for selected members.':'Doživotný prístup · Všetky funkcie BlinQ. Súkromná najvyššia úroveň pre vybraných členov.','Choose Rookie':'Vybrať Rookie','Upgrade to PRO':'Prejsť na PRO','Choose Elite':'Vybrať Elite','Choose Legend':'Vybrať Legend',
      'Tournament':'Turnaj','Market':'Trh','Projection pick':'Predikcia','Proj.':'Proj.','Opp. proj.':'Proj. súpera','Overall sample':'Celková vzorka','Surface sample':'Vzorka na povrchu','Avg Odds':'Priem. kurz','Sample':'Vzorka','Accuracy':'Presnosť','Log loss':'Log loss','Brier score':'Brier skóre','Published and scored':'Publikované a vyhodnotené','filtered settled sample':'filtrovaná vyhodnotená vzorka','no issued odds':'bez publikovaných kurzov','flat 1u on issued odds':'výpočet pri 1u na publikovaných kurzoch','profit · flat 1u stake':'zisk · výpočet pri 1u','settled published rows':'vyhodnotené publikované záznamy','Production artifact':'Produkčný artefakt','Chronological holdout':'Chronologický holdout','Evaluation report':'Vyhodnocovací report','Negative is better':'Záporné je lepšie','Data window':'Dátové obdobie','Model':'Model',
      'TBA':'Bude určené','ending':'končí'
    },
    cz: {
      'Skip to content':'Přeskočit na obsah','Dashboard':'Přehled','Prime Predictions':'Short Odds','Short Odds':'Short Odds','TOP Predictions':'TOP','Value Predictions':'Value','Doubles':'Čtyřhra','Ace Predictions':'Esa','S/G Predictions':'Sety / hry','Results':'Výsledky','Plans':'Plány','Level':'Úroveň','Remaining':'Zbývá','Account':'Účet','Account & membership':'Účet a členství','Profile, access and plans':'Profil, přístup a plány','Sign out':'Odhlásit se','End this session':'Ukončit tuto relaci',
      'Sign in to your analytics workspace':'Přihlas se do svého analytického prostoru','Get access':'Získej přístup','Restore your access':'Obnov svůj přístup','Set a new password':'Nastav nové heslo',
      'Welcome back.':'Vítej zpět.','Sign in to your tennis intelligence workspace.':'Přihlas se do svého tenisového analytického prostoru.','Create your BlinQ account.':'Vytvoř si účet BlinQ.','Create an account to access your BlinQ workspace.':'Vytvoř si účet a získej přístup do BlinQ.','Restore access.':'Obnov přístup.','We will send a password recovery link to your email.':'Na e-mail ti pošleme odkaz pro obnovu hesla.','Set a new password.':'Nastav nové heslo.','Choose a password with at least eight characters.':'Zvol heslo s minimálně osmi znaky.','Email':'E-mail','Password':'Heslo','Enter your email':'Zadej svůj e-mail','Enter your password':'Zadej své heslo','Show':'Zobrazit','Hide':'Skrýt','Show password':'Zobrazit heslo','Hide password':'Skrýt heslo','Sign in':'Přihlásit se','Create account':'Vytvořit účet','Back to sign in':'Zpět na přihlášení','Forgot password':'Zapomenuté heslo','Resend verification email':'Poslat ověřovací e-mail znovu','Send recovery link':'Poslat odkaz pro obnovu','Save password':'Uložit heslo',
      'Your account':'Tvůj účet','YOUR ACCOUNT':'TVŮJ ÚČET','CURRENT ACCESS':'AKTUÁLNÍ PŘÍSTUP','Email verified':'E-mail ověřen','Email not verified':'E-mail není ověřen','Telegram nick':'Telegram nick','Avatar style':'Typ avatara','Default':'Výchozí','Male':'Muž','Female':'Žena','Save profile':'Uložit profil','Reset password':'Obnovit heslo','BLINQ MEMBERSHIP':'BLINQ ČLENSTVÍ','Available plans':'Dostupné plány','Current plan':'Aktuální plán','CURRENT PLAN':'AKTUÁLNÍ PLÁN','INVITE ONLY':'JEN NA POZVÁNKU','Invite only':'Jen na pozvánku','Request invite':'Požádat o pozvánku','Lifetime access':'Doživotní přístup','Active':'Aktivní','No active access':'Bez aktivního přístupu','Rookie Trial':'Rookie zkušební verze','Lifetime':'Doživotně','Active membership':'Aktivní členství','Expired':'Expirované','Access':'Přístup','Validity':'Platnost','Member since':'Člen od','Security':'Zabezpečení','Verified email':'Ověřený e-mail','Verification required':'Vyžaduje se ověření',
      'Refresh':'Obnovit','Auto-refresh on':'Automatické obnovení zapnuto','picks':'predikcí','published':'publikovaných','settled':'vyhodnocených','See more':'Zobrazit více','See more →':'Zobrazit více →','All Tours':'Všechny okruhy','All Tournaments':'Všechny turnaje','All Surfaces':'Všechny povrchy','All Confidence':'Všechny úrovně jistoty','Unlock this pick':'Odemkni tuto predikci','Upgrade to unlock →':'Upgrade pro odemknutí →','Odds':'Kurz','Model edge':'Výhoda modelu','Category':'Kategorie','All published':'Všechny publikované','Tour':'Okruh','Surface':'Povrch','Period':'Období','All time':'Celé období','24 hours':'24 hodin','7 days':'7 dní','30 days':'30 dní','90 days':'90 dní','Date':'Datum','Match':'Zápas','Pick':'Predikcia','Probability':'Pravděpodobnost','Result':'Výsledek','Units':'Jednotky','WON':'VÝHRA','LOST':'PROHRA','VOID':'VOID','Record':'Bilance','Hit rate':'Úspěšnost','Vyhodnotené predikcie':'Vyhodnocené predikce','TENNIS INTELLIGENCE':'TENISOVÁ ANALYTIKA','MATCH WINNER':'VÍTĚZ ZÁPASU','CONFIDENCE FIRST':'JISTOTA NA PRVNÍM MÍSTĚ','VALUE EDGE':'VALUE VÝHODA','SETTLED PICKS':'VYHODNOCENÉ PREDIKCE','BLINQ MEMBERS':'BLINQ ČLENSTVÍ','LEARN':'INFO','How BlinQ Works':'Jak funguje BlinQ','Methodology':'Metodika','Model & Data':'Model a data','Responsible Use':'Zodpovědné používání','BlinQ Prediction':'BlinQ predikce','LANGUAGE':'JAZYK',
      'COMMUNITY':'KOMUNITA','Join our Telegram Community':'Přidej se do Telegram komunity','News · Predictions · Discussions':'Novinky · Predikce · Diskuse','JOIN':'PŘIDAT SE','Premium Predictions':'Prémiové predikce','Higher value. Better decisions.':'Vyšší hodnota. Lepší rozhodnutí.','OPEN':'OTEVŘÍT','RESULTS & STATS':'VÝSLEDKY A STATISTIKY','Track performance':'Sleduj výkonnost','Transparent. Verified.':'Transparentní. Ověřené.','VIEW':'ZOBRAZIT','Data. Analysis.':'Data. Analýza.','Better Decisions.':'Lepší rozhodnutí.','Advanced tennis intelligence for informed players.':'Pokročilá tenisová analytika pro informovaná rozhodnutí.','Join the BlinQ':'Přidej se do BlinQ','Telegram Community':'Telegram komunity','Track performance.':'Sleduj výkonnost.','Stay informed.':'Měj přehled.','Transparent model results and published statistics.':'Transparentní výsledky modelu a publikované statistiky.','SEE RESULTS':'VÝSLEDKY','✓ Email verified':'✓ E-mail ověřen','! Email not verified':'! E-mail není ověřen','← Dashboard':'← Přehled','Loading current model predictions…':'Načítám aktuální predikce modelu…','Data could not be refreshed. Please try again.':'Data se nepodařilo obnovit. Zkus to znovu.','Published data is older than 12 hours. Check prediction creation times before evaluating them.':'Publikovaná data jsou starší než 12 hodin. Před vyhodnocením zkontroluj čas vytvoření predikcí.','Short Odds Prediction':'Short Odds','Value Prediction':'Value predikce','Ace / DF Prediction':'Esa / dvojchyby','Set / Game Prediction':'Predikce setu / hry','TOP Prediction':'TOP predikce','Projection only · no odds':'Pouze projekce · bez kurzu','VERY HIGH':'VELMI VYSOKÁ','HIGH':'VYSOKÁ','MEDIUM':'STŘEDNÍ','LOW':'NÍZKÁ','PROJECTION':'PREDIKCE','No published predictions are available in this section yet.':'V této sekci zatím nejsou dostupné publikované predikce.','Both Teams To Score':'Oba týmy dají gól','Data not connected':'Data nejsou připojena','No demo or fabricated predictions are shown.':'Nezobrazují se žádné demo ani vymyšlené predikce.','BETA · FOOTBALL':'BETA · FOTBAL',
      'Entry access to the BlinQ workspace.':'Základní přístup do BlinQ.','Start with BlinQ':'Začni s BlinQ','Core predictions':'Hlavní predikce','Core predictions + expanded daily board.':'Hlavní predikce a rozšířený denní přehled.','Advanced analytics':'Pokročilá analytika','Maximum public access':'Nejvyšší veřejný přístup','The highest publicly available BlinQ tier.':'Nejvyšší veřejně dostupná úroveň BlinQ.','Private all-access':'Soukromý plný přístup','Lifetime access · All BlinQ features. Private top-tier access for selected members.':'Doživotní přístup · Všechny funkce BlinQ. Soukromá nejvyšší úroveň pro vybrané členy.','Tournament':'Turnaj','Market':'Trh','Projection pick':'Predikce','Opp. proj.':'Proj. soupeře','Overall sample':'Celkový vzorek','Surface sample':'Vzorek na povrchu','Avg Odds':'Prům. kurz','Sample':'Vzorek','Accuracy':'Přesnost','Brier score':'Brier skóre','Published and scored':'Publikované a vyhodnocené','Data window':'Datové období',
      'TBA':'Bude určeno','ending':'končí'
    }
  };
  function publicText(value){
    const raw=String(value??'');
    if(locale==='en')return raw;
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
    const keys=String(path||'').split('.').filter(Boolean);let node=state.ui?.ui_copy;
    for(const key of keys){if(!node||typeof node!=='object')return String(fallback??'');node=node[key];}
    if(node&&typeof node==='object'&&!Array.isArray(node)){const localized=node[locale]??node.sk??node.en;return localized==null?String(fallback??''):String(localized);}
    return node==null?String(fallback??''):String(node);
  }
  function applyEditableUiCopy(){
    const eyebrow=$('bootEyebrow'),bootStatus=$('bootStatus');
    if(eyebrow)eyebrow.textContent=uiCopy('loading.eyebrow','BLINQ INTELLIGENCE');
    if(bootStatus)bootStatus.textContent=uiCopy('loading.status',lcopy('Loading model · data · today’s predictions','Načítavam model · dáta · dnešné predikcie','Načítám model · data · dnešní predikce'));
  }
  function translatePublicDom(root=document){
    if(locale==='en'||!root)return;
    const shouldSkip=node=>{const el=node?.parentElement;return Boolean(el?.closest?.('.admin-route,.admin-canvas,.admin-inspector,.admin-toolbar,.admin-tabbar,.admin-accounts-grid,.admin-plan-grid,.reference-wordmark'))};
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(node=>{if(shouldSkip(node))return;const raw=node.nodeValue||'';const core=raw.trim();if(!core)return;const translated=publicText(core);if(translated!==core)node.nodeValue=raw.replace(core,translated);});
    root.querySelectorAll?.('[placeholder],[aria-label],[title]').forEach(el=>{if(el.closest?.('.admin-route,.admin-canvas,.admin-inspector,.admin-toolbar,.admin-tabbar'))return;['placeholder','aria-label','title'].forEach(attr=>{if(!el.hasAttribute(attr))return;const raw=el.getAttribute(attr);const translated=publicText(raw);if(translated!==raw)el.setAttribute(attr,translated);});});
  }
  const dashboardPickSectionKeys=['prime','top_daily','value','doubles','ace','sg'];
  const dashboardSectionKeys=[...dashboardPickSectionKeys,'results','btts'];
  const dashboardSectionFallback={
    prime:{label:'Short Odds',panel_id:'predictionsPanel',sidebar_element:'SIDEBAR_PRIME',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:1,preview_limit:5},
    top_daily:{label:'TOP Predictions',panel_id:'topDailyPanel',sidebar_element:'SIDEBAR_TOP_DAILY',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:2,preview_limit:5},
    value:{label:'Value Predictions',panel_id:'valuePanel',sidebar_element:'SIDEBAR_VALUE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:3,preview_limit:5},
    doubles:{label:'Doubles',panel_id:'doublesPanel',sidebar_element:'SIDEBAR_DOUBLES',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:4,preview_limit:5},
    ace:{label:'Ace Predictions',panel_id:'acePanel',sidebar_element:'SIDEBAR_ACE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:5,preview_limit:5},
    sg:{label:'S/G Predictions',panel_id:'sgPanel',sidebar_element:'SIDEBAR_SG',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:6,preview_limit:5},
    results:{label:'Results',panel_id:'resultsPreviewPanel',sidebar_element:'SIDEBAR_RESULTS',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:7,preview_limit:5},
    btts:{label:'BTTS Bonus',panel_id:'bttsBonusPanel',sidebar_element:'SIDEBAR_BTTS',sidebar_enabled:true,dashboard_enabled:false,dashboard_order:8,preview_limit:5},
  };
  const isAdminAccount = () => Boolean(state.feed?.account?.is_admin || String(state.feed?.account?.role||'').toLowerCase() === 'admin');
  const draftKey = () => state.ui?.admin?.draft_storage_key || state.uiSource?.admin?.draft_storage_key || 'blinq_admin_ui_config_v1';
  const elements = () => state.ui?.elements || {};
  const elementList = (kind=null, zone=null) => Object.entries(elements())
    .map(([id,value])=>({id,...(value||{})}))
    .filter(item=>(!kind||item.kind===kind)&&(!zone||item.zone===zone))
    .sort((a,b)=>Number(a.order||0)-Number(b.order||0));

  function bannerCreativeStyle(c={}){
    const n=(v,min,max,fallback)=>{const x=Number(v);return Number.isFinite(x)?Math.max(min,Math.min(max,x)):fallback;};
    const vars=[`--creative-headline-size:${n(c.headline_size,16,72,36)}px`,`--creative-text-size:${n(c.text_size,9,28,14)}px`,`--creative-eyebrow-size:${n(c.eyebrow_size,7,18,10)}px`,`--creative-delay:${n(c.animation_delay_ms,0,5000,80)}ms`];
    if(c.headline_color)vars.push(`--creative-headline-color:${String(c.headline_color)}`);if(c.text_color)vars.push(`--creative-text-color:${String(c.text_color)}`);if(c.overlay)vars.push(`--creative-overlay:${String(c.overlay)}`);
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
      const [tiers,banners,footer,theme,siteContent]=await Promise.all([getJSON('/config/membership-tiers.json'),getJSON('/config/banners.json'),getJSON('/config/footer-links.json'),getJSON('/config/site-theme.json'),getJSON('/config/site-content.json')]);
      state.presentationConfig={tiers,banners,footer,theme,siteContent}; state.siteContent=siteContent;
      Object.entries(tiers?.tiers||{}).forEach(([id,data])=>{if(!state.ui?.plans?.[id])return;const p=state.ui.plans[id];['label','card_title','description','short_description','cta_label','invite_only'].forEach(k=>{if(data[k]!==undefined)p[k]=data[k];});const u=safeExternalUrl(data.url||'');if(u)p.url=u;else if(data.url==='')p.url='';});
      const hero=banners?.main_banner||{};if(state.ui){const liveHero=state.ui.hero_banner||{};state.ui.hero_banner={...liveHero,rotation_seconds:liveHero.rotation_seconds??hero.rotation_seconds??6,auto_rotate:liveHero.auto_rotate??hero.auto_rotate??true,show_dots:liveHero.show_dots??hero.show_dots??true,pause_on_hover:liveHero.pause_on_hover??hero.pause_on_hover??true,slot_count:liveHero.slot_count??(Array.isArray(hero.slides)?Math.min(5,hero.slides.filter(x=>x?.enabled!==false).length):1)};}
      (hero.slides||[]).slice(0,5).forEach((row,i)=>{const item=state.ui?.elements?.[`HERO_BANNER_${i+1}`];if(item){item.content={...row,...(item.content||{})};}});
      const small=banners?.home_small_banners||{};(small.slides||[]).slice(0,4).forEach((row,i)=>{const item=state.ui?.elements?.[`SIDEBAR_PROMO_${i+1}`];if(item){item.content={...row,...(item.content||{})};}});
      const rail=state.ui?.elements?.VIP_RAIL;if(rail&&footer){const c=rail.content=rail.content||{};(footer.links||[]).slice(0,4).forEach((row,i)=>{const n=i+1;c[`benefit_${n}_title`]=row.enabled===false?'':row.title||'';c[`benefit_${n}_text`]=row.text||'';c[`benefit_${n}_title_size`]=row.title_size||15;c[`benefit_${n}_text_size`]=row.text_size||12;c[`benefit_${n}_icon`]=row.icon||'';c[`benefit_${n}_icon_url`]=row.icon_url||'';c[`benefit_${n}_link`]=row.link||'#predictions';});if(footer.cta){c.button_text=footer.cta.label||c.button_text;c.link=footer.cta.link||c.link;}};
      const bg=theme?.background||{};const style=document.documentElement.style;style.setProperty('--blinq-page-bg',`url("${String(bg.image||bg.fallback||'')}")`);style.setProperty('--blinq-page-bg-fallback',`url("${String(bg.fallback||'')}")`);style.setProperty('--blinq-page-bg-position',String(bg.position||'center top'));style.setProperty('--blinq-page-bg-size',String(bg.size||'cover'));style.setProperty('--blinq-page-bg-opacity',String(bg.enabled===false?0:(Number(bg.opacity)||0.2)));style.setProperty('--blinq-page-bg-overlay',String(bg.overlay||'linear-gradient(rgba(0,9,13,.8),rgba(0,9,13,.95))'));if(theme?.login?.background_image)style.setProperty('--blinq-login-bg',`url("${String(theme.login.background_image)}")`);if(theme?.login?.card_width)style.setProperty('--blinq-login-width',`${Number(theme.login.card_width)}px`);if(theme?.login?.logo_width)style.setProperty('--blinq-login-logo-width',`${Number(theme.login.logo_width)}px`);
    }catch{}
  }
  function applyManagedPageBackground(){
    const hero=state.ui?.elements?.HERO_BANNER_1?.content||{};
    const theme=state.presentationConfig?.theme?.background||{};
    const bg=String(hero.site_background_url||theme.image||theme.fallback||'').trim();
    const fallback=String(theme.fallback||bg||'').trim();
    const style=document.documentElement.style;
    if(bg)style.setProperty('--blinq-page-bg',`url("${bg.replaceAll('\"','')}")`);
    if(fallback)style.setProperty('--blinq-page-bg-fallback',`url("${fallback.replaceAll('\"','')}")`);
  }

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
          // Merge the new release schema around the already-published settings.
          // User-managed order, visibility, banner images/links and rotation must
          // survive an application update instead of silently reverting to repo defaults.
          state.ui.ui_revision=state.uiSource.ui_revision;
          state.ui.dashboard=mergeConfig(state.uiSource.dashboard||{},runtime.config.dashboard||{});
          // 6.7.0 product decision: Prime Predictions ship OFF. Apply this once when an
          // older published runtime config is migrated; after the admin publishes
          // 6.7.0, the new global category switch becomes the source of truth.
          if(['6.7.0','6.7.3','6.7.4','6.7.5','6.7.6','6.7.7'].includes(String(state.uiSource.ui_revision||''))){
            const primeTab=state.ui.dashboard?.daily_hub?.tabs?.prime;if(primeTab)primeTab.enabled=false;
            const primeSection=state.ui.dashboard?.sections?.prime;if(primeSection){primeSection.dashboard_enabled=false;primeSection.sidebar_enabled=false;}
          }
          state.ui.dashboard.user_switches=false;
          state.ui.dashboard.show_disabled_strip=false;
          state.ui.content_rows=mergeConfig(state.uiSource.content_rows||{},runtime.config.content_rows||{});
          state.ui.header_cta=mergeConfig(state.uiSource.header_cta||{},runtime.config.header_cta||{});
          state.ui.hero_banner=mergeConfig(state.uiSource.hero_banner||{enabled:true,slot_count:1,rotation_seconds:10,auto_rotate:true,show_dots:true,pause_on_hover:true},runtime.config.hero_banner||{});
          // 6.6.0 visual migration: reset only the first hero COPY to the approved base while preserving any admin-managed image, link, schedule and access. Once published under this revision, future edits are preserved.
          const srcHero=state.uiSource?.elements?.HERO_BANNER_1?.content,liveHero=state.ui?.elements?.HERO_BANNER_1?.content;
          if(srcHero&&liveHero){['eyebrow','headline','accent_text','text','button_text','theme','show_copy','creative_mode'].forEach(k=>{liveHero[k]=srcHero[k];});}
        }
      }
    } catch {}
    try {
      const rawLinks = await getJSON('/membership-links.json');
      const catalog = rawLinks?.plans && typeof rawLinks.plans==='object' ? rawLinks.plans : rawLinks;
      const aliases={pro_plus:'elite',premium_telegram:'legend'};
      const fields=['enabled','label','description','note','card_title','cta_label','invite_only','show_price','order'];
      Object.entries(catalog||{}).forEach(([rawId,row])=>{
        const id=aliases[String(rawId||'').toLowerCase()]||String(rawId||'').toLowerCase();
        if(!state.ui?.plans?.[id]) return;
        const plan=state.ui.plans[id];
        const data=(typeof row==='string')?{url:row}:((row&&typeof row==='object')?row:{});
        const url=safeExternalUrl(data.payment_url||data.url||data.link);
        if(url) plan.url=url;
        const invite=safeExternalUrl(data.invite_url||data.telegram_url);
        if(invite) plan.invite_url=invite;
        fields.forEach(key=>{ if(data[key]!==undefined) plan[key]=data[key]; });
        if(data.title!==undefined) plan.card_title=data.title;
        if(data.button_text!==undefined) plan.cta_label=data.button_text;
      });
    } catch {}
    await loadEditablePresentationConfig();
    applyV6514AdminCleanup();
    state.dashboardVisibility=null;
    renderAllUiContent();
  }

  function applyV6514AdminCleanup(){
    if(!state.ui)return;
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
    if(liveHub){liveHub.tabs=liveHub.tabs||{};['prime','top','doubles'].forEach(tab=>{if(!liveHub.tabs[tab]&&sourceTabs[tab])liveHub.tabs[tab]=clone(sourceTabs[tab]);});}
    // Replace only untouched stock middle placeholders with the new internal
    // information banners. Admin-edited or campaign-managed content survives.
    for(let i=1;i<=4;i++){
      const id=`CONTENT_MID_${i}`,live=state.ui?.elements?.[id],src=state.uiSource?.elements?.[id];
      const headline=String(live?.content?.headline||'');
      const untouched=/^Middle external slot/i.test(headline)||/^PARTNER SLOT$/i.test(String(live?.content?.eyebrow||''));
      if(live&&src&&untouched){live.content={...clone(src.content),active_from:live.content?.active_from||'',active_until:live.content?.active_until||''};}
    }
    if(state.adminTab==='feeds')state.adminTab='banners';
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

  function renderNavigationGroup(items, containerId) {
    const host=$(containerId); host.innerHTML='';
    [...(items||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
      const href=item.id==='btts'?'#btts':(item.href||`#${item.id}`);
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
  function bannerClickAllowed(item,plan=accountPlan()){
    if(plan==='admin'&&!state.previewPlan)return true;
    const normalized=plan==='trial'?'rookie':plan,map=item?.click_access||{};
    const value=Object.prototype.hasOwnProperty.call(map,plan)?map[plan]:Object.prototype.hasOwnProperty.call(map,normalized)?map[normalized]:true;
    return value!==false;
  }
  function firstBannerClickPlan(item){
    const plans=['rookie','pro','elite','legend','goat'].filter(id=>state.ui?.plans?.[id]?.enabled!==false).sort((a,b)=>Number(state.ui?.plans?.[a]?.order||99)-Number(state.ui?.plans?.[b]?.order||99));
    return plans.find(plan=>bannerClickAllowed(item,plan))||'goat';
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
    if($('overviewTitle'))$('overviewTitle').textContent=lcopy('Tennis. A clearer perspective.','Tenis pod drobnohľadom.','Tenis pod drobnohledem.');
    if($('overviewDescription'))$('overviewDescription').textContent=lcopy('Predictions and model projections, all in one place.','Predikcie a modelové projekcie na jednom mieste.','Predikce a modelové projekce na jednom místě.');
    const top=$('bannerTop'),mid=$('bannerMid'),bottom=$('bannerBottom');if(top)top.style.order='10';if(mid)mid.style.order='45';if(bottom)bottom.style.order='80';
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
    for(const key of ['results','btts']){const cfg=dashboardSectionConfig(key),panel=$(cfg.panel_id);if(panel)panel.hidden=true;}
    dashboardSectionKeys.forEach(key=>{
      const see=sectionSeeAllNode(key),ent=dashboardPlanEntitlement(key);if(!see)return;
      see.hidden=false;see.classList.toggle('section-see-all-locked',!ent.see_all);see.dataset.dashboardSection=key;
      const b=see.querySelector('b');
      if(ent.see_all){see.dataset.route=key;see.href=key==='btts'?'#btts':`#${key}`;delete see.dataset.upgradePlan;if(b)b.textContent=key==='btts'?'Open →':'See more →';}
      else{delete see.dataset.route;see.href='#';see.dataset.upgradePlan=firstUnlockPlan(key,0,true);if(b)b.textContent=`${lcopy('Available with','Dostupné s','Dostupné s')} ${upgradePlanLabel(see.dataset.upgradePlan).replace(/^BlinQ\s+/i,'')} →`;}
    });
    renderDashboardSectionToggles();
  }
  
  function lockedPickCard(key,index){
    const plan=firstUnlockPlan(key,index,false),label=upgradePlanLabel(plan),section=dashboardSectionConfig(key);
    return `<article class="prediction-card dashboard-locked-card access-locked" data-upgrade-plan="${escapeHtml(plan)}" data-upgrade-section="${escapeHtml(section.label||key)}"><div class="locked-ghost"><span></span><i>VS</i><span></span></div><div class="locked-pick-copy"><b aria-hidden="true">⌑</b><strong>Uzamknutý pick</strong><small>Dostupné od ${escapeHtml(label.replace(/^BlinQ\s+/i,''))}.</small><button type="button" class="btn btn-primary" data-upgrade-plan="${escapeHtml(plan)}" data-upgrade-section="${escapeHtml(section.label||key)}" data-upgrade-explicit="1">Upgrade →</button></div></article>`;
  }
  function translateSignalLabel(label){
    const raw=String(label||'Model signal');
    const legacy={'Celková výkonnosť':'Overall performance','Sila na povrchu':'Surface strength','Aktuálna forma':'Recent form','Vzájomné zápasy':'Head to head','Výkonnosť':'Performance','Forma':'Recent form'};
    const canonical=legacy[raw]||raw; return publicText(canonical);
  }

  function renderNavigation(){
    // Keep the visible top navigation in sync with the current route.
    // Secondary prediction routes belong to Predikcie, results to Štatistiky,
    // and informational model pages to Modely.
    const predictionRoutes=new Set(['predictions','prime','top_daily','value','doubles','ace','sg','btts']);
    const modelRoutes=new Set(['model_data','methodology','how_blinq_works']);
    const referenceRoute=predictionRoutes.has(state.route)?'predictions':state.route==='results'?'results':modelRoutes.has(state.route)?'model_data':state.route==='account'?'account':'';
    const referenceNav=document.querySelector('.reference-navigation');
    if(referenceNav){
      referenceNav.querySelectorAll('[data-route]').forEach(node=>{
        const active=Boolean(referenceRoute)&&node.dataset.route===referenceRoute;
        node.classList.toggle('active',active);
        if(active)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');
      });
      const community=referenceNav.querySelector('[data-open-insights]');
      if(community){community.classList.remove('active');community.removeAttribute('aria-current');}
    }
    const navIcons={prime:'✦',top_daily:'★',value:'◇',doubles:'◈',ace:'♠',sg:'▥',results:'✓',btts:'⚽'};
    const orderedSections=[...dashboardSectionKeys].filter(id=>id!=='btts').sort((a,b)=>sectionPlanOrder(a)-sectionPlanOrder(b)||Number(dashboardSectionConfig(a).dashboard_order||99)-Number(dashboardSectionConfig(b).dashboard_order||99));
    const primaryNav=[['predictions','Prehľad','⌂'],...orderedSections.map(id=>[id,dashboardSectionConfig(id).label||id,navIcons[id]||'•'])];
    const configNav=elementList('navigation');
    const main=primaryNav.map(([id,label,icon],index)=>{
      const item=configNav.find(entry=>entry.content?.route===id);
      const section=dashboardSectionKeys.includes(id)?dashboardSectionConfig(id):null;
      const access=item?.id?elementAccess(item.id):'active';return {id,label:publicText(label),icon,order:index+1,enabled:(section?section.sidebar_enabled!==false:true)&&access!=='hidden',beta:id==='btts',href:id==='btts'?'#btts':`#${id}`,element_id:item?.id||''};
    });
    renderNavigationGroup(main,'mainNavigation');
    const adminWrap=$('adminNavigationWrap');
    if(adminWrap){
      adminWrap.hidden=!isAdminAccount();
      renderNavigationGroup(isAdminAccount()?[{id:'admin',href:'#admin',icon:'⚙',label:'Admin',order:1,enabled:true}]:[],'adminNavigation');
    }
    const profileAdmin=$('profileAdminLink');if(profileAdmin)profileAdmin.hidden=!isAdminAccount();
    const footer=$('footerLearnNavigation');
    if(footer){
      footer.innerHTML='';
      [...(state.ui?.footer?.links||state.ui?.navigation?.learn||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
        const a=document.createElement('a'); a.href=item.href||`#${item.id}`; a.dataset.route=item.id||''; a.textContent=publicText(item.label||item.id); footer.appendChild(a);
      });
    }
  }

  function watermarkHtml(item){
    const wm=item?.watermark||{};
    if(!wm.enabled)return '';
    const preset=String(wm.preset||'violet').replace(/[^a-z0-9_-]/gi,'');
    const position=['top-left','top-right','bottom-left','bottom-right','center'].includes(String(wm.position))?String(wm.position):'bottom-right';
    const opacity=Math.max(.12,Math.min(1,Number(wm.opacity)||.42));
    const size=Math.max(.7,Math.min(1.6,Number(wm.size)||1));
    return `<span class="slot-watermark wm-${escapeHtml(preset)} wm-${escapeHtml(position)}" style="--wm-opacity:${opacity};--wm-scale:${size}">${escapeHtml(wm.text||'COMING SOON')}</span>`;
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
  // v6.5.8 fixed banner zones: the outer row is stable; 1–4 active blocks divide it equally.
  const contentRowZones=['content_top','content_mid','content_bottom'];
  const rowPresetMap={'1':1,'2':2,'3':3,'4':4,'1+1+1+1':4,'2+2':2,'2+1+1':3,'1+1+2':3};
  function rowConfig(zone){ return state.ui?.content_rows?.[zone]||{}; }
  function rowEnabled(zone){ return rowConfig(zone).enabled!==false && rowSlotCount(zone)>0; }
  function rowSlotCount(zone){
    const row=rowConfig(zone);
    const explicit=Number(row.slot_count);
    if(Number.isInteger(explicit)&&explicit>=0&&explicit<=4)return explicit;
    return rowPresetMap[String(row.preset||'1')]||1;
  }
  function rowPreset(zone){ return String(rowSlotCount(zone)); }
  function rowItems(zone){
    const count=rowSlotCount(zone);if(!rowEnabled(zone)||!count)return [];
    const all=elementList('large_banner',zone).filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden');
    return all.slice(0,count).map((item,index)=>({item,index,span:1,layoutCount:count}));
  }

  function marketingAvatarUrl(planId){
    const id=String(planId||'').toLowerCase();
    const entry=state.ui?.assets?.account_avatars?.[id]||{};
    // v6.5.16: membership artwork is image-only. Plan labels are rendered beside
    // the avatar and never baked/overlaid into the circular artwork.
    return avatarAssetSrc(entry.marketing||entry.default||entry.w||entry.m||'');
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
    const rawContent=resolvedBannerContent(item,index),c={...rawContent,eyebrow:publicText(rawContent.eyebrow||''),headline:publicText(rawContent.headline||''),accent_text:publicText(rawContent.accent_text||''),text:publicText(rawContent.text||''),button_text:publicText(rawContent.button_text||'')},route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#predictions'),external=isExternalLink(href);
    const theme=String(c.theme||'blue').replace(/[^a-z0-9_-]/gi,'');
    const icon=String(c.icon||({blue:'✈',gold:'♛',green:'▥',purple:'✦',violet:'✦'}[theme]||'✦')).slice(0,3);
    const image=safeLink(c.image_url,'');
    const imageHtml=image&&!image.startsWith('#')?`<span class="header-slot-image"><img src="${escapeHtml(image)}" alt="" loading="lazy"></span>`:`<span class="header-slot-icon" aria-hidden="true">${escapeHtml(icon)}</span>`;
    const clickable=bannerClickAllowed(item),lockedPlan=clickable?'':firstBannerClickPlan(item),finalHref=clickable?href:'#';
    return `<a href="${escapeHtml(finalHref)}" ${clickable&&external?'target="_blank" rel="noopener"':''} ${clickable&&route&&!external?`data-route="${escapeHtml(route)}"`:''} ${!clickable?`data-upgrade-plan="${escapeHtml(lockedPlan)}" data-upgrade-section="${escapeHtml(c.headline||item.label||'Premium banner')}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)} class="header-slot theme-${escapeHtml(theme)}${c.plan_id?' has-plan-avatar':''}${clickable?'':' is-link-locked'}">${imageHtml}<div class="header-slot-copy"><small>${escapeHtml(c.eyebrow||item.label)}</small><strong>${escapeHtml(c.headline||'')}</strong><span>${escapeHtml(c.text||'')}</span></div><b class="header-slot-cta">${!clickable?'🔒 '+escapeHtml(upgradePlanLabel(lockedPlan).replace(/^BlinQ\s+/i,'')):escapeHtml(c.button_text||'OPEN')+' →'}</b>${watermarkHtml(item)}</a>`;
  }
  function renderHeaderSlots(){
    const host=$('headerFeatureStrip'); if(!host)return;
    const cfg=state.ui?.header_cta||{};
    const requested=Math.max(0,Math.min(3,Number(cfg.slot_count??3)||0));
    const managed=elementList('header_slot','header').filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden').slice(0,requested);
    host.hidden=cfg.enabled===false||!managed.length;
    host.dataset.layout=String(managed.length);
    host.style.setProperty('--header-slot-count',String(Math.max(1,managed.length)));
    host.innerHTML=managed.map((item,index)=>headerSlotHtml(item,index)).join('');
    if(managed.length)installBannerTracking(host);
  }

  function heroConfig(){
    return state.ui?.hero_banner||{};
  }
  function heroItems(){
    const cfg=heroConfig();
    const requested=Math.max(0,Math.min(5,Number(cfg.slot_count??1)||0));
    if(cfg.enabled===false||!requested)return [];
    return elementList('hero_banner','hero').slice(0,requested).filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden');
  }
  function heroImageHtml(content){
    const desktop=safeLink(content?.image_url,'');
    const mobile=safeLink(content?.mobile_image_url,'');
    if(!desktop||desktop.startsWith('#'))return '';
    const fit=['cover','contain'].includes(String(content?.image_fit||'cover'))?String(content.image_fit||'cover'):'cover';
    const position=['center','left','right','top','bottom'].includes(String(content?.image_position||'center'))?String(content.image_position||'center'):'center';
    const img=`<img class="hero-slide-image fit-${escapeHtml(fit)} pos-${escapeHtml(position)}" src="${escapeHtml(desktop)}" alt="" loading="eager">`;
    return mobile&&!mobile.startsWith('#')?`<picture class="hero-slide-picture"><source media="(max-width: 700px)" srcset="${escapeHtml(mobile)}">${img}</picture>`:img;
  }
  function heroSlideHtml(item,index){
    const rawContent=resolvedBannerContent(item,index),c={...rawContent,eyebrow:publicText(rawContent.eyebrow||''),headline:publicText(rawContent.headline||''),accent_text:publicText(rawContent.accent_text||''),text:publicText(rawContent.text||''),button_text:publicText(rawContent.button_text||'')},route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#predictions'),external=isExternalLink(href);
    const theme=String(c.theme||'violet').replace(/[^a-z0-9_-]/gi,'');
    const showCopy=c.show_copy!==false;
    const sponsored=c.sponsored?'<span class="sponsored-label hero-sponsored">SPONSORED</span>':'';
    const image=heroImageHtml(c);
    const art=image?'':`<div class="dashboard-hero-ball" aria-hidden="true"><i></i><b></b></div><div class="dashboard-hero-mark" aria-hidden="true"><strong>BlinQ</strong><span>STATISTICAL ENGINE</span><small>by BackstageTalks</small></div>`;
    const accent=String(c.accent_text||'').trim();
    const title=escapeHtml(c.headline||'Data. Analysis.');
    const titleHtml=accent?`<h2><span>${title}</span><strong>${escapeHtml(accent)}</strong></h2>`:`<h2><strong>${title}</strong></h2>`;
    const copy=showCopy?`<div class="dashboard-hero-copy"><small>${escapeHtml(c.eyebrow||'BLINQ')}</small>${titleHtml}<p>${escapeHtml(c.text||'')}</p>${c.button_text?`<b class="hero-slide-cta">${escapeHtml(c.button_text)} →</b>`:''}</div>`:'';
    const clickable=bannerClickAllowed(item),lockedPlan=clickable?'':firstBannerClickPlan(item),finalHref=clickable?href:'#';
    return `<a class="dashboard-hero hero-slide theme-${escapeHtml(theme)}${bannerCreativeClasses(c)}${index===state.heroIndex?' is-active':''}${showCopy?'':' hero-image-only'}${clickable?'':' is-link-locked'}" ${bannerCreativeStyle(c)} href="${escapeHtml(finalHref)}" ${clickable&&external?'target="_blank" rel="noopener"':''} ${clickable&&route&&!external?`data-route="${escapeHtml(route)}"`:''} ${!clickable?`data-upgrade-plan="${escapeHtml(lockedPlan)}" data-upgrade-section="${escapeHtml(c.headline||item.label||'Premium banner')}"`:''} data-hero-index="${index}" data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)} aria-hidden="${index===state.heroIndex?'false':'true'}">${sponsored}${image}${copy}${art}${watermarkHtml(item)}</a>`;
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

  function bannerHtml(item, sidebar=false, index=0, layoutCount=1){
    const rawContent=resolvedBannerContent(item,index),c={...rawContent,eyebrow:publicText(rawContent.eyebrow||''),headline:publicText(rawContent.headline||''),accent_text:publicText(rawContent.accent_text||''),text:publicText(rawContent.text||''),button_text:publicText(rawContent.button_text||'')},route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#account'),external=isExternalLink(href),clickable=bannerClickAllowed(item),lockedPlan=clickable?'':firstBannerClickPlan(item),finalHref=clickable?href:'#'; const theme=String(c.theme||'violet').replace(/[^a-z0-9_-]/gi,'');
    const sponsored=c.sponsored?'<span class="sponsored-label">SPONSORED</span>':'';
    const attrs=`aria-label="${escapeHtml(c.headline||c.button_text||item.label||'Open partner content')}" ${clickable&&route&&!external?`data-route="${escapeHtml(route)}"`:''} ${!clickable?`data-upgrade-plan="${escapeHtml(lockedPlan)}" data-upgrade-section="${escapeHtml(c.headline||item.label||'Premium banner')}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)}`;
    const target=clickable&&external?'target="_blank" rel="noopener"':'';
    if(sidebar){
      return `<a class="sidebar-promo theme-${theme}${c.plan_id?' has-plan-avatar':''}" href="${escapeHtml(finalHref)}" ${target} ${attrs}>${sponsored}<div class="sidebar-promo-copy"><small>${escapeHtml(c.eyebrow||'BLINQ')}</small><strong>${escapeHtml(c.headline||'')}</strong><span>${escapeHtml(c.text||'')}</span><b>${escapeHtml(c.button_text||'Open')}</b></div>${promoPlanAvatarHtml(c,true)}${watermarkHtml(item)}</a>`;
    }
    const count=Math.max(1,Math.min(4,Number(layoutCount)||1));
    const fullCreative=c.creative_mode==='full'||(c.type==='advertisement'&&c.show_copy===false);
    const showCopy=c.show_copy!==false;
    return `<a class="promo-banner promo-card theme-${theme} layout-${count}${fullCreative?' creative-full':''}${showCopy?'':' no-copy'}${c.plan_id?' has-plan-avatar':''}" href="${escapeHtml(finalHref)}" ${target} ${attrs}>${sponsored}${bannerImageHtml(c,count)}${showCopy?`<div class="promo-copy"><span class="promo-eyebrow">${escapeHtml(c.eyebrow||'BLINQ')}</span><strong>${escapeHtml(c.headline||'')}</strong><p>${escapeHtml(c.text||'')}</p><span class="promo-cta">${escapeHtml(c.button_text||'Open')}</span></div>`:''}${promoPlanAvatarHtml(c,false)}${watermarkHtml(item)}</a>`;
  }
  function renderBanners(){
    const hostByZone={content_top:'bannerTop',content_mid:'bannerMid',content_bottom:'bannerBottom'};
    contentRowZones.forEach((zone,rowIndex)=>{
      const host=$(hostByZone[zone]);if(!host)return;
      const visible=rowItems(zone),count=visible.length;
      host.hidden=!count;host.dataset.layout=String(count);host.dataset.rowEnabled=count?'true':'false';
      host.style.setProperty('--banner-slot-count',String(Math.max(1,count)));
      host.innerHTML=visible.map((entry,index)=>bannerHtml(entry.item,false,rowIndex*4+index,count)).join('');
      if(count)installBannerTracking(host);
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
    const rssSlots=elementList().some(item=>['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind)&&item.content?.type==='rss');
    const adSlots=elementList().some(item=>['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind)&&(item.content?.type==='advertisement'||item.content?.sponsored===true));
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
      node.dataset.uiStateLabel=mode==='active'?'':`${mode.toUpperCase()} · ${accessLabel()}`;
      node.setAttribute('aria-disabled',mode==='active'?'false':'true');
      if(mode!=='active'){
        node.classList.add('access-locked');
        if(!node.dataset.upgradePlan){
          const sectionKey=dashboardSectionKeyForSidebarElement(id)||'top_daily';
          node.dataset.upgradePlan=firstUnlockPlan(sectionKey,0,true);
          node.dataset.upgradeSection=node.textContent?.trim().slice(0,70)||dashboardSectionConfig(sectionKey).label||'BlinQ';
          node.dataset.accessAutoLock='1';
        }
      }else if(node.dataset.accessAutoLock==='1'){
        delete node.dataset.upgradePlan;delete node.dataset.upgradeSection;delete node.dataset.accessAutoLock;
      }
    });
  }
  function refreshTopPlanCta(){
    const button=$('topUpgradeButton'),label=$('topUpgradeLabel');if(!button||!label)return;
    const plan=accountPlan();
    if(plan==='goat'){button.hidden=true;return;}
    const current=membershipHierarchy.indexOf(plan);
    const next=current>=0&&current<membershipHierarchy.length-1?membershipHierarchy[current+1]:'pro';
    button.hidden=false;button.dataset.upgradePlan=next;button.dataset.upgradeSection='BlinQ Membership';
    label.textContent=publicText('Upgrade');
  }
  function updateLanguageLinks(){
    document.querySelectorAll('#footerLanguages [data-lang],#authLanguages [data-lang]').forEach(link=>{const lang=link.dataset.lang||'sk';link.href=link.closest('#authLanguages')?`?lang=${encodeURIComponent(lang)}`:`?lang=${encodeURIComponent(lang)}#${encodeURIComponent(state.route||'predictions')}`;link.classList.toggle('active',lang===locale);});
  }
  function vipFeatureIcon(index=0){
    const icons=[
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18 3.8 8.8 9 12l3-6 3 6 5.2-3.2L19 18z"></path><path d="M5 21h14"></path></svg>',
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16c3.5-7 6.5 1 10-6 1.5-2.6 3.3-3.4 6-2"></path><circle cx="4" cy="16" r="1.3"></circle><circle cx="14" cy="10" r="1.3"></circle><circle cx="20" cy="8" r="1.3"></circle></svg>',
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14v14H5z"></path><path d="M9 5v14M15 5v14M5 10h14M5 15h14"></path></svg>',
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"></circle><circle cx="12" cy="12" r="2.4"></circle><path d="M12 2.5V5M21.5 12H19M12 21.5V19M2.5 12H5"></path></svg>'
    ];return icons[index]||icons[0];
  }
  function lockIcon(){return '<svg class="inline-lock-icon" viewBox="0 0 20 20" aria-hidden="true"><rect x="4.5" y="8.5" width="11" height="8" rx="2"></rect><path d="M7 8.5V6a3 3 0 0 1 6 0v2.5"></path></svg>';}
  function renderVipRail(){
    const host=$('vipRail');if(!host)return;
    const item=elements()?.VIP_RAIL,c=item?.content||{};
    if(!item||c.enabled===false||elementAccess('VIP_RAIL')==='hidden'){host.hidden=true;host.innerHTML='';return;}
    host.hidden=false;
    const benefits=[1,2,3,4].map((n,i)=>{
      const title=String(c[`benefit_${n}_title`]||'').trim(),text=String(c[`benefit_${n}_text`]||'').trim();
      if(!title&&!text)return '';
      const iconUrl=safeUiAsset(c[`benefit_${n}_icon_url`]||'')||safeExternalUrl(c[`benefit_${n}_icon_url`]||'');
      const icon=iconUrl?`<img src="${escapeHtml(iconUrl)}" alt="" loading="lazy">`:`<span class="vip-feature-svg" aria-hidden="true">${vipFeatureIcon(i)}</span>`;
      const rawLink=String(c[`benefit_${n}_link`]||'').trim();
      const href=rawLink?safeLink(rawLink,''):'';
      const external=href&&isExternalLink(href);
      const arrow=external?'↗':'→';
      const inner=`<span class="vip-link-icon">${icon}</span><span class="vip-link-copy"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text)}</small></span><span class="vip-link-arrow" aria-hidden="true">${arrow}</span>`;
      return href?`<a class="vip-link-card" href="${escapeHtml(href)}" ${external?'target="_blank" rel="noopener"':''}>${inner}</a>`:`<div class="vip-link-card is-static">${inner}</div>`;
    }).filter(Boolean).join('');
    if(!benefits){host.hidden=true;host.innerHTML='';return;}
    host.innerHTML=`<div class="vip-rail-content vip-links-only"><div class="vip-benefits">${benefits}</div></div>`;
  }
  function renderFooterConfig(){
    const footer=state.ui?.footer||{};
    const copyright=$('footerCopyright');if(copyright)copyright.textContent=String(footer.copyright||'© 2026 BlinQ');
    const wrap=document.querySelector('.system-status'),status=wrap?.querySelector('strong');
    const model=$('footerModelState');
    const generated=state.feed?.generated_at||'';
    const generatedMs=Date.parse(generated);
    const feedAgeMin=Number.isFinite(generatedMs)?Math.max(0,(Date.now()-generatedMs)/60000):Infinity;
    const liveScan=state.userLiveRadarStatus?.scanned_at||'';
    const liveMs=Date.parse(liveScan);
    const liveAgeMin=Number.isFinite(liveMs)?Math.max(0,(Date.now()-liveMs)/60000):Infinity;
    const liveError=Boolean(state.userLiveRadarStatus?.error);
    const feedStale=Boolean(state.feed?.stale)||feedAgeMin>90;
    const feedOld=feedAgeMin>30;
    const liveFresh=liveAgeMin<=3&&!liveError;
    const updated=generated?fmtTime(generated):'—';
    const liveUpdated=liveScan?fmtTime(liveScan):'';
    if(wrap){
      wrap.classList.toggle('is-error',liveError&&!Number.isFinite(generatedMs));
      wrap.classList.toggle('is-warning',!liveFresh&&(feedOld||feedStale||liveError));
      wrap.classList.toggle('is-ok',liveFresh||(!feedOld&&!feedStale&&!liveError));
    }
    if(status){
      if(liveFresh){
        status.textContent=`${uiCopy('footer.live_ok',lcopy('LIVE radar active','LIVE radar aktívny','LIVE radar aktivní'))}${liveUpdated?' · '+liveUpdated:''}`;
      }else if(liveError){
        status.textContent=`${uiCopy('footer.offline',lcopy('Services reconnecting','Služby sa obnovujú','Služby se obnovují'))} · ${uiCopy('footer.updated',lcopy('Updated','Aktualizované','Aktualizováno'))} ${updated}`;
      }else if(feedStale){
        status.textContent=`${uiCopy('footer.updated',lcopy('Updated','Aktualizované','Aktualizováno'))} ${updated} · ${uiCopy('footer.feed_stale',lcopy('Waiting for data refresh','Čaká sa na aktualizáciu dát','Čeká se na aktualizaci dat'))}`;
      }else if(feedOld){
        status.textContent=`${uiCopy('footer.updated',lcopy('Updated','Aktualizované','Aktualizováno'))} ${updated} · ${uiCopy('footer.feed_old',lcopy('Data is older','Dáta sú staršie','Data jsou starší'))}`;
      }else{
        status.textContent=`${uiCopy('footer.updated',lcopy('Updated','Aktualizované','Aktualizováno'))} ${updated} · ${uiCopy('footer.feed_fresh',lcopy('Data is current','Dáta sú aktuálne','Data jsou aktuální'))}`;
      }
    }
    if(model&&liveScan){model.title=`${model.title||model.textContent||''} · LIVE ${liveUpdated}`.trim();}
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
    if(route==='support')wireSupportForm();
    if(!dialog.open)dialog.showModal();
  }
  function renderAllUiContent(){ applyEditableUiCopy(); if(state.bannerObserver){state.bannerObserver.disconnect();state.bannerObserver=null;}state.bannerTimers=new WeakMap();renderNavigation(); wireDashboardSearch(); applyManagedPageBackground(); renderHeaderSlots(); renderHeroBanner(); renderBanners(); renderVipRail(); renderFooterConfig(); renderMarketSections(); renderDashboardResultsPreview(); renderDashboardComposition(); renderDashboardKpis(); refreshTopPlanCta(); updateLanguageLinks(); applyAccessStates(); renderInsightBell(); translatePublicDom(document.body); }

  function auth(mode='login'){
    feedGeneration++;
    window.BlinqUI.closeMenu(false); $('appShell').hidden=true;
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
    $('authTitle').textContent=uiCopy(authCopyKey,publicText(authFallback));
    $('authSubtitle').textContent=''; $('authSubtitle').hidden=true;
    $('authSubmit').textContent=publicText({login:'Sign in',signup:'Create account',reset:'Send recovery link',recovery:'Save password'}[mode]);
    $('switchSignup').textContent=publicText(mode==='login'?'Create account':'Back to sign in'); $('switchReset').hidden=mode!=='login';
    $('authSubmit').disabled=!state.authEnabled;
    if(!state.authEnabled) $('authMessage').textContent=publicText('Authentication is temporarily unavailable.');
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
    button.disabled=true; message.textContent=publicText('Working…');
    try{
      if(state.authMode==='reset'){ await BlinqAuth.reset(email); $('authMessage').textContent=publicText('If the account exists, check your email for the recovery link.'); return; }
      if(state.authMode==='recovery') await BlinqAuth.update({password});
      else if(state.authMode==='signup'){
        const result=await BlinqAuth.signUp(email,password,$('authName').value.trim(),{version:String(state.siteContent?.updated_at||'2026-09-16'),locale:contentLocale()});
        if(result?.verification_required){
          auth('login');$('authEmail').value=email;$('authPassword').value='';
          $('authMessage').textContent=publicText('Verification email sent. Open the link in your inbox, then sign in.');
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
          ?publicText('This BlinQ account is suspended. Contact support if you believe this is a mistake.')
          :publicText(error.message||'Sign-in failed. Please try again.');
      if($('resendVerification'))$('resendVerification').hidden=!verification;
      if(!$('authDialog').open)$('authDialog').showModal();
    }
    finally{ button.disabled=false; }
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
    return {id:row?.event_id||row?.id,date:row?.scheduled_at,tour:String(row?.tour||'').toUpperCase(),tournament:row?.tournament||'Tournament',surface:row?.surface||'unknown',round:row?.round||'',p1:player1?.name||'Player 1',p2:player2?.name||'Player 2',p1Id:player1?.id,p2Id:player2?.id,p1Prob:p1,p2Prob:p2,p1Rank:player1?.rank??null,p2Rank:player2?.rank??null,p1PrevRank:player1?.previous_rank??null,p2PrevRank:player2?.previous_rank??null,p1BestRank:player1?.best_rank??null,p2BestRank:player2?.best_rank??null,p1RankingPoints:player1?.ranking_points??null,p2RankingPoints:player2?.ranking_points??null,p1Country:player1?.country_code||'',p2Country:player2?.country_code||'',p1Photo:safePhotoUrl(player1?.photo_url),p2Photo:safePhotoUrl(player2?.photo_url),pick:winner?.name||'—',pickId:winnerId,probability,confidence:Number.isFinite(probability)?confidenceBand(probability):'unknown',signals:Array.isArray(row?.signals)?row.signals:[],quality:row?.quality&&typeof row.quality==='object'?row.quality:{},dataDepth:Number(row?.data_depth),odds:Number(betting.odds),edge:Number(betting.edge),expectedValue:Number(betting.expected_value),bettingDay:betting.betting_day||'',model:row?.model_version||state.feed?.model?.version||'',raw:row};
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
    if(Number.isFinite(currentRank)&&Number.isFinite(previousRank)&&currentRank>0&&previousRank>0&&currentRank!==previousRank){const delta=previousRank-currentRank;signals.push({key:'rank',label:lcopy('Ranking trend','Trend rebríčka','Trend žebříčku'),value:`${delta>0?'↑':'↓'}${Math.abs(Math.trunc(delta))}`,tone:delta>0?'positive':'warning',note:''});}
    if(Number.isFinite(overallElo)&&Number.isFinite(surfaceElo)){const delta=surfaceElo-overallElo;signals.push({key:'fit',label:lcopy('Surface fit','Povrchový fit','Povrchový fit'),value:`${delta>=0?'+':''}${Math.round(delta)}`,tone:delta>35?'positive':delta<-35?'warning':'neutral',note:'Elo'});}
    const known=signals.filter(item=>item.key!=='stakes').length;
    return {motivation,label:motivation>=3?lcopy('High','Vysoká','Vysoká'):motivation>=1?lcopy('Elevated','Zvýšená','Zvýšená'):lcopy('Neutral','Neutrálna','Neutrální'),signals,known};
  }
  function renderMotivationPanel(row){
    const match=normalize(row),m1=motivationContext(row,1),m2=motivationContext(row,2);
    const card=(name,m)=>`<article class="motivation-card context-card"><header><div><small>${escapeHtml(lcopy('PRE-MATCH CONTEXT','PREDZÁPASOVÝ KONTEXT','PŘEDZÁPASOVÝ KONTEXT'))}</small><strong>${escapeHtml(name)}</strong></div><b class="motivation-score ${m.motivation>=1?'is-positive':''}">${escapeHtml(m.label)}</b></header><div class="context-signal-grid">${m.signals.slice(0,8).map(item=>`<span class="context-signal tone-${escapeHtml(item.tone||'neutral')}"><small>${escapeHtml(item.label)}</small><strong>${escapeHtml(item.value)}</strong>${item.note?`<em>${escapeHtml(item.note)}</em>`:''}</span>`).join('')}</div></article>`;
    return `<section class="rail-motivation rail-context"><div class="rail-section-title"><div><small>CONTEXT</small><h3>${escapeHtml(lcopy('Motivation & readiness','Motivácia & pripravenosť','Motivace & připravenost'))}</h3></div><span>${escapeHtml(lcopy('Point-in-time · pre-match','Point-in-time · pred zápasom','Point-in-time · před zápasem'))}</span></div><div class="motivation-grid">${card(match.p1,m1)}${card(match.p2,m2)}</div><p class="motivation-note">${escapeHtml(lcopy('Motivation reflects observable stakes and home context. Rest, workload, travel, altitude and form are shown separately; no psychological state is inferred.','Motivácia vychádza iba z pozorovateľnej dôležitosti zápasu a domáceho prostredia. Oddych, zaťaženie, presun, výška a forma sú zobrazené samostatne; psychický stav neodhadujeme.','Motivace vychází pouze z pozorovatelné důležitosti zápasu a domácího prostředí. Odpočinek, zátěž, přesun, výška a forma jsou zobrazeny samostatně; psychický stav neodhadujeme.'))}</p></section>`;
  }
  function dashboardDailyRows(){
    const rows=dailyHubRows('daily');
    return Array.isArray(rows)?rows:[];
  }
  function renderDashboardKpis(){
    const host=$('dashboardKpis');if(!host)return;
    const rows=dashboardDailyRows();
    const odds=rows.map(r=>Number(r?.odds??r?.betting?.odds)).filter(Number.isFinite);
    const edges=rows.map(r=>Number(r?.edge??r?.betting?.edge)).filter(Number.isFinite);
    const perf=state.feed?.performance||{};
    const accuracy=Number(perf?.accuracy);
    const avgOdds=odds.length?odds.reduce((a,b)=>a+b,0)/odds.length:null;
    const avgEdge=edges.length?edges.reduce((a,b)=>a+b,0)/edges.length:null;
    const icons={
      board:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20V11M10 20V6M15 20v-8M20 20V3"/></svg>',
      target:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/><path d="M17 7l3-3M17 4h3v3"/></svg>',
      chart:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 18l5-5 4 3 7-9"/><path d="M15 7h5v5"/></svg>',
      coins:'<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>'
    };
    const rawDelta=firstFinite(perf?.accuracy_delta,perf?.accuracy_change,perf?.trend_accuracy,perf?.last_7d_delta);
    const delta=rawDelta==null?'':`${rawDelta>0?'+':''}${(rawDelta*(Math.abs(rawDelta)<=1?100:1)).toFixed(1)}%`;
    const cards=[
      [icons.board,lcopy('TODAY PREDICTIONS','DNEŠNÉ PREDIKCIE','DNEŠNÍ PREDIKCE'),String(rows.length),lcopy('matches','zápasov','zápasů'),''],
      [icons.target,lcopy('MODEL SUCCESS','MODEL ÚSPEŠNOSŤ','ÚSPĚŠNOST MODELU'),Number.isFinite(accuracy)?pct(accuracy):'—',lcopy('(last 7 days)','(posledných 7 dní)','(posledních 7 dní)'),delta],
      [icons.chart,lcopy('AVERAGE ODDS','PRIEMERNÝ KURZ','PRŮMĚRNÝ KURZ'),avgOdds==null?'—':avgOdds.toFixed(2),'',''],
      [icons.coins,lcopy('AVERAGE EDGE','PRIEMERNÝ EDGE','PRŮMĚRNÝ EDGE'),avgEdge==null?'—':`${avgEdge>0?'+':''}${(avgEdge*(Math.abs(avgEdge)<=1?100:1)).toFixed(1)}%`,'','']
    ];
    host.innerHTML=cards.map(([icon,label,value,note,trend])=>`<article class="dashboard-kpi"><span>${icon}</span><div><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}${trend?`<em class="kpi-trend">↗ ${escapeHtml(trend)}</em>`:''}</strong>${note?`<p>${escapeHtml(note)}</p>`:''}</div></article>`).join('');
  }
  function highlightRow(){
    return dashboardDailyRows()[0]||dailyHubRows('top')[0]||dailyHubRows('value')[0]||null;
  }
  function clearRailPromoRotation(){if(state.railPromoTimer){clearInterval(state.railPromoTimer);state.railPromoTimer=null;}}
  function railPromoItems(){return elementList('sidebar_promo','sidebar').slice(0,4);}
  function railPromoSlideHtml(item,index){
    const raw=resolvedBannerContent(item,index+8),c={...raw,eyebrow:publicText(raw.eyebrow||''),headline:publicText(raw.headline||''),text:publicText(raw.text||''),button_text:publicText(raw.button_text||'')};
    const route=c.route||'',href=safeLink(c.link,route?`#${route}`:'#account'),external=isExternalLink(href),clickable=bannerClickAllowed(item),lockedPlan=clickable?'':firstBannerClickPlan(item),finalHref=clickable?href:'#';
    const theme=String(c.theme||'green').replace(/[^a-z0-9_-]/gi,'');
    const sponsored=c.sponsored===true||c.type==='advertisement';
    const image=safePhotoUrl(c.image_url||'');
    const attrs=`${clickable&&route&&!external?`data-route="${escapeHtml(route)}"`:''} ${!clickable?`data-upgrade-plan="${escapeHtml(lockedPlan)}" data-upgrade-section="${escapeHtml(c.headline||item.label||'Premium banner')}"`:''} data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)}`;
    return `<a class="rail-native-banner theme-${theme}${bannerCreativeClasses(c)}${index===state.railPromoIndex?' is-active':''}" ${bannerCreativeStyle(c)} href="${escapeHtml(finalHref)}" ${clickable&&external?'target="_blank" rel="noopener"':''} ${attrs} data-rail-promo-slide="${index}" aria-hidden="${index===state.railPromoIndex?'false':'true'}">${image?`<img src="${escapeHtml(image)}" alt="" loading="lazy">`:''}<span class="rail-native-glow" aria-hidden="true"></span><div class="rail-native-copy">${sponsored?`<small class="rail-sponsored">${escapeHtml(lcopy('Sponsored','Sponzorované','Sponzorováno'))}</small>`:`<small>${escapeHtml(c.eyebrow||'BLINQ')}</small>`}<strong>${escapeHtml(c.headline||item.label||'BlinQ')}</strong><p>${escapeHtml(c.text||'')}</p><b>${escapeHtml(c.button_text||lcopy('Open','Otvoriť','Otevřít'))} →</b></div>${watermarkHtml(item)}</a>`;
  }
  function setRailPromoSlide(index,restart=false){
    const host=$('dashboardRightRailContent'),slides=[...(host?.querySelectorAll('[data-rail-promo-slide]')||[])];
    if(!slides.length)return;
    state.railPromoIndex=((Number(index)||0)%slides.length+slides.length)%slides.length;
    slides.forEach((slide,i)=>{const active=i===state.railPromoIndex;slide.classList.toggle('is-active',active);slide.setAttribute('aria-hidden',active?'false':'true');slide.tabIndex=active?0:-1;});
    [...host.querySelectorAll('[data-rail-promo-dot]')].forEach((dot,i)=>{const active=i===state.railPromoIndex;dot.classList.toggle('is-active',active);dot.setAttribute('aria-current',active?'true':'false');});
    const counter=host.querySelector('[data-rail-promo-counter]');if(counter)counter.textContent=`${state.railPromoIndex+1}/${slides.length}`;
    if(restart)startRailPromoRotation();
  }
  function startRailPromoRotation(){
    clearRailPromoRotation();const items=railPromoItems();
    if(items.length<2||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    state.railPromoTimer=setInterval(()=>{if(state.railPromoPaused||document.hidden||state.route!=='predictions'||state.railMatch)return;setRailPromoSlide(state.railPromoIndex+1,false);},9000);
  }
  function renderDashboardRightRailDefault(){
    const defaultPanel=$('dashboardSidebarDefault'),matchPanel=$('dashboardSidebarMatch'),host=$('dashboardRightRailContent');
    if(defaultPanel)defaultPanel.hidden=false;if(matchPanel){matchPanel.hidden=true;matchPanel.innerHTML='';}
    if(!host||state.railMatch)return;
    clearRailPromoRotation();
    const items=railPromoItems();
    if(!items.length){host.innerHTML=`<div class="rail-empty">${escapeHtml(lcopy('No banners are active.','Nie sú aktívne žiadne bannery.','Nejsou aktivní žádné bannery.'))}</div>`;return;}
    state.railPromoIndex=Math.max(0,Math.min(state.railPromoIndex,items.length-1));
    host.innerHTML=`<section class="rail-native-carousel" aria-label="BlinQ banners"><div class="rail-native-slides">${items.map((item,index)=>railPromoSlideHtml(item,index)).join('')}</div><div class="rail-native-controls"><button type="button" data-rail-promo-prev aria-label="Previous"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 5-5 5 5 5"></path></svg></button><div class="rail-native-dots">${items.map((_,index)=>`<button type="button" data-rail-promo-dot="${index}" class="${index===state.railPromoIndex?'is-active':''}" aria-label="Banner ${index+1}" aria-current="${index===state.railPromoIndex?'true':'false'}"></button>`).join('')}</div><span data-rail-promo-counter>${state.railPromoIndex+1}/${items.length}</span><button type="button" data-rail-promo-next aria-label="Next"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7.5 5 5 5-5 5"></path></svg></button></div></section>`;
    host.querySelector('[data-rail-promo-prev]')?.addEventListener('click',()=>setRailPromoSlide(state.railPromoIndex-1,true));
    host.querySelector('[data-rail-promo-next]')?.addEventListener('click',()=>setRailPromoSlide(state.railPromoIndex+1,true));
    host.querySelectorAll('[data-rail-promo-dot]').forEach(dot=>dot.addEventListener('click',()=>setRailPromoSlide(Number(dot.dataset.railPromoDot)||0,true)));
    host.onmouseenter=()=>{state.railPromoPaused=true;};host.onmouseleave=()=>{state.railPromoPaused=false;};
    installBannerTracking(host);setRailPromoSlide(state.railPromoIndex,false);startRailPromoRotation();
  }
  function findRowByEventId(id){
    const target=String(id||'');
    for(const tab of ['daily','prime','top','value','ace','games','doubles']){
      const row=(dailyHubRows(tab)||[]).find(item=>eventKey(item)===target);
      if(row)return {row,tab};
    }
    return null;
  }
  function renderSidebarMatchDetail(row=state.railMatch){
    if(!row)return '';
    const match=normalize(row),prob=marketProbability(row),m1=playerInsightStats(row,1),m2=playerInsightStats(row,2);
    const compactMetrics=[
      [lcopy('Rank','Rebríček','Žebříček'),m1.rankDisplay,m2.rankDisplay],
      [lcopy('Form','Forma','Forma'),m1.formDisplay,m2.formDisplay],
      [lcopy('Surface','Povrch','Povrch'),m1.surfaceDisplay,m2.surfaceDisplay],
      ['H2H',m1.h2hDisplay,m2.h2hDisplay]
    ];
    const active=state.railDetailTab||'overview';
    const tabs=[['overview','Prehľad'],['stats','Štatistiky'],['radar','Radar'],['history','História']];
    const overview=`<div class="rail-detail-panel rail-detail-overview-compact" data-rail-panel="overview" ${active==='overview'?'':'hidden'}><div class="rail-player-pair">${insightPlayerCard(row,1)}${insightPlayerCard(row,2)}</div><section class="rail-compare rail-compare-compact">${compactMetrics.map(([label,a,b])=>`<div class="rail-compare-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(a))}</strong><b>${escapeHtml(String(b))}</b></div>`).join('')}</section></div>`;
    const stats=`<div class="rail-detail-panel" data-rail-panel="stats" ${active==='stats'?'':'hidden'}><section class="rail-compare"><div class="rail-section-title"><div><small>${escapeHtml(lcopy('Match context','Kontext zápasu','Kontext zápasu'))}</small><h3>${escapeHtml(lcopy('Key metrics','Kľúčové metriky','Klíčové metriky'))}</h3></div></div>${compactMetrics.map(([label,a,b])=>`<div class="rail-compare-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(a))}</strong><b>${escapeHtml(String(b))}</b></div>`).join('')}</section></div>`;
    const radar=`<div class="rail-detail-panel" data-rail-panel="radar" ${active==='radar'?'':'hidden'}><section class="rail-radar">${renderRadarComparison(row)}</section></div>`;
    const history=`<div class="rail-detail-panel" data-rail-panel="history" ${active==='history'?'':'hidden'}><section class="rail-history">${renderMatchHistoryPanel(row)}</section></div>`;
    return `<article class="rail-match-detail"><header class="rail-match-head"><div><small>${escapeHtml(String(match.tour||'').toUpperCase())} · ${escapeHtml(match.tournament)}</small><h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2></div><div class="rail-match-head-actions"><button type="button" data-rail-open-modal aria-label="${escapeHtml(lcopy('Open full detail','Otvoriť celý detail','Otevřít celý detail'))}" title="${escapeHtml(lcopy('Open full detail','Otvoriť celý detail','Otevřít celý detail'))}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 16 16 8M10 8h6v6"/></svg></button><button type="button" data-rail-close-match aria-label="${escapeHtml(lcopy('Back to highlight','Späť na highlight','Zpět na highlight'))}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></button></div></header><div class="rail-pick"><div><small>BLINQ PREDICTION</small><strong>${escapeHtml(match.pick)}</strong></div><b>${prob==null?'—':pct(prob)}</b></div><nav class="rail-detail-tabs" aria-label="Detail zápasu">${tabs.map(([id,label])=>`<button type="button" data-rail-detail-tab="${id}" class="${active===id?'active':''}">${label}</button>`).join('')}</nav>${overview}${stats}${radar}${history}<button class="rail-open-full-detail" type="button" data-rail-open-modal>${escapeHtml(lcopy('Open full detail','Otvoriť celý detail','Otevřít celý detail'))}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 16 16 8M10 8h6v6"/></svg></button>${row?.__liveIntelligenceLoading?`<div class="match-intelligence-status is-loading">${escapeHtml(lcopy('Loading live player analytics…','Načítavam analytické dáta hráčov…','Načítám analytická data hráčů…'))}</div>`:row?.__liveIntelligenceFailed?`<div class="match-intelligence-status is-error">${escapeHtml(lcopy('Extra live analytics are temporarily unavailable.','Doplnkové analytické dáta sú dočasne nedostupné.','Doplňková analytická data jsou dočasně nedostupná.'))}</div>`:''}<footer class="rail-match-footer"><span>${escapeHtml(String(match.surface||'').replaceAll('_',' '))}</span><span>${fmtDate(match.date)} · ${fmtTime(match.date)}</span></footer></article>`;
  }
  function renderDashboardSidebar(){
    const defaultPanel=$('dashboardSidebarDefault'),matchPanel=$('dashboardSidebarMatch');
    if(state.railMatch){if(defaultPanel)defaultPanel.hidden=true;if(matchPanel){matchPanel.hidden=false;matchPanel.innerHTML=renderSidebarMatchDetail(state.railMatch);}return;}
    if(matchPanel){matchPanel.hidden=true;matchPanel.innerHTML='';}if(defaultPanel)defaultPanel.hidden=false;renderDashboardRightRailDefault();
  }
  function renderMatchRail(){renderDashboardSidebar();}
  function selectMatchInRail(row,tab='daily'){
    if(!row)return;
    clearRailPromoRotation();state.railMatch=row;state.railMatchTab=tab;state.railDetailTab='overview';
    renderMatchRail();
    if(!row.__liveIntelligenceLoaded&&!row.__liveIntelligenceLoading)requestLiveMatchIntelligence(row,tab);
    if(innerWidth<1100)$('dashboardRightRail')?.scrollIntoView({behavior:'smooth',block:'start'});
  }
  function clearMatchRail(){state.railMatch=null;state.railDetailTab='overview';renderDashboardSidebar();}

  function notificationReadIds(){
    return new Set((state.insights||[]).filter(item=>item?.read).map(item=>String(item?.id||'')).filter(Boolean));
  }
  function notificationAudienceConfig(){
    const cfg=state.ui?.notifications||{};
    return {enabled:cfg.enabled!==false,one_way:cfg.one_way!==false,default_levels:Array.isArray(cfg.default_levels)?cfg.default_levels:['elite','legend','goat'],editable_levels:Array.isArray(cfg.editable_levels)?cfg.editable_levels:['rookie','pro','elite','legend','goat']};
  }
  function insightTypeLabel(type){return ({info:'Info',insight:'Premium Info',alert:'LIVE · COMEBACK',live_watch:'LIVE · WATCH',set2:'LIVE · 2. SET',vip:'Premium Info'})[String(type||'').toLowerCase()]||'Insight';}
  function insightAudienceText(levels){
    const list=Array.isArray(levels)?levels:[];
    if(['elite','legend','goat'].every(v=>list.includes(v))&&list.length===3)return 'ELITE+';
    return list.map(v=>String(state.ui?.plans?.[v]?.label||v).replace(/^BlinQ\s+/i,'').toUpperCase()).join(' · ')||'—';
  }
  function isLiveInsight(item){return ['alert','live_watch','set2'].includes(String(item?.type||'').toLowerCase());}
  function renderInsightBell(){
    const bell=$('insightBell'),badge=$('insightUnread'),shortcut=$('insightShortcut'),shortcutLabel=$('insightShortcutLabel'),shortcutCount=$('insightShortcutCount');if(!bell||!badge)return;
    const plan=accountPlan();
    const eligible=notificationAudienceConfig().enabled&&['rookie','pro','elite','legend','goat','admin'].includes(plan);
    const infoEligible=eligible;
    const liveEligible=['elite','legend','goat','admin'].includes(plan);
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
      if(eligible&&!liveEligible){shortcut.dataset.upgradePlan='elite';shortcut.dataset.upgradeSection='Comeback LIVE';shortcut.setAttribute('aria-label','Comeback LIVE · dostupné od ELITE');}
      else{delete shortcut.dataset.upgradePlan;delete shortcut.dataset.upgradeSection;shortcut.setAttribute('aria-label','Comeback LIVE Radar');}
      shortcut.setAttribute('aria-expanded',state.insightDrawerOpen&&state.insightChannel==='live'?'true':'false');
    }
    if(shortcutCount){const n=confirmed?Number(radar.signals)||0:watching?Number(radar.candidates)||0:0;shortcutCount.textContent=String(n);shortcutCount.hidden=!n||!liveEligible;}
    if(shortcutLabel)shortcutLabel.textContent=liveEligible?(confirmed?'CONFIRMED':watching?'WATCH':'RADAR'):'ELITE';
    const infoUnread=state.insights.filter(item=>!item.read&&!isLiveInsight(item)).length;
    badge.textContent=infoUnread>99?'99+':String(infoUnread);badge.hidden=!infoUnread;
    bell.classList.toggle('has-unread',infoUnread>0);bell.setAttribute('aria-expanded',state.insightDrawerOpen&&state.insightChannel==='info'?'true':'false');
  }
  function insightTypeIcon(type){
    return ({info:'i',insight:'✦',alert:'!',live_watch:'◉',set2:'②',vip:'◆'})[String(type||'').toLowerCase()]||'✦';
  }
  function renderInsightDrawer(){
    const drawer=$('insightDrawer'),list=$('insightDrawerList'),status=$('insightDrawerStatus'),toolbar=$('insightDrawerToolbar');if(!drawer||!list||!status)return;
    const channel=state.insightChannel==='live'?'live':'info';
    const filter=state.insightFilter||'all';
    const liveTab=state.liveRadarTab==='set2'?'set2':'comeback';
    const channelRows=state.insights.filter(item=>channel==='live'?isLiveInsight(item):!isLiveInsight(item)).filter(item=>channel!=='live'||(liveTab==='set2'?String(item?.type||'').toLowerCase()==='set2':String(item?.type||'').toLowerCase()!=='set2'));
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
    const liveEligible=['elite','legend','goat','admin'].includes(plan);
    const radar=state.userLiveRadarStatus||{};
    const candidateNames=Array.isArray(radar.candidate_items)?radar.candidate_items.map(x=>x?.favorite).filter(Boolean).slice(0,2):[];
    const radarMode=Number(radar.signals)>0?'is-confirmed':Number(radar.candidates)>0?'is-watching':'';
    const radarStrip=channel==='live'&&liveEligible?`<div class="insight-live-strip ${radar.error?'is-error':radar.ok?'is-ok':''} ${radarMode}"><span class="insight-live-dot"></span><div><strong>Comeback LIVE Radar</strong><small>${escapeHtml(state.userLiveRadarLoading?lcopy('Checking live matches…','Kontrolujem live zápasy…','Kontroluji live zápasy…'):radar.error?lcopy('LIVE status is temporarily unavailable.','LIVE stav je dočasne nedostupný.','LIVE stav je dočasně nedostupný.'):radar.scanned_at?`${Number(radar.live_events)||0} live · ${Number(radar.candidates)||0} WATCH · ${Number(radar.signals)||0} potvrdené${candidateNames.length?' · '+candidateNames.join(', '):''}`:lcopy('Automatic monitoring is active.','Automatické sledovanie je aktívne.','Automatické sledování je aktivní.'))}</small></div></div>`:'';
    const radarCandidateCards=channel==='live'&&liveEligible&&Array.isArray(radar.candidate_items)?radar.candidate_items.slice(0,3).map(item=>{
      const stage=String(item?.stage||'watch'),p=Number(item?.second_set_probability),odds=Number(item?.second_set_odds),edge=Number(item?.second_set_edge),ev=Number(item?.second_set_ev),samples=Number(item?.second_set_samples);
      const quality=String(item?.second_set_quality||'').toUpperCase();
      const status=stage==='second_set_won'||stage==='break_lead'?lcopy('COMEBACK CONFIRMED','COMEBACK POTVRDENÝ','COMEBACK POTVRZENÝ'):lcopy('COMEBACK WATCH','COMEBACK WATCH','COMEBACK WATCH');
      if(state.liveRadarTab==='set2'){
        const set2=[];if(Number.isFinite(p))set2.push(`${lcopy('P(win set 2)','P(výhra 2. setu)','P(výhra 2. setu)')} ${pct(p)}`);if(Number.isFinite(odds))set2.push(`${lcopy('live odds','live kurz','live kurz')} ${odds.toFixed(2)}`);if(Number.isFinite(edge))set2.push(`edge ${(edge*100).toFixed(1)} p.b.`);if(Number.isFinite(ev))set2.push(`EV ${(ev*100).toFixed(1)}%`);
        const depth=[quality,Number.isFinite(samples)&&samples>0?`${Math.trunc(samples)} samples`:null].filter(Boolean).join(' · ');
        return `<article class="live-radar-candidate is-set2"><header><div><small>${escapeHtml(lcopy('SET 2 MODEL · independent support signal','MODEL 2. SETU · samostatný podporný signál','MODEL 2. SETU · samostatný podporný signál'))}</small><strong>${escapeHtml(String(item?.favorite||'—'))} <span>vs</span> ${escapeHtml(String(item?.opponent||'—'))}</strong></div><b>${escapeHtml(String(item?.second_set||'—'))}</b></header><div class="live-radar-status-grid"><span class="set2-model"><small>${escapeHtml(lcopy('Projection','Projekcia','Projekce'))}</small><strong>${escapeHtml(set2.length?set2.join(' · '):lcopy('Projection only — no live market','Len projekcia — bez live marketu','Pouze projekce — bez live marketu'))}</strong></span><span><small>DATA DEPTH</small><strong>${escapeHtml(depth||'—')}</strong></span></div></article>`;
      }
      return `<article class="live-radar-candidate"><header><div><small>${escapeHtml(status)}</small><strong>${escapeHtml(String(item?.favorite||'—'))} <span>vs</span> ${escapeHtml(String(item?.opponent||'—'))}</strong></div><b>${escapeHtml(String(item?.second_set||'—'))}</b></header><div class="live-radar-status-grid"><span><small>${escapeHtml(lcopy('Comeback status','Comeback stav','Comeback stav'))}</small><strong>${escapeHtml(String(item?.first_set||'—'))} → ${escapeHtml(String(item?.second_set||'—'))}</strong></span><span><small>${escapeHtml(lcopy('Signal','Signál','Signál'))}</small><strong>${escapeHtml(stage==='second_set_won'?lcopy('Won set 2','Vyhral 2. set','Vyhrál 2. set'):stage==='break_lead'?lcopy('Break lead in set 2','Break náskok v 2. sete','Break náskok ve 2. setu'):lcopy('Watching after lost set 1','Sledujeme po prehratom 1. sete','Sledujeme po prohraném 1. setu'))}</strong></span></div></article>`;
    }).join(''):'';
    const radarTabs=channel==='live'&&liveEligible?`<div class="live-radar-tabs"><button type="button" data-live-radar-tab="comeback" class="${state.liveRadarTab!=='set2'?'is-active':''}">Comeback</button><button type="button" data-live-radar-tab="set2" class="${state.liveRadarTab==='set2'?'is-active':''}">2. set</button></div>`:'';
    const radarPanel=radarTabs+(state.liveRadarTab==='set2'?radarCandidateCards:radarStrip+radarCandidateCards);
    if(state.insightsLoading){list.innerHTML=radarPanel+'<div class="insight-feed-empty insight-feed-loading"><span></span><strong>Načítavam…</strong></div>';return;}
    if(state.insightsStorageUnavailable){
      const liveCopy=uiCopy('private_feed.history_unavailable',lcopy('Alert history is temporarily unavailable. LIVE radar continues to work.','História upozornení je dočasne nedostupná. LIVE radar ďalej funguje.','Historie upozornění je dočasně nedostupná. LIVE radar dále funguje.'));
      const infoCopy=uiCopy('private_feed.info_unavailable',lcopy('Premium Info needs persistent storage. Messages will return automatically when storage is restored.','Premium Info potrebuje trvalé úložisko. Po obnovení sa správy zobrazia automaticky.','Premium Info potřebuje trvalé úložiště. Po obnovení se zprávy zobrazí automaticky.'));
      if(channel==='live'){list.innerHTML=radarPanel+`<div class="insight-storage-note"><i>i</i><span>${escapeHtml(liveCopy)}</span></div>`;}
      else{list.innerHTML=`<div class="insight-feed-empty insight-feed-offline"><i>!</i><strong>${escapeHtml(lcopy('Premium Info temporarily unavailable','Premium Info je dočasne nedostupné','Premium Info je dočasně nedostupné'))}</strong><p>${escapeHtml(infoCopy)}</p></div>`;}
      return;
    }
    if(!rows.length){const msg=filter==='unread'?lcopy('You have read everything.','Všetko máš prečítané.','Všechno máš přečtené.'):filter==='pinned'?lcopy('No pinned messages yet.','Zatiaľ nemáš pripnuté správy.','Zatím nemáš připnuté zprávy.'):channel==='live'?lcopy('No LIVE signal is active right now.','Momentálne nie je aktívny žiadny LIVE signál.','Momentálně není aktivní žádný LIVE signál.'):lcopy('No messages for your membership yet.','Pre tvoju úroveň zatiaľ nie sú žiadne správy.','Pro tvoji úroveň zatím nejsou žádné zprávy.');list.innerHTML=radarPanel+`<div class="insight-feed-empty"><i>✦</i><strong>${escapeHtml(msg)}</strong><p>${escapeHtml(channel==='live'?lcopy('WATCH candidates and confirmed comeback signals will appear here.','WATCH kandidáti a potvrdené comeback signály sa zobrazia tu.','WATCH kandidáti a potvrzené comeback signály se zobrazí zde.'):lcopy('Important BlinQ updates and private member notes will appear here.','Dôležité BlinQ informácie a súkromné správy pre členov sa zobrazia tu.','Důležité BlinQ informace a soukromé zprávy pro členy se zobrazí zde.'))}</p></div>`;return;}
    list.innerHTML=radarPanel+rows.map(item=>`<article class="insight-feed-item ${item.read?'is-read':'is-unread'} priority-${escapeHtml(item.priority||'normal')}" data-insight-id="${escapeHtml(item.id)}"><div class="insight-feed-icon type-${escapeHtml(item.type||'insight')}">${escapeHtml(insightTypeIcon(item.type))}</div><div class="insight-feed-content"><header><div><span>${escapeHtml(insightTypeLabel(item.type))}</span>${item.pinned?'<b>PRIPNUTÉ</b>':''}${!item.read?'<em>NEW</em>':''}</div><time>${escapeHtml(item.created_at?fmtDate(item.created_at)+' · '+fmtTime(item.created_at):'')}</time></header><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p><footer><small>${escapeHtml(insightAudienceText(item.levels))}</small>${item.match_id?`<button type="button" data-insight-match="${escapeHtml(item.match_id)}">${escapeHtml(item.link_label||lcopy('Open match','Otvoriť zápas','Otevřít zápas'))}<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 5 5 5-5 5"></path></svg></button>`:item.link?`<a href="${escapeHtml(item.link)}" ${isExternalLink(item.link)?'target="_blank" rel="noopener"':''}>${escapeHtml(item.link_label||lcopy('Open','Otvoriť','Otevřít'))}<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 5 5 5-5 5"></path></svg></a>`:''}</footer></div></article>`).join('');
  }
  async function loadInsights(force=false){
    const plan=accountPlan();
    if(!['rookie','pro','elite','legend','goat','admin'].includes(plan)){state.insights=[];state.insightsUnread=0;state.insightsStorageUnavailable=false;renderInsightBell();return;}
    if(state.insightsLoading||(!force&&state.insights.length))return;
    const previousUnread=Math.max(0,Number(state.insightsUnread)||0);state.insightsLoading=true;renderInsightDrawer();
    try{const data=await BlinqAuth.insights();state.insights=Array.isArray(data?.items)?data.items:[];state.insightsUnread=Number(data?.unread)||0;state.insightsStorageUnavailable=Boolean(data?.storage_unavailable);if(force&&state.insightsUnread>previousUnread){const newest=state.insights.find(item=>!item.read);showStatus(newest?`${insightTypeLabel(newest.type)} · ${newest.title}`:'Nová BlinQ správa');}}
    catch{state.insights=[];state.insightsUnread=0;state.insightsStorageUnavailable=true;}
    finally{state.insightsLoading=false;renderInsightBell();renderInsightDrawer();}
  }
  async function refreshPrivateUpdates(force=false){
    if(state.privateUpdatesBusy||document.hidden||$('appShell')?.hidden)return;const plan=accountPlan();if(!['rookie','pro','elite','legend','goat','admin'].includes(plan))return;const now=Date.now();if(!force&&now-Number(state.privateUpdatesLastPoll||0)<25000)return;state.privateUpdatesBusy=true;state.privateUpdatesLastPoll=now;try{await loadInsights(true);if(['elite','legend','goat','admin'].includes(plan))await loadUserLiveRadarStatus(false);}finally{state.privateUpdatesBusy=false;}
  }
  async function loadUserLiveRadarStatus(force=false){
    const plan=accountPlan();if(!['elite','legend','goat','admin'].includes(plan)||state.userLiveRadarLoading)return;
    const scanned=Date.parse(state.userLiveRadarStatus?.scanned_at||'');
    if(!force&&Number.isFinite(scanned)&&Date.now()-scanned<55000)return;
    state.userLiveRadarLoading=true;renderInsightDrawer();
    try{state.userLiveRadarStatus={...(await BlinqAuth.liveRadar()),ok:true};}
    catch(error){state.userLiveRadarStatus={error:error.message||'live_unavailable'};}
    finally{state.userLiveRadarLoading=false;renderInsightBell();renderInsightDrawer();renderFooterConfig();}
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
    const item=state.insights.find(row=>String(row.id)===String(id));if(!item||item.read)return;
    item.read=true;state.insightsUnread=Math.max(0,state.insightsUnread-1);renderInsightBell();renderInsightDrawer();
    try{await BlinqAuth.markInsightRead(id);}catch{item.read=false;state.insightsUnread+=1;renderInsightBell();renderInsightDrawer();}
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
    return raw.includes('double')||raw.includes('fault')?lcopy('Double faults','Dvojchyby','Dvojchyby'):lcopy('Aces','Esá','Esa');
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
    if(raw==='over'||raw==='o')return lcopy('Over','Nad','Nad');
    if(raw==='under'||raw==='u')return lcopy('Under','Pod','Pod');
    return '';
  }
  function aceHasApiLine(row){return Number.isFinite(apiMarketLine(row));}


  function dailyHubConfig(){
    return state.ui?.dashboard?.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};
  }
  function dailyHubEntitlement(tab){
    if(tab==='see_all'){
      const plan=accountPlan();
      const allowed=['elite','legend','goat','admin'].includes(plan);
      const daily=state.feed?.entitlements?.sections?.daily||{};
      const value=state.feed?.entitlements?.sections?.value||{};
      const total=Math.max(0,Number(daily.total)||0)+Math.max(0,Number(value.total)||0);
      return {visible_picks:allowed?'ALL':0,blur_remaining:!allowed,enabled:true,see_all:allowed,total,returned:allowed?total:0,locked_count:allowed?0:total};
    }
    const key=tab==='calendar'?'daily':tab==='daily'?'daily':tab==='ace'?'ace':(tab==='games'||tab==='sets')?'sg':tab;
    return state.feed?.entitlements?.sections?.[key]||{visible_picks:'ALL',blur_remaining:false,enabled:true,total:0,returned:0};
  }
  function dailyPickIdentity(row){
    return `${row?.event_id||row?.id||row?.match_id||''}::${row?.pick||row?.selection||row?.prediction||row?.betting?.selection_id||''}`;
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
    (marketRows('value')||[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'value'}));
    (Array.isArray(state.feed?.daily_picks)?state.feed.daily_picks:[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'daily'}));
    (marketRows('ace')||[]).filter(offerSurfaceEligible).forEach(row=>add({...row,_hub_source:'ace'}));
    (marketRows('sg')||[]).filter(offerSurfaceEligible).forEach(row=>{const market=String(row?.market||'').toLowerCase();if(market==='games'||market==='sets')add({...row,_hub_source:market});});
    return rows.sort((a,b)=>(marketProbability(b)||0)-(marketProbability(a)||0));
  }
  function dailyHubRows(tab){
    if(tab==='daily'){
      // `daily_picks` is already server-authorized: ROOKIE=1, PRO=3, ELITE+=ALL.
      // Do not re-merge the legacy prime/top arrays here or a low tier could receive extra rows.
      return (Array.isArray(state.feed?.daily_picks)?state.feed.daily_picks:[]).filter(offerSurfaceEligible);
    }
    if(tab==='value')return marketRows('value').filter(offerSurfaceEligible);
    if(tab==='ace')return marketRows('ace').filter(offerSurfaceEligible);
    if(tab==='games'||tab==='sets')return marketRows('sg').filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()===tab);
    if(tab==='see_all')return ['elite','legend','goat','admin'].includes(accountPlan())?leanSeeAllRows():[];
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
    return {daily:'TOP',value:'VALUE',ace:'ESA',games:'GAMES',sets:'SETS',see_all:'SEE ALL'}[tab]||String(tab||'').toUpperCase();
  }
  function dailyHubIsComingSoon(tab){return false;}
  function dailyHubColumns(tab){
    if(dailyHubIsComingSoon(tab))return [''];
    if(tab==='value')return ['#','ČAS','TURNAJ','ZÁPAS','PREDIKCIA','KURZ','BLINQ %','EDGE',''];
    if(tab==='ace')return ['#','ČAS','TURNAJ','ZÁPAS','PREDIKCIA','PROJEKCIA','ISTOTA'];
    if(tab==='games'||tab==='sets')return ['#','ČAS','TURNAJ','ZÁPAS','PREDIKCIA','PROJEKCIA','ISTOTA'];
    return ['#','ČAS','TURNAJ','ZÁPAS','PREDIKCIA','KURZ','BLINQ %',''];
  }
  function dailyHubColumnKeys(tab){
    if(tab==='value')return ['rank','time','tournament','match','pick','number','confidence','edge','action'];
    if(tab==='ace'||tab==='games'||tab==='sets')return ['rank','time','tournament','match','pick','number','confidence'];
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
    const label=subLabel||({daily:'TOP',value:'VALUE',ace:'ESA',games:'GAMES',sets:'SETS'}[sourceTab]||String(sourceTab||'').toUpperCase());
    return `<span class="hub-pick-stack"><small>${escapeHtml(label)}</small><strong title="${escapeHtml(text)}">${escapeHtml(text)}</strong></span>`;
  }
  function hubNumberHtml(value,label=''){
    return `<span class="hub-number-stack"><strong>${escapeHtml(value)}</strong>${label?`<small>${escapeHtml(label)}</small>`:''}</span>`;
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
    const logo=explicit||(/^\d{1,12}$/.test(tournamentId)?`/api/v1/tournament-logo/${tournamentId}`:'');
    const fallback=tournamentFallbackHtml(row);
    if(logo) return '<span class="hub-tournament-logo has-image"><img data-tournament-logo src="'+escapeHtml(logo)+'" alt="" loading="lazy" onerror="this.parentElement.classList.add(\'logo-failed\');this.remove()"><span class="hub-logo-fallback">'+fallback+'</span></span>';
    return '<span class="hub-tournament-logo hub-tournament-badge">'+fallback+'</span>';
  }
  function smallAvatar(photo,name,tour,gender=''){
    const safe=safePhotoUrl(photo),fallback=playerFallbackUrl(tour,gender),src=safe||fallback;
    const fail=fallback&&fallback!==src?` onerror="this.onerror=null;this.src='${escapeHtml(fallback)}'"`:'';
    return src?'<span class="hub-avatar has-photo"><img src="'+escapeHtml(src)+'" alt="" loading="lazy"'+fail+'></span>':'<span class="hub-avatar">'+escapeHtml(initials(name))+'</span>';
  }
  function hubPlayerMeta(player,tour){
    const name=player?.name||'—';
    const rank=firstFinite(player?.rank,player?.ranking,player?.current_rank);
    const country=player?.country_code||player?.country_code2||player?.country_code3||player?.country?.alpha2||player?.country?.alpha3||'';
    const photo=player?.photo_url||player?.image_url||player?.photo||(String(player?.id||'').match(/^\d{1,12}$/)?`/api/v1/player-image/${player.id}`:'');
    const rankText=rank!=null&&rank>0?'#'+Math.trunc(rank):'—';
    const tourText=String(tour||'').toUpperCase();
    return '<span class="hub-player">'+smallAvatar(photo,name,tour,player?.gender||player?.sex||'')+'<span class="hub-player-copy"><b>'+escapeHtml(name)+'</b><small class="hub-player-meta">'+flagIconHtml(country,true)+'<span class="hub-rank">'+escapeHtml(rankText)+'</span><span class="hub-tour">'+escapeHtml(tourText)+'</span></small></span></span>';
  }
  function dailyHubTournament(row){
    const tournament=String(row?.tournament||row?.competition||row?.tour||'—').trim();
    const country=row?.tournament_country_code||row?.country_code||row?.venue_country_code||'';
    const tour=String(row?.tour||'').trim().toUpperCase();
    const round=String(row?.round||row?.round_name||'').trim();
    const surface=surfaceShortName(row?.surface||'');
    const meta=[tour,round,surface&&surface!=='Surface'?surface:''].filter(Boolean);
    return `<span class="hub-tournament hub-tournament-pro">${tournamentVisual(row)}<span class="hub-tournament-copy"><b title="${escapeHtml(tournament)}">${escapeHtml(tournament)}</b><small>${flagIconHtml(country,true)}${meta.map(value=>`<span>${escapeHtml(value)}</span>`).join('')}</small></span></span>`;
  }
  function dailyHubMatch(row){
    const p1=row?.player1||{},p2=row?.player2||{};
    const n1=String(p1.name||row?.player1_name||'—'),n2=String(p2.name||row?.player2_name||'—');
    const c1=p1.country_code||p1.country_code2||p1.country_code3||row?.player1_country_code||row?.p1_country_code||'';
    const c2=p2.country_code||p2.country_code2||p2.country_code3||row?.player2_country_code||row?.p2_country_code||'';
    const r1=firstFinite(p1.rank,p1.ranking,p1.current_rank,row?.player1_rank,row?.p1_rank),r2=firstFinite(p2.rank,p2.ranking,p2.current_rank,row?.player2_rank,row?.p2_rank);
    const photoFor=(player,side)=>player?.photo_url||player?.image_url||player?.photo||row?.[`${side}_photo_url`]||row?.[`${side}_image_url`]||(String(player?.id||row?.[`${side}_id`]||'').match(/^\d{1,12}$/)?`/api/v1/player-image/${player?.id||row?.[`${side}_id`]}`:'');
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
      return '<div class="insight-radar-head"><div><small>'+escapeHtml(lcopy('Match comparison','Porovnanie zápasu','Porovnání zápasu'))+'</small><h3>'+escapeHtml(lcopy('Player radar','Radar hráčov','Radar hráčů'))+'</h3></div></div><div class="radar-unavailable">'+escapeHtml(lcopy('Not enough comparable API data for a radar yet.','Zatiaľ nie je dosť porovnateľných API dát pre radar.','Zatím není dost porovnatelných API dat pro radar.'))+'</div>';
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
    return '<div class="insight-radar-head"><div><small>'+escapeHtml(lcopy('Match comparison','Porovnanie zápasu','Porovnání zápasu'))+'</small><h3>'+escapeHtml(lcopy('Player radar','Radar hráčov','Radar hráčů'))+'</h3></div><div class="insight-radar-legend"><span><i class="legend-dot player-1"></i>'+escapeHtml(match.p1)+'</span><span><i class="legend-dot player-2"></i>'+escapeHtml(match.p2)+'</span></div></div><svg class="insight-radar-svg" viewBox="0 0 340 340" role="img" aria-label="Player comparison radar chart">'+grids.join('')+axes+'<polygon points="'+p2Polygon+'" class="insight-radar-area player-2"></polygon><polygon points="'+p1Polygon+'" class="insight-radar-area player-1"></polygon></svg>';
  }
  function insightSummaryCards(row,tab){
    const match=normalize(row),stats1=playerInsightStats(row,1),stats2=playerInsightStats(row,2);const probability=marketProbability(row);const line=apiMarketLine(row),odds=Number(row?.odds??row?.betting?.odds),ev=Number(row?.expected_value??row?.betting?.expected_value);
    const lineValue=tab==='ace'||tab==='games'?(Number.isFinite(line)?line.toFixed(1):'—'):(Number.isFinite(odds)?odds.toFixed(2):'—');
    const marketLabel=tab==='value'?lcopy('Close market','Trh','Trh'):tab==='ace'?lcopy('Aces line','Hranica es','Hranica es'):tab==='games'?lcopy('Games line','Hranica gemov','Hranice gemů'):lcopy('Odds','Kurz','Kurz');
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
    const movement=rankMovement(rank,previousRank);
    const surfaceLabel=surfaceShortName(row?.surface||match.surface);
    const metrics=[
      ['BlinQ %',stats.probabilityDisplay],
      [lcopy('Rank','Rank','Rank'),stats.rankDisplay+(tour?' '+tour:'')+(movement?' · '+movement:'')],
      [lcopy('Form','Forma','Forma'),stats.overallFormDisplay],
      [surfaceLabel,stats.surfaceFormDisplay],
      ['H2H',h2h]
    ];
    if(Number.isFinite(Number(bestRank))&&Number(bestRank)>0) metrics.push([lcopy('Career high','Career high','Career high'),'#'+Math.trunc(Number(bestRank))]);
    if(Number.isFinite(Number(rankingPoints))&&Number(rankingPoints)>0) metrics.push([lcopy('Points','Body','Body'),Math.trunc(Number(rankingPoints)).toLocaleString()]);
    return '<article class="insight-player-card'+(picked?' picked':'')+'">'+(picked?'<span class="insight-picked-badge">BLINQ PICK</span>':'')+'<div class="insight-player-head">'+smallAvatar(photo,name,row?.tour||'')+'<div><h4>'+escapeHtml(name)+'</h4><p class="insight-player-rankline">'+playerMetaHtml(rank,country,tour)+(movement?'<span class="ranking-movement">'+escapeHtml(movement)+'</span>':'')+'</p></div></div><div class="insight-player-metrics">'+metrics.map(([label,value])=>'<span><small>'+escapeHtml(label)+'</small><strong>'+escapeHtml(value)+'</strong></span>').join('')+'</div></article>';
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
    return {useful,p1Name,p2Name,selectedName:selectedName||'—',opponentName,projection,opponentProjection,gap,confidence,p1Samples,p2Samples,p1Surface,p2Surface,market,line,side};
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
    return `<div class="match-detail-shell ace-detail-shell"><header class="match-detail-head"><div><div class="dialog-eyebrow">ESA · ${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}</div><h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2></div></header><div class="ace-detail-pick"><div><small>${escapeHtml(d.market)}</small><strong>${escapeHtml(d.selectedName)}</strong></div><div class="ace-detail-main"><b>${escapeHtml(d.projection.toFixed(2))}</b><small>${escapeHtml(lcopy('projection','projekcia','projekce'))}</small></div></div><div class="ace-detail-grid">${metrics.filter(Boolean).join('')}</div><p class="ace-detail-note">${escapeHtml(lcopy('Only verified Aces / Double Faults projection data are shown here. Missing serve or return statistics are intentionally hidden.','Zobrazujeme iba overené projekčné dáta pre esá a dvojchyby. Chýbajúce štatistiky podania alebo returnu zámerne nezobrazujeme.','Zobrazujeme pouze ověřená projekční data pro esa a dvojchyby. Chybějící statistiky podání nebo returnu záměrně nezobrazujeme.'))}</p><div class="dialog-meta"><span>${escapeHtml(String(match.surface||'').replaceAll('_',' '))}</span><span>${fmtDate(match.date)} · ${fmtTime(match.date)}</span><span>${escapeHtml(String(row?.projection_source||'historical_event_statistics').replaceAll('_',' '))}</span></div></div>`;
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
    const projection=Number(row?.projection),baseline=Number(row?.reference_projection??row?.baseline_projection),gap=Number(row?.projection_gap),confidence=Number(row?.projection_confidence),depth=Number(row?.data_depth);
    return {match,market,projection,baseline,gap,confidence,depth,bestOf:Number(row?.best_of),samples,selection:String(row?.pick||row?.selection||'—'),source:String(row?.projection_source||'historical_structured_scores')};
  }
  function sgProjectionDetailHtml(row,sourceTab=''){
    const d=sgProjectionDetailData(row,sourceTab),isSets=d.market==='sets';
    const projectionText=Number.isFinite(d.projection)?(isSets?pct(d.projection):d.projection.toFixed(1)):'—';
    const baselineText=Number.isFinite(d.baseline)?(isSets?pct(d.baseline):d.baseline.toFixed(1)):'—';
    const gapText=Number.isFinite(d.gap)?(isSets?`${(d.gap*100).toFixed(1)} p.b.`:`${d.gap.toFixed(1)} gemu`):'—';
    const depthText=Number.isFinite(d.depth)?`${Math.round(Math.max(0,Math.min(1,d.depth))*100)}%`:'—';
    const p1=Number(d.samples.player1),p2=Number(d.samples.player2),s1=Number(d.samples.player1_surface),s2=Number(d.samples.player2_surface);
    const sample=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)?`${Math.trunc(a)} / ${Math.trunc(b)}`:'—';
    const why=isSets
      ?lcopy(`The model compares how often both players' historical matches extend beyond the reference set length and shrinks sparse evidence toward neutral.`,`Model porovnáva, ako často sa historické zápasy oboch hráčov predĺžia nad referenčnú dĺžku setov a pri malej vzorke výsledok konzervatívne približuje k neutrálu.`,`Model porovnává, jak často se historické zápasy obou hráčů prodlužují nad referenční délku setů a při malém vzorku výsledek konzervativně přibližuje k neutrálu.`)
      :lcopy(`The projection is built from structured historical total-games scores for both players, adjusted by sample depth and surface evidence.`,`Projekcia vychádza zo štruktúrovaných historických počtov gemov oboch hráčov a zohľadňuje hĺbku vzorky aj dáta na povrchu.`,`Projekce vychází ze strukturovaných historických počtů gemů obou hráčů a zohledňuje hloubku vzorku i data na povrchu.`);
    return `<div class="match-detail-shell sg-detail-shell" data-detail-market="${escapeHtml(d.market)}"><header class="match-detail-head"><div><div class="dialog-eyebrow">${isSets?'SETS':'GAMES'} · ${escapeHtml(d.match.tour)} · ${escapeHtml(d.match.tournament)}</div><h2>${escapeHtml(d.match.p1)} <span>vs</span> ${escapeHtml(d.match.p2)}</h2></div></header><div class="sg-detail-hero"><div><small>${escapeHtml(lcopy('Model projection','Modelová projekcia','Modelová projekce'))}</small><strong>${escapeHtml(d.selection)}</strong></div><div><b>${escapeHtml(projectionText)}</b><small>${escapeHtml(isSets?lcopy('direction probability','pravdepodobnosť smeru','pravděpodobnost směru'):lcopy('projected total games','projekcia gemov','projekce gemů'))}</small></div></div><div class="sg-detail-grid"><article><small>${escapeHtml(lcopy('Reference','Referencia','Reference'))}</small><strong>${escapeHtml(baselineText)}</strong></article><article><small>${escapeHtml(lcopy('Projection gap','Rozdiel projekcie','Rozdíl projekce'))}</small><strong>${escapeHtml(gapText)}</strong></article><article><small>${escapeHtml(lcopy('Model confidence','Istota modelu','Jistota modelu'))}</small><strong>${Number.isFinite(d.confidence)?escapeHtml(pct(d.confidence)):'—'}</strong></article><article class="data-depth"><small>DATA DEPTH</small><strong>${escapeHtml(depthText)}</strong></article><article><small>${escapeHtml(lcopy('History samples P1 / P2','Historická vzorka P1 / P2','Historický vzorek P1 / P2'))}</small><strong>${escapeHtml(sample(p1,p2))}</strong></article><article><small>${escapeHtml(lcopy('Surface samples P1 / P2','Vzorka na povrchu P1 / P2','Vzorek na povrchu P1 / P2'))}</small><strong>${escapeHtml(sample(s1,s2))}</strong></article></div><section class="detail-why-card"><small>${escapeHtml(lcopy('Why BlinQ','Prečo BlinQ','Proč BlinQ'))}</small><p>${escapeHtml(why)}</p></section><p class="ace-detail-note">${escapeHtml(lcopy('This is a model projection, not an odds-backed betting market. Odds, edge and EV are shown only when a real provider market exists.','Ide o modelovú projekciu, nie o predikciu podloženú kurzovým marketom. Kurz, edge a EV zobrazujeme iba vtedy, keď existuje reálny market od providera.','Jde o modelovou projekci, ne o predikci podloženou kurzovým marketem. Kurz, edge a EV zobrazujeme pouze tehdy, když existuje reálný market od providera.'))}</p><div class="dialog-meta"><span>${escapeHtml(String(d.match.surface||'').replaceAll('_',' '))}</span><span>${fmtDate(d.match.date)} · ${fmtTime(d.match.date)}</span>${Number.isFinite(d.bestOf)?`<span>BO${Math.trunc(d.bestOf)}</span>`:''}<span>${escapeHtml(d.source.replaceAll('_',' '))}</span></div></div>`;
  }
  function openSgProjection(row,sourceTab=''){
    const dialog=$('matchDialog'),content=$('dialogContent');if(!dialog||!content)return;
    content.innerHTML=sgProjectionDetailHtml(row,sourceTab);
    dialog.classList.remove('ace-projection-dialog');dialog.classList.add('sg-projection-dialog');
    if(!dialog.open)dialog.showModal();
  }
  function dailyHubRow(row,tab,active=false,index=0){
    const sourceTab=tab==='see_all'?String(row?._hub_source||''):tab;
    const time=fmtTime(row?.scheduled_at||row?.date),tournament=dailyHubTournament(row),key=escapeHtml(eventKey(row));
    const rowClass=active?' class="hub-row-active"':'';
    const leading=`<td class="hub-rank">${index+1}</td><td class="hub-time">${escapeHtml(time)}</td><td class="hub-tournament-cell">${tournament}</td><td class="hub-match-cell">${dailyHubMatch(row)}</td>`;
    if(sourceTab==='games'||sourceTab==='sets'){
      const confidence=Number(row?.projection_confidence),projection=Number(row?.projection),pick=String(row?.pick||row?.selection||'—');
      const unit=String(row?.projection_unit||'');
      const projectionText=Number.isFinite(projection)?(unit==='probability'?pct(projection):projection.toFixed(1)):'—';
      const projectionUnit=unit==='probability'?lcopy('model','model','model'):lcopy('games','gemov','gemů');
      const actionCell=tab==='see_all'?'<td class="hub-action-cell hub-optional-action"><span class="hub-projection-badge">MODEL</span></td>':'';
      return `<tr${rowClass} data-hub-event="${key}" data-hub-market="${escapeHtml(sourceTab)}">${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick,lcopy('Model prediction','Modelová predikcia','Modelová predikce'))}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(projectionText,projectionUnit)}</td><td class="hub-confidence-cell">${hubConfidenceHtml(confidence,row)}</td>${actionCell}</tr>`;
    }
    if(sourceTab==='ace'){
      const confidence=Number(row?.projection_confidence),projection=Number(row?.projection),pick=modelPickName(row),market=aceMarketName(row);
      const action=aceProjectionDetailAvailable(row)?`<button class="hub-detail hub-projection-detail" type="button" data-ace-projection aria-label="${escapeHtml(lcopy('Aces projection','Projekcia ESA','Projekce ESA'))}">${escapeHtml(lcopy('Detail','Detail','Detail'))}<span aria-hidden="true">→</span></button>`:'';
      const actionCell=tab==='see_all'?`<td class="hub-action-cell hub-optional-action">${action}</td>`:'';
      return `<tr${rowClass} data-hub-event="${key}" data-hub-market="ace">${leading}<td class="hub-pick">${hubPredictionHtml('ace',pick,market||'ESA')}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(Number.isFinite(projection)?projection.toFixed(2):'—',lcopy('projection','projekcia','projekce'))}</td><td class="hub-confidence-cell">${hubConfidenceHtml(confidence,row)}</td>${actionCell}</tr>`;
    }
    const probability=marketProbability(row),odds=Number(row?.odds??row?.betting?.odds),pick=modelPickName(row);
    const base=`${leading}<td class="hub-pick">${hubPredictionHtml(sourceTab,pick)}</td><td class="hub-odds hub-number-cell">${hubNumberHtml(Number.isFinite(odds)?odds.toFixed(2):'—',lcopy('odds','kurz','kurz'))}</td><td class="hub-confidence-cell">${hubConfidenceHtml(probability,row)}</td>`;
    if(tab==='value'){
      const ev=Number(row?.expected_value??row?.betting?.expected_value);
      const edge=Number(row?.edge??row?.betting?.edge);
      const value=Number.isFinite(ev)?ev:Number.isFinite(edge)?edge:null;
      const valueText=value==null?'—':`${value>0?'+':''}${(value*(Math.abs(value)<=1?100:1)).toFixed(1)}%`;
      return `<tr${rowClass} data-hub-event="${key}">${base}<td class="hub-edge-cell metric-positive">${hubNumberHtml(valueText,'edge')}</td><td class="hub-action-cell"><button class="hub-detail" type="button" data-hub-detail aria-label="Detail"><span>${escapeHtml(lcopy('Detail','Detail','Detail'))}</span><span aria-hidden="true">→</span></button></td></tr>`;
    }
    return `<tr${rowClass} data-hub-event="${key}">${base}<td class="hub-action-cell"><button class="hub-detail" type="button" data-hub-detail aria-label="Detail"><span>${escapeHtml(lcopy('Detail','Detail','Detail'))}</span><span aria-hidden="true">→</span></button></td></tr>`;
  }

  function dailyHubLockedRow(tab,index){
    const colspan=Math.max(1,dailyHubColumns(tab).length);
    if(tab==='see_all')return `<tr class="hub-row-locked hub-row-seeall"><td colspan="${colspan}"><span>◆</span><b>SEE ALL je dostupné od ELITE</b><small>Kompletný kvalifikovaný výber bez limitu TOP 10.</small></td></tr>`;
    return `<tr class="hub-row-locked"><td colspan="${colspan}"><span>🔒</span><b>Ďalší pick</b><small>Vyššia úroveň odomkne viac riadkov v tejto kategórii.</small></td></tr>`;
  }
  function renderDailyHub(){
    const host=$('dailyHub'); if(!host)return; wireDailyHub();
    const cfg=dailyHubConfig(); host.hidden=cfg.enabled===false; if(host.hidden)return;
    const tabs=['daily','value','ace','games','sets','see_all'];
    if(!tabs.includes(state.dailyHubTab))state.dailyHubTab='daily';
    const plan=accountPlan();
    $('dailyHubTabs').innerHTML=tabs.map(tab=>{
      const ent=dailyHubEntitlement(tab),locked=tab==='see_all'&&!ent.see_all,coming=dailyHubIsComingSoon(tab);
      let count='';
      if(coming)count='<em>COMING SOON</em>';
      else if(tab==='see_all')count=locked?'<em>ELITE+</em>':`<b>${Number(ent.total)||dailyHubRows(tab).length}</b>`;
      else {const total=Number(ent.total);const rows=dailyHubRows(tab);const n=Number.isFinite(total)?total:rows.length;count=n?`<b>${n}</b>`:'';}
      const lockAttrs=locked?` data-upgrade-plan="${escapeHtml(firstUnlockPlan('top_daily',0,true)||'elite')}" data-upgrade-section="SEE ALL"`:'';
      return `<button type="button" role="tab" aria-selected="${tab===state.dailyHubTab?'true':'false'}" class="daily-hub-tab${tab===state.dailyHubTab?' active':''}${locked?' is-locked access-locked':''}${coming?' is-coming':''}" data-daily-hub-tab="${tab}"${lockAttrs}><span>${escapeHtml(dailyHubTabLabel(tab))}</span>${count}</button>`;
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
    const preview=Math.max(1,Number(cfg.preview_rows)||10);
    const allCount=tab==='see_all'?Math.max(Number(ent.total)||0,rows.length):Math.max(Number(ent.total)||0,rows.length);
    const canExpand=ent.see_all===true&&allCount>preview;
    let limit=(state.dailyHubExpanded&&canExpand)?allCount:preview;
    limit=Math.min(limit,Math.max(rows.length,Number(ent.returned)||0));
    const columnKeys=dailyHubColumnKeys(tab);
    head.innerHTML=`<tr>${dailyHubColumns(tab).map((c,i)=>`<th class="hub-head-${escapeHtml(columnKeys[i]||'generic')}">${escapeHtml(c)}</th>`).join('')}</tr>`;
    const out=[];
    if(tab==='see_all'&&!ent.see_all)out.push(dailyHubLockedRow(tab,0));
    else{
      for(let i=0;i<limit;i++){if(i<rows.length)out.push(dailyHubRow(rows[i],tab,false,i));}
      if(!rows.length&&ent.blur_remaining!==false)out.push(dailyHubLockedRow(tab,0));
      else if(rows.length<allCount&&ent.blur_remaining!==false)out.push(dailyHubLockedRow(tab,rows.length));
    }
    body.innerHTML=out.join('');
    if(empty){empty.hidden=Boolean(out.length);empty.textContent=lcopy('No predictions are available in this category yet.','V tejto kategórii zatiaľ nie sú dostupné predikcie.','V této kategorii zatím nejsou dostupné predikce.');}
    const first=rows[0]||sourceRows[0];const raw=first?.scheduled_at||first?.date||first?.start_time||first?.start_at||'';const d=raw?new Date(raw):new Date();const dateText=Number.isNaN(d.getTime())?lcopy('Today','Dnes','Dnes'):new Intl.DateTimeFormat(locale==='en'?'en-GB':locale==='cz'?'cs-CZ':'sk-SK',{weekday:'short',day:'numeric',month:'numeric'}).format(d);
    if($('dailyHubMetaDate'))$('dailyHubMetaDate').textContent=dateText;if($('dailyHubToolbarDate'))$('dailyHubToolbarDate').textContent=dateText;
    if(tournamentSelect){
      const options=[...new Set(sourceRows.map(row=>String(row?.tournament||row?.competition||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));const current=String(state.dailyHubTournament||'');
      tournamentSelect.innerHTML=`<option value="">${escapeHtml(lcopy('All tournaments','Všetky turnaje','Všechny turnaje'))}</option>`+options.map(name=>`<option value="${escapeHtml(name)}"${name===current?' selected':''}>${escapeHtml(name)}</option>`).join('');if(current&&!options.includes(current)){state.dailyHubTournament='';tournamentSelect.value='';}
    }
    if(expand){const hasMore=allCount>preview;expand.hidden=!hasMore;expand.dataset.locked=ent.see_all===true?'0':'1';expand.setAttribute('aria-expanded',state.dailyHubExpanded?'true':'false');expand.title=state.dailyHubExpanded?lcopy('Show first 10','Zobraziť prvých 10','Zobrazit prvních 10'):lcopy('Show all rows','Zobraziť všetky riadky','Zobrazit všechny řádky');}
    const boardNotice=$('dailyHubBoardNotice');if(boardNotice)boardNotice.hidden=true;
  }


  function marketPreviewCard(row,key,index=0,locked=false,compact=false){
    if(locked)return lockedPickCard(key,index);
    const p1=row?.player1||{},p2=row?.player2||{};const probability=marketProbability(row);const pick=row?.pick||row?.selection||row?.prediction||'—';const odds=Number(row?.odds),edge=Number(row?.edge),ev=Number(row?.expected_value);
    const projection=Number(row?.projection),opponentProjection=Number(row?.opponent_projection),projectionGap=Number(row?.projection_gap),projectionConfidence=Number(row?.projection_confidence);const samples=row?.projection_samples||{};const projectionOnly=row?.price_status==='projection_only'&&Number.isFinite(projection);
    let badge='',mainValue='—',confidenceClass='low',pickLabel=publicText(key==='prime'?'Short Odds Prediction':key==='value'?'Value Prediction':key==='ace'?'Ace / DF Prediction':key==='sg'?'Set / Game Prediction':'TOP Prediction'),note='',metrics=[];
    if(projectionOnly){
      const marketLabel=row?.market_type||String(row?.market||'Projection').replaceAll('_',' ');const sampleText=Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${publicText('Data')} ${samples.player1}/${samples.player2}`:'';const unit=String(row?.projection_unit||'count');const reference=Number(row?.reference_projection??row?.baseline_projection);
      if(key==='sg'&&unit==='probability'){mainValue=`${pct(projection)}<small> proj.</small>`;metrics=[[lcopy('Baseline','Základ','Základ'),Number.isFinite(reference)?pct(reference):'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${(projectionGap*100).toFixed(1)} pp`:'—'],[lcopy('Score','Skóre','Skóre'),Number.isFinite(projectionConfidence)?`${Math.round(projectionConfidence*100)}/100`:'—']];pickLabel=lcopy('Sets projection','Projekcia setov','Projekce setů');}
      else if(key==='sg'&&unit==='games'){mainValue=`${projection.toFixed(1)}<small> games</small>`;metrics=[[lcopy('Baseline','Základ','Základ'),Number.isFinite(reference)?reference.toFixed(1):'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${projectionGap.toFixed(1)}`:'—'],[lcopy('Score','Skóre','Skóre'),Number.isFinite(projectionConfidence)?`${Math.round(projectionConfidence*100)}/100`:'—']];pickLabel=lcopy('Games projection','Projekcia hier','Projekce her');}
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
      else if(key==='value'){metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),dataDepthMetric(row)],[lcopy('Market','Trh','Trh'),closeMarketLabel(row)],['EV',Number.isFinite(ev)?`${ev>0?'+':''}${(ev*(Math.abs(ev)<=1?100:1)).toFixed(1)}%`:'—']];}
      else{metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),dataDepthMetric(row)],[publicText('Surface'),surfaceSampleLabel(row)]];}
      badge=probability==null?publicText('MODEL'):confidenceLabel(confidenceBand(probability));mainValue=probability==null?'—':pct(probability);confidenceClass=probability==null?'low':confidenceBand(probability);
    }
    const p1Photo=safePhotoUrl(p1.photo_url),p2Photo=safePhotoUrl(p2.photo_url),fallback=playerFallbackUrl(row?.tour);const avatar=(photo,name)=>{const src=photo||fallback;return src?`<span class="player-avatar has-photo"><img src="${escapeHtml(src)}" alt="" loading="lazy" /></span>`:`<span class="player-avatar">${escapeHtml(initials(name))}</span>`};const p1Name=p1.name||row?.player1_name||'Player 1',p2Name=p2.name||row?.player2_name||'Player 2';
    const metricHtml=metrics.map(([label,value])=>{const raw=String(value??'');const tone=raw.trim().startsWith('+')?' metric-positive':raw.trim().startsWith('-')?' metric-negative':'';return `<span class="card-metric${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(raw)}</strong></span>`}).join('');
    const footer=`<div class="card-metrics-bar match-kpi-bar">${metricHtml}</div><div class="card-link-row"><button class="card-more-link" type="button" data-route="${escapeHtml(key)}">${escapeHtml(publicText('See more →'))}</button></div>`;
    const optionalNote=note&&!compact?`<div class="market-card-note">${escapeHtml(note)}</div>`:'';
    return `<article class="prediction-card featured market-card match-card-v3${projectionOnly?' projection-card':''}${compact?' dashboard-preview-card':''}"><div class="card-meta match-card-meta"><span class="tour match-card-tournament">${tournamentVisual(row)}<span class="match-card-tournament-copy">${escapeHtml(String(row?.tour||'').toUpperCase())} ${escapeHtml(row?.tournament||row?.competition||'')}</span></span><span class="time">${escapeHtml(fmtTime(row?.scheduled_at||row?.date))}</span><span class="surface">${escapeHtml(String(row?.surface||key).replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row match-players-row"><div class="player">${avatar(p1Photo,p1Name)}<strong class="player-name">${escapeHtml(p1Name)}</strong><small class="player-rank">${playerMetaHtml(p1.rank,p1.country_code,row?.tour)}</small></div><div class="vs match-vs">VS</div><div class="player">${avatar(p2Photo,p2Name)}<strong class="player-name">${escapeHtml(p2Name)}</strong><small class="player-rank">${playerMetaHtml(p2.rank,p2.country_code,row?.tour)}</small></div></div><div class="pick-row match-pick-row"><div class="pick-copy"><small>${escapeHtml(pickLabel)}</small><strong class="pick-name">${escapeHtml(pick)}</strong></div><div class="pick-score"><div class="probability">${mainValue}</div><span class="confidence ${confidenceClass}">${escapeHtml(badge)}</span></div></div>${optionalNote}${footer}</article>`;
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
    const avatar=box.querySelector('.player-avatar'),fallbackText=initials(name),fallback=playerFallbackUrl(tour),safe=safePhotoUrl(photo);
    avatar.textContent=fallbackText;avatar.classList.remove('has-photo');
    const install=src=>{if(!src)return;const img=document.createElement('img');img.src=src;img.alt='';img.loading='lazy';img.addEventListener('error',()=>{if(src!==fallback&&fallback){install(fallback);return;}avatar.classList.remove('has-photo');avatar.textContent=fallbackText},{once:true});avatar.textContent='';avatar.classList.add('has-photo');avatar.replaceChildren(img);};
    install(safe||fallback);
    box.querySelector('.player-name').textContent=name;box.querySelector('.player-rank').innerHTML=playerMetaHtml(rank,country,tour);
  }
  function dataDepthLabel(m){const q=m.quality||{},a=q.player1||{},b=q.player2||{};const values=[a.matches,b.matches,a.surface_matches,b.surface_matches].map(Number);if(values.every(Number.isFinite))return `${publicText('History')} ${values[0]} / ${values[1]} · ${publicText('Surface')} ${values[2]} / ${values[3]}`;if(Number.isFinite(m.dataDepth))return `${publicText('Data depth')} ${Math.round(m.dataDepth*100)}%`;return '';}
  function renderCard(m, slotIndex=0){
    const template=$('predictionTemplate').content.cloneNode(true),card=template.querySelector('.prediction-card');
    card.dataset.id=m.id;card.dataset.uiElement=slotIndex<8?`TOP_PICK_${slotIndex+1}`:'TOP_PICK_MORE';card.classList.add('featured','dashboard-preview-card');
    card.querySelector('.tour').textContent=`${m.tour} ${m.tournament}${m.round?` · ${m.round}`:''}`;card.querySelector('.time').textContent=fmtTime(m.date);card.querySelector('.surface').textContent=String(m.surface).replaceAll('_',' ').toUpperCase();
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

  function winnerWhyBlinqHtml(row,tab='daily'){
    const match=normalize(row),depth=hubDataDepthLabel(row),surface=surfaceSampleLabel(row),form=publicFormLabel(row,match.pickId),odds=Number(row?.odds??row?.betting?.odds),edge=Number(row?.edge??row?.betting?.edge),ev=Number(row?.expected_value??row?.betting?.expected_value);
    const chips=[];
    if(depth)chips.push(depth);
    if(surface&&surface!=='—')chips.push(`${lcopy('Surface sample','Povrchová vzorka','Povrchový vzorek')} · ${surface}`);
    if(form&&form!=='—')chips.push(`${lcopy('Recent form','Aktuálna forma','Aktuální forma')} · ${form}`);
    if(Number.isFinite(odds)&&odds>1)chips.push(`${lcopy('Published odds','Publikovaný kurz','Publikovaný kurz')} · ${odds.toFixed(2)}`);
    if(tab==='value'&&Number.isFinite(edge))chips.push(`EDGE · ${(edge*(Math.abs(edge)<=1?100:1)).toFixed(1)}%`);
    if(tab==='value'&&Number.isFinite(ev))chips.push(`EV · ${(ev*(Math.abs(ev)<=1?100:1)).toFixed(1)}%`);
    const note=tab==='value'
      ?lcopy('VALUE combines the match-winner model with the published market price. The market metrics below are supporting context, not a separate prediction.','VALUE kombinuje model víťaza zápasu s publikovaným kurzom. Trhové metriky nižšie sú podporný kontext, nie samostatná predikcia.','VALUE kombinuje model vítěze zápasu s publikovaným kurzem. Tržní metriky níže jsou podpůrný kontext, ne samostatná predikce.')
      :lcopy('The winner detail shows only factors relevant to the match-winner model: ranking, current form, surface evidence, return/serve context, H2H and usable historical depth.','Detail víťaza zobrazuje iba faktory relevantné pre model víťaza zápasu: rebríček, aktuálnu formu, dáta na povrchu, kontext podania/returnu, H2H a použiteľnú hĺbku histórie.','Detail vítěze zobrazuje pouze faktory relevantní pro model vítěze zápasu: žebříček, aktuální formu, data na povrchu, kontext podání/returnu, H2H a použitelnou hloubku historie.');
    return `<section class="detail-why-card winner-why"><small>${escapeHtml(lcopy('Why BlinQ','Prečo BlinQ','Proč BlinQ'))}</small><p>${escapeHtml(note)}</p>${chips.length?`<div class="detail-context-chips">${chips.map(x=>`<span>${escapeHtml(x)}</span>`).join('')}</div>`:''}</section>`;
  }
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
    BlinqAuth.matchIntelligence(p1,p2,row?.surface||'',row?.custom_id||row?.customId||'').then(payload=>{
      mergeLiveMatchIntelligence(row,payload);
      row.__liveIntelligenceLoading=false;
      const dialog=$('matchDialog');
      if(state.railMatch&&eventKey(state.railMatch)===eventKey(row)){state.railMatch=row;renderMatchRail();}
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
    const overview=`<div class="match-detail-overview">${winnerWhyBlinqHtml(row,tab)}<div class="dialog-duel-grid">${insightPlayerCard(row,1)}${insightPlayerCard(row,2)}</div><div class="match-overview-context">${renderMotivationPanel(row)}</div></div>`;
    const statistics=`<div class="match-detail-statistics">${renderMatchStatsPanel(row)}</div>`;
    const radar=`<div class="match-detail-radar"><div class="dialog-section dialog-radar-wrap">${renderRadarComparison(row)}</div><div class="dialog-section match-model-signals"><h3>${escapeHtml(lcopy('Winner model signals','Signály modelu víťaza','Signály modelu vítěze'))}</h3>${signalRows}</div></div>`;
    const history=`<div class="match-detail-history">${renderMatchHistoryPanel(row)}</div>`;
    return `<div class="match-detail-shell"><header class="match-detail-head"><div><div class="dialog-eyebrow">${escapeHtml(match.tour)} · ${escapeHtml(match.tournament)}</div><h2>${escapeHtml(match.p1)} <span>vs</span> ${escapeHtml(match.p2)}</h2></div><button class="match-popout-button" type="button" data-match-popout><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 16 16 8M10 8h6v6"/></svg>${escapeHtml(lcopy('Open in new window','Otvoriť v novom okne','Otevřít v novém okně'))}</button></header><div class="dialog-pick match-detail-pick"><div><small>BlinQ Prediction</small><strong>${escapeHtml(match.pick)}</strong></div><div class="dialog-prob">${marketProbability(row)==null?'—':pct(marketProbability(row))}<small>${escapeHtml(lcopy('win probability','šanca na výhru','šance na výhru'))}</small></div></div><nav class="match-detail-tabs" role="tablist"><button type="button" class="active" data-match-tab="overview">${escapeHtml(lcopy('Overview','Prehľad','Přehled'))}</button><button type="button" data-match-tab="statistics">${escapeHtml(lcopy('Form & surface','Forma & povrch','Forma & povrch'))}</button><button type="button" data-match-tab="radar">${escapeHtml(lcopy('Winner model','Model víťaza','Model vítěze'))}</button><button type="button" data-match-tab="history">${escapeHtml(lcopy('History / H2H','História / H2H','Historie / H2H'))}</button></nav><section class="match-detail-panel active" data-match-panel="overview">${overview}</section><section class="match-detail-panel" data-match-panel="statistics" hidden>${statistics}</section><section class="match-detail-panel" data-match-panel="radar" hidden>${radar}</section><section class="match-detail-panel" data-match-panel="history" hidden>${history}</section>${row?.__liveIntelligenceLoading?`<div id="matchIntelligenceStatus" class="match-intelligence-status is-loading">${escapeHtml(lcopy('Loading live player analytics…','Načítavam analytické dáta hráčov…','Načítám analytická data hráčů…'))}</div>`:row?.__liveIntelligenceFailed?`<div id="matchIntelligenceStatus" class="match-intelligence-status is-error">${escapeHtml(lcopy('Extra live analytics are temporarily unavailable.','Doplnkové analytické dáta sú dočasne nedostupné.','Doplňková analytická data jsou dočasně nedostupná.'))}</div>`:''}<div class="dialog-meta"><span>${escapeHtml(String(match.surface).replaceAll('_',' '))}</span><span>${fmtDate(match.date)} · ${fmtTime(match.date)}</span><span>Model ${escapeHtml(match.model||'—')}</span><span class="dialog-system-ok"><i></i>${escapeHtml(lcopy('All systems operational','Všetky systémy funkčné','Všechny systémy funkční'))}</span></div></div>`;
  }
  function openMatchPopout(){
    const source=$('dialogContent');if(!source)return;
    const w=window.open('','blinq_match_detail','popup=yes,width=980,height=900,resizable=yes,scrollbars=yes');if(!w){showStatus(lcopy('Popup was blocked by the browser.','Prehliadač zablokoval nové okno.','Prohlížeč zablokoval nové okno.'));return;}
    const base=`${location.origin}/`;
    w.document.open();w.document.write(`<!doctype html><html lang="${escapeHtml(locale)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><base href="${escapeHtml(base)}"><title>BlinQ · Detail zápasu</title><link rel="stylesheet" href="/blinq.css?v=7016"><link rel="stylesheet" href="/redesign-680.css?v=7016"><link rel="stylesheet" href="/polish-681.css?v=7016"><link rel="stylesheet" href="/polish-683.css?v=7016"><link rel="stylesheet" href="/polish-684.css?v=7016"><link rel="stylesheet" href="/polish-685.css?v=7016"></head><body id="blinqPremium" class="blinq-detail-popout"><main class="match-popout-shell">${source.innerHTML}</main><script>document.addEventListener('click',function(e){var b=e.target.closest('[data-match-tab]');if(!b)return;var id=b.getAttribute('data-match-tab');document.querySelectorAll('[data-match-tab]').forEach(function(x){x.classList.toggle('active',x===b)});document.querySelectorAll('[data-match-panel]').forEach(function(p){var on=p.getAttribute('data-match-panel')===id;p.hidden=!on;p.classList.toggle('active',on)});});document.querySelectorAll('[data-match-popout]').forEach(function(x){x.remove()});<\/script></body></html>`);w.document.close();w.focus();
  }
  function openMatch(m,tab='daily',rowOverride=null,skipLiveHydration=false){
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
    predictions:['TENNIS INTELLIGENCE','Dashboard','Daily predictions, model signals and current BlinQ intelligence.'],prime:['SHORT ODDS','Short Odds','Short-priced favourite selections with strong model probability and data quality.'],top_daily:['CONFIDENCE FIRST','TOP','Strongest daily predictions ranked by model probability and data quality.'],value:['VALUE EDGE','Value','Predictions with stronger model value; EV is shown only as context.'],doubles:['DOUBLES','Doubles','Separate doubles model and team-pair intelligence.'],ace:['ACES + DOUBLE FAULTS','Aces','Top Aces and Double Faults market selections.'],sg:['SETS + GAMES','Sets / Games','Top Sets and Games market selections.'],results:['SETTLED PREDICTIONS','Results','Settled predictions, hit rate, ROI, units and related performance statistics.'],btts:['FOOTBALL · BETA','BTTS Bonus','Both Teams To Score is prepared as a separate BlinQ beta module.'],account:['BLINQ MEMBERS','Account','Profile, security, membership and access.'],admin:['BLINQ CONTROL','Admin centrum','Správa modelu, publikovania, prístupov, účtov a obsahu BlinQ.'],how_blinq_works:['LEARN','How BlinQ Works','How the BlinQ workflow turns point-in-time tennis data into probabilities.'],methodology:['LEARN','Methodology','The principles used to keep predictions point-in-time and auditable.'],model_data:['LEARN','Model & Data','What the published feed exposes about data and model state.'],faq:['LEARN','FAQ','Common questions about probabilities, results and model output.'],responsible_use:['LEARN','Responsible Use','Use probabilities as information, never as guarantees.'],terms:['LEGAL','Terms of Use','Rules for using the BlinQ service.'],privacy:['LEGAL','Privacy','How BlinQ works with account and service data.'],cookies:['LEGAL','Cookies','Browser storage, essential functionality and analytics preferences.'],support:['SUPPORT','BlinQ Support','Account, membership, data or technical help.']
  };
  const routeMetaSk={
    predictions:['TENISOVÁ ANALYTIKA','Prehľad','Denné predikcie, kľúčové modelové signály a aktuálna BlinQ analytika.'],prime:['SHORT ODDS','Short Odds','Predikcie favoritov s nižším kurzom a silnou modelovou pravdepodobnosťou.'],top_daily:['NAJSILNEJŠIE SIGNÁLY','TOP','Najsilnejšie denné predikcie zoradené podľa pravdepodobnosti modelu a kvality dát.'],value:['MODEL VALUE','Value','Predikcie so zvýšenou modelovou hodnotou a priaznivým pomerom rizika a ceny.'],doubles:['ŠTVORHRA','Štvorhra','Samostatný model štvorhry a inteligencia dvojíc/tímov.'],ace:['ESÁ + DVOJCHYBY','Esá','Najlepšie projekcie pre esá a dvojchyby.'],sg:['SETY + HRY','Sety / hry','Najlepšie projekcie pre sety a počet hier.'],results:['VYHODNOTENÉ PREDIKCIE','Výsledky','Vyhodnotené predikcie, úspešnosť, ROI, jednotky a súvisiace štatistiky výkonu.'],btts:['FUTBAL · BETA','BTTS Bonus','Both Teams To Score je pripravený ako samostatný beta modul BlinQ.'],account:['BLINQ ČLENSTVO','Účet','Profil, zabezpečenie, členstvo a prístup.'],how_blinq_works:['INFO','Ako funguje BlinQ','Ako BlinQ mení point-in-time tenisové dáta na pravdepodobnosti.'],methodology:['INFO','Metodika','Princípy, ktoré udržujú predikcie point-in-time a auditovateľné.'],model_data:['INFO','Model a dáta','Čo publikovaný feed ukazuje o dátach a stave modelu.'],faq:['INFO','FAQ','Najčastejšie otázky o pravdepodobnostiach, výsledkoch a výstupe modelu.'],responsible_use:['INFO','Zodpovedné používanie','Pravdepodobnosti používaj ako informáciu, nikdy nie ako záruku.'],terms:['LEGAL','Podmienky používania','Pravidlá používania služby BlinQ.'],privacy:['LEGAL','Ochrana súkromia','Ako BlinQ pracuje s údajmi používateľov.'],cookies:['LEGAL','Cookies','Nevyhnutné úložisko, preferencie a analytika.'],support:['PODPORA','BlinQ Support','Účet, členstvo, dáta alebo technický problém.']
  };
  const routeMetaCz={
    predictions:['TENISOVÁ ANALYTIKA','Přehled','Denní predikce, klíčové modelové signály a aktuální BlinQ analytika.'],prime:['SHORT ODDS','Short Odds','Predikce favoritů s nižším kurzem a silnou modelovou pravděpodobností.'],top_daily:['NEJSILNĚJŠÍ SIGNÁLY','TOP','Nejsilnější denní predikce seřazené podle pravděpodobnosti modelu a kvality dat.'],value:['MODEL VALUE','Value','Predikce se zvýšenou modelovou hodnotou a příznivým poměrem rizika a ceny.'],doubles:['ČTYŘHRA','Čtyřhra','Samostatný model čtyřhry a inteligence dvojic/týmů.'],ace:['ESA + DVOJCHYBY','Esa','Nejlepší projekce pro esa a dvojchyby.'],sg:['SETY + HRY','Sety / hry','Nejlepší projekce pro sety a počet her.'],results:['VYHODNOCENÉ PREDIKCE','Výsledky','Vyhodnocené predikce, úspěšnost, ROI, jednotky a související statistiky výkonu.'],btts:['FOTBAL · BETA','BTTS Bonus','Both Teams To Score je připraven jako samostatný beta modul BlinQ.'],account:['BLINQ ČLENSTVÍ','Účet','Profil, zabezpečení, členství a přístup.'],how_blinq_works:['INFO','Jak funguje BlinQ','Jak BlinQ mění point-in-time tenisová data na pravděpodobnosti.'],methodology:['INFO','Metodika','Principy, které udržují predikce point-in-time a auditovatelné.'],model_data:['INFO','Model a data','Co publikovaný feed ukazuje o datech a stavu modelu.'],faq:['INFO','FAQ','Nejčastější otázky o pravděpodobnostech, výsledcích a výstupu modelu.'],responsible_use:['INFO','Zodpovědné používání','Pravděpodobnosti používej jako informaci, nikdy ne jako záruku.'],terms:['LEGAL','Podmínky používání','Pravidla používání služby BlinQ.'],privacy:['LEGAL','Ochrana soukromí','Jak BlinQ pracuje s údaji uživatelů.'],cookies:['LEGAL','Cookies','Nezbytné úložiště, preference a analytika.'],support:['PODPORA','BlinQ Support','Účet, členství, data nebo technický problém.']
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
      const boardMode=target.closest('button[data-board-mode]');
      if(boardMode){state.boardMode=boardMode.dataset.boardMode==='results'?'results':'live';state.dailyHubExpanded=false;renderDailyHub();return;}
      if(target.closest('#dailyHubExpand')){ const ent=dailyHubEntitlement(state.dailyHubTab); if(ent.see_all!==true){ const expand=target.closest('#dailyHubExpand');const plan=state.dailyHubTab==='board'?'legend':'elite';const label=state.dailyHubTab==='board'?'BlinQ Board':lcopy('Full daily offer','Celá denná ponuka','Celá denní nabídka');showAccessHint(expand,plan,label,true); return; } state.dailyHubExpanded=!state.dailyHubExpanded; renderDailyHub(); return; }
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
          if(sourceTab==='ace'){
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

  function setRoute(route,push=true){ if(!routeMeta[route]) route='predictions'; if(route==='admin'&&!isAdminAccount()) route='predictions'; document.body.classList.toggle('blinq-home',route==='predictions'); document.body.classList.toggle('blinq-admin',route==='admin'); document.body.classList.toggle('blinq-route',route!=='predictions'&&route!=='admin'); const section=dashboardSectionKeys.includes(route)?dashboardSectionConfig(route):null; if(section&&route!=='predictions'&&elementAccess(section.sidebar_element)!=='active'&&state.route!=='admin'){const source=document.querySelector(`[data-route="${CSS.escape(route)}"]`)||document.body;showAccessHint(source,firstUnlockPlan(route,0,true),section.label||route,true);route='predictions';} if(route==='admin') state.previewPlan=null; const routeChanged=state.route!==route;state.route=route;renderCookieConsent(false);if(routeChanged)state.page=0;const meta=routeMeta[route]; const overview=route==='predictions'; const routeHeading=$('routeHeading'); if(routeHeading) routeHeading.hidden=overview; $('pageEyebrow').textContent=meta[0]; $('pageTitle').textContent=meta[1]; $('pageSubtitle').textContent=meta[2]; const topbar=document.querySelector('.dashboard-topbar'); if(topbar) topbar.classList.toggle('overview-mode',overview); $('predictionsView').hidden=!overview; $('routePanel').hidden=overview; renderNavigation(); if(overview){renderPredictions();renderMarketSections();renderDailyHub();renderDashboardResultsPreview();applyAccessStates();} else renderRoute(route); if(push&&location.hash!==`#${route}`) history.pushState(null,'',`#${route}`); window.BlinqUI.routeChanged(route,push); updateLanguageLinks(); document.title=`${meta[1]} · BlinQ`; if(route!=='admin')translatePublicDom(document.body); }

  function metricCards(items){ return `<div class="metric-cards">${items.map(([label,value,note])=>`<div class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note||'')}</span></div>`).join('')}</div>`; }
  function issuedMarketPublications(row){
    return (Array.isArray(row?.market_publications)?row.market_publications:[]).filter(p=>p&&p.issued_at&&p.result&&!p.excluded_reason);
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
  function isProjectionPublication(publication){return publication?.price_status==='projection_only'||['aces','double_faults'].includes(String(publication?.market||''));}
  function publicationMatchesResultCategory(publication,category='all'){
    if(category==='all')return true;
    if(category==='sg')return ['sets','games'].includes(String(publication?.section||''));
    if(category==='ace')return String(publication?.market||'')==='aces';
    if(category==='double_faults')return String(publication?.market||'')==='double_faults';
    return String(publication?.section||'')===category;
  }
  function esaResultTypeLabel(publication){
    const scope=String(publication?.projection_scope||'player');
    const metric=String(publication?.projection_metric||publication?.market||'');
    const scopeLabel=scope==='total'?lcopy('MATCH TOTAL','SPOLU ZÁPAS','SPOLU ZÁPAS'):lcopy('PLAYER','HRÁČ','HRÁČ');
    const metricLabel=metric==='double_faults'?lcopy('DOUBLE FAULTS','DVOJCHYBY','DVOJCHYBY'):lcopy('ACES','ESÁ','ESA');
    return `${scopeLabel} · ${metricLabel}`;
  }
  function resultCategoryLabel(value){const en=({all:'All published',prime:'Short Odds',top_daily:'TOP Prediction',value:'Value',doubles:'Doubles',ace:'Aces',aces:'Aces',double_faults:'Double Faults',sg:'Sets & Games',sets:'Sets & Games',games:'Sets & Games'})[value]||String(value||'').replaceAll('_',' ');if(locale==='sk')return ({'All published':'Všetky publikované','TOP Prediction':'TOP predikcie','Doubles':'Štvorhra','Aces':'Esá','Double Faults':'Dvojchyby','Sets & Games':'Sety a gamy'})[en]||en;if(locale==='cz')return ({'All published':'Všechny publikované','TOP Prediction':'TOP predikce','Doubles':'Čtyřhra','Aces':'Esa','Double Faults':'Dvojchyby','Sets & Games':'Sety a gamy'})[en]||en;return en;}
  function resultPublication(row,category='all'){
    const pubs=issuedMarketPublications(row);
    const filtered=['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category)?pubs.filter(p=>publicationMatchesResultCategory(p,category)):pubs;
    return filtered.sort((a,b)=>new Date(a.issued_at)-new Date(b.issued_at))[0]||null;
  }
  function publicationOutcome(publication){
    const result=publication?.result||{};
    const raw=String(result?.status||result?.outcome||result?.settlement||result?.result||'').trim().toLowerCase();
    const reason=String(result?.reason||result?.void_reason||result?.settlement_reason||'').trim();
    const isVoid=result?.void===true||result?.is_void===true||['void','push','cancelled','canceled','postponed','walkover','w/o','retired','ret','abandoned','no_action'].includes(raw);
    if(isVoid)return {kind:'void',reason:reason||raw.toUpperCase()||'VOID'};
    if(result?.correct===true)return {kind:'win',reason:''};
    if(result?.correct===false)return {kind:'loss',reason:''};
    return {kind:'pending',reason:''};
  }
  function filteredResults(){
    const filters=state.resultsFilters||{},now=Date.now(),windowDays=Number(filters.window);
    const from=String(filters.dateFrom||'').trim(),to=String(filters.dateTo||'').trim();
    const fromTs=from?new Date(`${from}T00:00:00`).getTime():null;
    const toTs=to?new Date(`${to}T23:59:59.999`).getTime():null;
    return (state.feed.results||[]).filter(row=>{
      if(filters.tour&&String(row?.tour||'').toUpperCase()!==filters.tour)return false;
      if(filters.surface){const raw=String(row?.surface||'').toLowerCase();const mapped=raw==='indoor_hard'?'hard':raw;if(mapped!==filters.surface)return false;}else if(String(row?.surface||'').toLowerCase()==='unknown')return false;
      const ts=new Date(row?.scheduled_at||0).getTime();
      if(filters.window==='custom'){
        if(fromTs!==null&&(!Number.isFinite(ts)||ts<fromTs))return false;
        if(toTs!==null&&(!Number.isFinite(ts)||ts>toTs))return false;
      }else if(Number.isFinite(windowDays)&&windowDays>0){if(!Number.isFinite(ts)||ts<now-windowDays*86400000)return false;}
      const category=filters.category||'all';
      const pubs=issuedMarketPublications(row);
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
  function renderResultsFilters(){
    const rows=state.feed.results||[],filters=state.resultsFilters||{},hours=resultsHistoryHours();
    const tours=[...new Set(rows.map(r=>String(r?.tour||'').toUpperCase()).filter(Boolean))].sort();
    const surfaces=[...new Set(rows.map(r=>{const v=String(r?.surface||'').toLowerCase();return v==='indoor_hard'?'hard':v;}).filter(v=>v&&v!=='unknown'))].sort();
    const option=(value,label,selected)=>`<option value="${escapeHtml(value)}"${value===selected?' selected':''}>${escapeHtml(label)}</option>`;
    if(hours){state.resultsFilters.window=String(hours/24);state.resultsFilters.dateFrom='';state.resultsFilters.dateTo='';}
    const periodOptions=hours?[[String(hours/24),hours===24?lcopy('Last 24 hours','Posledných 24 hodín','Posledních 24 hodin'):lcopy('Last 48 hours','Posledných 48 hodín','Posledních 48 hodin')]]:[['all',publicText('All time')],['1',publicText('24 hours')],['7',publicText('7 days')],['30',publicText('30 days')],['90',publicText('90 days')],['custom',lcopy('Custom range','Vlastné obdobie','Vlastní období')]];
    const accessNote=hours?`<div class="results-access-note"><strong>${hours===24?'ROOKIE FREE':'PRO'}</strong><span>${hours===24?'História posledných 24 hodín.':'História posledných 48 hodín.'}</span><b>ELITE+ odomyká celú históriu</b></div>`:`<div class="results-access-note is-full"><strong>${escapeHtml(String(accountPlan()).toUpperCase())}</strong><span>Celá história výsledkov</span><b>ROI · Yield · mesačné obdobia</b></div>`;
    return `${accessNote}<div class="results-filter-bar results-filter-bar-v683">
      <label class="results-filter-field"><span>${escapeHtml(publicText('Category'))}</span><span class="select-shell"><select id="resultsCategory">${['all','top_daily','value','ace','double_faults','sg','doubles'].map(v=>option(v,resultCategoryLabel(v),filters.category||'all')).join('')}</select><i aria-hidden="true"></i></span></label>
      <label class="results-filter-field"><span>${escapeHtml(publicText('Tour'))}</span><span class="select-shell"><select id="resultsTour">${option('',publicText('All Tours'),filters.tour||'')}${tours.map(v=>option(v,v,filters.tour||'')).join('')}</select><i aria-hidden="true"></i></span></label>
      <label class="results-filter-field"><span>${escapeHtml(publicText('Surface'))}</span><span class="select-shell"><select id="resultsSurface">${option('',publicText('All Surfaces'),filters.surface||'')}${surfaces.map(v=>option(v,v.replaceAll('_',' '),filters.surface||'')).join('')}</select><i aria-hidden="true"></i></span></label>
      <label class="results-filter-field"><span>${escapeHtml(publicText('Period'))}</span><span class="select-shell"><select id="resultsWindow" ${hours?'disabled':''}>${periodOptions.map(([v,l])=>option(v,l,filters.window||periodOptions[0][0])).join('')}</select><i aria-hidden="true"></i></span></label>
      ${hours?'':`<label class="results-filter-field results-date-field"><span>${escapeHtml(lcopy('From','Od','Od'))}</span><span class="date-shell"><input id="resultsDateFrom" type="date" value="${escapeHtml(filters.dateFrom||'')}"><i aria-hidden="true"></i></span></label><label class="results-filter-field results-date-field"><span>${escapeHtml(lcopy('To','Do','Do'))}</span><span class="date-shell"><input id="resultsDateTo" type="date" value="${escapeHtml(filters.dateTo||'')}"><i aria-hidden="true"></i></span></label>`}
    </div>`;
  }
  function settledPublishedEntries(rows,category='all'){
    const specific=['prime','top_daily','value','doubles','ace','double_faults','sets','games'].includes(category);
    const unique=new Map();
    (rows||[]).forEach(row=>{
      const pubs=issuedMarketPublications(row).filter(p=>!specific&&category!=='sg'?true:publicationMatchesResultCategory(p,category)).filter(p=>publicationOutcome(p).kind!=='pending');
      pubs.forEach((publication,index)=>{
        const key=String(publication.selection_key||publication.publication_key||`${row?.id||row?.event_id||row?.scheduled_at||''}::${publication.section||''}::${publication.selection_id||publication.selection||index}`);
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
    const odds=graded.filter(p=>p.odds!=null&&!isProjectionPublication(p)).map(p=>Number(p.odds)).filter(v=>Number.isFinite(v)&&v>1);
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
    const projectionOnly=category==='ace'||category==='double_faults';
    const body=entries.slice(startIndex,endIndex).map(({row:r,publication})=>{
      const p1=r.player1||{},p2=r.player2||{},outcome=publicationOutcome(publication),projection=isProjectionPublication(publication);
      const pickId=publication?.selection_id,pickName=publication?.selection||(pickId===p1.id?p1.name:pickId===p2.id?p2.name:'—');
      const probability=publication?.model_probability==null?NaN:Number(publication?.model_probability);
      const odds=publication?.odds==null?NaN:Number(publication?.odds),rawUnits=publication?.result?.profit_units==null?NaN:Number(publication?.result?.profit_units),units=outcome.kind==='void'?0:rawUnits;
      const tag=projection?(String(publication?.market||'')==='double_faults'?'double_faults':'ace'):String(publication?.section||'');
      const tags=`<span class="result-tag ${escapeHtml(tag)}">${escapeHtml(projection?esaResultTypeLabel(publication):resultCategoryLabel(tag||'all'))}</span>`;
      const resultHtml=projection?(outcome.kind==='win'?'<b class="correct">✓ HIT</b>':outcome.kind==='loss'?'<b class="wrong">× MISS</b>':`<b class="void">○ VOID</b>${outcome.reason?`<small class="void-reason">${escapeHtml(outcome.reason)}</small>`:''}`):(outcome.kind==='win'?'<b class="correct">✓ VÝHRA</b>':outcome.kind==='loss'?'<b class="wrong">× PREHRA</b>':`<b class="void">○ VOID</b>${outcome.reason?`<small class="void-reason">${escapeHtml(outcome.reason)}</small>`:''}`);
      const p1Name=p1.name||'Player 1',p2Name=p2.name||'Player 2';
      const p1Photo=p1.photo_url||p1.image_url||p1.photo||(String(p1.id||'').match(/^\d{1,12}$/)?`/api/v1/player-image/${p1.id}`:'');
      const p2Photo=p2.photo_url||p2.image_url||p2.photo||(String(p2.id||'').match(/^\d{1,12}$/)?`/api/v1/player-image/${p2.id}`:'');
      const match=`<div class="results-match-player">${smallAvatar(p1Photo,p1Name,r?.tour,p1?.gender||p1?.sex||'')}${flagIconHtml(p1.country_code||p1.country_code2||p1.country_code3,true)}<strong>${escapeHtml(p1Name)}</strong></div><small class="results-match-sub"><span class="results-vs">vs</span><span class="results-opponent">${smallAvatar(p2Photo,p2Name,r?.tour,p2?.gender||p2?.sex||'')}${flagIconHtml(p2.country_code||p2.country_code2||p2.country_code3,true)}<b>${escapeHtml(p2Name)}</b></span><span class="results-tournament-inline">${tournamentVisual(r)}<span>${escapeHtml(r.tournament||'')}</span></span></small>`;
      if(projection){
        const projected=Number(publication?.projection),actual=Number(publication?.result?.actual_count),oppActual=Number(publication?.result?.opponent_actual_count),depth=Number(publication?.data_depth??publication?.result?.data_depth),actualText=Number.isFinite(actual)?`${actual.toFixed(actual%1?1:0)}${Number.isFinite(oppActual)?` · súper ${oppActual.toFixed(oppActual%1?1:0)}`:''}`:'—';
        return `<tr><td>${escapeHtml(fmtDate(r.scheduled_at))}<small>${escapeHtml(fmtTime(r.scheduled_at))}</small></td><td>${tags}</td><td>${match}</td><td><strong>${escapeHtml(pickName)}</strong><small>${escapeHtml(esaResultTypeLabel(publication))}</small></td><td>${Number.isFinite(projected)?projected.toFixed(2):'—'}</td><td>${escapeHtml(actualText)}</td><td>${resultHtml}</td><td>${Number.isFinite(depth)?pct(depth):'—'}</td></tr>`;
      }
      return `<tr><td>${escapeHtml(fmtDate(r.scheduled_at))}<small>${escapeHtml(fmtTime(r.scheduled_at))}</small></td><td>${tags}</td><td>${match}</td><td>${escapeHtml(pickName)}</td><td>${Number.isFinite(probability)?pct(probability):'—'}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td><td>${resultHtml}</td><td class="${outcome.kind==='void'?'void':Number.isFinite(units)&&units>=0?'correct':'wrong'}">${outcome.kind==='void'?'0.00u':Number.isFinite(units)?`${units>0?'+':''}${units.toFixed(2)}u`:'—'}</td></tr>`;
    }).join('');
    const pager=`<div class="results-pagination"><div class="results-pagination-meta"><strong>${startIndex+1}–${endIndex}</strong><span>z ${entries.length}</span></div><label><span>Riadkov</span><select id="resultsPageSize">${allowedSizes.map(size=>`<option value="${size}"${size===pageSize?' selected':''}>${size}</option>`).join('')}</select></label><div class="results-pagination-nav"><button type="button" id="resultsPrevPage" ${state.resultsPage<=0?'disabled':''}>←</button><span>Strana <strong>${state.resultsPage+1}</strong> / ${pages}</span><button type="button" id="resultsNextPage" ${state.resultsPage>=pages-1?'disabled':''}>→</button></div></div>`;
    const head=projectionOnly?'<tr><th>Dátum</th><th>Typ</th><th>Zápas</th><th>Projekcia pre</th><th>Projekcia</th><th>Skutočne</th><th>Výsledok</th><th>DATA DEPTH</th></tr>':'<tr><th>Dátum</th><th>Kategória</th><th>Zápas</th><th>Predikcia / projekcia</th><th>BlinQ % / projekcia</th><th>Kurz / skutočne</th><th>Výsledok</th><th>Jednotky / DATA DEPTH</th></tr>';
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

  function planSelectOptions(selected='', includeBlank=true){
    const rows=membershipHierarchy.map(id=>[id,state.ui?.plans?.[id]]).filter(([id,p])=>p&&(p.enabled!==false||id===selected));
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
    if(plan.lifetime)return 'Doživotne';
    const days=Number(plan.duration_days); return Number.isFinite(days)&&days>0?`${days} dní`:'Vlastná platnosť';
  }
  function accessSelect(id, plan){
    const selected=elementAccess(id,plan);
    return `<select data-admin-access="${escapeHtml(plan)}">${accessStates.map(value=>`<option value="${value}"${value===selected?' selected':''}>${value.toUpperCase()}</option>`).join('')}</select>`;
  }
  function adminMiniBlock(id, compact=false, extraClass='', customSmall=''){
    const item=elements()?.[id]; if(!item)return '';
    const mode=elementAccess(id,state.adminPlan),selected=state.selectedElement===id?' selected':'';
    const kindLabel={navigation:'NAV',header_slot:'CTA',hero_banner:'MAIN BANNER',large_banner:'BANNER',feature:'FEATURE',pick:'PICK',sidebar_promo:'PROMO'}[item.kind]||item.zone||'ELEMENT';
    return `<button type="button" title="${escapeHtml(id)}" class="admin-mini-block ${compact?'compact ':''}${extraClass}state-${mode}${selected}" data-admin-element="${escapeHtml(id)}"><small>${escapeHtml(customSmall||kindLabel)}</small><strong>${escapeHtml(item.label||id)}</strong><span>${mode.toUpperCase()}</span></button>`;
  }
  function rowPrefix(zone){ return zone==='content_top'?'CONTENT_TOP_':zone==='content_mid'?'CONTENT_MID_':'CONTENT_BOTTOM_'; }
  function adminRowHtml(zone){
    const count=rowSlotCount(zone);
    return rowItems(zone).map((entry,index)=>adminMiniBlock(entry.item.id,false,'',`${entry.item.id} · block ${index+1}/${count} · ${creativeSpecText(entry.item,count)}`)).join('');
  }
  function rowCreativeSummary(zone){if(!rowEnabled(zone))return 'ROW OFF';const count=rowSlotCount(zone);return `${count} × equal width · ${creativeSpecText({kind:'large_banner'},count)}`;}


  function renderAdminCanvas(){
    const nav=elementList('navigation').map(x=>adminMiniBlock(x.id,true)).join('');
    const headerCount=Math.max(0,Math.min(3,Number(state.ui?.header_cta?.slot_count??3)||0));
    const headerBlocks=[1,2,3].slice(0,headerCount).map(i=>adminMiniBlock(`HEADER_BANNER_${i}`)).join('');
    const hero=heroItems().map(item=>adminMiniBlock(item.id,true)).join('')||'BANNER VYPNUTÝ';
    const ordered=orderedDashboardKeys(state.adminPlan);
    const sections=ordered.map(key=>{const cfg=dashboardSectionConfig(key);const id=Object.keys({PRIME_PICKS_PANEL:'prime',TOP_DAILY_PANEL:'top_daily',VALUE_PICKS_PANEL:'value',DOUBLES_PANEL:'doubles',ACE_PICKS_PANEL:'ace',SG_PICKS_PANEL:'sg'}).find(x=>adminDashboardSectionKeyForElement(x)===key);return id?adminMiniBlock(id,false,'',`ORDER ${sectionPlanOrder(key,state.adminPlan)}`):'';}).join('');
    const extra=adminMiniBlock('RESULTS_PANEL')+adminMiniBlock('BTTS_BONUS_PANEL');
    return `<div class="admin-canvas admin-canvas-v658"><div class="admin-canvas-header"><div class="admin-logo-lock">BLINQ LOGO<br><small>PEVNÉ</small></div><div class="admin-header-slots row-count-${headerCount}">${headerBlocks||'<div class="admin-row-off-label">HORNÉ CTA VYPNUTÉ</div>'}</div><div class="admin-account-lock">PLÁNY · ÚČET<br><small>PEVNÉ</small></div></div><div class="admin-topnav-map"><b>HORNÁ NAVIGÁCIA</b><div>${nav}</div></div><div class="admin-canvas-main admin-canvas-main-full"><div class="admin-hero-lock admin-hero-rotator"><strong>HLAVNÝ ROTUJÚCI BANNER</strong><span>${hero}</span><small>${Math.max(3,Math.min(300,Number(state.ui?.hero_banner?.rotation_seconds)||10))} s rotácia · max. 5 bannerov</small></div><div class="admin-row-caption"><span>SEKCIE DASHBOARDU · ${escapeHtml(accessLabel(state.adminPlan))}</span><b>Poradie nastavíš číslom PORADIE</b></div><div class="admin-dashboard-section-map">${sections}</div><div class="admin-functional-row">${extra}</div></div></div>`;
  }


  function campaignOptions(selected=''){
    const rows=Object.entries(state.ui?.campaigns||{}).sort((a,b)=>String(a[1]?.name||a[0]).localeCompare(String(b[1]?.name||b[0])));
    return `<option value="">Inline / no campaign</option>`+rows.map(([id,c])=>`<option value="${escapeHtml(id)}"${id===selected?' selected':''}>${escapeHtml(c.name||id)}</option>`).join('');
  }
  function layoutCountForElement(id){
    const item=elements()?.[id];if(item?.kind==='header_slot')return Math.max(1,Math.min(4,Number(state.ui?.header_cta?.slot_count)||1));
    if(item?.kind==='hero_banner')return 1;
    for(const zone of contentRowZones){if(elementList('large_banner',zone).some(row=>row.id===id))return Math.max(1,rowSlotCount(zone));}
    return 1;
  }
  function creativeSpecForItem(item,layoutOverride=null){
    const specs=state.ui?.creative_specs||{};
    const count=Math.max(1,Math.min(4,Number(layoutOverride||layoutCountForElement(item?.id))||1));
    if(item?.kind==='header_slot')return specs[`header_${count}`]||specs.header_slot||{};
    if(item?.kind==='hero_banner')return specs.hero_banner||specs.large_1||{};
    if(item?.kind==='sidebar_promo')return specs.sidebar_promo||{};
    if(item?.kind==='large_banner')return specs[`large_${count}`]||specs.large_1||{};
    return {};
  }
  function creativeSpecText(item,layoutOverride=null){
    const spec=creativeSpecForItem(item,layoutOverride);
    const parts=[spec.aspect_ratio?`ratio ${spec.aspect_ratio}`:'',spec.recommended?`recommended ${spec.recommended}`:'',spec.minimum?`min ${spec.minimum}`:'',spec.safe_area?`safe ${spec.safe_area}`:''].filter(Boolean);
    return parts.join(' · ')||'fixed BlinQ creative format';
  }

  function contentEditor(item){
    const c=item.content||{};
    if(item.kind==='navigation') return `<div class="admin-field-grid"><label>Button label<input data-admin-content="label" value="${escapeHtml(c.label||'')}"></label><label>Icon<input data-admin-content="icon" value="${escapeHtml(c.icon||'')}"></label><label>Route<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label></div>`;
    if(!['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind)) return '<p class="admin-muted">Funkčný prvok dashboardu. Verejné umiestnenie a viditeľnosť predikcií nastav v bloku zobrazenia dashboardu nižšie.</p>';
    const sidebarDestination=item.kind==='sidebar_promo'?`<div class="admin-link-callout span-2"><div><strong>Cieľ bočného bannera</strong><span>Celý banner je klikateľný. Použi externú https:// URL alebo internú #route.</span></div><label>URL po kliknutí na banner<input data-admin-content="link" value="${escapeHtml(c.link||'')}" placeholder="https://... or #account"></label></div>`:'';
    const standardDestination=item.kind!=='sidebar_promo'?`<label>Cieľová URL / odkaz<input data-admin-content="link" value="${escapeHtml(c.link||'')}" placeholder="https://... or #account"></label>`:'';
    return `<div class="admin-field-grid">
      ${sidebarDestination}
      <label>Typ obsahu<select data-admin-content="type"><option value="internal"${c.type==='internal'?' selected':''}>Interný</option><option value="advertisement"${c.type==='advertisement'?' selected':''}>Reklama</option><option value="image"${c.type==='image'?' selected':''}>Obrázok</option><option value="promo"${(!c.type||c.type==='promo')?' selected':''}>Promo</option></select></label>
      <label>Téma<select data-admin-content="theme">${['violet','blue','purple','green','gold'].map(v=>`<option value="${v}"${v===(c.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label>
      <div class="field-hint-box span-2">${escapeHtml(item.kind==='large_banner'?`The outer zone width is fixed. Active banners divide it equally. Current creative: ${creativeSpecText(item)}.`:`Fixed creative: ${creativeSpecText(item)}.`)}</div>
      <label class="check-field"><input type="checkbox" data-admin-content="enabled" ${c.enabled!==false?'checked':''}> Obsah zapnutý</label>
      <label>Kampaň<select data-admin-content="campaign_id">${campaignOptions(String(c.campaign_id||''))}</select></label>
      <label>ID inzerenta<input data-admin-content="advertiser_id" value="${escapeHtml(c.advertiser_id||'')}" placeholder="inline / fallback advertiser"></label>
      <label>Avatar plánu<select data-admin-content="plan_id"><option value="">Žiadny</option>${['rookie','pro','elite','legend','goat'].map(v=>`<option value="${v}"${v===String(c.plan_id||'').toLowerCase()?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label>Ikona / emoji<input data-admin-content="icon" value="${escapeHtml(c.icon||'')}" placeholder="✈"></label>
      <label>Horný popis<input data-admin-content="eyebrow" value="${escapeHtml(c.eyebrow||'')}"></label>
      <label>Nadpis<input data-admin-content="headline" value="${escapeHtml(c.headline||'')}"></label>${item.kind==='hero_banner'?`<label>Zvýraznený riadok<input data-admin-content="accent_text" value="${escapeHtml(c.accent_text||'')}" placeholder="Better Decisions."></label>`:''}
      <label class="span-2">Text<textarea data-admin-content="text" rows="3">${escapeHtml(c.text||'')}</textarea></label>
      <label>Text CTA<input data-admin-content="button_text" value="${escapeHtml(c.button_text||'')}"></label>
      ${standardDestination}
      <label>Interná route (voliteľná)<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label>
      ${item.kind==='hero_banner'?`<div class="admin-link-callout span-2 hero-image-callout"><div><strong>Hlavný banner image</strong><span>Tu nahraď hero kreatívu. Pre asset v repozitári použi /assets/filename.webp alebo úplnú https:// URL. Mobilný obrázok je voliteľný.</span></div></div><label class="check-field"><input type="checkbox" data-admin-content="show_copy" ${c.show_copy!==false?'checked':''}> Zobraziť text nad bannerom</label><label>Režim kreatívy<select data-admin-content="creative_mode"><option value="split"${(c.creative_mode||'split')==='split'?' selected':''}>Rozdelené · obrázok + text</option><option value="full"${c.creative_mode==='full'?' selected':''}>Kreatíva ako celý obrázok</option></select></label>`:''}
      <label class="span-2">${item.kind==='hero_banner'?'Cesta / URL hlavného obrázka pre desktop':'Obrázok pre desktop path / URL'}<input data-admin-content="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/... or https://..."></label>
      <label class="span-2">Obrázok pre mobil (voliteľný)<input data-admin-content="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="Optional mobile-specific creative"></label>
      ${item.kind==='hero_banner'&&c.image_url?`<div class="admin-hero-image-preview span-2"><img src="${escapeHtml(safeLink(c.image_url,''))}" alt="Náhľad aktuálneho hlavného bannera"><small>Aktuálny obrázok hlavného bannera</small></div>`:''}
      <label>Prispôsobenie obrázka<select data-admin-content="image_fit"><option value="cover"${(c.image_fit||'cover')==='cover'?' selected':''}>Cover · vyplniť slot</option><option value="contain"${c.image_fit==='contain'?' selected':''}>Contain · zobraziť celý obrázok</option></select></label>
      <label>Pozícia obrázka<select data-admin-content="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(c.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label>Show from · optional<input data-admin-content="active_from" type="datetime-local" value="${escapeHtml(c.active_from||'')}"></label>
      <label>Show until · optional<input data-admin-content="active_until" type="datetime-local" value="${escapeHtml(c.active_until||'')}"></label>
      <label>When ad is unavailable<select data-admin-content="ad_hidden_fallback">${['auto','image','internal'].map(v=>`<option value="${v}"${v===(c.ad_hidden_fallback||'auto')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label class="check-field"><input type="checkbox" data-admin-content="sponsored" ${c.sponsored?'checked':''}> Označenie sponzorované</label>
    </div>`;
  }
  function watermarkEditor(item){
    if(!['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind))return '';
    const wm=item.watermark||{},presets=state.ui?.watermark_presets||{violet:{label:'BlinQ Violet'},blue:{label:'Deep Blue'},cyan:{label:'Cyan'},gold:{label:'Legend Gold'},slate:{label:'Slate'}};
    const preset=String(wm.preset||'violet'),position=String(wm.position||'bottom-right'),opacity=Number(wm.opacity)||.42,size=Number(wm.size)||1;
    return `<div class="admin-section"><div class="admin-section-title"><strong>Watermark overlay</strong><span>Text, color, position and intensity</span></div><div class="admin-field-grid watermark-controls"><label class="check-field"><input type="checkbox" data-admin-watermark="enabled" ${wm.enabled?'checked':''}> Enable watermark</label><label>Watermark text<input data-admin-watermark="text" value="${escapeHtml(wm.text||'COMING SOON')}"></label><label>Color<select data-admin-watermark="preset">${Object.entries(presets).map(([id,row])=>`<option value="${escapeHtml(id)}"${id===preset?' selected':''}>${escapeHtml(row?.label||id)}</option>`).join('')}</select></label><label>Position<select data-admin-watermark="position">${['top-left','top-right','bottom-left','bottom-right','center'].map(v=>`<option value="${v}"${v===position?' selected':''}>${v.replaceAll('-',' ').toUpperCase()}</option>`).join('')}</select></label><label>Opacity<input type="number" min="0.12" max="1" step="0.05" data-admin-watermark="opacity" value="${opacity}"></label><label>Scale<input type="number" min="0.7" max="1.6" step="0.1" data-admin-watermark="size" value="${size}"></label></div><div class="watermark-preview wm-${escapeHtml(preset)}"><span>${escapeHtml(wm.text||'COMING SOON')}</span></div></div>`;
  }

  function adminDashboardSectionKeyForElement(id){
    const map={PRIME_PICKS_PANEL:'prime',TOP_DAILY_PANEL:'top_daily',VALUE_PICKS_PANEL:'value',DOUBLES_PANEL:'doubles',ACE_PICKS_PANEL:'ace',SG_PICKS_PANEL:'sg',RESULTS_PANEL:'results',BTTS_BONUS_PANEL:'btts'};
    return map[id]||dashboardSectionKeyForSidebarElement(id)||'';
  }
  function dashboardDisplayEditor(elementId){
    const key=adminDashboardSectionKeyForElement(elementId);if(!key)return '';
    const choices=state.ui?.admin?.dashboard_preview_choices||[0,1,2,3,4,5,'ALL'],previewChoices=[5,10,15,20,'ALL'];
    const cfg=dashboardSectionConfig(key);
    const preview=previewChoices.map(v=>`<option value="${escapeHtml(v)}"${String(cfg.preview_limit).toUpperCase()===String(v).toUpperCase()?' selected':''}>${escapeHtml(v)}</option>`).join('');
    const rows=accessContexts.map(plan=>{const ent=cfg.plans?.[plan]||cfg.plans?.rookie||{},options=choices.map(v=>`<option value="${escapeHtml(v)}"${String(ent.visible_picks).toUpperCase()===String(v).toUpperCase()?' selected':''}>${escapeHtml(v)}</option>`).join(''),order=Number(ent.order||cfg.dashboard_order||99);return `<div class="admin-plan-rule" data-dashboard-plan-row="${escapeHtml(plan)}"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</b><label>Viditeľné predikcie<select data-dashboard-matrix-field="visible_picks">${options}</select></label><label>Poradie<input type="number" min="1" max="20" data-dashboard-matrix-field="order" value="${order}"></label><label class="check-field"><input type="checkbox" data-dashboard-matrix-field="blur_remaining" ${ent.blur_remaining!==false?'checked':''}> Rozmazať zvyšok</label><label class="check-field"><input type="checkbox" data-dashboard-matrix-field="see_all" ${ent.see_all?'checked':''}> Zobraziť viac</label></div>`;}).join('');
    return `<div class="admin-section dashboard-inspector-section" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-title"><strong>Pravidlá sekcie · ${escapeHtml(adminSectionLabelSk(key,cfg.label||key))}</strong><span>Viditeľnosť, počet predikcií a poradie nastavíš samostatne pre každú úroveň členstva.</span></div><div class="admin-field-grid"><label class="check-field"><input type="checkbox" data-dashboard-field="sidebar_enabled" ${cfg.sidebar_enabled!==false?'checked':''}> Zobraziť v hornej navigácii</label><label class="check-field"><input type="checkbox" data-dashboard-field="dashboard_enabled" ${cfg.dashboard_enabled!==false?'checked':''}> Sekcia zapnutá</label><label>Limit náhľadu<select data-dashboard-field="preview_limit">${preview}</select></label></div><div class="admin-plan-rules">${rows}</div><small class="field-hint">Viditeľné predikcie = 0 + Rozmazať zvyšok znamená, že sekcia ostane viditeľná, ale všetky predikcie budú rozmazané. Poradie môže byť pre každú úroveň odlišné.</small></div>`;
  }
  function bannerAudienceEditor(item){
    if(!['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind))return '';
    item.click_access=item.click_access||{};
    return `<div class="admin-section"><div class="admin-section-title"><strong>Audience / link access</strong><span>Choose who can see this banner and who may open its link.</span></div><div class="admin-audience-grid">${accessContexts.map(plan=>{const visible=elementAccess(item.id,plan)!=='hidden',click=item.click_access?.[plan]!==false;return `<div class="admin-audience-row"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</b><label><input type="checkbox" data-banner-visible-plan="${escapeHtml(plan)}" ${visible?'checked':''}> Viditeľné</label><label><input type="checkbox" data-banner-click-plan="${escapeHtml(plan)}" ${click?'checked':''}> Odkaz aktívny</label></div>`;}).join('')}</div><small class="field-hint">Example: keep a PRO Telegram banner visible to ROOKIE, but disable its link. ROOKIE sees the offer with a lock instead of entering the premium group.</small></div>`;
  }
  function renderAdminInspector(){
    const item=elements()?.[state.selectedElement] || elements()?.HEADER_BANNER_1;
    if(!item)return '<aside class="admin-inspector"><p>No configurable elements.</p></aside>';
    return `<aside class="admin-inspector"><div class="admin-inspector-head"><small>${escapeHtml(state.selectedElement)}</small><h3>${escapeHtml(item.label||state.selectedElement)}</h3><span>${escapeHtml(item.kind||'element')} · ${escapeHtml(item.zone||'')}</span></div>
      <div class="admin-section"><div class="admin-section-title"><strong>Content / details</strong><span>What this fixed position displays</span></div>${contentEditor(item)}</div>
      ${watermarkEditor(item)}
      ${dashboardDisplayEditor(state.selectedElement)}
      ${bannerAudienceEditor(item)}
      ${['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind)?'':`<div class="admin-section"><div class="admin-section-title"><strong>Plan access</strong><span>Layout stays reserved even when hidden</span></div><div class="admin-access-grid">${accessContexts.map(plan=>`<label><span>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</span>${accessSelect(state.selectedElement,plan)}</label>`).join('')}</div></div>`}
    </aside>`;
  }
  function renderDashboardQuickControls(){
    return `<div class="admin-canvas-divider"></div><b>DASHBOARD DISPLAY</b><div class="admin-dashboard-quick">${dashboardPickSectionKeys.map(key=>{const cfg=dashboardSectionConfig(key);return `<label data-dashboard-section="${escapeHtml(key)}"><span>${escapeHtml(cfg.label||key)}</span><input type="checkbox" data-dashboard-field="dashboard_enabled" ${cfg.dashboard_enabled!==false?'checked':''}></label>`}).join('')}</div>`;
  }
  function renderAdminDashboardControls(){ return renderDashboardQuickControls(); }

  function adminLevelChips(selected,attr='admin-plan-chip',includeExpired=true){
    const ids=includeExpired?accessContexts:membershipHierarchy;
    return `<div class="admin-level-chips">${ids.map(id=>`<button type="button" class="admin-level-chip${id===selected?' active':''}${id==='goat'?' top-tier':''}" data-${attr}="${escapeHtml(id)}"><span>${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</span>${id==='goat'?'<small>TOP</small>':''}</button>`).join('')}</div>`;
  }
  function adminVisiblePickOptions(selected){
    const choices=[0,1,2,3,4,5,6,7,8,9,10,'ALL'];
    return choices.map(v=>`<option value="${escapeHtml(v)}"${String(selected).toUpperCase()===String(v).toUpperCase()?' selected':''}>${String(v).toUpperCase()==='ALL'?'ALL':v}</option>`).join('');
  }
  function adminSectionRouteAccess(key,plan){
    const id=dashboardSectionConfig(key).sidebar_element;
    return id?elementAccess(id,plan):'active';
  }
  function adminSectionAccessOptions(selected){
    const normalized=selected==='blurred'?'locked':selected;
    const choices=[['active','OTVORENÉ'],['locked','VIDITEĽNÉ · ZAMKNUTÉ'],['hidden','SKRYTÉ']];
    return choices.map(([value,label])=>`<option value="${value}"${value===normalized?' selected':''}>${label}</option>`).join('');
  }
  function adminSectionPresetButtons(key){
    const plan=state.adminPlan,label=state.ui?.plans?.[plan]?.label||plan.toUpperCase();
    return `<div class="admin-section-presets"><span>Rýchle nastavenie · ${escapeHtml(label)}</span><div><button type="button" data-section-preset="full" data-section-key="${escapeHtml(key)}">Plný prístup</button><button type="button" data-section-preset="teaser" data-section-key="${escapeHtml(key)}">1 viditeľný + rozmazanie</button><button type="button" data-section-preset="blurred" data-section-key="${escapeHtml(key)}">Všetko rozmazané</button><button type="button" data-section-preset="hidden" data-section-key="${escapeHtml(key)}">Skryť pre úroveň</button></div></div>`;
  }
  function adminSectionRuleRow(key,plan,compact=false){
    const cfg=dashboardSectionConfig(key),ent=cfg.plans?.[plan]||cfg.plans?.rookie||{};
    const order=Number(ent.order||cfg.dashboard_order||99),routeAccess=adminSectionRouteAccess(key,plan);
    return `<div class="admin-section-rule-row${compact?' compact':''}" data-dashboard-plan-row="${escapeHtml(plan)}"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</b><label><span>Prístup na stránku</span><select data-dashboard-route-access>${adminSectionAccessOptions(routeAccess)}</select></label><label><span>Viditeľné predikcie</span><select data-dashboard-matrix-field="visible_picks">${adminVisiblePickOptions(ent.visible_picks)}</select></label><label><span>Poradie</span><input type="number" min="1" max="20" data-dashboard-matrix-field="order" value="${order}"></label><label class="admin-toggle-line"><input type="checkbox" data-dashboard-matrix-field="blur_remaining" ${ent.blur_remaining!==false?'checked':''}><span>Rozmazať zvyšok</span></label><label class="admin-toggle-line"><input type="checkbox" data-dashboard-matrix-field="see_all" ${ent.see_all?'checked':''}><span>Zobraziť viac</span></label></div>`;
  }
  function adminSectionLabelSk(key, fallback){
    const labels={prime:'Short Odds',top_daily:'TOP',ace:'Esá',value:'Value',doubles:'Štvorhra',sg:'Sety / hry',results:'Výsledky',btts:'BTTS Bonus'};
    return labels[key]||fallback||key;
  }
  function renderAdminSectionCard(key){
    const cfg=dashboardSectionConfig(key),ent=cfg.plans?.[state.adminPlan]||cfg.plans?.rookie||{};
    const enabled=cfg.dashboard_enabled!==false,nav=cfg.sidebar_enabled!==false;
    const order=Number(ent.order||cfg.dashboard_order||99);
    return `<article class="admin-section-card" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-card-head"><div><small>PORADIE ${order}</small><h3>${escapeHtml(adminSectionLabelSk(key,cfg.label||key))}</h3></div><div class="admin-section-card-switches"><span>GLOBÁLNE</span><label><input type="checkbox" data-dashboard-field="dashboard_enabled" ${enabled?'checked':''}> Web</label><label><input type="checkbox" data-dashboard-field="sidebar_enabled" ${nav?'checked':''}> Navigácia</label></div></div>${adminSectionPresetButtons(key)}${adminSectionRuleRow(key,state.adminPlan,true)}<details class="admin-all-levels"><summary>Všetky úrovne členstva</summary><div class="admin-all-level-rules">${accessContexts.map(plan=>adminSectionRuleRow(key,plan)).join('')}</div></details></article>`;
  }
  function adminPageAccessRow(key,plan){
    const access=adminSectionRouteAccess(key,plan);
    return `<div class="admin-page-access-row" data-dashboard-plan-row="${escapeHtml(plan)}"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}${plan==='goat'?'<small>TOP</small>':''}</b><label><span>Prístup na stránku</span><select data-dashboard-route-access>${adminSectionAccessOptions(access)}</select></label></div>`;
  }
  function renderAdminPageCard(key){
    const cfg=dashboardSectionConfig(key);
    return `<article class="admin-section-card admin-page-card" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-card-head"><div><small>NAVIGAČNÁ STRÁNKA</small><h3>${escapeHtml(adminSectionLabelSk(key,cfg.label||key))}</h3></div><div class="admin-section-card-switches"><label><input type="checkbox" data-dashboard-field="sidebar_enabled" ${cfg.sidebar_enabled!==false?'checked':''}> Horná navigácia</label></div></div>${adminPageAccessRow(key,state.adminPlan)}<details class="admin-all-levels"><summary>Všetky úrovne členstva</summary><div class="admin-all-level-rules">${accessContexts.map(plan=>adminPageAccessRow(key,plan)).join('')}</div></details></article>`;
  }
  function renderAdminLayout(){
    const copyOptions=accessContexts.filter(id=>id!==state.adminPlan).map(id=>`<option value="${id}">${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</option>`).join('');
    const ordered=orderedDashboardKeys(state.adminPlan);
    const levelLabel=accessLabel(state.adminPlan);
    const hub=dailyHubConfig();
    const rows=['daily','top','value','ace','games','doubles'].map(tab=>{
      const tc=hub.tabs?.[tab]||{},rule=tc.plans?.[state.adminPlan]||{},globalOn=tc.enabled!==false,levelOn=rule.tab_enabled!==false;
      const visible=String(rule.visible_rows??0).toUpperCase();
      return `<div class="admin-daily-matrix-row${globalOn?'':' is-global-off'}${levelOn?'':' is-level-off'}" data-admin-hub-tab-card="${tab}">
        <div class="admin-daily-category"><strong>${escapeHtml(dailyHubTabLabel(tab))}</strong><small>${globalOn?'Na webe':'Globálne vypnuté'}</small></div>
        <label class="admin-switch-compact"><input type="checkbox" data-admin-hub-global-field="enabled" data-admin-hub-tab="${tab}" ${globalOn?'checked':''}><span>Na webe</span></label>
        <label class="admin-switch-compact"><input type="checkbox" data-admin-hub-field="tab_enabled" data-admin-hub-tab="${tab}" ${levelOn?'checked':''}><span>Pre ${escapeHtml(levelLabel)}</span></label>
        <label class="admin-daily-row-count"><span>Riadky</span><select data-admin-hub-field="visible_rows" data-admin-hub-tab="${tab}" ${!globalOn||!levelOn?'disabled':''}>${[0,1,2,3,4,5,6,7,8,9,10,'ALL'].map(v=>`<option value="${v}"${visible===String(v).toUpperCase()?' selected':''}>${String(v).toUpperCase()==='ALL'?'VŠETKY':v}</option>`).join('')}</select></label>
        <label class="admin-switch-compact"><input type="checkbox" data-admin-hub-field="blur_remaining" data-admin-hub-tab="${tab}" ${rule.blur_remaining!==false?'checked':''} ${!globalOn||!levelOn?'disabled':''}><span>Zamknúť zvyšok</span></label>
        <label class="admin-switch-compact"><input type="checkbox" data-admin-hub-field="see_all" data-admin-hub-tab="${tab}" ${rule.see_all===true?'checked':''} ${!globalOn||!levelOn?'disabled':''}><span>Celá ponuka</span></label>
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
      <div class="admin-daily-preset-bar"><div><strong>Rýchle nastavenie pre ${escapeHtml(levelLabel)}</strong><span>Voliteľné. Prepíše iba pravidlá dennej ponuky pre tento level, nie globálne zapnutie kategórií.</span></div><div><button type="button" data-admin-daily-preset="full">Plný prístup</button><button type="button" data-admin-daily-preset="preview3">3 riadky</button><button type="button" data-admin-daily-preset="teaser1">1 riadok</button><button type="button" data-admin-daily-preset="hidden">Skryť všetko</button></div></div>
      <div class="admin-daily-matrix-card">
        <header><div><small>DENNÁ PONUKA</small><h3>Čo uvidí ${escapeHtml(levelLabel)}</h3><p>Domovská stránka drží maximálne 10 pozícií. „VŠETKY“ odomkne všetky aktuálne riadky. „Celá ponuka“ dovolí otvoriť rozšírený zoznam.</p></div><button class="btn btn-ghost" type="button" data-admin-action="preview">Náhľad ako ${escapeHtml(levelLabel)}</button></header>
        <div class="admin-daily-matrix-head"><span>Kategória</span><span>Globálne</span><span>Level</span><span>Viditeľné</span><span>Ďalšie riadky</span><span>Rozšírenie</span></div>
        <div class="admin-daily-matrix">${rows}</div>
        <div class="admin-admin-legend"><span><i class="is-global"></i><b>Na webe</b> = kategória existuje pre používateľov</span><span><i class="is-level"></i><b>Pre level</b> = zvolená úroveň ju vidí</span><span><i class="is-lock"></i><b>Zamknúť zvyšok</b> = ďalšie riadky zostanú ako premium teaser</span></div>
      </div>
      <details class="admin-compact-tools"><summary>Kopírovať nastavenie z iného levelu</summary><div class="admin-copy-strip"><label>Zdrojová úroveň<select id="adminCopyFrom">${copyOptions}</select></label><button class="btn btn-ghost" type="button" data-admin-action="copy-plan">Skopírovať všetky pravidlá → ${escapeHtml(levelLabel)}</button><small>Skopíruje prístupy, počty predikcií, poradie, rozmazanie a oprávnenia bannerov.</small></div></details>
      <details class="admin-layout-advanced"><summary><span><strong>Rozšírené sekcie dashboardu</strong><small>TOP / Short Odds / Value / Esá / Sety a hry / Štvorhra – poradie, navigácia a limity</small></span><b>Rozbaliť</b></summary><div class="admin-layout-advanced-body"><div class="admin-section-list">${ordered.map(renderAdminSectionCard).join('')}</div></div></details>
      <details class="admin-layout-advanced"><summary><span><strong>Ďalšie stránky</strong><small>Prístup k Results a ďalším samostatným stránkam</small></span><b>Rozbaliť</b></summary><div class="admin-layout-advanced-body"><div class="admin-section-list admin-page-list">${['results','btts'].map(renderAdminPageCard).join('')}</div></div></details>
    </section>`;
  }

  function simpleBannerAudienceRows(id,item){
    item.click_access=item.click_access||{};
    return accessContexts.map(plan=>{
      const visible=elementAccess(id,plan)!=='hidden',click=item.click_access?.[plan]!==false;
      const label=state.ui?.plans?.[plan]?.label||plan.toUpperCase();
      return `<div class="simple-banner-audience-row"><b>${escapeHtml(label)}</b><label><input type="checkbox" data-simple-banner-visible="${escapeHtml(plan)}" ${visible?'checked':''}> Viditeľné</label><label><input type="checkbox" data-simple-banner-click="${escapeHtml(plan)}" ${click?'checked':''}> Odkaz aktívny</label></div>`;
    }).join('');
  }
  function simpleBannerPreview(id,item,kind){
    const c=item?.content||{},theme=String(c.theme||'blue').replace(/[^a-z0-9_-]/gi,''),image=safeLink(c.image_url,'');
    const style=image&&!image.startsWith('#')?` style="background-image:linear-gradient(90deg,rgba(4,12,22,.78),rgba(4,12,22,.28)),url('${escapeHtml(image)}')"`:'';
    const title=c.headline||item?.label||id,sub=c.text||'',cta=c.button_text||'OPEN';
    return `<div class="simple-banner-preview theme-${escapeHtml(theme)} ${kind==='hero'?'is-hero':''}"${style}><span>${escapeHtml(c.eyebrow||item?.label||'BLINQ')}</span><strong>${escapeHtml(title)}</strong>${sub?`<small>${escapeHtml(sub)}</small>`:''}<b>${escapeHtml(cta)} →</b></div>`;
  }
  function renderSimpleBannerCard(id,index,kind='header'){
    const item=elements()?.[id];if(!item)return '';
    const c=item.content=item.content||{},isHero=kind==='hero';
    const themes=['blue','green','gold','purple','violet'];
    return `<article class="admin-simple-banner-card" data-simple-banner="${escapeHtml(id)}">
      <div class="admin-simple-banner-head"><div><small>${isHero?'MAIN SLIDE':'TOP CTA'} ${index}</small><h3>${escapeHtml(c.headline||item.label||id)}</h3></div><label class="admin-switch"><input type="checkbox" data-simple-banner-field="enabled" ${c.enabled!==false?'checked':''}><span>Zapnuté</span></label></div>
      ${simpleBannerPreview(id,item,kind)}
      <div class="admin-simple-banner-fields">
        <label>Horný popis<input data-simple-banner-field="eyebrow" value="${escapeHtml(c.eyebrow||'')}" placeholder="COMMUNITY"></label>
        <label>Title<input data-simple-banner-field="headline" value="${escapeHtml(c.headline||'')}" placeholder="Join our Telegram community"></label>
        ${isHero?`<label>Zvýraznený riadok<input data-simple-banner-field="accent_text" value="${escapeHtml(c.accent_text||'')}" placeholder="Telegram komunita"></label>`:''}
        <label class="span-2">Podnadpis<input data-simple-banner-field="text" value="${escapeHtml(c.text||'')}" placeholder="Novinky · Predikcie · Diskusia"></label>
        <label>Text tlačidla<input data-simple-banner-field="button_text" value="${escapeHtml(c.button_text||'')}" placeholder="PRIDAŤ SA"></label>
        <label>${isHero?'Destination / Telegram URL':'Telegram / destination URL'}<input data-simple-banner-field="link" value="${escapeHtml(c.link||'')}" placeholder="https://t.me/... or #results"></label>
        ${!isHero?`<label>Ikona / emoji<input data-simple-banner-field="icon" value="${escapeHtml(c.icon||'')}" placeholder="✈"></label>`:''}
        <label>Téma<select data-simple-banner-field="theme">${themes.map(v=>`<option value="${v}"${v===(c.theme||'blue')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
        <label class="span-2">Obrázok pre desktop URL / path<input data-simple-banner-field="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/banner.webp or https://..."></label>
        ${isHero?`<label class="span-2">Obrázok pre mobil URL / path<input data-simple-banner-field="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="Optional mobile-specific image"></label><label class="admin-switch"><input type="checkbox" data-simple-banner-field="show_copy" ${c.show_copy!==false?'checked':''}><span>Zobraziť text nad obrázkom</span></label>`:''}
      </div>
      <details class="simple-banner-access"><summary>Audience & link access</summary><div class="simple-banner-audience-grid">${simpleBannerAudienceRows(id,item)}</div><p>Visible can stay ON while Link active is OFF. Example: ROOKIE sees the premium Telegram banner but cannot open the group.</p></details>
    </article>`;
  }
  function bannerLibraryButton(id,index,kind){
    const item=elements()?.[id];if(!item)return '';
    const c=item.content||{},selected=state.selectedElement===id,active=c.enabled!==false,link=String(c.link||'').trim();
    return `<button type="button" class="admin-banner-library-card${selected?' selected':''}" data-admin-element="${escapeHtml(id)}"><span class="admin-banner-index">${index}</span><span><small>${kind==='hero'?'MAIN SLIDE':kind==='content'?'CONTENT':kind==='vip'?'VIP RAIL':'TOP CTA'}</small><strong>${escapeHtml(c.headline||item.label||id)}</strong><em>${active?'ACTIVE':'OFF'}${link?' · LINKED':''}</em></span><b>›</b></button>`;
  }
  function bannerPreviewForPlan(id,item,kind,plan){
    const visible=elementAccess(id,plan)!=='hidden',click=bannerClickAllowed(item,plan),label=state.ui?.plans?.[plan]?.label||plan.toUpperCase();
    return `<div class="admin-banner-preview-wrap">${simpleBannerPreview(id,item,kind)}<div class="admin-banner-preview-state ${!visible?'hidden-state':!click?'locked-state':'active-state'}"><strong>${escapeHtml(label)}</strong><span>${!visible?'Hidden':!click?'Visible · link locked':'Visible · link active'}</span></div></div>`;
  }
  function renderBannerAccessMatrix(id,item){
    item.click_access=item.click_access||{};
    const allVisible=accessContexts.every(plan=>elementAccess(id,plan)!=='hidden');
    const allClickable=accessContexts.every(plan=>item.click_access?.[plan]!==false);
    const allRow=`<div class="admin-banner-access-row admin-banner-access-all"><b>ALL<small>VŠETCI</small></b><label><input type="checkbox" data-simple-banner-visible="ALL" ${allVisible?'checked':''}><span>Viditeľné</span></label><label><input type="checkbox" data-simple-banner-click="ALL" ${allClickable?'checked':''}><span>Link aktívny</span></label></div>`;
    const rows=accessContexts.map(plan=>{const visible=elementAccess(id,plan)!=='hidden',click=item.click_access?.[plan]!==false;return `<div class="admin-banner-access-row"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}${plan==='goat'?'<small>TOP</small>':''}</b><label><input type="checkbox" data-simple-banner-visible="${escapeHtml(plan)}" ${visible?'checked':''}><span>Viditeľné</span></label><label><input type="checkbox" data-simple-banner-click="${escapeHtml(plan)}" ${click?'checked':''}><span>Link aktívny</span></label></div>`;}).join('');
    return `<div class="admin-banner-access-matrix">${allRow}${rows}</div>`;
  }
  /* Legacy/static QA anchors for VIP admin fields: data-simple-banner-field="benefit_1_title" data-simple-banner-field="benefit_2_title" data-simple-banner-field="benefit_3_title" */
  function renderBannerEditor(id){
    const item=elements()?.[id];if(!item)return '<div class="admin-empty-panel">Choose a banner.</div>';
    const c=item.content=item.content||{},isHero=item.kind==='hero_banner',isContent=item.kind==='large_banner',isVip=id==='VIP_RAIL',kind=isHero?'hero':isContent?'content':'header',themes=['blue','green','gold','purple','violet'];
    if(isVip){
      const linkEditors=[1,2,3,4].map(n=>`<article class="admin-footer-link-item"><div class="admin-footer-link-index">0${n}</div><label>Názov<input data-simple-banner-field="benefit_${n}_title" value="${escapeHtml(c[`benefit_${n}_title`]||'')}" placeholder="Napr. VIP komunita"></label><label>Popis<input data-simple-banner-field="benefit_${n}_text" value="${escapeHtml(c[`benefit_${n}_text`]||'')}" placeholder="Krátky popis odkazu"></label><label class="span-2">Odkaz<input data-simple-banner-field="benefit_${n}_link" value="${escapeHtml(c[`benefit_${n}_link`]||'')}" placeholder="https://t.me/... alebo #results"></label></article>`).join('');
      const preview=[1,2,3,4].map((n,i)=>{const title=c[`benefit_${n}_title`]||`Odkaz ${n}`,text=c[`benefit_${n}_text`]||'Krátky popis',link=String(c[`benefit_${n}_link`]||'').trim();return `<div class="admin-footer-preview-card"><span class="admin-footer-preview-icon">${vipFeatureIcon(i)}</span><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text)}</small></span><b>${link?'↗':'—'}</b></div>`;}).join('');
      return `<article class="admin-banner-editor admin-footer-editor" data-simple-banner="${escapeHtml(id)}"><div class="admin-banner-editor-head"><div><small>SPODNÉ ODKAZY</small><h2>Footer odkazy</h2><p>Názov · popis · URL. Bez zbytočných bannerových nastavení.</p></div><label class="admin-master-switch"><input type="checkbox" data-simple-banner-field="enabled" ${c.enabled!==false?'checked':''}><span>Zapnuté</span></label></div><div class="admin-footer-preview">${preview}</div><div class="admin-form-section admin-footer-links-editor"><div class="admin-form-section-title"><strong>4 odkazy</strong><span>Telegram, VIP skupina, výsledky, štatistiky alebo ľubovoľná externá URL.</span></div><div class="admin-footer-link-grid">${linkEditors}</div></div></article>`;
    }
    return `<article class="admin-banner-editor" data-simple-banner="${escapeHtml(id)}"><div class="admin-banner-editor-head"><div><small>${isVip?'SPODNÝ VIP BANNER':isHero?'HLAVNÝ ROTUJÚCI BANNER':isContent?'OBSAHOVÝ BANNER':'HORNÝ CTA BANNER'}</small><h2>${escapeHtml(c.headline||item.label||id)}</h2><p>${escapeHtml(id)}</p></div><label class="admin-master-switch"><input type="checkbox" data-simple-banner-field="enabled" ${c.enabled!==false?'checked':''}><span>Zapnuté</span></label></div><div class="admin-banner-preview-toolbar"><span>Náhľad ako</span>${adminLevelChips(state.adminBannerPreviewPlan,'admin-banner-preview-plan',true)}</div>${bannerPreviewForPlan(id,item,kind,state.adminBannerPreviewPlan)}<div class="admin-form-section"><div class="admin-form-section-title"><strong>Obsah</strong><span>Všetko, čo návštevník vidí.</span></div><div class="admin-form-grid"><label>Horný popis<input data-simple-banner-field="eyebrow" value="${escapeHtml(c.eyebrow||'')}" placeholder="COMMUNITY"></label><label>Téma<select data-simple-banner-field="theme">${themes.map(v=>`<option value="${v}"${v===(c.theme||'blue')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label class="span-2">Nadpis<input data-simple-banner-field="headline" value="${escapeHtml(c.headline||'')}" placeholder="Join our Telegram community"></label>${isHero?`<label class="span-2">Zvýraznený riadok<input data-simple-banner-field="accent_text" value="${escapeHtml(c.accent_text||'')}" placeholder="Telegram komunita"></label>`:''}<label class="span-2">Podnadpis<input data-simple-banner-field="text" value="${escapeHtml(c.text||'')}" placeholder="Novinky · Predikcie · Diskusia"></label><label>Text tlačidla<input data-simple-banner-field="button_text" value="${escapeHtml(c.button_text||'')}" placeholder="PRIDAŤ SA"></label>${!isHero?`<label>Ikona / emoji<input data-simple-banner-field="icon" value="${escapeHtml(c.icon||'')}" placeholder="✈"></label>`:''}</div></div>${isVip?`<div class="admin-form-section admin-footer-links-editor"><div class="admin-form-section-title"><strong>Spodné odkazy</strong><span>Stačí názov, krátky popis a cieľový odkaz. Vhodné pre Telegram, VIP skupinu, štatistiky alebo internú stránku.</span></div><div class="admin-footer-link-grid">${[1,2,3,4].map(n=>`<article class="admin-footer-link-item"><div class="admin-footer-link-index">0${n}</div><label>Názov<input data-simple-banner-field="benefit_${n}_title" value="${escapeHtml(c[`benefit_${n}_title`]||'')}" placeholder="Napr. VIP komunita"></label><label>Popis<input data-simple-banner-field="benefit_${n}_text" value="${escapeHtml(c[`benefit_${n}_text`]||'')}" placeholder="Krátky popis odkazu"></label><label class="span-2">Odkaz<input data-simple-banner-field="benefit_${n}_link" value="${escapeHtml(c[`benefit_${n}_link`]||'')}" placeholder="https://t.me/... alebo #results"></label></article>`).join('')}</div></div>`:''}<div class="admin-form-section"><div class="admin-form-section-title"><strong>Odkaz</strong><span>Telegram, web alebo interná stránka BlinQ.</span></div><label class="admin-wide-field">Cieľová URL / odkaz<input data-simple-banner-field="link" value="${escapeHtml(c.link||'')}" placeholder="https://t.me/... or #results"></label></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Podklad bannera</strong><span>Nahraj alebo zadaj cestu k obrázku a text BlinQ sa vykreslí nad ním.</span></div><div class="field-hint-box">Odporúčaný formát pre tento slot: ${escapeHtml(creativeSpecText(item))}</div><div class="admin-form-grid"><label class="span-2">Obrázok pre desktop<input data-simple-banner-field="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/banner.webp or https://..."></label><label class="span-2">Obrázok pre mobil (voliteľný)<input data-simple-banner-field="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="/assets/banner-mobile.webp or https://..."></label><label>Prispôsobenie<select data-simple-banner-field="image_fit"><option value="cover"${(c.image_fit||'cover')==='cover'?' selected':''}>Cover</option><option value="contain"${c.image_fit==='contain'?' selected':''}>Contain</option></select></label><label>Pozícia<select data-simple-banner-field="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(c.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label class="admin-toggle-line span-2"><input type="checkbox" data-simple-banner-field="show_copy" ${c.show_copy!==false?'checked':''}><span>Zobraziť vlastný text a CTA nad podkladom</span></label></div></div><div class="admin-form-section audience-section"><div class="admin-form-section-title"><strong>Kto ho môže vidieť a otvoriť?</strong><span>Viditeľnosť a možnosť kliknutia sa nastavujú samostatne.</span></div><div class="admin-banner-presets"><button type="button" class="btn btn-ghost" data-banner-preset="all">Všetci</button><button type="button" class="btn btn-ghost" data-banner-preset="teaser-elite">Viditeľné pre všetkých · odkaz ELITE+</button><button type="button" class="btn btn-ghost" data-banner-preset="pro-only">Iba PRO+</button><button type="button" class="btn btn-ghost" data-banner-preset="goat-only">Iba GOAT</button></div>${renderBannerAccessMatrix(id,item)}</div><details class="admin-advanced"><summary>Pokročilé možnosti</summary><div class="admin-form-grid"><label>Aktívne od<input type="datetime-local" data-simple-banner-field="active_from" value="${escapeHtml(String(c.active_from||'').replace('Z','').slice(0,16))}"></label><label>Aktívne do<input type="datetime-local" data-simple-banner-field="active_until" value="${escapeHtml(String(c.active_until||'').replace('Z','').slice(0,16))}"></label></div>${watermarkEditor(item)}</details></article>`;
  }
  function adminBannerMapSlot(id,label,size='normal'){
    const item=elements()?.[id];if(!item)return '';
    const c=item.content||{},selected=state.selectedElement===id?' selected':'',disabled=c.enabled===false?' is-off':'';
    const image=safePhotoUrl(c.image_url||'');
    const headline=String(c.headline||item.label||id).trim();
    return `<button type="button" class="admin-site-slot ${escapeHtml(size)}${selected}${disabled}" data-admin-element="${escapeHtml(id)}" title="${escapeHtml(id)}">${image?`<img src="${escapeHtml(image)}" alt="" loading="lazy">`:''}<span class="admin-site-slot-shade"></span><small>${escapeHtml(label)}</small><strong>${escapeHtml(headline)}</strong><em>${disabled?'VYPNUTÉ':'UPRAVIŤ'}</em></button>`;
  }
  function renderAdminBannerMap(){
    const row=(zone,label)=>`<section class="admin-site-map-row"><header><strong>${escapeHtml(label)}</strong><span>${rowEnabled(zone)?`${rowSlotCount(zone)} aktívne sloty`:'riadok vypnutý'}</span></header><div class="admin-site-map-slots">${[1,2,3,4].map(i=>adminBannerMapSlot(`${rowPrefix(zone)}${i}`,`Slot ${i}`,'content')).join('')}</div></section>`;
    return `<div class="admin-site-map"><div class="admin-site-map-browser"><div class="admin-site-map-browserbar"><i></i><i></i><i></i><span>BLINQ · HLAVNÁ STRÁNKA</span></div><div class="admin-site-map-header"><div class="admin-site-map-logo">BlinQ</div><div class="admin-site-map-header-slots">${[1,2,3].map(i=>adminBannerMapSlot(`HEADER_BANNER_${i}`,`CTA ${i}`,'header')).join('')}</div><div class="admin-site-map-account">ÚČET</div></div><section class="admin-site-map-hero"><header><strong>Hlavný banner</strong><span>Klikni na konkrétny slide</span></header><div>${[1,2,3,4,5].map(i=>adminBannerMapSlot(`HERO_BANNER_${i}`,`Slide ${i}`,'hero')).join('')}</div></section><div class="admin-site-map-content"><div class="admin-site-map-table"><span></span><span></span><span></span><span></span></div>${row('content_top','Obsah · horný rad')}${row('content_mid','Obsah · stredný rad')}${row('content_bottom','Obsah · spodný rad')}<div class="admin-site-map-table compact"><span></span><span></span><span></span></div></div><section class="admin-site-map-vip"><header><strong>Spodný VIP / membership banner</strong><span>Fixná pozícia</span></header>${adminBannerMapSlot('VIP_RAIL','VIP RAIL','vip')}</section></div><p class="admin-site-map-help">Rozloženie stránky ostáva pevné. Meníš iba obsah vo vybranom slote, takže kreatíva s rovnakým pomerom strán nerozhodí layout.</p></div>`;
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
    const desktop=safePhotoUrl(c.image_url||'')||'/assets/hero-reference-exact-v680.webp';
    const mobile=safePhotoUrl(c.mobile_image_url||'')||desktop;
    const hero1=elements()?.HERO_BANNER_1?.content||{};
    const bg=safePhotoUrl(hero1.site_background_url||'')||String(state.presentationConfig?.theme?.background?.image||'/assets/blinq_background.webp');
    const effects=['fade-up','fade','slide-down'];
    const preview=(mode,img)=>`<div class="lean-admin-preview ${mode}" style="--preview-image:url('${escapeHtml(img)}')"><div><small>${escapeHtml(c.eyebrow||'BLINQ')}</small><strong>${escapeHtml(c.headline||'Tennis intelligence for a smarter tomorrow.')}</strong><p>${escapeHtml(c.text||'')}</p>${c.button_text?`<b>${escapeHtml(c.button_text)} →</b>`:''}</div></div>`;
    const tabs=heroIds.map((id,index)=>{const slot=elements()?.[id]||{},content=slot.content||{},active=index<activeCount,selected=id===selectedId,ready=Boolean(String(content.image_url||'').trim());return `<button type="button" class="admin-hero-tab${selected?' is-selected':''}${active?' is-live':''}${ready?' is-ready':''}" data-admin-element="${id}"><span>0${index+1}</span><strong>Banner ${index+1}</strong><small>${active?'AKTÍVNY':ready?'PRIPRAVENÝ':'NEAKTÍVNY'}</small></button>`;}).join('');
    const countOptions=[1,2,3,4,5].map(n=>`<option value="${n}"${n===activeCount?' selected':''}>${n}</option>`).join('');
    const delayOptions=[3,4,5,6,7,8,9,10].map(n=>`<option value="${n}"${n===rotation?' selected':''}>${n} s</option>`).join('');
    return `<section class="admin-ux-section lean-admin-banners admin-hero-manager" data-simple-banner="${escapeHtml(selectedId)}">
      <div class="admin-ux-heading"><div><small>BANNERY</small><h2>Hero carousel</h2><p>Pripravených je 5 pevných bannerových pozícií. Vyplň ďalší banner a potom zvýš počet aktívnych bannerov.</p></div></div>
      <div class="admin-hero-carousel-controls">
        <label><span>Počet aktívnych bannerov</span><select data-admin-hero-count>${countOptions}</select><small>Aktivujú sa bannery od 1 po zvolený počet.</small></label>
        <label><span>Interval automatickej zmeny</span><select data-admin-hero-seconds>${delayOptions}</select><small>Rozsah 3–10 sekúnd.</small></label>
        <div class="admin-hero-rotation-status"><i></i><div><strong>${activeCount>1?'Automatické prepínanie zapnuté':'Jeden statický banner'}</strong><small>${activeCount>1?`Zmena každých ${rotation} sekúnd · pozastaví sa pri hoveri`:'Pridaj Banner 2 a nastav počet aktívnych na 2.'}</small></div></div>
      </div>
      <div class="admin-hero-tabs" role="tablist" aria-label="Hero bannery">${tabs}</div>
      <div class="admin-hero-selected-head"><div><small>UPRAVUJEŠ</small><strong>${escapeHtml(item.label||selectedId)}</strong></div><span>${Number(selectedId.split('_').pop())<=activeCount?'Zobrazuje sa v rotácii':'Mimo aktuálnej rotácie'}</span></div>
      <div class="lean-admin-specs"><article><strong>DESKTOP HERO</strong><span>1920 × 640 px</span><small>WebP / AVIF odporúčané</small></article><article><strong>MOBILE HERO</strong><span>1080 × 720 px</span><small>Samostatný crop pre telefón</small></article><article><strong>ROTÁCIA</strong><span>${activeCount} / 5</span><small>${rotation} s medzi bannermi</small></article></div>
      <div class="lean-admin-preview-grid"><div><span>Desktop preview</span>${preview('desktop',desktop)}</div><div><span>Mobile preview</span>${preview('mobile',mobile)}</div></div>
      <div class="admin-form-section"><div class="admin-form-section-title"><strong>Text nad bannerom</strong><span>Nie je súčasťou obrázka.</span></div><div class="admin-form-grid">
        <label>Eyebrow<input data-simple-banner-field="eyebrow" value="${escapeHtml(c.eyebrow||'')}"></label>
        <label>Animácia<select data-simple-banner-field="effect">${effects.map(v=>`<option value="${v}"${v===(c.effect||'fade-up')?' selected':''}>${v}</option>`).join('')}</select></label>
        <label class="span-2">Nadpis<input data-simple-banner-field="headline" value="${escapeHtml(c.headline||'')}"></label>
        <label class="span-2">Podnadpis<textarea rows="3" data-simple-banner-field="text">${escapeHtml(c.text||'')}</textarea></label>
        <label>Text tlačidla<input data-simple-banner-field="button_text" value="${escapeHtml(c.button_text||'')}"></label>
        <label>Odkaz<input data-simple-banner-field="link" value="${escapeHtml(c.link||'')}"></label>
      </div></div>
      <div class="admin-form-section"><div class="admin-form-section-title"><strong>Grafické podklady · Banner ${escapeHtml(selectedId.split('_').pop())}</strong><span>Nahraj vlastný desktop a mobilný podklad.</span></div><div class="admin-form-grid">
        <label class="span-2">Desktop hero · 1920×640<input data-simple-banner-field="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/hero.webp"></label>
        <label class="span-2">Mobile hero · 1080×720<input data-simple-banner-field="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="/assets/hero-mobile.webp"></label>
        <label class="admin-toggle-line span-2"><input type="checkbox" data-simple-banner-field="show_copy" ${c.show_copy!==false?'checked':''}><span>Zobraziť editovateľný text nad podkladom</span></label>
      </div></div>
      <div class="admin-form-section admin-page-background-editor" data-simple-banner="HERO_BANNER_1"><div class="admin-form-section-title"><strong>Pozadie celej stránky</strong><span>Spoločné pre všetkých 5 bannerov. Nad obrázkom sa automaticky pridáva jemný BlinQ ambient efekt.</span></div><div class="admin-form-grid">
        <label class="span-2">Background · odporúčané 1920×1080<input data-simple-banner-field="site_background_url" value="${escapeHtml(hero1.site_background_url||bg)}" placeholder="/assets/blinq_background.webp"></label>
      </div></div>
      <div class="admin-banner-save-note"><span></span><strong>Po úprave klikni Publikovať.</strong><small>Prepínanie na webe sa aktivuje automaticky pri 2–5 banneroch.</small></div>
    </section>`;
  }


  function renderAdminPlans(){
    if(!membershipHierarchy.includes(state.adminPlanId))state.adminPlanId='rookie';
    const id=state.adminPlanId,p=state.ui?.plans?.[id]||{};
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>ČLENSTVO</small><h2>Plány</h2><p>Pevná hierarchia: ROOKIE → PRO → ELITE → LEGEND → GOAT. GOAT je vždy najvyššia úroveň.</p></div></div><div class="admin-plan-hierarchy">${membershipHierarchy.map((pid,i)=>`<button type="button" class="admin-plan-level${pid===id?' active':''}${pid==='goat'?' top-tier':''}" data-admin-plan-select="${pid}"><span>${i+1}</span><b>${escapeHtml(state.ui?.plans?.[pid]?.label||pid.toUpperCase())}</b>${pid==='goat'?'<small>TOP</small>':''}</button>`).join('<i>→</i>')}</div><article class="admin-plan-editor" data-plan-card="${escapeHtml(id)}"><div class="admin-plan-editor-preview">${planAvatarHtml(id,p)}<div><small>${escapeHtml(id.toUpperCase())}</small><h3>${escapeHtml(p.label||id.toUpperCase())}</h3><span>${escapeHtml(planTermLabel(id))}</span></div><label class="admin-master-switch"><input type="checkbox" data-plan-field="enabled" ${p.enabled!==false?'checked':''}><span>Viditeľný / zapnutý</span></label></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Karta plánu</strong><span>Verejný názov, popis a akcia.</span></div><div class="admin-form-grid"><label>Názov plánu<input data-plan-field="label" value="${escapeHtml(p.label||id.toUpperCase())}"></label><label>Avatar plánu<select data-plan-field="avatar">${membershipHierarchy.map(v=>`<option value="${v}"${v===(p.avatar||id)?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label class="span-2">Popis<textarea data-plan-field="description" rows="3">${escapeHtml(p.description||p.note||'')}</textarea></label><label>Text CTA<input data-plan-field="cta_label" value="${escapeHtml(p.cta_label||'Open plan')}"></label><label>Externý odkaz plánu<input data-plan-field="url" value="${escapeHtml(p.url||'')}" placeholder="https://..."></label>${id==='goat'?`<label class="span-2">GOAT pozvánka / Telegram URL<input data-plan-field="invite_url" value="${escapeHtml(p.invite_url||'')}" placeholder="https://t.me/..."></label>`:''}</div></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Dĺžka prístupu</strong><span>Predvolená platnosť po pridelení plánu.</span></div><div class="admin-form-grid">${id==='goat'?`<div class="admin-fixed-term span-2"><strong>Neobmedzený / doživotný</strong><span>GOAT je trvalá najvyššia úroveň.</span></div>`:`<label>Trvanie (dni)<input data-plan-field="duration_days" type="number" min="1" value="${p.duration_days??''}"></label><div class="admin-fixed-term"><strong>Časovo obmedzené členstvo</strong><span>Vľavo nastav predvolený počet dní.</span></div>`}</div></div></article></section>`;
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
    document.querySelectorAll('[data-admin-user]').forEach(row=>{row.hidden=!visible.has(String(row.dataset.adminUser));});
    const count=$('adminFilteredCount');if(count)count.textContent=String(visible.size);
  }

  function adminPaymentRows(user){
    const bucket=state.adminPayments?.[String(user?.id||'')];
    if(bucket?.loading)return '<div class="admin-payment-empty">Načítavam históriu platieb…</div>';
    if(bucket?.error)return `<div class="admin-payment-empty is-error">${escapeHtml(bucket.error)}</div>`;
    const items=Array.isArray(bucket?.items)?bucket.items:[];
    if(!items.length)return '<div class="admin-payment-empty">Zatiaľ nie je uložená žiadna manuálna platba.</div>';
    return `<div class="admin-payment-history">${items.map(item=>`<article><div><strong>${escapeHtml(Number(item.amount||0).toFixed(2))} ${escapeHtml(item.currency||'EUR')}</strong><span>${escapeHtml(String(item.plan||'').toUpperCase())} · ${escapeHtml(item.status||'confirmed')}</span></div><div><span>${escapeHtml(fmtDate(item.paid_at))}</span><small>${escapeHtml(item.reference||'bez referencie')}</small></div>${item.note?`<p>${escapeHtml(item.note)}</p>`:''}</article>`).join('')}</div>`;
  }
  function renderAdminPaymentLedger(user){
    const now=new Date(),date=now.toISOString().slice(0,10),plan=String(user?.plan||'pro');
    return `<div class="admin-form-section admin-payment-ledger"><div class="admin-form-section-title"><strong>Manuálne spárovanie platby</strong><span>Platby sa nespárujú automaticky. Každý potvrdený záznam ostane v histórii účtu.</span></div><div id="adminPaymentForm" class="admin-payment-form"><div class="admin-form-grid"><label>Suma<input id="adminPaymentAmount" type="number" min="0" step="0.01" placeholder="29.00" required></label><label>Mena<select id="adminPaymentCurrency"><option>EUR</option><option>CZK</option><option>USD</option></select></label><label>Dátum platby<input id="adminPaymentDate" type="date" value="${escapeHtml(date)}" required></label><label>Úroveň<select id="adminPaymentPlan">${['rookie','pro','elite','legend','goat','other'].map(id=>`<option value="${id}"${id===plan?' selected':''}>${id.toUpperCase()}</option>`).join('')}</select></label><label class="span-2">Referencia<input id="adminPaymentLedgerReference" maxlength="120" value="${escapeHtml(user?.payment_reference||'')}" placeholder="ID transakcie, VS, objednávka"></label><label class="span-2">Poznámka<textarea id="adminPaymentNote" maxlength="500" rows="2" placeholder="Napr. bankový prevod potvrdený manuálne"></textarea></label></div><div class="admin-payment-actions"><button class="btn btn-primary" type="button" data-admin-action="add-payment">Pridať platbu do histórie</button><span id="adminPaymentMessage"></span></div></div><div class="admin-form-section-title compact"><strong>História platieb</strong><button class="btn btn-ghost" type="button" data-admin-action="refresh-payments">Obnoviť</button></div>${adminPaymentRows(user)}</div>`;
  }
  function renderAdminUserHistory(user){
    if(!user)return '';
    const entry=state.adminUserAudit?.[String(user.id)]||{},items=Array.isArray(entry.items)?entry.items:[];
    const rows=items.slice(0,12).map(item=>`<div class="admin-account-history-row"><span>${escapeHtml(fmtDate(item.occurred_at))}<small>${escapeHtml(fmtTime(item.occurred_at))}</small></span><strong>${escapeHtml(auditDiffLabel(item))}</strong><em>${escapeHtml(item.actor_id||'admin')}</em></div>`).join('');
    return `<div class="admin-form-section admin-account-history"><div class="admin-form-section-title compact"><strong>História BlinQ účtu</strong><button class="btn btn-ghost" type="button" data-admin-action="refresh-user-audit">Obnoviť</button></div>${entry.loading?'<div class="admin-payment-empty">Načítavam históriu účtu…</div>':entry.error?`<div class="admin-payment-empty">${escapeHtml(entry.error)}</div>`:rows||'<div class="admin-payment-empty">Zatiaľ bez zaznamenaných zmien účtu.</div>'}</div>`;
  }
  function renderAdminUserEditor(user){
    if(!user)return `<div class="admin-user-empty admin-user-empty-v687"><strong>Vyber používateľa</strong><span>Klikni na účet vľavo. Potom môžeš upraviť e-mail, Telegram nickname, level a platnosť alebo mu poslať obnovu hesla.</span></div>`;
    const self=String(user.id)===String(state.feed?.account?.id),isAdmin=String(user.role||'').toLowerCase()==='admin'||String(user.plan||'').toLowerCase()==='admin',selectedPlan=!isAdmin&&user.plan&&!['expired','admin'].includes(user.plan)?String(user.plan):'',status=String(user.status||'expired').toLowerCase();
    const enabledPlans=membershipHierarchy.filter(id=>state.ui?.plans?.[id]?.enabled!==false);
    const planButtons=`<button type="button" class="admin-simple-plan reset${!selectedPlan?' active':''}" data-admin-user-plan=""><b>BEZ LEVELU</b><small>bez plateného prístupu</small></button>`+enabledPlans.map(id=>{const active=id===selectedPlan;return `<button type="button" class="admin-simple-plan${active?' active':''}${id==='goat'?' top-tier':''}" data-admin-user-plan="${escapeHtml(id)}"><b>${escapeHtml(String(state.ui?.plans?.[id]?.label||id.toUpperCase()).replace(/^BlinQ\s+/i,''))}</b><small>${escapeHtml(planTermLabel(id))}</small></button>`;}).join('');
    const currentExpiry=status==='lifetime'?'Doživotne':user.expires_at?`${fmtDate(user.expires_at)} · ${fmtTime(user.expires_at)}`:'Bez platnosti';
    return `<form id="adminUserForm" class="admin-user-editor admin-user-editor-simple">
      <div class="admin-user-simple-head"><div><small>UPRAVIŤ ÚČET</small><h3>${escapeHtml(user.telegram_nick||user.email||'Používateľ')}</h3><p>${escapeHtml(user.email||'')}</p></div><span class="admin-current-access">${escapeHtml(user.plan_label||user.plan||'Bez plánu')} · ${escapeHtml(status)}</span></div>
      <section class="admin-simple-card"><header><div><span>01</span><div><strong>Údaje</strong><small>E-mail a Telegram</small></div></div></header><div class="admin-simple-fields">
        <label>E-mail<input id="adminUserEmail" type="email" required maxlength="254" value="${escapeHtml(user.email||'')}"></label>
        <label>Telegram nickname<div class="admin-input-with-icon">${adminTelegramIcon()}<input id="adminUserTelegram" maxlength="33" value="${escapeHtml(user.telegram_nick||'')}" placeholder="@nickname"></div></label>
      </div><div class="admin-user-meta-line"><span>E-mail ${user.email_verified?'overený':'neoverený'}</span><span>Vytvorený ${escapeHtml(fmtDate(user.created_at))}</span><span>Posledné prihlásenie ${escapeHtml(fmtDate(user.last_sign_in_at))}</span></div>
      <div class="admin-password-reset-row"><div><strong>Obnova hesla</strong><small>Pošle sa e-mail s linkom</small></div><button class="btn btn-ghost" type="button" data-admin-action="reset-user-password">Poslať link na obnovu hesla</button></div></section>
      ${isAdmin?`<section class="admin-simple-card admin-admin-account-note"><header><div><span>02</span><div><strong>Admin účet</strong><small>Tento interný účet zostáva ADMIN a nepoužíva členský level ani expiráciu</small></div></div></header></section>`:`<section class="admin-simple-card"><header><div><span>02</span><div><strong>Level</strong><small>Prístup a platnosť</small></div></div><b>Teraz: ${escapeHtml(currentExpiry)}</b></header>
        <input id="adminUserPlan" type="hidden" value="${escapeHtml(selectedPlan)}"><div class="admin-simple-plans">${planButtons}</div>
        <div class="admin-simple-expiry"><label>Platnosť do<input id="adminUserExpires" type="datetime-local" value="${escapeHtml(userDateValue(user.expires_at))}" ${selectedPlan==='goat'?'disabled':''}></label><div class="admin-term-actions"><button type="button" data-admin-action="apply-default-term">Použiť predvolenú dĺžku</button><button type="button" data-admin-action="extend-default-term">Predĺžiť o predvolenú dĺžku</button></div></div>
        <div class="admin-expiry-shortcuts admin-expiry-shortcuts-simple"><span>Rýchlo pridať</span><button type="button" data-admin-expiry-days="30">+30 dní</button><button type="button" data-admin-expiry-days="90">+90 dní</button><button type="button" data-admin-expiry-days="180">+180 dní</button><button type="button" data-admin-expiry-days="365">+365 dní</button></div>
      </section>`}
      <div class="admin-user-savebar admin-user-savebar-simple"><p id="adminUserMessage" class="form-message"></p><button class="btn btn-primary" type="submit">Uložiť účet</button></div>
      ${self?'':`<details class="admin-danger-zone"><summary>Nebezpečná zóna</summary><div><div><strong>Zmazať účet</strong><small>Natrvalo odstráni Firebase účet a jeho profilové údaje</small></div><button type="button" data-admin-action="delete-user">Zmazať účet</button></div></details>`}
    </form>`;
  }
  function renderAdminAccounts(){
    const users=Array.isArray(state.adminUsers)?state.adminUsers:[],f=adminUserFilterState(),sorted=adminSortedUsers(users),filtered=adminFilteredUsers();
    const countActive=users.filter(u=>['active','lifetime','trial'].includes(String(u.status||'').toLowerCase())).length,countSuspended=users.filter(u=>String(u.status||'').toLowerCase()==='suspended').length;
    if(state.adminUsersError&&!state.adminUsersLoading&&!users.length)return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>POUŽÍVATELIA</small><h2>Správa účtov</h2><p>Jednoduchá správa používateľov BlinQ</p></div></div><div class="admin-accounts-unavailable"><span class="admin-accounts-unavailable-icon">!</span><div><strong>Účty sa nenačítali — nejde o nulový počet účtov.</strong><p>${escapeHtml(state.adminUsersError)}</p></div><button class="btn btn-ghost" type="button" data-admin-action="diagnostics">Diagnostika</button></div></section>`;
    const rows=state.adminUsersLoading?'<div class="state-card">Načítavam účty…</div>':sorted.length?sorted.map(user=>{const identity=user.telegram_nick||user.email||'Používateľ',initial=String(identity).replace(/^@/,'').trim().charAt(0).toUpperCase()||'U';return `<button type="button" class="admin-simple-user-row${state.adminSelectedUser?.id===user.id?' selected':''}" data-admin-user="${escapeHtml(user.id)}"><span class="admin-simple-user-identity"><i class="admin-simple-avatar">${escapeHtml(initial)}</i><span class="admin-simple-user-main"><b>${escapeHtml(identity)}</b><small>${escapeHtml(user.telegram_nick?user.email||'—':'Bez Telegram nicku')}</small></span></span><span class="admin-simple-level is-${escapeHtml(String(user.plan||'expired'))}">${escapeHtml(String(user.plan_label||user.plan||'—').replace(/^BlinQ\s+/i,''))}</span><span class="admin-simple-expire">${escapeHtml(user.status==='lifetime'?'Doživotne':fmtDate(user.expires_at))}</span><span class="admin-simple-state is-${escapeHtml(String(user.status||'expired').toLowerCase())}">${escapeHtml(user.status||'—')}</span><span class="admin-simple-edit">›</span></button>`;}).join(''):'<div class="admin-user-empty">Nie sú načítané žiadne účty</div>';
    const levelOptions=['all',...membershipHierarchy,'admin'].map(v=>`<option value="${v}"${f.plan===v?' selected':''}>${v==='all'?'Všetky levely':v.toUpperCase()}</option>`).join('');
    const statusOptions=['all','active','trial','expired','lifetime','suspended'].map(v=>`<option value="${v}"${f.status===v?' selected':''}>${v==='all'?'Všetky stavy':v.toUpperCase()}</option>`).join('');
    return `<section class="admin-ux-section admin-accounts-simple"><div class="admin-ux-heading"><div><small>POUŽÍVATELIA</small><h2>Správa účtov</h2><p>Nájdi účet, uprav prístup a ulož.</p></div><button class="btn btn-ghost icon-text-btn" type="button" data-admin-action="refresh-users"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15.5 6.2A6 6 0 1 0 16 12"></path><path d="M15.5 2.8v3.8h-3.8"></path></svg><span>Obnoviť</span></button></div>
      ${state.adminUsersWarning?`<div class="admin-note admin-note-warning"><strong>Profilové úložisko je v náhradnom režime</strong><span>Levely fungujú cez Firebase. Niektoré profilové zmeny môžu čakať na dostupné úložisko.</span></div>`:''}
      <div class="admin-simple-stats"><span><b>${users.length}</b> účtov</span><span><b>${countActive}</b> aktívnych</span>${countSuspended?`<span><b>${countSuspended}</b> pozastavených</span>`:''}</div>
      <div class="admin-simple-toolbar"><label class="search-box"><span class="admin-search-icon" aria-hidden="true"><svg viewBox="0 0 20 20"><circle cx="8.5" cy="8.5" r="5"></circle><path d="m12.2 12.2 4 4"></path></svg></span><input id="adminUserSearch" type="search" value="${escapeHtml(f.q)}" placeholder="Hľadať e-mail, Telegram alebo UID"></label><label>Level<select id="adminUserLevelFilter">${levelOptions}</select></label><label>Stav<select id="adminUserStatusFilter">${statusOptions}</select></label><label>Zoradiť<select id="adminUserSort"><option value="email"${f.sort==='email'?' selected':''}>E-mail</option><option value="telegram"${f.sort==='telegram'?' selected':''}>Telegram</option><option value="level"${f.sort==='level'?' selected':''}>Level</option><option value="expiry"${f.sort==='expiry'?' selected':''}>Najbližšia expirácia</option><option value="last-login"${f.sort==='last-login'?' selected':''}>Posledné prihlásenie</option></select></label><span>Zobrazených <b id="adminFilteredCount">${filtered.length}</b></span></div>
      <div class="admin-accounts-split"><div class="admin-simple-user-table"><div class="admin-simple-user-head"><span>Používateľ</span><span>Level</span><span>Platnosť</span><span>Stav</span><span></span></div><div class="admin-simple-user-list">${rows}</div></div><div class="admin-simple-user-editor-wrap">${renderAdminUserEditor(state.adminSelectedUser)}</div></div>
    </section>`;
  }
  function renderAdminCampaigns(){
    state.ui.advertisers=state.ui.advertisers||{};state.ui.campaigns=state.ui.campaigns||{};
    const advertisers=Object.entries(state.ui.advertisers);
    const campaigns=Object.entries(state.ui.campaigns);
    if(state.adminCampaignId&&!state.ui.campaigns[state.adminCampaignId])state.adminCampaignId=null;
    if(!state.adminCampaignId&&campaigns.length)state.adminCampaignId=campaigns[0][0];
    const selected=state.adminCampaignId?state.ui.campaigns[state.adminCampaignId]:null;
    const advertiserCards=advertisers.length?advertisers.map(([id,a])=>`<article class="entity-card" data-advertiser-id="${escapeHtml(id)}"><div class="entity-card-head"><small>${escapeHtml(id)}</small><button class="icon-button danger" type="button" data-admin-action="delete-advertiser" data-entity-id="${escapeHtml(id)}" title="Odstrániť inzerenta"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5 5 15"></path></svg></button></div><label>Názov<input data-advertiser-field="name" value="${escapeHtml(a.name||'')}"></label><label>Web<input data-advertiser-field="website" value="${escapeHtml(a.website||'')}"></label><label>Poznámka<input data-advertiser-field="note" value="${escapeHtml(a.note||'')}"></label></article>`).join(''):'<div class="admin-user-empty">Zatiaľ nie sú žiadni inzerenti.</div>';
    const campaignRows=campaigns.length?campaigns.map(([id,c])=>`<button type="button" class="campaign-row${id===state.adminCampaignId?' selected':''}" data-admin-campaign="${escapeHtml(id)}"><span><strong>${escapeHtml(c.name||id)}</strong><small>${escapeHtml(c.advertiser_id||'nepriradené')}</small></span><b>${c.enabled===false?'VYP':'ZAP'}</b></button>`).join(''):'<div class="admin-user-empty">Zatiaľ nie sú žiadne kampane.</div>';
    const images=selected?.images&&typeof selected.images==='object'?selected.images:{};
    const specs=state.ui?.creative_specs||{};
    const spec1=specs.large_1||{},spec2=specs.large_2||{},spec3=specs.large_3||{},spec4=specs.large_4||{};
    const editor=selected?`<form id="adminCampaignForm" class="campaign-editor"><div class="admin-inspector-head"><small>${escapeHtml(state.adminCampaignId)}</small><h3>${escapeHtml(selected.name||state.adminCampaignId)}</h3><span>Kreatíva a plánovanie kampane</span></div><div class="admin-field-grid"><label>Názov<input data-campaign-field="name" value="${escapeHtml(selected.name||'')}"></label><label>Inzerent<select data-campaign-field="advertiser_id">${advertiserOptions(String(selected.advertiser_id||''))}</select></label><label class="check-field"><input type="checkbox" data-campaign-field="enabled" ${selected.enabled!==false?'checked':''}> Zapnuté</label><label class="check-field"><input type="checkbox" data-campaign-field="sponsored" ${selected.sponsored!==false?'checked':''}> Označenie sponzorované</label><label>Režim kreatívy<select data-campaign-field="creative_mode"><option value="full"${(selected.creative_mode||'full')==='full'?' selected':''}>Banner ako celý obrázok</option><option value="split"${selected.creative_mode==='split'?' selected':''}>Obrázok + text BlinQ</option></select></label><label class="check-field"><input type="checkbox" data-campaign-field="show_copy" ${selected.show_copy!==false?'checked':''}> Zobraziť nadpis / CTA nad kreatívou</label><label>Téma<select data-campaign-field="theme">${['violet','blue','purple','green'].map(v=>`<option value="${v}"${v===(selected.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label><label>Horný popis<input data-campaign-field="eyebrow" value="${escapeHtml(selected.eyebrow||'SPONSORED')}"></label><label class="span-2">Nadpis<input data-campaign-field="headline" value="${escapeHtml(selected.headline||'')}"></label><label class="span-2">Text<textarea data-campaign-field="text" rows="3">${escapeHtml(selected.text||'')}</textarea></label><label>Text CTA<input data-campaign-field="button_text" value="${escapeHtml(selected.button_text||'Open')}"></label><label>Cieľová URL<input data-campaign-field="link" value="${escapeHtml(selected.link||'')}"></label><div class="field-hint-box">Priprav všetky užitočné formáty nižšie. Vonkajšia zóna bannera zostáva pevná; 1 / 2 / 3 / 4 aktívne bloky ju rozdelia rovnomerne a BlinQ automaticky vyberie správnu kreatívu.</div><label class="span-2">1-column · ${escapeHtml(spec1.aspect_ratio||'4:1')} · rec ${escapeHtml(spec1.recommended||'1200 × 300 px')} · min ${escapeHtml(spec1.minimum||'800 × 200 px')} · safe ${escapeHtml(spec1.safe_area||'center 80%')}<input data-campaign-image="1" value="${escapeHtml(images['1']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">2-column · ${escapeHtml(spec2.aspect_ratio||'8:1')} · rec ${escapeHtml(spec2.recommended||'2400 × 300 px')} · min ${escapeHtml(spec2.minimum||'1600 × 200 px')} · safe ${escapeHtml(spec2.safe_area||'center 85%')}<input data-campaign-image="2" value="${escapeHtml(images['2']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">3-column · ${escapeHtml(spec3.aspect_ratio||'2:1')} · rec ${escapeHtml(spec3.recommended||'400 × 180 px')} · min ${escapeHtml(spec3.minimum||'320 × 144 px')} · safe ${escapeHtml(spec3.safe_area||'center 84%')}<input data-campaign-image="3" value="${escapeHtml(images['3']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">4-column · ${escapeHtml(spec4.aspect_ratio||'5:3')} · rec ${escapeHtml(spec4.recommended||'300 × 180 px')} · min ${escapeHtml(spec4.minimum||'240 × 144 px')} · safe ${escapeHtml(spec4.safe_area||'center 82%')}<input data-campaign-image="4" value="${escapeHtml(images['4']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">Záložný obrázok pre desktop<input data-campaign-field="image_url" value="${escapeHtml(selected.image_url||'')}" placeholder="Použije sa, keď chýba obrázok pre konkrétnu veľkosť"></label><label class="span-2">Obrázok pre mobil (voliteľný)<input data-campaign-field="mobile_image_url" value="${escapeHtml(selected.mobile_image_url||'')}" placeholder="Voliteľná mobilná kreatíva"></label><label>Prispôsobenie obrázka<select data-campaign-field="image_fit"><option value="cover"${(selected.image_fit||'cover')==='cover'?' selected':''}>Cover · orez na stred</option><option value="contain"${selected.image_fit==='contain'?' selected':''}>Contain · celý obrázok</option></select></label><label>Pozícia obrázka<select data-campaign-field="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(selected.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label>Aktívne od<input data-campaign-field="active_from" type="datetime-local" value="${escapeHtml(selected.active_from||'')}"></label><label>Aktívne do<input data-campaign-field="active_until" type="datetime-local" value="${escapeHtml(selected.active_until||'')}"></label></div><div class="admin-actions-row"><button class="btn btn-ghost danger" type="button" data-admin-action="delete-campaign" data-entity-id="${escapeHtml(state.adminCampaignId)}">Odstrániť kampaň</button></div></form>`:'<div class="admin-user-empty">Vytvor kampaň a potom ju priraď do ľubovoľného pevného slotu.</div>';
    return `<div class="admin-note"><strong>Bannerové kampane · voliteľné</strong><span>Pre opakovane použiteľné alebo plánované reklamy. Kampaň vytvoríš raz a potom ju môžeš priradiť do ľubovoľného bannerového slotu bez straty histórie zobrazení a kliknutí.</span></div><div class="admin-toolbar"><button class="btn btn-ghost" type="button" data-admin-action="add-advertiser">+ Inzerent</button><button class="btn btn-primary" type="button" data-admin-action="add-campaign">+ Kampaň</button><span class="admin-toolbar-spacer"></span><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Uložiť koncept v prehliadači</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publikovať zmeny</button></div><div class="campaign-admin-grid"><section><div class="admin-section-title"><strong>Inzerenti</strong><span>Identita partnera je oddelená od histórie kampane.</span></div><div class="entity-grid">${advertiserCards}</div></section><section><div class="admin-section-title"><strong>Bannerové kampane</strong><span>Kreatívy môžeš presúvať medzi slotmi bez straty analytiky.</span></div><div class="campaign-workspace"><div class="campaign-list">${campaignRows}</div>${editor}</div></section></div>`;
  }
  function renderAdminFeeds(){
    state.ui.rss=state.ui.rss||{enabled:true,refresh_minutes:60,max_age_hours:48,max_items:24,sources:[]};
    const rss=state.ui.rss;rss.sources=Array.isArray(rss.sources)?rss.sources:[];
    const rows=rss.sources.map((source,index)=>`<article class="rss-source-card" data-rss-source="${index}"><div class="entity-card-head"><small>${escapeHtml(source.id||`rss-${index+1}`)}</small><button class="icon-button danger" type="button" data-admin-action="delete-rss-source" data-source-index="${index}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5 5 15"></path></svg></button></div><div class="admin-field-grid"><label class="check-field"><input type="checkbox" data-rss-source-field="enabled" ${source.enabled!==false?'checked':''}> Zapnuté</label><label>Priority<input type="number" data-rss-source-field="priority" value="${Number(source.priority||0)}"></label><label>Name<input data-rss-source-field="name" value="${escapeHtml(source.name||'')}"></label><label class="span-2">RSS URL<input data-rss-source-field="url" value="${escapeHtml(source.url||'')}" placeholder="https://.../rss"></label></div></article>`).join('');
    return `<div class="admin-note"><strong>Záložný RSS zdroj</strong><span>One or two quality tennis feeds are enough. Articles are normalized and deduplicated before they fill unused ad slots.</span></div><div class="admin-field-grid rss-global"><label class="check-field"><input type="checkbox" data-rss-field="enabled" ${rss.enabled!==false?'checked':''}> RSS zapnuté</label><label>Obnovenie (minúty)<input type="number" min="5" max="240" data-rss-field="refresh_minutes" value="${Number(rss.refresh_minutes||60)}"></label><label>Maximálny vek článku (hodiny)<input type="number" min="1" max="720" data-rss-field="max_age_hours" value="${Number(rss.max_age_hours||48)}"></label><label>Veľkosť zásobníka<input type="number" min="1" max="100" data-rss-field="max_items" value="${Number(rss.max_items||24)}"></label></div><div class="rss-sources">${rows||'<div class="admin-user-empty">Nie sú nastavené žiadne RSS zdroje.</div>'}</div><div class="admin-actions-row"><button class="btn btn-ghost" type="button" data-admin-action="add-rss-source">+ RSS source</button><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Uložiť koncept v prehliadači</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publikovať RSS nastavenia</button></div>`;
  }
  function renderAdminAnalytics(){
    if(state.adminAnalyticsLoading)return '<div class="state-card">Načítavam analytiku bannerov…</div>';
    const data=state.adminAnalytics;
    if(!data?.available)return `<div class="admin-note"><strong>Analytika bannerov nie je dostupná</strong><span>Admin analytics storage nie je dostupné. Backend skúsi Azure Table a potom Firebase Firestore.</span></div><button class="btn btn-ghost" type="button" data-admin-action="refresh-analytics">Skúsiť znova</button>`;
    const summary=data.summary||{};
    const cards=[['Zobrazenia',String(summary.impressions||0)],['Unikátne zobrazenia',String(summary.unique_impressions||0)],['Kliknutia',String(summary.clicks||0)],['Unikátne kliknutia',String(summary.unique_clicks||0)],['CTR',pct(summary.ctr||0)],['Kampane',String(summary.campaigns||0)]];
    const rows=(data.campaigns||[]).map(row=>`<tr><td><strong>${escapeHtml(row.campaign_id)}</strong><small>${escapeHtml(row.advertiser_id||'')}</small></td><td>${row.impressions}</td><td>${row.unique_impressions}</td><td>${row.clicks}</td><td>${row.unique_clicks}</td><td>${pct(row.ctr||0)}</td><td>${escapeHtml(Object.keys(row.slots||{}).join(', ')||'—')}</td><td>${escapeHtml(fmtDate(row.last_seen))}</td></tr>`).join('');
    return `<div class="admin-analytics-head"><div class="metric-cards">${cards.map(([label,value])=>`<div class="metric-card"><small>${label}</small><strong>${value}</strong><span>posledných ${data.days||30} dní</span></div>`).join('')}</div><button class="btn btn-ghost" type="button" data-admin-action="refresh-analytics">↻ Obnoviť</button></div><div class="admin-table-wrap"><table class="admin-analytics-table"><thead><tr><th>Kampaň</th><th>Zobrazenia</th><th>Unikátne</th><th>Kliknutia</th><th>Unikátne kliknutia</th><th>CTR</th><th>Sloty</th><th>Naposledy</th></tr></thead><tbody>${rows||'<tr><td colspan="8">Zatiaľ nie sú zaznamenané žiadne udalosti bannerov.</td></tr>'}</tbody></table></div><p class="admin-muted">Zobrazenie sa započíta, keď je viditeľných aspoň ${Math.round((Number(state.ui?.analytics?.impression_threshold)||.5)*100)}% bannera približne ${Number(state.ui?.analytics?.impression_ms)||1000} ms.</p>`;
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
    return `<div class="admin-note"><strong>Kvalita modelu</strong><span>Tu sleduješ kvalitu predikcií: vyhodnotené výsledky, holdout metriky a historické backtesty. Táto časť nemení verejné predikcie ani rozloženie webu.</span></div>${metricCards([['Model',String(feed.model?.version||'—'),'produkčný model'],['Vyhodnotené',String(p.n??0),'publikované výsledky'],['Aktuálna úspešnosť',p.accuracy!=null?pct(p.accuracy):'—','vyhodnotený feed'],['Holdout n',String(holdout.n??'—'),'chronological evaluation'],['Holdout úspešnosť',holdout.accuracy!=null?pct(holdout.accuracy):'—','report modelu'],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—','nižšie je lepšie']])}<div class="route-sub static-copy"><h3>Backtesty</h3><p>Historická walk-forward validácia je súčasťou kvality modelu. Posledný vložený report: ${escapeHtml(backtest.method||report.method||'dostupný po publikovaní spolu s modelom')}.</p></div>`;
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
    if(state.adminInsightsLoading||(!force&&Array.isArray(state.adminInsights)))return;
    state.adminInsightsLoading=true;state.adminInsightsError='';rerenderAdmin();
    try{const data=await BlinqAuth.adminInsights();state.adminInsights=Array.isArray(data?.items)?data.items:[];}
    catch(error){state.adminInsights=[];state.adminInsightsError=error.status===503?'Trvalé admin úložisko nie je dostupné. Insighty vyžadujú Firestore alebo Azure Table.':error.message;}
    finally{state.adminInsightsLoading=false;rerenderAdmin();}
  }
  function adminInsightDraft(){
    const editing=(state.adminInsights||[]).find(row=>String(row.id)===String(state.adminInsightEditingId));
    return editing||{title:'',body:'',type:'insight',priority:'normal',levels:['elite','legend','goat'],link:'',link_label:'',match_id:'',active:true,pinned:false,active_from:'',active_until:''};
  }
  function adminDatetimeValue(value){const text=String(value||'');return text?text.replace('Z','').slice(0,16):'';}
  function renderAdminInsights(){
    const item=adminInsightDraft(),levels=Array.isArray(item.levels)?item.levels:[];const list=Array.isArray(state.adminInsights)?state.adminInsights:[];
    const allowed=new Set(notificationAudienceConfig().editable_levels||['elite','legend','goat']);
    const allLevels=['rookie','pro','elite','legend','goat'].filter(level=>allowed.has(level));
    const levelChecks=allLevels.map(level=>`<label class="admin-insight-level"><input type="checkbox" name="insight_level" value="${level}" ${levels.includes(level)||(!item.id&&['elite','legend','goat'].includes(level))?'checked':''}><span>${escapeHtml(String(state.ui?.plans?.[level]?.label||level).replace(/^BlinQ\s+/i,''))}</span></label>`).join('');
    const rows=list.map(row=>`<article class="admin-insight-row ${row.active===false?'is-inactive':''} priority-${escapeHtml(row.priority||'normal')}"><div><span>${escapeHtml(insightTypeLabel(row.type))}${row.pinned?' · PIN':''}</span><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml(row.body)}</p><small>${escapeHtml(insightAudienceText(row.levels))} · ${escapeHtml(row.created_at?fmtDate(row.created_at)+' '+fmtTime(row.created_at):'')} · ${Number(row.read_count)||0} prečítaní</small></div><div class="admin-insight-row-actions"><button type="button" class="btn btn-ghost" data-admin-action="insight-edit" data-insight-id="${escapeHtml(row.id)}">Upraviť</button><button type="button" class="btn btn-ghost danger" data-admin-action="insight-delete" data-insight-id="${escapeHtml(row.id)}">Zmazať</button></div></article>`).join('');
    const radar=state.adminLiveRadarStatus||{};const radarTone=radar.error?' is-error':radar.ok?' is-ok':'';
    const radarText=state.adminLiveRadarLoading?'Kontrolujem live zápasy…':radar.error?String(radar.error):radar.scanned_at?`Posledný scan ${fmtTime(radar.scanned_at)} · live ${Number(radar.live_events)||0} · kandidáti ${Number(radar.candidates)||0} · signály ${Number(radar.signals)||0} · nové ${Number(radar.new_alerts??radar.created)||0}`:'Automatický radar beží na serveri. Tu ho vieš kedykoľvek otestovať ručne.';
    return `<section class="admin-ux-section admin-insights-section"><div class="admin-ux-heading"><div><small>SPRÁVY & LIVE</small><h2>Info & Comeback LIVE</h2><p>INFO kanál pre zvolené levely a LIVE Radar pre ELITE+.</p></div><button type="button" class="btn btn-ghost" data-admin-action="insight-new">Nová správa</button></div>${state.adminInsightsError?`<div class="admin-runtime-note is-error"><strong>Feed nie je dostupný</strong><span>${escapeHtml(state.adminInsightsError)}</span></div>`:''}<div class="admin-live-radar-card${radarTone}"><div><small>COMEBACK LIVE RADAR</small><strong>PRIME pool → prehratý 1. set → potvrdený návrat</strong><span>${escapeHtml(radarText)}</span></div><button type="button" class="btn btn-ghost" data-admin-action="live-radar-scan" ${state.adminLiveRadarLoading?'disabled':''}>${state.adminLiveRadarLoading?'Skenujem…':'Scan LIVE teraz'}</button></div><div class="admin-insights-grid"><form id="adminInsightForm" class="admin-insight-composer"><div class="admin-insight-composer-head"><div><small>${item.id?'UPRAVIŤ':'NOVÁ SPRÁVA'}</small><h3>${item.id?escapeHtml(item.title):'Napíš Premium Info alebo ručné LIVE upozornenie'}</h3></div><span>${escapeHtml(insightAudienceText(levels.length?levels:['elite','legend','goat']))}</span></div><label>Nadpis<input id="adminInsightTitle" maxlength="140" required value="${escapeHtml(item.title||'')}"></label><label>Správa<textarea id="adminInsightBody" maxlength="4000" required rows="7">${escapeHtml(item.body||'')}</textarea></label><div class="admin-form-grid"><label>Typ<select id="adminInsightType"><option value="vip"${String(item.type||'vip')==='vip'?' selected':''}>Premium Info</option><option value="alert"${item.type==='alert'?' selected':''}>LIVE</option></select></label><label>Priorita<select id="adminInsightPriority"><option value="normal"${item.priority==='normal'?' selected':''}>Normal</option><option value="important"${item.priority==='important'?' selected':''}>Important</option><option value="critical"${item.priority==='critical'?' selected':''}>Critical</option></select></label></div><fieldset class="admin-insight-audience"><legend>Viditeľné pre</legend><div>${levelChecks}</div><div class="admin-insight-audience-presets"><button type="button" class="btn btn-ghost" data-admin-action="insight-audience-rookie">ROOKIE</button><button type="button" class="btn btn-ghost" data-admin-action="insight-audience-elite">ELITE+</button><button type="button" class="btn btn-ghost" data-admin-action="insight-audience-all">VŠETCI</button></div><small>INFO môžeš poslať ľubovoľným levelom. Ručné a automatické LIVE upozornenia zostávajú iba ELITE+.</small></fieldset><div class="admin-form-grid"><label>Event ID / zápas (voliteľné)<input id="adminInsightMatchId" value="${escapeHtml(item.match_id||'')}"></label><label>Text odkazu<input id="adminInsightLinkLabel" maxlength="80" value="${escapeHtml(item.link_label||'')}"></label><label class="span-2">Odkaz (voliteľné)<input id="adminInsightLink" value="${escapeHtml(item.link||'')}"></label><label>Aktívne od<input id="adminInsightFrom" type="datetime-local" value="${escapeHtml(adminDatetimeValue(item.active_from))}"></label><label>Aktívne do<input id="adminInsightUntil" type="datetime-local" value="${escapeHtml(adminDatetimeValue(item.active_until))}"></label></div><div class="admin-insight-flags"><label><input id="adminInsightActive" type="checkbox" ${item.active!==false?'checked':''}> Aktívna</label><label><input id="adminInsightPinned" type="checkbox" ${item.pinned?'checked':''}> Pripnúť hore</label></div><div class="admin-insight-actions"><button class="btn btn-primary" type="submit">${item.id?'Uložiť':'Publikovať'}</button>${item.id?'<button class="btn btn-ghost" type="button" data-admin-action="insight-new">Zrušiť</button>':''}<span id="adminInsightMessage"></span></div></form><div class="admin-insight-list"><div class="admin-subsection-heading"><div><strong>Publikované</strong><span>${state.adminInsightsLoading?'Načítavam…':`${list.length} správ`}</span></div></div>${state.adminInsightsLoading?'<div class="admin-note"><strong>Načítavam…</strong></div>':rows||'<div class="admin-note"><strong>Zatiaľ žiadne správy</strong><span>Premium Info sa zobrazí v INFO a LIVE upozornenia v samostatnom LIVE tlačidle podľa vybraných levelov.</span></div>'}</div></div></section>`;
  }


  function renderAdminSupport(){
    const items=Array.isArray(state.adminSupport)?state.adminSupport:[];
    const counts={all:items.length,new:items.filter(x=>x.status==='new').length,in_progress:items.filter(x=>x.status==='in_progress').length,resolved:items.filter(x=>x.status==='resolved').length};
    const filtered=state.adminSupportStatus==='all'?items:items.filter(x=>x.status===state.adminSupportStatus);
    const rows=filtered.map(item=>`<article class="admin-support-ticket" data-support-ticket="${escapeHtml(item.ticket_id||'')}"><header><div><small>${escapeHtml(item.ticket_id||'')}</small><strong>${escapeHtml(item.subject||item.category||'Support')}</strong></div><span class="support-status is-${escapeHtml(item.status||'new')}">${escapeHtml(item.status==='in_progress'?'RIEŠI SA':item.status==='resolved'?'VYRIEŠENÉ':'NOVÉ')}</span></header><div class="admin-support-meta"><span>${escapeHtml(item.email||'—')}</span><span>${escapeHtml(item.category||'other')}</span><span>${escapeHtml(fmtDate(item.created_at))} · ${escapeHtml(fmtTime(item.created_at))}</span></div><p>${escapeHtml(item.message||'')}</p><div class="admin-support-controls"><label>Stav<select data-support-status><option value="new"${item.status==='new'?' selected':''}>Nové</option><option value="in_progress"${item.status==='in_progress'?' selected':''}>Rieši sa</option><option value="resolved"${item.status==='resolved'?' selected':''}>Vyriešené</option></select></label><label>Interná poznámka<input data-support-note maxlength="2000" value="${escapeHtml(item.admin_note||'')}" placeholder="Poznámka iba pre admina"></label><button class="btn btn-primary" type="button" data-admin-action="save-support" data-ticket-id="${escapeHtml(item.ticket_id||'')}">Uložiť</button></div></article>`).join('');
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>SUPPORT</small><h2>Požiadavky používateľov</h2><p>Jednoduchý manuálny support. Bez externého helpdesku.</p></div><button class="btn btn-ghost" type="button" data-admin-action="refresh-support">Obnoviť</button></div>${state.adminSupportError?`<div class="admin-runtime-note is-error"><strong>Support nie je dostupný</strong><span>${escapeHtml(state.adminSupportError)}</span></div>`:''}<div class="admin-support-filters">${[['all','Všetky'],['new','Nové'],['in_progress','Rieši sa'],['resolved','Vyriešené']].map(([id,label])=>`<button type="button" class="${state.adminSupportStatus===id?'active':''}" data-support-filter="${id}">${label}<b>${counts[id]||0}</b></button>`).join('')}</div><div class="admin-support-list">${state.adminSupportLoading?'<div class="state-card">Načítavam support…</div>':rows||'<div class="admin-user-empty">Žiadne support požiadavky v tomto filtri.</div>'}</div></section>`;
  }
  function auditDiffLabel(item){
    const before=item?.before||{},after=item?.after||{};const changes=[];
    ['plan','status','expires_at','role','tg_private_member'].forEach(key=>{if(String(before[key]??'')!==String(after[key]??''))changes.push(`${key}: ${before[key]??'—'} → ${after[key]??'—'}`);});
    if(item?.action==='account_admin_metadata_update'&&String(before.admin_note||'')!==String(after.admin_note||''))changes.push('interná poznámka upravená');
    return changes.join(' · ')||item?.action||'zmena účtu';
  }
  function renderAdminAudit(){
    const items=Array.isArray(state.adminAudit)?state.adminAudit:[];
    const rows=items.map(item=>`<tr><td><strong>${escapeHtml(fmtDate(item.occurred_at))}</strong><small>${escapeHtml(fmtTime(item.occurred_at))}</small></td><td>${escapeHtml(item.target_id||'—')}</td><td>${escapeHtml(auditDiffLabel(item))}</td><td>${escapeHtml(item.actor_id||'—')}</td><td><span class="audit-outcome is-${escapeHtml(item.outcome||'success')}">${escapeHtml(item.outcome||'success')}</span></td></tr>`).join('');
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>AUDIT LOG</small><h2>História zmien účtov</h2><p>Kto, komu, kedy a čo zmenil. História je append-only a nemení sa spolu s aktuálnym účtom.</p></div><button class="btn btn-ghost" type="button" data-admin-action="refresh-audit">Obnoviť</button></div><div class="admin-table-wrap"><table class="admin-analytics-table"><thead><tr><th>Čas</th><th>Účet</th><th>Zmena</th><th>Admin</th><th>Výsledok</th></tr></thead><tbody>${state.adminAuditLoading?'<tr><td colspan="5">Načítavam audit…</td></tr>':rows||'<tr><td colspan="5">Zatiaľ nie sú dostupné auditné záznamy.</td></tr>'}</tbody></table></div></section>`;
  }
  function systemState(ok,warning=false){return ok?'ok':warning?'warning':'error';}
  function renderAdminSystem(){
    const d=state.adminDiagnostics||{},feed=d.feed||{},provider=d.provider||{},ops=d.ops||{},counts=ops.counts||{};
    const storage=d.storage||{},storageServices=storage.services||{};
    const privateServicesReady=Boolean(storageServices.premium_info&&storageServices.live_alert_history&&storageServices.support);
    const storageDetail=d.content_storage_ready?`${d.admin_storage||'storage'}${storage.azure_connection_source?' · '+storage.azure_connection_source:''}`:(storage.recommended_setting?`SET ${storage.recommended_setting}`:'unavailable');
    const cards=[
      ['API / AUTH',Boolean(d.accounts_ready),d.auth_provider||'—'],
      ['ADMIN STORAGE',Boolean(d.content_storage_ready),storageDetail],
      ['INFO / LIVE / SUPPORT',privateServicesReady,privateServicesReady?'ONLINE':'NEED STORAGE'],
      ['PUBLISHED FEED',Boolean(feed.ready)&&!feed.stale,feed.ready?(feed.stale?'STALE':'FRESH'):'NO FEED'],
      ['DATA PROVIDER',Boolean(provider.configured),provider.configured?'CONFIGURED':'MISSING KEY'],
      ['ERRORS · 24H',Number(counts.error||0)===0,String(counts.error||0)],
    ];
    const events=(ops.items||[]).map(item=>`<tr><td><span class="ops-level is-${escapeHtml(item.level||'info')}">${escapeHtml(String(item.level||'info').toUpperCase())}</span></td><td>${escapeHtml(item.component||'app')}</td><td>${escapeHtml(item.message||'')}</td><td>${escapeHtml(fmtDate(item.occurred_at))} · ${escapeHtml(fmtTime(item.occurred_at))}</td></tr>`).join('');
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>SYSTEM HEALTH</small><h2>Prevádzkový stav</h2><p>Rýchla kontrola API, účtov, úložiska, feedu a dátového providera. Pri chybe sa tu zobrazí aj posledný prevádzkový záznam.</p></div><div class="admin-system-actions"><button class="btn btn-ghost" type="button" data-admin-action="copy-diagnostics">Kopírovať diagnostiku</button><button class="btn btn-primary" type="button" data-admin-action="diagnostics">Spustiť kontrolu</button></div></div><div class="admin-system-cards">${cards.map(([name,ok,detail])=>`<article class="admin-system-card is-${systemState(ok,false)}"><span></span><small>${name}</small><strong>${ok?'OK':'CHECK'}</strong><em>${escapeHtml(detail)}</em></article>`).join('')}</div><div class="admin-system-details"><div><small>Posledný feed</small><strong>${escapeHtml(feed.generated_at?`${fmtDate(feed.generated_at)} · ${fmtTime(feed.generated_at)}`:'—')}</strong></div><div><small>Model</small><strong>${escapeHtml(feed.model_version||state.feed?.model?.version||'—')}</strong></div><div><small>Upcoming / Results</small><strong>${Number(feed.upcoming||0)} / ${Number(feed.results||0)}</strong></div><div><small>Úložisko</small><strong>${escapeHtml(storageDetail)}</strong></div><div><small>Kontrola</small><strong>${d.checked_at?new Date(Number(d.checked_at)*1000).toLocaleTimeString('sk-SK',{hour:'2-digit',minute:'2-digit'}):'—'}</strong></div></div>${!d.content_storage_ready?`<div class="admin-runtime-note is-error"><strong>INFO, uložená história LIVE a Support potrebujú trvalé úložisko</strong><span>Nastav jeden spoločný App Setting <code>${escapeHtml(storage.recommended_setting||'BLINQ_STORAGE_CONNECTION_STRING')}</code>. Ak už používaš storage pre bannery, BlinQ ho automaticky znovu použije.</span></div>`:''}<div class="admin-form-section"><div class="admin-form-section-title"><strong>Posledné udalosti</strong><span>Serverové chyby, ktoré zachytil BlinQ prevádzkový journal.</span></div><div class="admin-table-wrap"><table class="admin-analytics-table"><thead><tr><th>Level</th><th>Komponent</th><th>Správa</th><th>Čas</th></tr></thead><tbody>${events||'<tr><td colspan="4">Za posledných 24 hodín nie sú zaznamenané žiadne prevádzkové udalosti.</td></tr>'}</tbody></table></div></div></section>`;
  }
  function renderAdminPages(){
    const pages=state.siteContent?.pages?.sk||{};
    const ids=['how_blinq_works','methodology','model_data','faq','responsible_use','terms','privacy','cookies','support'];
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>WEB CONTENT</small><h2>Textové stránky</h2><p>Obsah je oddelený od HTML v <code>/web/config/site-content.json</code>. Táto sekcia je určená iba na kontrolu pripravených textov.</p></div></div><div class="admin-content-pages">${ids.map(id=>{const page=pages[id]||{};return `<article><div><small>${escapeHtml(id)}</small><strong>${escapeHtml(page.title||id)}</strong><span>${page.sections?.length||page.faq?.length||0} blokov</span></div><a class="btn btn-ghost" href="#${escapeHtml(id)}" data-route="${escapeHtml(id)}">Otvoriť stránku</a></article>`;}).join('')}</div></section>`;
  }
  function renderAdminOverview(){
    const d=state.adminDiagnostics||{},systemReady=Boolean(d.accounts_ready&&d.content_storage_ready);
    return `<section class="admin-ux-section admin-overview-v687">
      <div class="admin-overview-hero"><div><small>ZAČNI TU</small><h2>Čo chceš dnes upraviť?</h2><p>Admin je rozdelený podľa úloh. Nemusíš nastavovať všetko. Vyber iba oblasť, ktorú chceš zmeniť.</p></div><span class="admin-overview-health ${systemReady?'is-ok':''}"><i></i>${systemReady?'Systém pripravený':'Skontrolovať systém'}</span></div>
      <div class="admin-overview-actions">
        <button type="button" data-admin-tab="accounts"><span>01</span><div><strong>Používateľský účet</strong><small>Upraviť údaje, poslať obnovu hesla, zmeniť level alebo platnosť</small></div><b>Otvoriť</b></button>
        <button type="button" data-admin-tab="layout"><span>02</span><div><strong>Denná ponuka</strong><small>Nastaviť, čo vidí ROOKIE / PRO / ELITE / LEGEND / GOAT a koľko riadkov je odomknutých</small></div><b>Otvoriť</b></button>
        <button type="button" data-admin-tab="banners"><span>03</span><div><strong>Bannery a vizuálny obsah</strong><small>Kliknúť na pozíciu v mini náhľade webu a zmeniť obrázok, text, odkaz alebo cielenie</small></div><b>Otvoriť</b></button>
        <button type="button" data-admin-tab="support"><span>04</span><div><strong>Support</strong><small>Prečítať požiadavky používateľov, pridať internú poznámku a označiť stav</small></div><b>Otvoriť</b></button>
      </div>
      <div class="admin-overview-storage"><article><span>UKLADÁ SA OKAMŽITE</span><strong>Používatelia · support</strong><p>Zmeny účtov a supportu sa po potvrdení aplikujú priamo. Nie je potrebné stláčať Publikovať.</p></article><article><span>VYŽADUJE PUBLIKOVANIE</span><strong>Denná ponuka · bannery · plány · kampane</strong><p>Najprv upravíš koncept. Až tlačidlo <b>Publikovať</b> vpravo hore prenesie zmenu na live web.</p></article></div>
      <div class="admin-overview-checklist"><div><small>NAJČASTEJŠÍ POSTUP</small><strong>Úprava levelu používateľa</strong><p>Používatelia → nájdi účet → vyber plán a platnosť → Použiť zmeny účtu</p></div><div><small>NAJČASTEJŠÍ POSTUP</small><strong>Úprava dennej ponuky</strong><p>Denná ponuka → vyber level → nastav kategórie a počet riadkov → Publikovať</p></div><div><small>NAJČASTEJŠÍ POSTUP</small><strong>Výmena bannera</strong><p>Bannery → klikni na slot v náhľade → uprav obsah → Publikovať</p></div></div>
      <button type="button" class="admin-overview-system-link" data-admin-tab="system"><span><i></i>Diagnostika a stav systému</span><b>Otvoriť System →</b></button>
    </section>`;
  }

  function renderAdminRoute(){
    const tabs=[['accounts','Účty','Prístup · platnosť'],['banners','Bannery','Hero · pozadie'],['insights','Info & LIVE','Správy · radar'],['support','Support','Požiadavky'],['system','Systém','Diagnostika']];
    const valid=tabs.map(row=>row[0]);if(!valid.includes(state.adminTab))state.adminTab='accounts';
    const renderers={accounts:renderAdminAccounts,banners:renderAdminBanners,insights:renderAdminInsights,support:renderAdminSupport,system:renderAdminSystem};const panel=renderers[state.adminTab]();
    const info={accounts:['Účty','Levely, platnosť a prístup.'],banners:['Bannery','Hero, mobil a pozadie.'],insights:['Info & LIVE','Správy podľa levelu a Comeback radar.'],support:['Support','Požiadavky používateľov a stav riešenia.'],system:['Systém','Úložisko, API, feed a prevádzková diagnostika.']}[state.adminTab];
    let contextual='';
    if(state.adminTab==='accounts')contextual='<div class="admin-account-direct-note"><span></span>Zmeny účtov sa aplikujú okamžite</div>';
    else if(state.adminTab==='insights')contextual='<div class="admin-account-direct-note"><span></span>Správy sa publikujú okamžite</div>';
    else if(state.adminTab==='support')contextual='<div class="admin-account-direct-note"><span></span>Support sa ukladá okamžite</div>';
    else if(state.adminTab==='system')contextual='<button class="btn btn-primary" type="button" data-admin-action="diagnostics">Spustiť kontrolu</button>';
    else contextual='<div class="admin-publish-hint"><span>Koncept</span><i></i><b>Live po publikovaní</b></div><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Uložiť koncept</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publikovať</button>';
    const nav=tabs.map(([id,label,hint])=>`<button type="button" class="${state.adminTab===id?'active':''}" data-admin-tab="${id}"><span class="admin-nav-mark"></span><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(hint)}</small></span></button>`).join('');
    return `<div class="admin-console admin-console-v685 admin-console-v687 lean-admin-console"><aside class="admin-side-nav"><div class="admin-side-brand"><span>BLINQ CONTROL</span><strong>Admin</strong><small>Účty · obsah · LIVE</small></div><nav class="admin-tabs admin-tabs-v685" aria-label="Admin navigácia"><div class="admin-nav-group"><span>SPRÁVA</span>${nav}</div></nav><div class="admin-side-foot"><a href="#predictions" data-route="predictions"><svg viewBox="0 0 20 20"><path d="M4 10h12M9 5l-5 5 5 5"></path></svg><span>Späť na web</span></a></div></aside><section class="admin-workarea"><header class="admin-workarea-head admin-control-toolbar"><div><small>ADMIN / ${escapeHtml(state.adminTab.toUpperCase())}</small><h2>${escapeHtml(info[0])}</h2><p>${escapeHtml(info[1])}</p></div><div class="admin-global-actions">${contextual}</div></header><div class="admin-panel admin-panel-v685">${panel}</div></section></div>`;
  }


  function rerenderAdmin(){ if(state.route!=='admin')return; const host=$('routePanel');host.innerHTML=renderAdminRoute();wireAdmin(); }
  function saveDraft(){ localStorage.setItem(draftKey(),JSON.stringify(state.ui)); showStatus('Admin koncept bol uložený v tomto prehliadači.'); }
  function exportUiConfig(){ const blob=new Blob([JSON.stringify(state.ui,null,2)+'\n'],{type:'application/json'}); const url=URL.createObjectURL(blob); const a=document.createElement('a');a.href=url;a.download='ui-config.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),0); }
  async function loadAdminDiagnostics(force=false){
    if(state.adminDiagnosticsLoading||(!force&&state.adminDiagnostics))return;
    state.adminDiagnosticsLoading=true;rerenderAdmin();
    try{state.adminDiagnostics=await BlinqAuth.adminDiagnostics();}
    catch(error){state.adminDiagnostics={ok:false,error:error.message,status:error.status||0};}
    finally{state.adminDiagnosticsLoading=false;rerenderAdmin();}
  }
  async function loadAdminUsers(force=false){
    if(state.adminUsersLoading||(!force&&Array.isArray(state.adminUsers)))return;
    state.adminUsersLoading=true;rerenderAdmin();
    try{
      const all=[];const perPage=200;let page=1;
      let storageWarning='';
      while(page<=25){const data=await BlinqAuth.adminUsers(page,perPage);const batch=Array.isArray(data?.users)?data.users:[];all.push(...batch);if(data?.storage_warning)storageWarning=data.storage_warning;if(batch.length<perPage)break;page+=1;}
      state.adminUsersWarning=storageWarning?'Účty sú načítané cez Firebase fallback. TG Private funguje, ale interné poznámky a platobné referencie potrebujú trvalé admin úložisko.':'';
      state.adminUsersError=all.length>=5000?'Zobrazených prvých 5000 účtov. Pre väčší zoznam treba serverové cursor filtrovanie.':'';state.adminUsers=all;
      if(state.adminSelectedUser)state.adminSelectedUser=state.adminUsers.find(x=>x.id===state.adminSelectedUser.id)||null;
    }catch(error){state.adminUsers=[];state.adminUsersWarning='';state.adminUsersError=error.status===503?'Admin API pre účty nie je dostupné. Otvor Diagnostiku pre presný stav Firebase Admin konfigurácie.':error.message;}
    finally{state.adminUsersLoading=false;rerenderAdmin();adminApplyUserFilters();}
  }

  async function loadAdminPayments(userId,force=false){
    const id=String(userId||'');if(!id)return;
    state.adminPayments=state.adminPayments||{};
    const current=state.adminPayments[id]||{};
    if(current.loading||(!force&&Array.isArray(current.items)))return;
    state.adminPayments[id]={...current,loading:true,error:''};rerenderAdmin();
    try{const data=await BlinqAuth.adminPayments(id);state.adminPayments[id]={loading:false,error:'',items:Array.isArray(data?.items)?data.items:[]};}
    catch(error){state.adminPayments[id]={loading:false,error:error.message||'História platieb nie je dostupná.',items:[]};}
    finally{rerenderAdmin();}
  }
  async function loadAdminUserAudit(userId,force=false){
    const id=String(userId||'');if(!id)return;
    state.adminUserAudit=state.adminUserAudit||{};const current=state.adminUserAudit[id]||{};
    if(current.loading||(!force&&Array.isArray(current.items)))return;
    state.adminUserAudit[id]={...current,loading:true,error:''};rerenderAdmin();
    try{const data=await BlinqAuth.adminAudit(id);state.adminUserAudit[id]={loading:false,error:'',items:Array.isArray(data?.items)?data.items:[]};}
    catch(error){state.adminUserAudit[id]={loading:false,error:error.message||'História účtu nie je dostupná.',items:[]};}
    finally{rerenderAdmin();}
  }
  async function loadAdminSupport(force=false){
    if(state.adminSupportLoading||(!force&&Array.isArray(state.adminSupport)))return;
    state.adminSupportLoading=true;rerenderAdmin();
    try{const data=await BlinqAuth.adminSupport('all');state.adminSupport=Array.isArray(data?.items)?data.items:[];state.adminSupportError='';}
    catch(error){state.adminSupport=[];state.adminSupportError=error.message||'Support nie je dostupný.';}
    finally{state.adminSupportLoading=false;rerenderAdmin();}
  }
  async function loadAdminAudit(force=false){
    if(state.adminAuditLoading||(!force&&Array.isArray(state.adminAudit)))return;
    state.adminAuditLoading=true;rerenderAdmin();
    try{const data=await BlinqAuth.adminAudit();state.adminAudit=Array.isArray(data?.items)?data.items:[];}
    catch(error){state.adminAudit=[];showStatus(error.message||'Audit log nie je dostupný.');}
    finally{state.adminAuditLoading=false;rerenderAdmin();}
  }
  function setSelectedElement(id){ if(!elements()?.[id])return;state.selectedElement=id;rerenderAdmin(); }
  function updateSelectedContent(field,target){ const item=elements()?.[state.selectedElement];if(!item)return;item.content=item.content||{};item.content[field]=target.type==='checkbox'?target.checked:target.value;if(field==='campaign_id'&&target.value){item.content.type='advertisement';item.content.sponsored=true;}renderAllUiContent(); }
  function updateSelectedWatermark(field,target){ const item=elements()?.[state.selectedElement];if(!item)return;item.watermark=item.watermark||{enabled:false,text:'COMING SOON',preset:'default'};let value=target.type==='checkbox'?target.checked:target.value;if(['opacity','size'].includes(field))value=Number(value);item.watermark[field]=value;renderAllUiContent(); }
  function setAdminPlanDefaults(planId, force=false){
    const expiry=$('adminUserExpires');if(!expiry)return;
    const plan=state.ui?.plans?.[planId]||{};
    if(!planId){expiry.value='';expiry.disabled=false;return;}
    if(plan.lifetime||planId==='goat'){expiry.value='';expiry.disabled=true;return;}
    expiry.disabled=false;
    const current=expiry.value?new Date(expiry.value).getTime():0;
    if(force||!current||current<=Date.now()){
      const date=planDefaultExpiry(planId);expiry.value=userDateValue(date?.toISOString());
    }
  }
  function adminAddDaysToExpiry(days){
    const expiry=$('adminUserExpires');if(!expiry)return;
    const current=expiry.value?new Date(expiry.value).getTime():0,base=Math.max(Date.now(),Number.isFinite(current)?current:0);
    expiry.disabled=false;expiry.value=userDateValue(new Date(base+Math.max(1,Number(days)||1)*86400000).toISOString());
  }
  function adminDefaultPlanDays(){
    const planId=String($('adminUserPlan')?.value||'');const plan=state.ui?.plans?.[planId]||{};return plan.lifetime||planId==='goat'?0:Math.max(1,Number(plan.duration_days)||30);
  }
  function decorateAdminMediaUploads(host){
    if(!host)return;
    const selector=[
      'input[data-simple-banner-field="image_url"]',
      'input[data-simple-banner-field="mobile_image_url"]',
      'input[data-simple-banner-field="site_background_url"]',
      'input[data-simple-banner-field$="_icon_url"]',
      'input[data-campaign-image]',
      'input[data-campaign-field="image_url"]',
      'input[data-campaign-field="mobile_image_url"]'
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
      const tab=event.target.closest('[data-admin-tab]');if(tab){state.adminTab=tab.dataset.adminTab;rerenderAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='insights')loadAdminInsights();if(state.adminTab==='analytics')loadBannerAnalytics();if(state.adminTab==='support')loadAdminSupport();if(state.adminTab==='audit')loadAdminAudit();if(state.adminTab==='system')loadAdminDiagnostics(true);return;}
      const planChip=event.target.closest('[data-admin-plan-chip]');if(planChip){state.adminPlan=planChip.dataset.adminPlanChip;rerenderAdmin();return;}
      const dailyPreset=event.target.closest('[data-admin-daily-preset]');if(dailyPreset){const preset=dailyPreset.dataset.adminDailyPreset,hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};hub.tabs=hub.tabs||{};['daily','top','value','ace','games','doubles'].forEach(tab=>{const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc.plans=tc.plans||{};const rule=tc.plans[state.adminPlan]=tc.plans[state.adminPlan]||{};if(preset==='full'){rule.tab_enabled=true;rule.visible_rows='ALL';rule.blur_remaining=false;rule.see_all=true;}else if(preset==='preview3'){rule.tab_enabled=true;rule.visible_rows=3;rule.blur_remaining=true;rule.see_all=false;}else if(preset==='teaser1'){rule.tab_enabled=true;rule.visible_rows=1;rule.blur_remaining=true;rule.see_all=false;}else if(preset==='hidden'){rule.tab_enabled=false;rule.visible_rows=0;rule.blur_remaining=true;rule.see_all=false;}if(state.adminPlan==='rookie')tc.plans.trial=clone(rule);});renderAllUiContent();rerenderAdmin();showStatus(`Denná ponuka · ${accessLabel(state.adminPlan)} preset bol nastavený.`);return;}
      const bannerPreviewChip=event.target.closest('[data-admin-banner-preview-plan]');if(bannerPreviewChip){state.adminBannerPreviewPlan=bannerPreviewChip.dataset.adminBannerPreviewPlan;rerenderAdmin();return;}
      const planSelect=event.target.closest('[data-admin-plan-select]');if(planSelect){state.adminPlanId=planSelect.dataset.adminPlanSelect;rerenderAdmin();return;}
      const sectionPreset=event.target.closest('[data-section-preset]');if(sectionPreset){const key=sectionPreset.dataset.sectionKey,plan=state.adminPlan,cfg=key?state.ui?.dashboard?.sections?.[key]:null,id=cfg?.sidebar_element,item=id?elements()?.[id]:null;if(cfg&&item&&plan){cfg.plans=cfg.plans||{};cfg.plans[plan]=cfg.plans[plan]||{};item.access=item.access||{};const ent=cfg.plans[plan],preset=sectionPreset.dataset.sectionPreset;if(preset==='full'){item.access[plan]='active';ent.visible_picks='ALL';ent.blur_remaining=false;ent.see_all=true;}else if(preset==='teaser'){item.access[plan]='active';ent.visible_picks=1;ent.blur_remaining=true;ent.see_all=true;}else if(preset==='blurred'){item.access[plan]='locked';ent.visible_picks=0;ent.blur_remaining=true;ent.see_all=false;}else if(preset==='hidden'){item.access[plan]='hidden';ent.visible_picks=0;ent.blur_remaining=true;ent.see_all=false;}if(plan==='rookie'){item.access.trial=item.access[plan];cfg.plans.trial=clone(ent);}state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();showStatus(`${cfg.label||key} · ${accessLabel(plan)} preset applied.`);}return;}
      const bannerPreset=event.target.closest('[data-banner-preset]');if(bannerPreset){const item=elements()?.[state.selectedElement];if(item){item.access=item.access||{};item.click_access=item.click_access||{};const preset=bannerPreset.dataset.bannerPreset;accessContexts.forEach(plan=>{let visible=true,click=true;if(preset==='teaser-elite')click=['elite','legend','goat'].includes(plan);if(preset==='pro-only'){visible=['pro','elite','legend','goat'].includes(plan);click=visible;}if(preset==='goat-only'){visible=plan==='goat';click=visible;}item.access[plan]=visible?'active':'hidden';item.click_access[plan]=click;});item.access.trial=item.access.rookie;item.click_access.trial=item.click_access.rookie;renderAllUiContent();rerenderAdmin();}return;}
      const element=event.target.closest('[data-admin-element]');if(element){setSelectedElement(element.dataset.adminElement);return;}
      const userButton=event.target.closest('[data-admin-user]');if(userButton){state.adminSelectedUser=(state.adminUsers||[]).find(x=>String(x.id)===String(userButton.dataset.adminUser))||null;rerenderAdmin();return;}
      const campaignButton=event.target.closest('[data-admin-campaign]');if(campaignButton){state.adminCampaignId=campaignButton.dataset.adminCampaign;rerenderAdmin();return;}
      const quick=event.target.closest('[data-admin-user-plan]');if(quick){const input=$('adminUserPlan');if(input){input.value=quick.dataset.adminUserPlan;host.querySelectorAll('[data-admin-user-plan]').forEach(btn=>btn.classList.toggle('active',btn===quick));setAdminPlanDefaults(input.value,false);}return;}
      const expiryQuick=event.target.closest('[data-admin-expiry-days]');if(expiryQuick){adminAddDaysToExpiry(Number(expiryQuick.dataset.adminExpiryDays));return;}
      const supportFilter=event.target.closest('[data-support-filter]');if(supportFilter){state.adminSupportStatus=supportFilter.dataset.supportFilter||'all';state.adminSupport=null;rerenderAdmin();loadAdminSupport(true);return;}
      const actionNode=event.target.closest('[data-admin-action]');const action=actionNode?.dataset.adminAction;if(!action)return;
      if(action==='insight-new'){state.adminInsightEditingId='';rerenderAdmin();return;}
      if(action==='insight-edit'){state.adminInsightEditingId=String(actionNode.dataset.insightId||'');rerenderAdmin();return;}
      if(action==='insight-delete'){const id=String(actionNode.dataset.insightId||'');if(!id)return;if(!window.confirm('Naozaj chceš túto správu odstrániť?'))return;try{await BlinqAuth.adminDeleteInsight(id);state.adminInsightEditingId='';state.adminInsights=null;await loadAdminInsights(true);await loadInsights(true);showStatus('Správa bola odstránená.');}catch(error){showStatus(error.message);}return;}
      if(action==='insight-audience-rookie'||action==='insight-audience-elite'||action==='insight-audience-all'){const form=$('adminInsightForm');if(!form)return;const wanted=action==='insight-audience-rookie'?new Set(['rookie']):action==='insight-audience-all'?new Set(['rookie','pro','elite','legend','goat']):new Set(['elite','legend','goat']);form.querySelectorAll('input[name="insight_level"]').forEach(node=>{node.checked=wanted.has(node.value);});return;}
      if(action==='live-radar-scan'){if(state.adminLiveRadarLoading)return;state.adminLiveRadarLoading=true;state.adminLiveRadarStatus=null;rerenderAdmin();try{const result=await BlinqAuth.adminLiveRadar(true,true);state.adminLiveRadarStatus={...result,ok:true,new_alerts:Number(result?.created)||0};state.adminInsights=null;await loadAdminInsights(true);await loadInsights(true);showStatus(`LIVE Radar: ${Number(result?.signals?.length??result?.signals)||0} signálov · ${Number(result?.created)||0} nových upozornení.`);}catch(error){state.adminLiveRadarStatus={error:error.message||'LIVE Radar sa nepodarilo spustiť.'};showStatus(state.adminLiveRadarStatus.error);}finally{state.adminLiveRadarLoading=false;rerenderAdmin();}return;}
      if(action==='diagnostics'){loadAdminDiagnostics(true);return;}
      if(action==='copy-diagnostics'){
        const d=state.adminDiagnostics||{};
        const safe={release:d.release||'',accounts_ready:Boolean(d.accounts_ready),content_storage_ready:Boolean(d.content_storage_ready),auth_provider:d.auth_provider||'',admin_storage:d.admin_storage||'unavailable',firebase_server_configured:Boolean(d.firebase_server_configured),firebase_admin_users:Boolean(d.firebase_admin_users),storage:{backend:d.storage?.backend||'unavailable',azure_configured:Boolean(d.storage?.azure_configured),azure_available:Boolean(d.storage?.azure_available),azure_connection_source:d.storage?.azure_connection_source||'',firestore_available:Boolean(d.storage?.firestore_available)},media_storage:{configured:Boolean(d.media_storage?.configured),available:Boolean(d.media_storage?.available),container:d.media_storage?.container||''},webpush:{enabled:Boolean(d.webpush?.enabled),keys_configured:Boolean(d.webpush?.keys_configured),storage_available:Boolean(d.webpush?.storage_available),subscriptions:d.webpush?.subscriptions??null},problems:Array.isArray(d.problems)?d.problems:[]};
        const value=JSON.stringify(safe,null,2);
        try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(value);else{const ta=document.createElement('textarea');ta.value=value;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();}showStatus('Bezpečná diagnostika bola skopírovaná. Môžeš ju poslať bez kľúčov a tokenov.');}catch{showStatus('Diagnostiku sa nepodarilo skopírovať.');}
        return;
      }
      if(action==='save-draft')saveDraft();
      else if(action==='publish-config')await publishUiConfig();
      else if(action==='export')exportUiConfig();
      else if(action==='reset'){localStorage.removeItem(draftKey());state.ui=clone(state.uiSource);state.selectedElement='HERO_BANNER_1';renderAllUiContent();rerenderAdmin();showStatus('Reset to repository defaults. Publish if you want this reset live.');}
      else if(action==='copy-plan'){const source=$('adminCopyFrom')?.value,target=state.adminPlan;if(source&&target){Object.values(elements()).forEach(item=>{item.access=item.access||{};item.access[target]=item.access[source]||'active';if(item.click_access){item.click_access[target]=item.click_access[source]!==false;}if(target==='rookie'){item.access.trial=item.access[target];if(item.click_access)item.click_access.trial=item.click_access[target];}});Object.keys(state.ui?.dashboard?.sections||{}).forEach(key=>{const cfg=state.ui.dashboard.sections[key];cfg.plans=cfg.plans||{};if(cfg.plans[source])cfg.plans[target]=clone(cfg.plans[source]);if(target==='rookie'&&cfg.plans.rookie)cfg.plans.trial=clone(cfg.plans.rookie);});state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();showStatus(`All rules copied from ${accessLabel(source)} to ${accessLabel(target)}.`);}}
      else if(action==='preview-demo'){state.previewPlan=null;enableDemoBoardPreview();}
      else if(action==='preview'){state.previewPlan=state.adminPlan;renderAllUiContent();setRoute('predictions');showStatus(`Previewing page as ${accessLabel(state.previewPlan)}.`);}
      else if(action==='clear-preview'){state.previewPlan=null;renderAllUiContent();rerenderAdmin();showStatus('Admin preview disabled.');}
      else if(action==='add-advertiser'){state.ui.advertisers=state.ui.advertisers||{};const id=nextEntityId('advertiser',state.ui.advertisers);state.ui.advertisers[id]={name:`Advertiser ${Object.keys(state.ui.advertisers).length+1}`,website:'',note:''};rerenderAdmin();}
      else if(action==='delete-advertiser'){const id=String(actionNode.dataset.entityId||'');const used=Object.values(state.ui?.campaigns||{}).some(c=>String(c?.advertiser_id||'')===id);if(used){showStatus('Advertiser is still assigned to a campaign. Reassign the campaign first.');}else if(id&&state.ui?.advertisers?.[id]){delete state.ui.advertisers[id];rerenderAdmin();}}
      else if(action==='add-campaign'){state.ui.campaigns=state.ui.campaigns||{};const id=nextEntityId('campaign',state.ui.campaigns);state.ui.campaigns[id]={name:`Campaign ${Object.keys(state.ui.campaigns).length+1}`,advertiser_id:'',enabled:true,sponsored:true,creative_mode:'full',show_copy:false,theme:'violet',eyebrow:'SPONSORED',headline:'',text:'',button_text:'Otvoriť',link:'',image_url:'',mobile_image_url:'',image_fit:'cover',image_position:'center',images:{'1':'','2':'','4':''},active_from:'',active_until:''};state.adminCampaignId=id;rerenderAdmin();}
      else if(action==='delete-campaign'){const id=String(actionNode.dataset.entityId||state.adminCampaignId||'');if(id&&state.ui?.campaigns?.[id]){delete state.ui.campaigns[id];Object.values(elements()).forEach(item=>{if(item?.content?.campaign_id===id)item.content.campaign_id='';});state.adminCampaignId=null;renderAllUiContent();rerenderAdmin();}}
      else if(action==='add-rss-source'){state.ui.rss=state.ui.rss||{enabled:true,sources:[]};state.ui.rss.sources=Array.isArray(state.ui.rss.sources)?state.ui.rss.sources:[];const max=Math.max(1,Number(state.ui?.admin?.max_rss_sources)||8);if(state.ui.rss.sources.length>=max){showStatus(`Maximum ${max} RSS sources.`);}else{const used=new Set(state.ui.rss.sources.map(x=>x.id));let n=1;while(used.has(`rss-${n}`))n++;state.ui.rss.sources.push({id:`rss-${n}`,name:`RSS source ${n}`,url:'',enabled:false,priority:0});rerenderAdmin();}}
      else if(action==='delete-rss-source'){const index=Number(actionNode.dataset.sourceIndex);if(Number.isInteger(index)&&index>=0&&index<(state.ui?.rss?.sources||[]).length){state.ui.rss.sources.splice(index,1);rerenderAdmin();}}
      else if(action==='reset-user-password'){const user=state.adminSelectedUser;if(!user)return;const savedEmail=String(user.email||'').trim(),editedEmail=String($('adminUserEmail')?.value||savedEmail).trim();if(!savedEmail){showStatus('Účet nemá uložený e-mail.');return;}if(editedEmail.toLowerCase()!==savedEmail.toLowerCase()){showStatus('Najprv ulož zmenený e-mail a potom pošli link na obnovu hesla.');return;}try{await BlinqAuth.reset(savedEmail);showStatus(`Link na obnovu hesla bol odoslaný na ${savedEmail}.`);}catch(error){showStatus(error.message||'Obnovu hesla sa nepodarilo odoslať.');}}
      else if(action==='apply-default-term'){const plan=String($('adminUserPlan')?.value||'');if(!plan){showStatus('Najprv vyber level.');return;}setAdminPlanDefaults(plan,true);}
      else if(action==='extend-default-term'){const plan=String($('adminUserPlan')?.value||'');if(!plan){showStatus('Najprv vyber level.');return;}if(plan==='goat'){setAdminPlanDefaults(plan,true);showStatus('GOAT má doživotnú platnosť.');return;}adminAddDaysToExpiry(adminDefaultPlanDays());}
      else if(action==='delete-user'){const user=state.adminSelectedUser;if(!user)return;const confirmation=window.prompt(`Naozaj zmazať účet ${user.email||user.id}?\n\nPre potvrdenie napíš DELETE`);if(confirmation!=='DELETE')return;try{await BlinqAuth.adminDeleteUser(user.id);state.adminUsers=(state.adminUsers||[]).filter(row=>row.id!==user.id);state.adminSelectedUser=null;rerenderAdmin();adminApplyUserFilters();showStatus('Účet bol zmazaný.');}catch(error){showStatus(error.message||'Účet sa nepodarilo zmazať.');}}
      else if(action==='refresh-users')await loadAdminUsers(true);
      else if(action==='refresh-payments'){if(state.adminSelectedUser)await loadAdminPayments(state.adminSelectedUser.id,true);}
      else if(action==='refresh-user-audit'){if(state.adminSelectedUser)await loadAdminUserAudit(state.adminSelectedUser.id,true);}
      else if(action==='refresh-support')await loadAdminSupport(true);
      else if(action==='refresh-audit')await loadAdminAudit(true);
      else if(action==='add-payment'){
        const user=state.adminSelectedUser,message=$('adminPaymentMessage');if(!user)return;
        const amount=Number($('adminPaymentAmount')?.value),date=String($('adminPaymentDate')?.value||'').trim();
        if(!Number.isFinite(amount)||amount<0){if(message)message.textContent='Zadaj platnú sumu.';return;}
        if(!date){if(message)message.textContent='Vyber dátum platby.';return;}
        if(message)message.textContent='Ukladám…';
        try{
          const payload={amount,currency:$('adminPaymentCurrency')?.value||'EUR',paid_at:new Date(`${date}T12:00:00`).toISOString(),plan:$('adminPaymentPlan')?.value||user.plan||'',reference:String($('adminPaymentLedgerReference')?.value||'').trim(),note:String($('adminPaymentNote')?.value||'').trim(),status:'confirmed',valid_until:user.expires_at||null};
          const result=await BlinqAuth.adminAddPayment(user.id,payload);
          state.adminPayments[user.id]={loading:false,error:'',items:Array.isArray(result?.items)?result.items:[result?.payment,...(state.adminPayments?.[user.id]?.items||[])].filter(Boolean)};
          if(payload.reference){user.payment_reference=payload.reference;const quick=$('adminPaymentReference');if(quick)quick.value=payload.reference;}
          if(message)message.textContent='Platba bola pridaná do histórie.';
          setTimeout(()=>rerenderAdmin(),450);
        }catch(error){if(message)message.textContent=error.message||'Platbu sa nepodarilo uložiť.';}
      }
      else if(action==='save-support'){
        const card=actionNode.closest('[data-support-ticket]');if(!card)return;
        const id=card.dataset.supportTicket,status=card.querySelector('[data-support-status]')?.value||'new',note=card.querySelector('[data-support-note]')?.value||'';
        try{await BlinqAuth.adminUpdateSupport(id,{status,admin_note:note});state.adminSupport=null;await loadAdminSupport(true);showStatus('Support požiadavka bola uložená.');}catch(error){showStatus(error.message||'Support požiadavku sa nepodarilo uložiť.');}
      }
      else if(action==='refresh-analytics')await loadBannerAnalytics(true);
      else if(action==='reset-user-filters'){state.adminUserFilters={q:'',plan:'all',status:'all',sort:'email'};rerenderAdmin();adminApplyUserFilters();}
      else if(action==='copy-tg-nicks'){const nicks=adminFilteredUsers().map(u=>String(u.telegram_nick||'').trim()).filter(Boolean);const text=nicks.join('\n');if(!text){showStatus('V aktuálnom filtri nie sú žiadne Telegram nicky.');return;}try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);else{const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();}showStatus(`Skopírovaných ${nicks.length} Telegram nickov.`);}catch{showStatus('Telegram nicky sa nepodarilo skopírovať.');}}
      else if(action==='refresh-analytics')await loadBannerAnalytics(true);
    };
    host.onchange=event=>{
      const t=event.target;
      const uf=adminUserFilterState();
      if(t.id==='adminUserLevelFilter'){uf.plan=t.value;adminApplyUserFilters();return;}
      if(t.id==='adminUserStatusFilter'){uf.status=t.value;adminApplyUserFilters();return;}
      if(t.id==='adminUserSort'){uf.sort=t.value;rerenderAdmin();adminApplyUserFilters();return;}
      if(t.id==='adminPlanSelect'){state.adminPlan=t.value;rerenderAdmin();return;}
      if(t.dataset.adminHeaderCount!==undefined){const count=Math.max(0,Math.min(3,Number(t.value)||0));state.ui.header_cta=state.ui.header_cta||{};state.ui.header_cta.enabled=count>0;state.ui.header_cta.slot_count=count;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHeroCount!==undefined){const count=Math.max(1,Math.min(5,Number(t.value)||1));state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.enabled=true;state.ui.hero_banner.slot_count=count;state.ui.hero_banner.auto_rotate=count>1;state.ui.hero_banner.show_dots=count>1;state.ui.hero_banner.pause_on_hover=true;[1,2,3,4,5].forEach(i=>{const slot=elements()?.[`HERO_BANNER_${i}`];if(slot){slot.content=slot.content||{};slot.content.enabled=i<=count;}});state.heroIndex=0;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHeroSeconds!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.rotation_seconds=Math.max(3,Math.min(10,Number(t.value)||6));renderHeroBanner();rerenderAdmin();return;}
      if(t.dataset.adminHeroRotate!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.auto_rotate=t.checked;renderHeroBanner();rerenderAdmin();return;}
      if(t.dataset.adminHeroDots!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.show_dots=t.checked;renderHeroBanner();rerenderAdmin();return;}
      const simpleBanner=t.closest('[data-simple-banner]');
      if(simpleBanner&&t.dataset.simpleBannerField){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id];if(item){item.content=item.content||{};item.content[t.dataset.simpleBannerField]=t.type==='checkbox'?t.checked:t.value;renderAllUiContent();rerenderAdmin();}return;}
      if(simpleBanner&&t.dataset.simpleBannerVisible){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id],plan=t.dataset.simpleBannerVisible;if(item){item.access=item.access||{};if(plan==='ALL'){accessContexts.forEach(level=>{item.access[level]=t.checked?'active':'hidden';});}else{item.access[plan]=t.checked?'active':'hidden';if(plan==='rookie')item.access.trial=item.access[plan];}renderAllUiContent();rerenderAdmin();}return;}
      if(simpleBanner&&t.dataset.simpleBannerClick){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id],plan=t.dataset.simpleBannerClick;if(item){item.click_access=item.click_access||{};if(plan==='ALL'){accessContexts.forEach(level=>{item.click_access[level]=t.checked;});}else{item.click_access[plan]=t.checked;if(plan==='rookie')item.click_access.trial=t.checked;}renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.adminRowCount){const zone=t.dataset.adminRowCount,count=Math.max(0,Math.min(4,Number(t.value)||0));state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].enabled=count>0;state.ui.content_rows[zone].slot_count=count;state.ui.content_rows[zone].preset=String(count||1);renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminRowEnabled){const zone=t.dataset.adminRowEnabled;state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].enabled=t.checked;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminRowPreset){const zone=t.dataset.adminRowPreset;state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].preset=t.value;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.dashboardGlobalField){state.ui.dashboard=state.ui.dashboard||{};let value=t.type==='checkbox'?t.checked:Number(t.value);state.ui.dashboard[t.dataset.dashboardGlobalField]=value;state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHubGlobalField){const tab=t.dataset.adminHubTab,hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};hub.tabs=hub.tabs||{};const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc[t.dataset.adminHubGlobalField]=t.type==='checkbox'?t.checked:t.value;renderAllUiContent();rerenderAdmin();showStatus(`${dailyHubTabLabel(tab)} · ${tc.enabled===false?'vypnuté':'zapnuté'} globálne.`);return;}
      if(t.dataset.adminHubField){const tab=t.dataset.adminHubTab,hub=state.ui.dashboard.daily_hub=state.ui.dashboard.daily_hub||{enabled:true,default_tab:'daily',preview_rows:10,expand_rows:20,tabs:{}};hub.tabs=hub.tabs||{};const tc=hub.tabs[tab]=hub.tabs[tab]||{enabled:true,plans:{}};tc.plans=tc.plans||{};const rule=tc.plans[state.adminPlan]=tc.plans[state.adminPlan]||{visible_rows:0,blur_remaining:true,tab_enabled:true,see_all:false};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.adminHubField==='visible_rows'&&String(value).toUpperCase()!=='ALL')value=Number(value);rule[t.dataset.adminHubField]=value;if(state.adminPlan==='rookie')tc.plans.trial=clone(rule);renderAllUiContent();rerenderAdmin();return;}
      const dashboardRow=t.closest('[data-dashboard-section]');
      if(dashboardRow&&t.dataset.dashboardField){const key=dashboardRow.dataset.dashboardSection;state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});let value=t.type==='checkbox'?t.checked:(t.dataset.dashboardField==='preview_limit'&&String(t.value).toUpperCase()!=='ALL'?Number(t.value):t.value);if(t.dataset.dashboardField==='dashboard_enabled'){const pickKeys=dashboardPickSectionKeys;cfg.dashboard_enabled=value;if(pickKeys.includes(key)&&value){const enabled=pickKeys.filter(k=>(state.ui.dashboard.sections[k]||dashboardSectionFallback[k]||{}).dashboard_enabled!==false);const max=Number(state.ui.dashboard.visible_slots||6);if(enabled.length>max){const victim=[...enabled].reverse().find(k=>k!==key);if(victim)state.ui.dashboard.sections[victim].dashboard_enabled=false;}}state.dashboardVisibility=null;}else cfg[t.dataset.dashboardField]=value;renderAllUiContent();rerenderAdmin();return;}
      if(dashboardRow&&t.dataset.dashboardPlanField){const key=dashboardRow.dataset.dashboardSection;state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});cfg.plans=cfg.plans||{};cfg.plans[state.adminPlan]=cfg.plans[state.adminPlan]||{};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.dashboardPlanField==='visible_picks'&&String(value).toUpperCase()!=='ALL')value=Number(value);cfg.plans[state.adminPlan][t.dataset.dashboardPlanField]=value;if(state.adminPlan==='rookie')cfg.plans.trial=clone(cfg.plans.rookie);renderAllUiContent();rerenderAdmin();return;}
      const matrixRow=t.closest('[data-dashboard-plan-row]');
      if(matrixRow&&t.dataset.dashboardRouteAccess!==undefined){const sectionRow=t.closest('[data-dashboard-section]'),key=sectionRow?.dataset.dashboardSection,plan=matrixRow.dataset.dashboardPlanRow,id=key?dashboardSectionConfig(key).sidebar_element:'';const item=id?elements()?.[id]:null;if(item&&plan){item.access=item.access||{};item.access[plan]=t.value;if(plan==='rookie')item.access.trial=t.value;state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();}return;}
      if(matrixRow&&t.dataset.dashboardMatrixField){const sectionRow=t.closest('[data-dashboard-section]'),key=sectionRow?.dataset.dashboardSection,plan=matrixRow.dataset.dashboardPlanRow;if(key&&plan){state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});cfg.plans=cfg.plans||{};cfg.plans[plan]=cfg.plans[plan]||{};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.dashboardMatrixField==='visible_picks'&&String(value).toUpperCase()!=='ALL')value=Number(value);if(t.dataset.dashboardMatrixField==='order')value=Math.max(1,Math.min(20,Number(value)||Number(cfg.dashboard_order||99)));cfg.plans[plan][t.dataset.dashboardMatrixField]=value;if(plan==='rookie')cfg.plans.trial=clone(cfg.plans.rookie);renderAllUiContent();rerenderAdmin();return;}}
      if(t.dataset.bannerVisiblePlan){const item=elements()?.[state.selectedElement],plan=t.dataset.bannerVisiblePlan;if(item){item.access=item.access||{};item.access[plan]=t.checked?'active':'hidden';if(plan==='rookie')item.access.trial=item.access[plan];renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.bannerClickPlan){const item=elements()?.[state.selectedElement],plan=t.dataset.bannerClickPlan;if(item){item.click_access=item.click_access||{};item.click_access[plan]=t.checked;if(plan==='rookie')item.click_access.trial=t.checked;renderAllUiContent();rerenderAdmin();}return;}
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
    const search=$('adminUserSearch');if(search)search.oninput=()=>{adminUserFilterState().q=search.value;adminApplyUserFilters();};
    adminApplyUserFilters();
    const form=$('adminUserForm');if(form)form.onsubmit=async event=>{event.preventDefault();const user=state.adminSelectedUser;if(!user)return;const message=$('adminUserMessage');message.textContent='Ukladám…';try{
      const email=String($('adminUserEmail')?.value||'').trim(),telegram_nick=String($('adminUserTelegram')?.value||'').trim();if(!email)throw new Error('E-mail je povinný.');
      let updated=await BlinqAuth.adminUpdateUserProfile(user.id,{email,telegram_nick});
      const existingAdmin=String(user.role||'').toLowerCase()==='admin'||String(user.plan||'').toLowerCase()==='admin',plan=String($('adminUserPlan')?.value||''),rawExpiry=String($('adminUserExpires')?.value||'');
      let role=existingAdmin?'admin':'user',status='expired',expires_at=null,accessPlan=existingAdmin?'':plan;
      if(existingAdmin){status='active';}
      else if(plan==='goat'){status='lifetime';expires_at=null;}
      else if(plan){if(!rawExpiry)throw new Error('Pre tento level nastav platnosť do.');expires_at=new Date(rawExpiry).toISOString();status=new Date(expires_at).getTime()>Date.now()?'active':'expired';}
      updated=await BlinqAuth.adminUpdateAccess(user.id,{role,plan:accessPlan,status,expires_at});
      state.adminUsers=(state.adminUsers||[]).map(row=>row.id===updated.id?updated:row);state.adminSelectedUser=updated;message.textContent='Účet bol uložený.';setTimeout(()=>{rerenderAdmin();adminApplyUserFilters();},300);
    }catch(error){message.textContent=error.message||'Účet sa nepodarilo uložiť.';}};

    const insightForm=$('adminInsightForm');if(insightForm)insightForm.onsubmit=async event=>{event.preventDefault();const message=$('adminInsightMessage');if(message)message.textContent='Publikujem…';try{const levels=[...insightForm.querySelectorAll('input[name="insight_level"]:checked')].map(node=>node.value);if(!levels.length)throw new Error('Vyber aspoň jeden level.');const payload={title:$('adminInsightTitle').value.trim(),body:$('adminInsightBody').value.trim(),type:$('adminInsightType').value,priority:$('adminInsightPriority').value,levels,link:$('adminInsightLink').value.trim(),link_label:$('adminInsightLinkLabel').value.trim(),match_id:$('adminInsightMatchId').value.trim(),active:Boolean($('adminInsightActive').checked),pinned:Boolean($('adminInsightPinned').checked),active_from:$('adminInsightFrom').value?new Date($('adminInsightFrom').value).toISOString():'',active_until:$('adminInsightUntil').value?new Date($('adminInsightUntil').value).toISOString():''};if(state.adminInsightEditingId)await BlinqAuth.adminUpdateInsight(state.adminInsightEditingId,payload);else await BlinqAuth.adminCreateInsight(payload);state.adminInsightEditingId='';state.adminInsights=null;await loadAdminInsights(true);await loadInsights(true);showStatus('BlinQ Insight bol publikovaný.');}catch(error){if(message)message.textContent=error.message;}};
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
  function renderPlanCardsForAccount(){
    const current=accountPlan();
    const plans=Object.entries(state.ui?.plans||{}).filter(([id,p])=>!['trial','expired'].includes(id)&&p.enabled!==false).sort((a,b)=>Number(a[1]?.order||99)-Number(b[1]?.order||99));
    return `<div class="account-plan-grid">${plans.map(([id,p])=>{const url=safeExternalUrl(p.url),active=current===id,restricted=Boolean(p.invite_only||p.verified_only),title=p.card_title||p.label||id.toUpperCase();let action='';if(active)action='<span class="membership-current">AKTUÁLNY</span>';else if(restricted){const invite=safeExternalUrl(p.invite_url||p.url);action=invite?`<a class="btn btn-ghost membership-cta invite-only" href="${escapeHtml(invite)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Požiadať o prístup')} →</a>`:`<button class="btn btn-ghost membership-cta invite-only" type="button" data-goat-request>${escapeHtml(p.cta_label||'Požiadať o prístup')}</button>`;}else if(url)action=`<a class="btn btn-primary membership-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Upgrade')} →</a>`;else action=`<button class="btn btn-primary membership-cta" type="button" data-plan-link-missing="${escapeHtml(id)}">${escapeHtml(p.cta_label||'Upgrade')} →</button>`;return `<article class="membership-card plan-${escapeHtml(id)}${active?' current-plan':''}${restricted?' restricted-plan':''}">${planAvatarPairHtml(id,p)}<div class="membership-card-copy"><small>${escapeHtml(p.label||id.toUpperCase())}</small><strong>${escapeHtml(title)}</strong><p>${escapeHtml(p.description||p.note||'')}</p></div>${restricted?'<span class="membership-badge">INVITE ONLY</span>':''}${action}</article>`}).join('')}</div>`;
  }
  function renderAccountModal(){
    const a=state.feed?.account||{},status=String(a.status||'expired').toLowerCase(),plan=accountPlan(),planCfg=state.ui?.plans?.[plan]||{},planLabel=a.plan_label||planCfg.label||plan;
    const verified=a.email_verified===true;
    const expiry=status==='lifetime'?'Doživotne':a.expires_at?`${remainingLabel(a.expires_at)} zostáva`:(status==='active'?'Bez expirácie':'Bez aktívneho prístupu');
    const tg=String(a.telegram_nick||'').trim();
    const plans=membershipHierarchy.filter(id=>state.ui?.plans?.[id]?.enabled!==false).map(id=>{
      const p=state.ui.plans[id]||{},url=safeExternalUrl(p.url||''),invite=safeExternalUrl(p.invite_url||p.url||''),current=id===plan;
      const action=current
        ?'<span class="account-plan-current">AKTUÁLNY</span>'
        :(p.invite_only?(invite?`<a class="account-plan-upgrade" href="${escapeHtml(invite)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Upgrade')} →</a>`:`<button class="account-plan-upgrade" type="button" data-goat-request>${escapeHtml(p.cta_label||'Upgrade')} →</button>`):(url?`<a class="account-plan-upgrade" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Upgrade')} →</a>`:`<button class="account-plan-upgrade" type="button" data-plan-link-missing="${escapeHtml(id)}">${escapeHtml(p.cta_label||'Upgrade')} →</button>`));
      return `<article class="account-modal-plan plan-${escapeHtml(id)}${current?' is-current':''}">${planAvatarPairHtml(id,p)}<div class="account-modal-plan-copy"><small>${escapeHtml(id.toUpperCase())}</small><strong>${escapeHtml(p.label||id.toUpperCase())}</strong><span>${escapeHtml(p.description||p.note||'')}</span></div>${action}</article>`;
    }).join('');
    return `<div class="account-modal-head"><div><small>BLINQ ÚČET</small><h2 id="accountDialogTitle">Tvoj BlinQ účet</h2><p>Spravuj profil, prístup a členskú úroveň na jednom mieste.</p></div></div>
      <form id="accountModalProfileForm" class="account-modal-main-card account-modal-main-card-v3">
        <div class="account-modal-access"><div class="account-modal-avatar" id="accountModalAvatar">${escapeHtml(accountAvatarFallback(a))}</div><div class="account-access-copy"><small>AKTUÁLNY PRÍSTUP</small><strong>${escapeHtml(planLabel)}</strong><span class="account-access-status"><i></i>${escapeHtml(status==='lifetime'?'Aktívny · doživotne':status==='active'?'Aktívny':expiry)}</span></div></div>
        <div class="account-profile-facts account-profile-facts-v3"><span class="account-email-fact"><small>Registrovaný e-mail</small><strong>${escapeHtml(a.email||'—')}</strong><b class="account-verified ${verified?'is-verified':'needs-verification'}">${verified?'✓ E-mail overený':'! E-mail neoverený'}</b></span><span><small>Telegram nick</small><strong>${escapeHtml(tg||'Nenastavený')}</strong></span><span><small>Úroveň</small><strong>${escapeHtml(planLabel)}</strong></span><span><small>Platnosť prístupu</small><strong>${escapeHtml(expiry)}</strong></span></div>
        <div class="account-profile-editor"><div class="account-profile-editor-head"><small>UPRAVIŤ PROFIL</small><span>${verified?'Overený účet':'Overenie čaká'}</span></div><label class="account-inline-field account-inline-telegram"><span>${adminTelegramIcon()} Telegram nick</span><input id="accountModalTelegram" maxlength="33" value="${escapeHtml(tg)}" placeholder="@username"></label><div class="account-inline-field account-inline-avatar"><span>Avatar</span><div class="avatar-sex-toggle" role="group" aria-label="Avatar"><button type="button" data-avatar-variant="m" class="${a.avatar_variant==='w'?'':'is-active'}" aria-label="Mužský avatar" aria-pressed="${a.avatar_variant==='w'?'false':'true'}">♂</button><button type="button" data-avatar-variant="w" class="${a.avatar_variant==='w'?'is-active':''}" aria-label="Ženský avatar" aria-pressed="${a.avatar_variant==='w'?'true':'false'}">♀</button></div><input id="accountModalAvatarVariant" type="hidden" value="${a.avatar_variant==='w'?'w':'m'}"></div><button class="btn btn-primary account-profile-save" type="submit">Uložiť profil</button><p id="accountModalMessage" class="form-message account-inline-message"></p></div>
      </form>
      <div class="account-modal-plans"><div class="account-modal-section-title"><div><small>BLINQ ČLENSTVO</small><h3>Vyber si svoju úroveň</h3></div><span>Každá úroveň prináša iný rozsah dát, funkcií a prístupu.</span></div>${plans}</div>`;
  }
  function openAccountDialog(){
    const d=$('accountDialog'),host=$('accountDialogContent');if(!d||!host)return;host.innerHTML=renderAccountModal();setAccountAvatar($('accountModalAvatar'),state.feed?.account||{});
    const form=$('accountModalProfileForm');if(form)form.onsubmit=async e=>{e.preventDefault();const m=$('accountModalMessage');m.textContent='Ukladám…';try{await BlinqAuth.update({data:{telegram_nick:$('accountModalTelegram').value.trim(),blinq_avatar_variant:$('accountModalAvatarVariant').value}});m.textContent='Profil uložený.';await loadFeed(false);openAccountDialog();}catch(err){m.textContent=err.message;}};
    host.querySelectorAll('[data-avatar-variant]').forEach(button=>button.onclick=()=>{const value=button.dataset.avatarVariant||'m',input=$('accountModalAvatarVariant');if(input)input.value=value;host.querySelectorAll('[data-avatar-variant]').forEach(node=>{const active=node===button;node.classList.toggle('is-active',active);node.setAttribute('aria-pressed',active?'true':'false');});setAccountAvatar($('accountModalAvatar'),{...(state.feed?.account||{}),avatar_variant:value});});
    host.querySelectorAll('[data-plan-link-missing]').forEach(button=>button.onclick=()=>showStatus(`Doplň odkaz pre ${button.dataset.planLinkMissing?.toUpperCase()||'plán'} v web/config/membership-tiers.json.`));
    const reset=$('accountModalPassword');if(reset)reset.onclick=async()=>{try{await BlinqAuth.reset(state.feed?.account?.email||'');showStatus('E-mail na obnovu hesla bol odoslaný.');}catch(err){showStatus(err.message);}};
    const out=$('accountModalSignOut');if(out)out.onclick=()=>{d.close();signOutCurrentSession();};
    if(!d.open)d.showModal();
  }
  function renderAccountPage(){
    const a=state.feed?.account||{},status=String(a.status||'expired').toLowerCase(),plan=accountPlan(),planLabel=a.plan_label||state.ui?.plans?.[plan]?.label||plan;
    const pushEligible=Boolean(a.is_admin||String(a.role||'').toLowerCase()==='admin'||(['elite','legend','goat'].includes(plan)&&['active','lifetime'].includes(status)));
    const expiry=status==='lifetime'?publicText('Lifetime access'):a.expires_at?`${remainingLabel(a.expires_at)} ${locale==='cz'?'zbývá':'zostáva'}`:(status==='active'?publicText('Active'):publicText('No active access'));
    const verified=a.email_verified===true;
    return `<section class="account-overview account-overview-v676">
      <article class="account-profile-card account-profile-card-v676"><div class="account-profile-head"><span class="avatar account-page-avatar" id="accountPageAvatar">${escapeHtml(accountAvatarFallback(a))}</span><div><span class="account-card-kicker">BLINQ ÚČET</span><h2>${escapeHtml(a.email||'BlinQ účet')}</h2><p>${escapeHtml(a.telegram_nick||'Telegram nickname zatiaľ nie je nastavený')}</p></div><span class="account-verified ${verified?'is-verified':'needs-verification'}">${escapeHtml(publicText(verified?'✓ Email verified':'! Email not verified'))}</span></div>
      <form id="accountProfileForm" class="account-profile-form account-profile-form-v676"><label><span class="telegram-label">${adminTelegramIcon()} Telegram</span><input id="accountTelegramNick" maxlength="33" value="${escapeHtml(a.telegram_nick||'')}" placeholder="@username"></label><div class="account-page-avatar-choice"><span>Avatar</span><div class="avatar-sex-toggle" role="group" aria-label="Avatar"><button type="button" data-avatar-page-variant="m" class="${a.avatar_variant==='w'?'':'is-active'}" aria-label="Mužský avatar" aria-pressed="${a.avatar_variant==='w'?'false':'true'}">♂</button><button type="button" data-avatar-page-variant="w" class="${a.avatar_variant==='w'?'is-active':''}" aria-label="Ženský avatar" aria-pressed="${a.avatar_variant==='w'?'true':'false'}">♀</button></div><input id="accountAvatarVariant" type="hidden" value="${a.avatar_variant==='w'?'w':'m'}"></div><button class="btn btn-primary" type="submit">Uložiť profil</button><p class="form-message" id="accountProfileMessage"></p></form></article>
      <article class="account-access-card"><div class="account-access-top"><span class="account-card-kicker">AKTUÁLNY PRÍSTUP</span>${planAvatarHtml(plan,state.ui?.plans?.[plan]||{})}</div><h2>${escapeHtml(planLabel)}</h2><p class="account-access-status">${escapeHtml(status==='trial'?'Rookie Trial':status==='lifetime'?'Doživotný':status==='active'?'Aktívny':'Expirovaný')}</p><div class="account-facts"><span><small>Prístup</small><strong>${escapeHtml(expiry)}</strong></span><span><small>Člen od</small><strong>${escapeHtml(a.created_at?fmtDate(a.created_at):'—')}</strong></span><span><small>Zabezpečenie</small><strong>${verified?'E-mail overený':'Vyžaduje overenie'}</strong></span></div><div class="account-access-actions"><button class="btn btn-ghost" id="accountPasswordReset" type="button">Obnoviť heslo</button><button class="btn btn-ghost account-signout" id="accountSignOut" type="button">Odhlásiť sa</button></div></article>
      <article class="account-push-card${pushEligible?'':' is-locked'}"><div><span class="account-card-kicker">LIVE & INFO PUSH</span><h2>Okamžité upozornenia</h2><p>${pushEligible?'Dostaneš systémovú notifikáciu aj keď BlinQ práve nemáš otvorený.':'Browser push je súčasť ELITE, Legend a GOAT.'}</p></div><div class="account-push-actions"><button class="btn ${pushEligible?'btn-primary':'btn-ghost'}" id="accountPushToggle" type="button" ${pushEligible?'':'disabled'}>Skontrolovať push</button><span id="accountPushStatus">${pushEligible?'Kontrolujem stav…':'Dostupné od ELITE'}</span></div></article>
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
      if(!cfg?.eligible){button.disabled=true;button.textContent='ELITE+';status.textContent='Dostupné od ELITE.';return;}
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
    document.querySelectorAll('[data-plan-link-missing]').forEach(button=>button.onclick=()=>{const message=$('accountProfileMessage');if(message)message.textContent=`Doplň odkaz pre ${button.dataset.planLinkMissing?.toUpperCase()||'plán'} v web/config/membership-tiers.json.`;});
    const reset=$('accountPasswordReset');if(reset)reset.onclick=async()=>{const message=$('accountProfileMessage');message.textContent=publicText('Sending recovery email…');try{await BlinqAuth.reset(a.email);message.textContent=publicText('Password reset email sent.');}catch(error){message.textContent=error.message;}};
    const logout=$('accountSignOut');if(logout)logout.onclick=signOutCurrentSession;
    const pushToggle=$('accountPushToggle');if(pushToggle&&!pushToggle.disabled){pushToggle.onclick=toggleBrowserPush;refreshPushControl();}
    document.querySelectorAll('[data-goat-request]').forEach(button=>button.onclick=()=>{const nick=String(state.feed?.account?.telegram_nick||'').trim();const input=$('accountTelegramNick');const message=$('accountProfileMessage');if(!nick){if(message)message.textContent='Add your Telegram nick first, save the profile, then request GOAT access.';input?.focus();return;}if(message)message.textContent=`GOAT is invite-only. Your Telegram ${nick.startsWith('@')?nick:`@${nick}`} is saved; configure the GOAT invite contact URL in Admin → Membership to make this button open the request chat.`;});
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
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Market</th><th>Projection pick</th><th>Projection</th><th>Baseline</th><th>Gap</th><th>Score</th><th>Data</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">Projection only. Structured historical set/game scores are used; bookmaker odds, edge and ROI stay blank until that market layer is separately calibrated and validated.</div>`;
  }
  function genericTable(rows,key){
    if(key==='ace'&&rows.some(row=>row?.price_status==='projection_only'))return aceProjectionTable(rows);
    if(key==='sg'&&rows.some(row=>row?.price_status==='projection_only'))return sgProjectionTable(rows);
    if(!rows.length)return '<div class="state-card">No published data are available for this section yet.</div>';
    if(key==='top_daily'){const body=rows.map(row=>{const p1=row?.p1||row?.player1?.name||row?.player1_name||'Player 1',p2=row?.p2||row?.player2?.name||row?.player2_name||'Player 2';const probability=marketProbability(row),depth=Number(row?.data_depth),q=row?.quality||{},s1=Number(q?.player1?.surface_matches),s2=Number(q?.player2?.surface_matches),m1=Number(q?.player1?.matches),m2=Number(q?.player2?.matches),odds=Number(row?.odds),pick=row?.pick||row?.selection||row?.prediction||'—';return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(pick)}</td><td>${probability==null?'—':pct(probability)}</td><td>${Number.isFinite(depth)?pct(depth):'—'}</td><td>${Number.isFinite(s1)&&Number.isFinite(s2)?`${s1}/${s2}`:'—'}</td><td>${Number.isFinite(m1)&&Number.isFinite(m2)?`${m1}/${m2}`:'—'}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td></tr>`}).join('');return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Prediction</th><th>Probability</th><th>Data depth</th><th>Surface sample</th><th>Overall sample</th><th>Odds</th></tr></thead><tbody>${body}</tbody></table></div><div class="results-limit-note">TOP predictions are confidence-first. Elo, surface Elo, H2H and form are already represented inside model probability; edge/EV do not determine this ranking.</div>`;}
    const body=rows.map(row=>{
      const p1=row?.p1||row?.player1?.name||row?.player1_name||'Player 1',p2=row?.p2||row?.player2?.name||row?.player2_name||'Player 2';
      const rawProb=row?.probability!=null?Number(row.probability):marketProbability(row); const probability=Number.isFinite(rawProb)?(rawProb>1?rawProb/100:rawProb):null; const pick=row?.pick||row?.selection||row?.prediction||'—';
      const odds=Number(row?.odds),edge=Number(row?.edge),ev=Number(row?.expected_value);
      return `<tr><td>${escapeHtml(fmtDate(row?.date||row?.scheduled_at))}<small>${escapeHtml(fmtTime(row?.date||row?.scheduled_at))}</small></td><td><strong>${escapeHtml(p1)}</strong><small>vs ${escapeHtml(p2)}</small></td><td>${escapeHtml(row?.tournament||row?.competition||'—')}</td><td>${escapeHtml(pick)}</td><td>${probability==null?'—':pct(probability)}</td><td>${Number.isFinite(odds)?odds.toFixed(2):'—'}</td><td>${Number.isFinite(edge)?`${edge>0?'+':''}${(edge*(Math.abs(edge)<=1?100:1)).toFixed(1)} pp`:'—'}</td><td>${Number.isFinite(ev)?`${ev>0?'+':''}${(ev*(Math.abs(ev)<=1?100:1)).toFixed(1)}%`:'—'}</td></tr>`;
    }).join('');
    return `<div class="admin-table-wrap picks-table-wrap"><table class="admin-analytics-table picks-table"><thead><tr><th>Date</th><th>Match</th><th>Tournament</th><th>Prediction</th><th>Probability</th><th>Odds</th><th>Model Edge</th><th>EV</th></tr></thead><tbody>${body}</tbody></table></div>`;
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
    const rows=filteredResults(),category=state.resultsFilters?.category||'all',m=localResultMetrics(rows,category);
    if(category==='ace'||category==='double_faults'){
      return metricCards([[lcopy('Result','Výsledok','Výsledek'),`${m.wins}-${m.losses}`,lcopy('HIT - MISS','HIT - MISS','HIT - MISS')],[publicText('Hit rate'),m.hit==null?'—':pct(m.hit),lcopy('settled ESA projection sample','vyhodnotená vzorka ESA projekcií','vyhodnocený vzorek ESA projekcí')],[lcopy('Projection type','Typ projekcie','Typ projekce'),category==='ace'?lcopy('ACES','ESÁ','ESA'):lcopy('DOUBLE FAULTS','DVOJCHYBY','DVOJCHYBY'),lcopy('No invented odds or ROI','Bez vymysleného kurzu a ROI','Bez vymyšleného kurzu a ROI')],[publicText('Sample'),String(m.sample),lcopy('published projections','publikované projekcie','publikované projekce')]]);
    }
    return metricCards([[publicText('Record'),`${m.wins}-${m.losses}`,lcopy('wins - losses','výhry - prehry','výhry - prohry')],[publicText('Hit rate'),m.hit==null?'—':pct(m.hit),lcopy('filtered settled sample','filtrovaná vyhodnotená vzorka','filtrovaný vyhodnocený vzorek')],[publicText('Avg Odds'),m.avgOdds==null?'—':m.avgOdds.toFixed(2),m.oddsSample?lcopy(`${m.oddsSample} odds-backed picks`,`${m.oddsSample} predikcií s kurzom`,`${m.oddsSample} predikcí s kurzem`):publicText('no issued odds')],['ROI',m.roi==null?'—':pct(m.roi),publicText('flat 1u on issued odds')],[publicText('Units'),m.oddsSample?`${m.profit>=0?'+':''}${m.profit.toFixed(2)}u`:'—',publicText('profit · flat 1u stake')],[publicText('Sample'),String(m.sample),publicText('settled published rows')]]);
  }

  function primeDetailCard(m,index=0){
    const photo1=safePhotoUrl(m.p1Photo)||playerFallbackUrl(m.tour),photo2=safePhotoUrl(m.p2Photo)||playerFallbackUrl(m.tour);
    const avatar=(src,name)=>src?`<span class="player-avatar has-photo"><img src="${escapeHtml(src)}" alt="" loading="lazy"></span>`:`<span class="player-avatar">${escapeHtml(initials(name))}</span>`;
    const metrics=[[publicText('Odds'),Number.isFinite(m.odds)?m.odds.toFixed(2):'—'],[lcopy('Edge','Výhoda','Výhoda'),Number.isFinite(m.edge)?`${m.edge>=0?'+':''}${(m.edge*100).toFixed(1)} pp`:'—'],['EV',Number.isFinite(m.expectedValue)?`${m.expectedValue>=0?'+':''}${(m.expectedValue*100).toFixed(1)}%`:'—']];
    const metricHtml=metrics.map(([label,value])=>{const raw=String(value);const tone=raw.trim().startsWith('+')?' metric-positive':raw.trim().startsWith('-')?' metric-negative':'';return `<span class="card-metric${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(raw)}</strong></span>`}).join('');
    return `<article class="prediction-card featured detail-pick-card match-card-v3"><div class="card-meta match-card-meta"><span class="tour">${escapeHtml(m.tour)} ${escapeHtml(m.tournament)}</span><span class="time">${escapeHtml(fmtTime(m.date))}</span><span class="surface">${escapeHtml(String(m.surface||'').replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row match-players-row"><div class="player">${avatar(photo1,m.p1)}<strong class="player-name">${escapeHtml(m.p1)}</strong></div><div class="vs match-vs">VS</div><div class="player">${avatar(photo2,m.p2)}<strong class="player-name">${escapeHtml(m.p2)}</strong></div></div><div class="pick-row match-pick-row"><div class="pick-copy"><small>${escapeHtml(lcopy('BlinQ prediction','Naša predikcia','Naše predikce'))}</small><strong class="pick-name">${escapeHtml(m.pick)}</strong></div><div class="pick-score"><div class="probability">${pct(m.probability)}</div><span class="confidence ${escapeHtml(m.confidence)}">${escapeHtml(confidenceLabel(m.confidence))}</span></div></div><div class="card-metrics-bar match-kpi-bar">${metricHtml}</div></article>`;
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
    const support=route==='support'?renderSupportForm():'';
    const cookieSettings=route==='cookies'?`<div class="cookie-settings-card"><strong>${escapeHtml(lcopy('Cookie preferences','Nastavenia cookies','Nastavení cookies'))}</strong><p>${escapeHtml(lcopy('You can change optional analytics consent at any time.','Súhlas s nepovinnou analytikou môžete kedykoľvek zmeniť.','Souhlas s nepovinnou analytikou můžete kdykoli změnit.'))}</p><div><button class="btn btn-ghost" type="button" data-cookie-choice="essential">${escapeHtml(lcopy('Essential only','Iba nevyhnutné','Pouze nezbytné'))}</button><button class="btn btn-primary" type="button" data-cookie-choice="analytics">${escapeHtml(lcopy('Allow analytics','Povoliť analytiku','Povolit analytiku'))}</button></div></div>`:'';
    return `<section class="content-page"><header class="content-page-hero"><span>${escapeHtml(page.eyebrow||'BLINQ')}</span><h2>${escapeHtml(page.title||'')}</h2><p>${escapeHtml(page.subtitle||'')}</p>${legalMeta}</header>${sections?`<div class="content-section-grid">${sections}</div>`:''}${faqs?`<div class="content-faq-list">${faqs}</div>`:''}${cookieSettings}${support}</section>`;
  }
  function supportCategoryOptions(selected=''){
    return (state.siteContent?.support?.categories||[]).map(row=>{const label=row?.[contentLocale()]||row?.sk||row?.en||row?.id;return `<option value="${escapeHtml(row.id||'other')}"${String(selected)===String(row.id)?' selected':''}>${escapeHtml(label||'')}</option>`;}).join('');
  }
  function supportFormCopy(){
    const rows=state.siteContent?.support?.form_copy||{};return rows?.[contentLocale()]||rows?.sk||{};
  }
  function renderSupportForm(){
    const account=state.feed?.account||{};
    const email=String(account.email||'');
    const copy=supportFormCopy();
    return `<div class="support-panel"><div class="support-panel-copy"><span>${escapeHtml(copy.eyebrow||'BLINQ SUPPORT')}</span><h3>${escapeHtml(copy.title||lcopy('Send us a message','Napíšte nám','Napište nám'))}</h3><p>${escapeHtml(copy.intro||lcopy('We handle support manually and keep the request linked to your account when you are signed in.','Podporu riešime manuálne a pri prihlásenom účte sa požiadavka automaticky spojí s vaším profilom.','Podporu řešíme manuálně a u přihlášeného účtu se požadavek automaticky spojí s vaším profilem.'))}</p></div><form id="supportForm" class="support-form"><div class="support-form-grid"><label>${escapeHtml(copy.category||lcopy('Category','Kategória','Kategorie'))}<select id="supportCategory" required>${supportCategoryOptions('technical')}</select></label><label>${escapeHtml(copy.email||'E-mail')}<input id="supportEmail" type="email" required value="${escapeHtml(email)}" ${email?'readonly':''} placeholder="name@example.com"></label><label class="span-2">${escapeHtml(copy.subject||lcopy('Subject','Predmet','Předmět'))}<input id="supportSubject" maxlength="160" placeholder="${escapeHtml(copy.subject_placeholder||lcopy('Short description','Krátky popis','Krátký popis'))}"></label><label class="span-2">${escapeHtml(copy.message||lcopy('Message','Správa','Zpráva'))}<textarea id="supportMessage" minlength="8" maxlength="5000" rows="7" required placeholder="${escapeHtml(copy.message_placeholder||lcopy('Describe what happened and what you expected.','Popíšte, čo sa stalo a čo ste očakávali.','Popište, co se stalo a co jste očekávali.'))}"></textarea></label></div><div class="support-form-actions"><button class="btn btn-primary" type="submit">${escapeHtml(copy.send||lcopy('Send request','Odoslať požiadavku','Odeslat požadavek'))}</button><span id="supportFormStatus" role="status"></span></div><small>${escapeHtml(copy.privacy||lcopy('Never send passwords or full payment-card details.','Nikdy neposielajte heslá ani celé údaje platobnej karty.','Nikdy neposílejte hesla ani celé údaje platební karty.'))}</small></form></div>`;
  }
  function wireSupportForm(){
    const form=$('supportForm');if(!form||form.dataset.wired==='1')return;form.dataset.wired='1';
    form.addEventListener('submit',async event=>{event.preventDefault();if(state.supportSubmitting)return;const status=$('supportFormStatus');state.supportSubmitting=true;status.textContent=supportFormCopy().sending||lcopy('Sending…','Odosielam…','Odesílám…');try{const result=await BlinqAuth.supportSubmit({category:$('supportCategory').value,email:$('supportEmail').value.trim(),subject:$('supportSubject').value.trim(),message:$('supportMessage').value.trim()});const ticket=result?.ticket?.ticket_id||'';status.textContent=ticket?lcopy(`Sent · ${ticket}`,`Odoslané · ${ticket}`,`Odesláno · ${ticket}`):lcopy('Sent','Odoslané','Odesláno');$('supportMessage').value='';$('supportSubject').value='';}catch(error){const code=String(error.code||'').toLowerCase();status.textContent=code==='support_storage_unavailable'?lcopy('Support storage is temporarily unavailable.','Support úložisko je dočasne nedostupné.','Support úložiště je dočasně nedostupné.'):(error.message||lcopy('Could not send the request.','Požiadavku sa nepodarilo odoslať.','Požadavek se nepodařilo odeslat.'));}finally{state.supportSubmitting=false;}});
  }
  function renderRoute(route){
    const host=$('routePanel'),feed=state.feed,p=feed.performance||{},history=feed.history||{},report=feed.model?.report||{}; let body='';
    if(route==='admin'){host.innerHTML=renderAdminRoute();wireAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='analytics')loadBannerAnalytics();if(state.adminTab==='support')loadAdminSupport();if(state.adminTab==='system')loadAdminDiagnostics();if(state.adminTab==='audit')loadAdminAudit();return;}
    if(route==='prime'){
      const r=state.ui?.market_rules?.prime||{};
      const desc=lcopy(`Accuracy first · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · depth ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · surface ${Number(r.min_surface_matches||5)}+/player · preferred odds ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)}, no hard odds band · reject materially negative EV.`,`Presnosť na prvom mieste · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · hĺbka dát ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasov/hráč · preferovaný kurz ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)} bez pevného pásma · výrazne negatívne EV sa odmieta.`,`Přesnost na prvním místě · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · hloubka dat ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasů/hráč · preferovaný kurz ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)} bez pevného pásma · výrazně negativní EV se odmítá.`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Short Odds rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(primeTableRows(),'prime')}`;
    }
    else if(route==='top_daily'){
      const r=state.ui?.market_rules?.top_daily||{},day=state.feed?.market_selection?.odds_report?.betting_day||'current';
      const desc=lcopy(`BlinQ publication day ${day} · CORE starts at 68% / 1.50. If fewer than 5 TOP picks remain after Value priority, thresholds relax stepwise only until 5 qualify, with a hard floor of 60% / 1.45. Data-depth and surface guardrails stay active.`,`Publikačný deň BlinQ ${day} · CORE začína na 68 % / 1,50. Ak po priorite Value ostane menej ako 5 TOP pickov, hranice sa uvoľňujú po krokoch iba dovtedy, kým sa nekvalifikuje 5 pickov; absolútne minimum je 60 % / 1,45. Pravidlá hĺbky dát a povrchu zostávajú aktívne.`,`Publikační den BlinQ ${day} · CORE začíná na 68 % / 1,50. Pokud po prioritě Value zůstane méně než 5 TOP picků, hranice se uvolňují po krocích jen do chvíle, kdy se kvalifikuje 5 picků; absolutní minimum je 60 % / 1,45. Pravidla hloubky dat a povrchu zůstávají aktivní.`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('TOP Predictions rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(marketRows('top_daily'),'top_daily')}`;
    }
    else if(route==='value'){
      const r=state.ui?.market_rules?.value||{},tiers=Array.isArray(r.fallback_tiers)?r.fallback_tiers.length:0;
      const desc=lcopy(`EV-first selection. Primary target: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · odds ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+. ${tiers?`${tiers} configured fallback tiers may widen market thresholds while preserving model/data guardrails.`:'No fallback tier is configured.'}`,`Výber podľa EV. Hlavný cieľ: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · kurz ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+. ${tiers?`${tiers} nastavených fallback úrovní môže rozšíriť trhové limity, pričom ostávajú zachované pravidlá modelu a dát.`:'Fallback úroveň nie je nastavená.'}`,`Výběr podle EV. Hlavní cíl: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · kurz ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+. ${tiers?`${tiers} nastavených fallback úrovní může rozšířit tržní limity při zachování pravidel modelu a dat.`:'Fallback úroveň není nastavena.'}`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Value rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(marketRows('value'),'value')}`;
    }
    else if(route==='ace') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Aces / Double Faults'))}</strong><span>${escapeHtml(lcopy(`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time count projections from stored event statistics. Projection score is not a calibrated win probability; odds/ROI stay blank until a verified price source exists.`,`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time projekcií z uložených štatistík zápasov. Skóre projekcie nie je kalibrovaná pravdepodobnosť výhry; kurz/ROI ostávajú prázdne, kým nebude dostupný overený zdroj kurzov.`,`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time projekcí z uložených statistik zápasů. Skóre projekce není kalibrovaná pravděpodobnost výhry; kurz/ROI zůstávají prázdné, dokud nebude dostupný ověřený zdroj kurzů.`))}</span></div>${detailCards(marketRows('ace'),'ace')}`;
    else if(route==='sg') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Sets / Games'))}</strong><span>${escapeHtml(lcopy('Point-in-time projections from structured historical set/game scores. Sets use long-match probability; Games use projected total versus the ATP/WTA best-of baseline. No odds/ROI are inferred yet.','Point-in-time projekcie zo štruktúrovaných historických skóre setov/hier. Sety používajú pravdepodobnosť dlhého zápasu; hry používajú projektovaný celkový počet oproti ATP/WTA baseline. Kurz/ROI sa zatiaľ neodvodzujú.','Point-in-time projekce ze strukturovaných historických skóre setů/her. Sety používají pravděpodobnost dlouhého zápasu; hry používají projektovaný celkový počet oproti ATP/WTA baseline. Kurz/ROI se zatím neodvozují.'))}</span></div>${detailCards(marketRows('sg'),'sg')}`;
    else if(route==='doubles') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Doubles model'))}</strong><span>${escapeHtml(lcopy('Separate pair/team model only. Pair identity, pair history, individual strength, surface form and pair chemistry stay isolated from singles probabilities.','Iba samostatný model dvojíc/tímov. Identita dvojice, spoločná história, individuálna sila, forma na povrchu a súhra zostávajú oddelené od pravdepodobností dvojhry.','Pouze samostatný model dvojic/týmů. Identita dvojice, společná historie, individuální síla, forma na povrchu a souhra zůstávají oddělené od pravděpodobností dvouhry.'))}</span></div>${detailCards(marketRows('doubles'),'doubles')}`;
    else if(route==='results') body=renderResultsFilters()+resultsSummary()+`<div class="route-sub results-section-head"><div><h3>${escapeHtml(publicText('Vyhodnotené predikcie'))}</h3><p>${escapeHtml(lcopy('Only successfully published pre-match records are graded. ROI uses the odds snapshot that was actually published and a flat 1u stake.','Vyhodnocujú sa iba úspešne publikované pre-match záznamy. ROI používa kurz, ktorý bol skutočne publikovaný, a rovnú stávku 1u.','Vyhodnocují se pouze úspěšně publikované pre-match záznamy. ROI používá kurz, který byl skutečně publikován, a rovnou sázku 1u.'))}</p></div>${renderResults()}</div>`;
    else if(route==='tournaments'){const names=[...new Set((feed.upcoming||[]).map(x=>x.tournament).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):escapeHtml(publicText('No upcoming tournament coverage is currently published.'))}</div>`;}
    else if(route==='players'){const names=[...new Set((feed.upcoming||[]).flatMap(x=>[x.player1?.name,x.player2?.name]).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):escapeHtml(publicText('No upcoming players are currently published.'))}</div>`;}
    else if(route==='stats') body=metricCards([[publicText('Vyhodnotené predikcie'),String(p.n??0),publicText('Published and scored')],[publicText('Accuracy'),p.accuracy!=null?pct(p.accuracy):'—',publicText('Observed results')],['Log loss',number(p.log_loss),publicText('Lower is better')],[publicText('Brier score'),number(p.brier_score),publicText('Probability quality')]])+`<div class="route-sub"><h3>${escapeHtml(publicText('Results'))}</h3>${renderResults()}</div>`;
    else if(route==='model'||route==='backtests'){const h=report.holdout||{},delta=report.delta_vs_elo||{};body=metricCards([[publicText('Model'),String(feed.model?.version||'—'),publicText('Production artifact')],['Holdout n',String(h.n??'—'),publicText('Chronological holdout')],['Holdout úspešnosť',h.accuracy!=null?pct(h.accuracy):'—',publicText('Evaluation report')],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—',publicText('Negative is better')]])+`<div class="route-sub static-copy"><h3>${escapeHtml(publicText('Data window'))}</h3><p>${escapeHtml(history.start?fmtDate(history.start):'—')} → ${escapeHtml(history.end?fmtDate(history.end):'—')} · ${escapeHtml(lcopy(`${history.matches??'—'} historical matches in the current serving metadata.`,`${history.matches??'—'} historických zápasov v aktuálnych metadátach.`,`${history.matches??'—'} historických zápasů v aktuálních metadatech.`))}</p><p>${escapeHtml(lcopy('No result here is presented as a guarantee. Holdout metrics describe a specific historical evaluation period.','Žiadny výsledok tu nie je prezentovaný ako záruka. Holdout metriky opisujú konkrétne historické obdobie vyhodnotenia.','Žádný výsledek zde není prezentován jako záruka. Holdout metriky popisují konkrétní historické období vyhodnocení.'))}</p></div>`;}
    else if(route==='btts') body=`<section class="btts-beta-page"><span class="btts-beta-badge">${escapeHtml(publicText('BETA · FOOTBALL'))}</span><h2>${escapeHtml(publicText('Both Teams To Score'))}</h2><p>${escapeHtml(publicText('The BlinQ BTTS module is prepared, but live football data and published predictions are not connected in this repository yet.'))}</p><div class="btts-beta-state"><i></i><span><strong>${escapeHtml(publicText('Data not connected'))}</strong><small>${escapeHtml(publicText('No demo or fabricated predictions are shown.'))}</small></span></div></section>`;
    else if(route==='account') body=renderAccountPage();
    else if(['how_blinq_works','methodology','model_data','faq','responsible_use','terms','privacy','cookies','support'].includes(route)) body=renderSiteContentPage(route);
    else body=`<div class="static-copy"><p>${escapeHtml(lcopy('This section is available in the BlinQ workspace.','Táto sekcia je dostupná v BlinQ.','Tato sekce je dostupná v BlinQ.'))}</p></div>`;
    host.innerHTML=`<div class="route-card route-card-clean">${body}</div>`; if(route!=='admin')translatePublicDom(host); window.BlinqUI.prepareRoute(host); if(route==='results')wireResultsFilters(); if(route==='account')wireAccountPage(); if(route==='support')wireSupportForm(); applyAccessStates(host);
  }

  function upgradePlanFacts(planId,plan={}){
    const label=String(plan.label||planId||'').trim()||'BlinQ';
    const access=String(plan.card_title||plan.description||plan.note||'').trim()||label;
    const duration=plan.lifetime?publicText('Lifetime'):Number.isFinite(Number(plan.duration_days))&&Number(plan.duration_days)>0?`${Math.trunc(Number(plan.duration_days))} ${locale==='cz'?'dní':locale==='sk'?'dní':'days'}`:publicText('Active membership');
    return [
      [publicText('Level'),label],
      [publicText('Access'),access],
      [publicText('Validity'),duration],
    ];
  }
  let accessHintTimer=0,accessHintHoverTimer=0,accessHintTarget=null;
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
    requestAnimationFrame(()=>{const h=hint.getBoundingClientRect().height;const below=r.bottom+9;const top=below+h<window.innerHeight-10?below:Math.max(10,r.top-h-9);hint.style.top=`${top}px`;});
  }
  function showAccessHint(target,planId='elite',sectionLabel='',autoHide=false){
    const hint=$('accessHint'),title=$('accessHintTitle'),text=$('accessHintText'),button=$('accessHintUpgrade');if(!hint||!target)return;
    const d=accessHintDetails(planId,sectionLabel);accessHintTarget=target;
    if(title)title.textContent=d.title;if(text)text.textContent=d.text;
    if(button){button.textContent=`Upgrade na ${d.levelName}`;button.dataset.upgradePlan=planId;button.dataset.upgradeSection=sectionLabel||d.levelName;}
    hint.hidden=false;positionAccessHint(target);
    clearTimeout(accessHintTimer);if(autoHide)accessHintTimer=setTimeout(()=>hideAccessHint(),4300);
  }

  function showUpgradePrompt(planId='pro',sectionLabel='this content'){
    window.BlinqUI.closeMenu(false);
    const dialog=$('upgradeDialog'),host=$('upgradeDialogContent');if(!dialog||!host)return;
    const plan=state.ui?.plans?.[planId]||state.ui?.plans?.pro||{},url=safeExternalUrl(plan.url),facts=upgradePlanFacts(planId,plan);
    const factHtml=facts.map(([label,value])=>`<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(publicText(value))}</strong></span>`).join('');
    const levelName=String(plan.label||upgradePlanLabel(planId)||planId).replace(/^BlinQ\s+/i,'').toUpperCase();
    const availability=lcopy(`Available from ${levelName} level.`,`Táto položka je dostupná od úrovne ${levelName} vyššie.`,`Tato položka je dostupná od úrovně ${levelName} výše.`);
    const title=lcopy(`Unlock ${sectionLabel}`,`${sectionLabel} · uzamknuté`,`${sectionLabel} · uzamčeno`);
    host.innerHTML=`<div class="upgrade-dialog-eyebrow">BLINQ MEMBERSHIP</div><div class="upgrade-dialog-plan">${planAvatarHtml(planId,plan)}<div><h2 id="upgradeDialogTitle">${escapeHtml(title)}</h2><p><strong>${escapeHtml(availability)}</strong><br>${escapeHtml(publicText(plan.description||plan.note||''))}</p></div></div><div class="upgrade-dialog-benefits upgrade-dialog-account-facts">${factHtml}</div>${url?`<a class="btn btn-primary upgrade-dialog-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(lcopy(`Upgrade to ${levelName}`,`Prejsť na ${levelName}`,`Přejít na ${levelName}`))} →</a>`:`<button class="btn btn-primary upgrade-dialog-cta" type="button" data-route="account">${escapeHtml(lcopy('View membership options','Zobraziť možnosti členstva','Zobrazit možnosti členství'))} →</button>`}`;
    if(locale!=='en')translatePublicDom(dialog); if(!dialog.open)dialog.showModal();
  }
  async function signOutCurrentSession(){feedGeneration++;await BlinqAuth.signOut();state.feed={upcoming:[],results:[],performance:{},history:{},model:null};state.insights=[];state.insightsUnread=0;state.railMatch=null;setInsightDrawer(false);auth('login');}
  function closeProfileMenu(){const menu=$('profileMenu'),toggle=$('profileMenuToggle');if(menu)menu.hidden=true;if(toggle)toggle.setAttribute('aria-expanded','false');}

  let feedLoading=false,feedGeneration=0;
  async function loadFeed(showLoading=true){
    if(feedLoading)return;feedLoading=true;const generation=feedGeneration;window.BlinqUI.sync('loading');
    if(showLoading&&state.route==='predictions') $('predictionGrid').innerHTML=`<div class="state-card">${escapeHtml(publicText('Loading current model predictions…'))}</div>`;
    try{
      const feed=(await BlinqAuth.feed())||{};if(generation!==feedGeneration)return;
      state.feed=feed; state.feed.upcoming=Array.isArray(feed?.upcoming)?feed.upcoming:[]; state.feed.results=Array.isArray(feed?.results)?feed.results:[];
      await loadNewsPool();if(generation!==feedGeneration)return;loadAdminDraft(); renderAllUiContent(); populateFilters();
      const a=feed.account||{};
      $('profileName').textContent=a.name||a.email||publicText('BlinQ User');
      const resolvedPlan=accountPlan();
      const planLabel=a.plan_label||state.ui?.plans?.[resolvedPlan]?.label||a.plan||publicText('Member');
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
      if(tooltipPlan)tooltipPlan.textContent=a.plan_label||state.ui?.plans?.[String(a.plan||'').toLowerCase()]?.label||a.plan||planLabel||'Member';
      if(tooltipRemaining){const status=String(a.status||'active').toLowerCase();tooltipRemaining.textContent=status==='lifetime'?publicText('Lifetime'):a.expires_at?remainingLabel(a.expires_at):(status==='active'?publicText('Managed manually'):status.toUpperCase());}
      $('updatedAt').textContent=feed.generated_at?fmtTime(feed.generated_at):'—'; $('todayLabel').textContent=fmtToday(); updateHeaderClock();
      const fullModelVersion=String(feed?.model?.version||'').trim(),compactModelVersion=shortModelVersion(fullModelVersion);
      const footerModel=$('footerModelState'); if(footerModel){footerModel.textContent=compactModelVersion?`Model ${compactModelVersion}`:publicText('Production feed');footerModel.title=fullModelVersion||publicText('Production feed');}
      const headerModel=$('headerModelState');if(headerModel){headerModel.textContent=compactModelVersion||publicText('Production');headerModel.title=fullModelVersion||publicText('Production');}
      const staleNotice=$('staleNotice'); if(staleNotice){staleNotice.hidden=true;staleNotice.textContent='';} $('appShell').hidden=false; if($('authDialog').open)$('authDialog').close();
      if(state.route==='admin'&&!isAdminAccount())state.route='predictions'; setRoute(state.route,false); applyAccessStates();renderDashboardKpis();loadInsights(true);renderFooterConfig();window.BlinqUI.sync(feed.stale?'stale':'ready',feed.generated_at);
    }catch(error){if(generation!==feedGeneration)return;if(error.status===401){BlinqAuth.clear();auth('login');$('authMessage').textContent=publicText('Your session could not be authorized. Sign in again.');return;}if(error.status===403&&String(error.code||'').toLowerCase()==='email_not_verified'){auth('login');$('authMessage').textContent=publicText('Verify your email before opening BlinQ. You can resend the verification email below.');$('resendVerification').hidden=false;return;}if(error.status===403&&String(error.code||'').toLowerCase()==='account_suspended'){auth('login');$('authMessage').textContent=publicText('This BlinQ account is suspended. Contact support if you believe this is a mistake.');return;}window.BlinqUI.sync(navigator.onLine?'error':'offline');const footerStatus=document.querySelector('.system-status');if(footerStatus&&!$('appShell').hidden){footerStatus.classList.add('is-error');footerStatus.classList.remove('is-warning');const label=footerStatus.querySelector('strong');if(label)label.textContent=lcopy('Refresh problem','Problém s aktualizáciou','Problém s aktualizací');}if(showLoading)showStatus(publicText('Data could not be refreshed. Please try again.'));if($('appShell').hidden){auth('login');$('authMessage').textContent=publicText(error.message||'The BlinQ workspace could not be opened. Please try again.');return;}if(state.route==='predictions')renderPredictions();throw error;}finally{feedLoading=false;window.BlinqUI.refreshFinished();}
  }
  async function refreshWorkspace(showLoading=false){await loadUiConfig();return loadFeed(showLoading);}

  function updateHeaderClock(){const date=$('headerDate'),time=$('headerTime');if(date)date.textContent=fmtToday();if(time)time.textContent=fmtClock();}

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
      const liveTab=event.target.closest('[data-live-radar-tab]');if(liveTab){state.liveRadarTab=liveTab.dataset.liveRadarTab==='set2'?'set2':'comeback';state.insightFilter='all';renderInsightDrawer();return;}
      const article=event.target.closest('[data-insight-id]');if(article)markInsightRead(article.dataset.insightId);
      const matchButton=event.target.closest('[data-insight-match]');if(matchButton){const found=findRowByEventId(matchButton.dataset.insightMatch);if(found){setInsightDrawer(false);setRoute('predictions');openMatch(normalize(found.row),found.tab,found.row);}else showStatus(lcopy('This match is not on the current board.','Tento zápas už nie je v aktuálnej ponuke.','Tento zápas už není v aktuální nabídce.'));}
    };
    if($('dashboardRightRail'))$('dashboardRightRail').onclick=event=>{
      if(event.target.closest('[data-rail-close-match]')){clearMatchRail();return;}
      if(event.target.closest('[data-rail-open-modal]')){if(state.railMatch)openMatch(normalize(state.railMatch),state.railMatchTab||'daily',state.railMatch);return;}
      const detailTab=event.target.closest('[data-rail-detail-tab]');if(detailTab){state.railDetailTab=detailTab.dataset.railDetailTab||'overview';renderDashboardSidebar();return;}
      const open=event.target.closest('[data-rail-open-highlight]');if(open){const found=findRowByEventId(open.dataset.railOpenHighlight);if(found)selectMatchInRail(found.row,found.tab);}
    };
    document.addEventListener('click',e=>{
      if(!e.target.closest('#profileShell'))closeProfileMenu();
      const dashboardToggle=e.target.closest('[data-dashboard-toggle]');if(dashboardToggle&&state.route==='predictions'){e.preventDefault();toggleDashboardSection(dashboardToggle.dataset.dashboardToggle);return;}
      const accessUpgrade=e.target.closest('#accessHintUpgrade');if(accessUpgrade){e.preventDefault();e.stopPropagation();hideAccessHint();showUpgradePrompt(accessUpgrade.dataset.upgradePlan||'elite',accessUpgrade.dataset.upgradeSection||'BlinQ');return;}
      const upgradeTarget=e.target.closest('[data-upgrade-plan]');if(upgradeTarget&&state.route!=='admin'){e.preventDefault();e.stopPropagation();const plan=upgradeTarget.dataset.upgradePlan||'pro',section=upgradeTarget.dataset.upgradeSection||'this content';if(upgradeTarget.dataset.upgradeExplicit==='1')showUpgradePrompt(plan,section);else showAccessHint(upgradeTarget,plan,section,true);return;}
      const restricted=e.target.closest('[data-ui-element].ui-state-locked,[data-ui-element].ui-state-blurred,[data-ui-element].ui-state-hidden');
      if(restricted&&state.route!=='admin'){e.preventDefault();e.stopPropagation();const plan=firstUnlockPlan(dashboardSectionKeyForSidebarElement(restricted.dataset.uiElement)||'top_daily',0,true);showAccessHint(restricted,plan,restricted.querySelector('span:nth-child(2)')?.textContent||'this content',true);return;}
      const banner=e.target.closest('[data-banner-slot]');if(banner)trackBanner(banner,'click');
      const prev=e.target.closest('[data-market-prev]');if(prev){const key=prev.dataset.marketPrev;state.marketPage[key]=Math.max(0,Number(state.marketPage[key]||0)-1);renderMarketSections();return;}
      const next=e.target.closest('[data-market-next]');if(next){const key=next.dataset.marketNext;state.marketPage[key]=Number(state.marketPage[key]||0)+1;renderMarketSections();return;}
      const target=e.target.closest('[data-route]');if(!target)return;const route=target.dataset.route;if(!routeMeta[route])return;e.preventDefault();if(route==='account'){openAccountDialog();return;}const upgradeDialog=$('upgradeDialog');if(upgradeDialog?.open&&target.closest('#upgradeDialog'))upgradeDialog.close();const matchDialog=$('matchDialog');if(matchDialog?.open&&target.closest('#matchDialog'))matchDialog.close();setRoute(route);
    });
    document.addEventListener('pointerover',e=>{const target=e.target.closest?.('[data-upgrade-plan]:not([data-upgrade-explicit="1"])');if(!target||state.route==='admin'||window.matchMedia('(hover: none)').matches)return;clearTimeout(accessHintHoverTimer);accessHintHoverTimer=setTimeout(()=>showAccessHint(target,target.dataset.upgradePlan||'elite',target.dataset.upgradeSection||'',false),320);});
    document.addEventListener('pointerout',e=>{const target=e.target.closest?.('[data-upgrade-plan]:not([data-upgrade-explicit="1"])');if(!target)return;const next=e.relatedTarget;if(next instanceof Node&&target.contains(next))return;clearTimeout(accessHintHoverTimer);hideAccessHint(120);});
    document.addEventListener('focusin',e=>{const target=e.target.closest?.('[data-upgrade-plan]:not([data-upgrade-explicit="1"])');if(target&&state.route!=='admin')showAccessHint(target,target.dataset.upgradePlan||'elite',target.dataset.upgradeSection||'',false);});
    document.addEventListener('focusout',e=>{if(e.target.closest?.('[data-upgrade-plan]:not([data-upgrade-explicit="1"])'))hideAccessHint(100);});
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
    window.addEventListener('popstate',()=>{if(!$('appShell').hidden)setRoute(location.hash.slice(1)||'predictions',false);});
    window.addEventListener('hashchange',()=>{const route=location.hash.slice(1)||'predictions';if(!$('appShell').hidden&&route!==state.route)setRoute(route,false);});
  }

  function finishBootSplash(){const splash=$('bootSplash');if(!splash)return;splash.classList.add('is-done');setTimeout(()=>splash.remove(),220);}
  async function boot(){
    setupEvents();window.BlinqUI.init();setupLiveRefresh();updateHeaderClock();setInterval(updateHeaderClock,30000);
    const hash=location.hash.replace(/^#/,'');if(routeMeta[hash])state.route=hash;
    try{
      // UI config and auth config are independent network calls; do them in parallel to reduce cold-start time.
      const [,cfg]=await Promise.all([loadUiConfig(),BlinqAuth.init()]);
      renderCookieConsent(false);
      state.authEnabled=Boolean(cfg.enabled);
      if(cfg.recovery){auth('recovery');finishBootSplash();return;}
      const session=await BlinqAuth.restore();
      if(session)await loadFeed();else auth('login');
    }catch(error){showStatus(error.message);auth('login');}
    finally{finishBootSplash();}
  }
  boot();
})();
