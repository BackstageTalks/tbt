(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = { feed: {upcoming:[],results:[],performance:{},history:{},model:null}, ui:null, uiSource:null, route:'predictions', page:0, showAll:false, authMode:'login', authEnabled:false, draftLoaded:false, selectedElement:'HEADER_BANNER_1', adminPlan:'rookie', adminPlanId:'rookie', adminBannerPreviewPlan:'rookie', adminTab:'layout', adminUsers:null, adminUsersLoading:false, adminSelectedUser:null, previewPlan:null, newsPool:[], bannerObserver:null, bannerTimers:new WeakMap(), adminAnalytics:null, adminAnalyticsLoading:false, runtimeConfigLoaded:false, adminCampaignId:null, adminAdvertiserId:null, resultsFilters:{category:'all',tour:'',surface:'',window:'all'}, marketPage:{top_daily:0,value:0,doubles:0,ace:0,sg:0}, dashboardVisibility:null, demoFeedBackup:null, demoMode:false, heroIndex:0, heroTimer:null, heroPaused:false };
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
  const flagEmoji = code => { const value=String(code||'').trim().toUpperCase(); if(!/^[A-Z]{2}$/.test(value))return ''; return [...value].map(ch=>String.fromCodePoint(127397+ch.charCodeAt(0))).join(''); };
  const safePhotoUrl = value => { const url=String(value||'').trim(); return /^\/assets\/players\/[A-Za-z0-9_.-]+$/.test(url)?url:''; };
  const safeUiAsset = value => { const url=String(value||'').trim(); return /^\/assets\/[A-Za-z0-9_.\/-]+$/.test(url)?url:''; };
  const avatarAssetSrc = value => { const url=safeUiAsset(value); return url ? `${url}?v=v6516` : ''; };
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
  const playerMetaLabel = (rank,country) => [flagEmoji(country),Number.isFinite(Number(rank))&&Number(rank)>0?`#${Math.trunc(Number(rank))}`:''].filter(Boolean).join(' ');
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
      'Dashboard':'Prehľad','Prime Picks':'Prime tipy','Top Bets':'Top tipy','Value Picks':'Value tipy','Doubles':'Štvorhra','Ace Picks':'Esá','S/G Picks':'Sety / hry','Results':'Výsledky','BTTS Bonus':'BTTS Bonus',
      'Plans':'Plány','Upgrade':'Upgrade','Level':'Úroveň','Remaining':'Zostáva','Account':'Účet','Account & membership':'Účet a členstvo','Profile, access and plans':'Profil, prístup a plány','Sign out':'Odhlásiť sa','End this session':'Ukončiť túto reláciu',
      'Welcome back.':'Vitaj späť.','Sign in to your tennis intelligence workspace.':'Prihlás sa do svojho tenisového analytického priestoru.','Create your BlinQ account.':'Vytvor si účet BlinQ.','Create an account to access your BlinQ workspace.':'Vytvor si účet a získaj prístup do BlinQ.','Restore access.':'Obnov prístup.','We will send a password recovery link to your email.':'Na e-mail ti pošleme odkaz na obnovenie hesla.','Set a new password.':'Nastav nové heslo.','Choose a password with at least eight characters.':'Zvoľ heslo s minimálne ôsmimi znakmi.',
      'Display name':'Zobrazované meno','Email':'E-mail','Password':'Heslo','Enter your email':'Zadaj svoj e-mail','Enter your password':'Zadaj svoje heslo','Show':'Zobraziť','Hide':'Skryť','Show password':'Zobraziť heslo','Hide password':'Skryť heslo','Sign in':'Prihlásiť sa','Create account':'Vytvoriť účet','Back to sign in':'Späť na prihlásenie','Forgot password':'Zabudnuté heslo','Resend verification email':'Poslať overovací e-mail znova','Send recovery link':'Poslať odkaz na obnovu','Save password':'Uložiť heslo','Working…':'Pracujem…','Authentication is temporarily unavailable.':'Prihlasovanie je dočasne nedostupné.',
      'Verification email sent. Open the link in your inbox, then sign in.':'Overovací e-mail bol odoslaný. Otvor odkaz v správe a potom sa prihlás.','Your email is not verified yet. Open the verification link or resend the email.':'Tvoj e-mail ešte nie je overený. Otvor overovací odkaz alebo si pošli e-mail znova.','Verify your email before opening BlinQ. You can resend the verification email below.':'Pred otvorením BlinQ over svoj e-mail. Overovací e-mail si môžeš poslať znova nižšie.','Sending verification email…':'Odosielam overovací e-mail…','Verification email sent again. Check your inbox and spam folder.':'Overovací e-mail bol odoslaný znova. Skontroluj doručenú poštu aj spam.','If the account exists, check your email for the recovery link.':'Ak účet existuje, skontroluj e-mail s odkazom na obnovu.',
      'Your account':'Tvoj účet','YOUR ACCOUNT':'TVOJ ÚČET','CURRENT ACCESS':'AKTUÁLNY PRÍSTUP','Email verified':'E-mail overený','Email not verified':'E-mail nie je overený','Legacy admin · verify email':'Legacy admin · over e-mail','Telegram nick':'Telegram nick','Avatar style':'Typ avatara','Default':'Predvolený','Male':'Muž','Female':'Žena','Save profile':'Uložiť profil','Reset password':'Obnoviť heslo','Saving…':'Ukladám…','Profile updated.':'Profil bol uložený.','Sending recovery email…':'Odosielam e-mail na obnovu…','Password reset email sent.':'E-mail na obnovu hesla bol odoslaný.','BLINQ MEMBERSHIP':'BLINQ ČLENSTVO','Available plans':'Dostupné plány','Choose the access level that fits your workflow. Plans without an active checkout stay visible but cannot be purchased online yet.':'Vyber si úroveň prístupu. Plány bez aktívnej platby zostávajú viditeľné, ale zatiaľ ich nemožno kúpiť online.','Current plan':'Aktuálny plán','CURRENT PLAN':'AKTUÁLNY PLÁN','ONLINE PURCHASE NOT OPEN YET':'ONLINE NÁKUP ZATIAĽ NIE JE DOSTUPNÝ','INVITE ONLY':'LEN NA POZVÁNKU','Invite only':'Len na pozvánku','Request invite':'Požiadať o pozvánku','Open plan':'Otvoriť plán','Lifetime access':'Doživotný prístup','Active':'Aktívne','No active access':'Bez aktívneho prístupu','Rookie Trial':'Rookie skúšobná verzia','Lifetime':'Doživotne','Active membership':'Aktívne členstvo','Expired':'Expirované','Access':'Prístup','Validity':'Platnosť','Member since':'Člen od','Security':'Zabezpečenie','Verified email':'Overený e-mail','Legacy admin access':'Legacy admin prístup','Verification required':'Vyžaduje sa overenie',
      'LIVE · Connecting…':'LIVE · Pripájam…','Auto-refresh on':'Automatické obnovenie zapnuté','Refresh':'Obnoviť','Live · updated':'Live · aktualizované','picks':'tipov','published':'publikovaných','settled':'vyhodnotených','See more':'Zobraziť viac','See more →':'Zobraziť viac →','Loading Prime Picks…':'Načítavam Prime tipy…','All Tours':'Všetky okruhy','All Tournaments':'Všetky turnaje','All Surfaces':'Všetky povrchy','All Confidence':'Všetky úrovne istoty',
      'Unlock this pick':'Odomkni tento tip','Upgrade to unlock →':'Upgrade pre odomknutie →','Model signal':'Signál modelu','Overall performance':'Celková výkonnosť','Surface strength':'Sila na povrchu','Recent form':'Aktuálna forma','Head to head':'Vzájomné zápasy','Current market snapshot':'Aktuálny stav trhu','Odds':'Kurz','Model edge':'Výhoda modelu','Model signals':'Signály modelu','supports pick':'podporuje tip','counter-signal':'protisignál','No secondary signals are available.':'Nie sú dostupné žiadne sekundárne signály.','History':'História','Surface':'Povrch','Data depth':'Hĺbka dát',
      'Category':'Kategória','All published':'Všetky publikované','Tour':'Okruh','Period':'Obdobie','All time':'Celé obdobie','7 days':'7 dní','30 days':'30 dní','90 days':'90 dní','Date':'Dátum','Match':'Zápas','Pick':'Tip','Probability':'Pravdepodobnosť','Result':'Výsledok','Units':'Jednotky','WON':'VÝHRA','LOST':'PREHRA','Record':'Bilancia','Hit rate':'Úspešnosť','ROI':'ROI','Settled predictions':'Vyhodnotené predikcie','Observed results':'Pozorované výsledky','Lower is better':'Nižšie je lepšie','Probability quality':'Kvalita pravdepodobnosti',
      'TENNIS INTELLIGENCE':'TENISOVÁ ANALYTIKA','MATCH WINNER':'VÍŤAZ ZÁPASU','CONFIDENCE FIRST':'ISTOTA NA PRVOM MIESTE','VALUE EDGE':'VALUE VÝHODA','SETTLED PICKS':'VYHODNOTENÉ TIPY','BLINQ MEMBERS':'BLINQ ČLENSTVO','LEARN':'INFO','How BlinQ Works':'Ako funguje BlinQ','Methodology':'Metodika','Model & Data':'Model a dáta','Responsible Use':'Zodpovedné používanie',
      'Prime rule':'Pravidlo Prime','Top Bets rule':'Pravidlo Top tipov','Value rule':'Pravidlo Value','Doubles model':'Model štvorhry','Aces / Double Faults':'Esá / dvojchyby','Sets / Games':'Sety / hry','Projection only.':'Iba projekcia.','No published data are available for this section yet.':'Pre túto sekciu zatiaľ nie sú dostupné publikované dáta.','No Prime Picks available yet. This board updates automatically when new picks qualify.':'Prime tipy zatiaľ nie sú dostupné. Prehľad sa automaticky aktualizuje, keď sa kvalifikujú nové tipy.','No Top Bets available yet. New qualifying picks appear automatically.':'Top tipy zatiaľ nie sú dostupné. Nové kvalifikované tipy sa zobrazia automaticky.','No Value Picks available yet. We are waiting for qualifying opportunities.':'Value tipy zatiaľ nie sú dostupné. Čakáme na kvalifikované príležitosti.','No Doubles picks have been published yet.':'Tipy na štvorhru zatiaľ neboli publikované.','No Ace Picks available yet. New projections appear automatically.':'Tipy na esá zatiaľ nie sú dostupné. Nové projekcie sa zobrazia automaticky.','No Sets / Games picks available yet. New projections appear automatically.':'Tipy na sety / hry zatiaľ nie sú dostupné. Nové projekcie sa zobrazia automaticky.','No settled published predictions match these filters yet.':'Týmto filtrom zatiaľ nezodpovedajú žiadne vyhodnotené publikované predikcie.','No upcoming tournament coverage is currently published.':'Momentálne nie je publikované pokrytie nadchádzajúcich turnajov.','No upcoming players are currently published.':'Momentálne nie sú publikovaní žiadni nadchádzajúci hráči.',
      'BlinQ Pick':'BlinQ tip','Prime tipy':'Prime tipy','Top tipy':'Top tipy','Value tipy':'Value tipy','Štvorhra':'Štvorhra','Esá':'Esá','Sety / hry':'Sety / hry','Výsledky':'Výsledky',
      'LANGUAGE':'JAZYK','Live model':'Live model','Production feed':'Produkčný feed','This data is provided for informational and analytical purposes only. Powered by BackstageTalks Statistical Engine.':'Tieto dáta slúžia iba na informačné a analytické účely. Powered by BackstageTalks Statistical Engine.',
      'More published picks':'Viac publikovaných tipov','Full card details':'Kompletné detaily karty','See all access':'Prístup ku všetkým tipom','View membership options →':'Zobraziť možnosti členstva →','UNLOCK MORE WITH BLINQ':'ODOMKNI VIAC S BLINQ',
      'COMMUNITY':'KOMUNITA','Join our Telegram Community':'Pridaj sa do Telegram komunity','News · Picks · Discussions':'Novinky · Tipy · Diskusie','JOIN':'PRIDAŤ SA','Premium Picks':'Prémiové tipy','Higher value. Better decisions.':'Vyššia hodnota. Lepšie rozhodnutia.','OPEN':'OTVORIŤ','RESULTS & STATS':'VÝSLEDKY A ŠTATISTIKY','Track performance':'Sleduj výkonnosť','Transparent. Verified.':'Transparentné. Overené.','VIEW':'ZOBRAZIŤ','Data. Analysis.':'Dáta. Analýza.','Better Decisions.':'Lepšie rozhodnutia.','Advanced tennis intelligence for informed players.':'Pokročilá tenisová analytika pre informované rozhodnutia.','Join the BlinQ':'Pridaj sa do BlinQ','Telegram Community':'Telegram komunity','Track performance.':'Sleduj výkonnosť.','Stay informed.':'Maj prehľad.','Transparent model results and published statistics.':'Transparentné výsledky modelu a publikované štatistiky.','SEE RESULTS':'VÝSLEDKY','BLINQ NEWS':'BLINQ NOVINKY','Updates & releases':'Novinky a aktualizácie','Product news and new features.':'Novinky produktu a nové funkcie.','BLINQ PARTNER':'BLINQ PARTNER','Your campaign.':'Tvoja kampaň.','Your message.':'Tvoja správa.','Assign a campaign, image, link and schedule in Admin.':'V Adminovi nastav kampaň, obrázok, odkaz a časovanie.',
      'Incorrect email or password.':'Nesprávny e-mail alebo heslo.','An account with this email already exists.':'Účet s týmto e-mailom už existuje.','Choose a stronger password with at least eight characters.':'Zvoľ silnejšie heslo s minimálne ôsmimi znakmi.','Enter a valid email address.':'Zadaj platnú e-mailovú adresu.','Too many attempts. Try again later.':'Príliš veľa pokusov. Skús to neskôr.','This account has been disabled.':'Tento účet bol deaktivovaný.','Verify your email before opening the BlinQ workspace.':'Pred otvorením BlinQ over svoj e-mail.','Your session expired. Sign in again.':'Tvoja relácia vypršala. Prihlás sa znova.','Your session is no longer valid. Sign in again.':'Tvoja relácia už nie je platná. Prihlás sa znova.',
      '✓ Email verified':'✓ E-mail overený','! Email not verified':'! E-mail nie je overený','! Legacy admin · verify email':'! Legacy admin · over e-mail','← Dashboard':'← Prehľad','Loading current model predictions…':'Načítavam aktuálne predikcie modelu…','Data could not be refreshed. Please try again.':'Dáta sa nepodarilo obnoviť. Skús to znova.','Published data is older than 12 hours. Check prediction creation times before evaluating them.':'Publikované dáta sú staršie ako 12 hodín. Pred vyhodnotením skontroluj čas vytvorenia predikcií.','Managed manually':'Spravované manuálne','Production feed':'Produkčný feed','Production':'Produkcia','Member':'Člen','BlinQ User':'Používateľ BlinQ',
      'Prime Pick':'Prime tip','Value Pick':'Value tip','Ace / DF Pick':'Esá / dvojchyby','Set / Game Pick':'Set / hra','Top Bet':'Top tip','Sets Projection':'Projekcia setov','Games Projection':'Projekcia hier','Ace / DF Projection':'Projekcia es / dvojchýb','Projection':'Projekcia','Projection only · no odds':'Iba projekcia · bez kurzu','Baseline':'Základ','Gap':'Rozdiel','Score':'Skóre','Opponent proj.':'Projekcia súpera','Data':'Dáta','games':'hier','proj.':'proj.','MODEL':'MODEL','VERY HIGH':'VEĽMI VYSOKÁ','HIGH':'VYSOKÁ','MEDIUM':'STREDNÁ','LOW':'NÍZKA','PROJECTION':'PROJEKCIA',
      'No published picks are available in this section yet.':'V tejto sekcii zatiaľ nie sú dostupné publikované tipy.','Both Teams To Score':'Oba tímy dajú gól','The BlinQ BTTS module is prepared, but live football data and published picks are not connected in this repository yet.':'Modul BlinQ BTTS je pripravený, ale live futbalové dáta a publikované tipy zatiaľ nie sú v tomto repozitári pripojené.','Data not connected':'Dáta nie sú pripojené','No demo or fabricated picks are shown.':'Nezobrazujú sa žiadne demo ani vymyslené tipy.','BETA · FOOTBALL':'BETA · FUTBAL',
      'Entry access to the BlinQ workspace.':'Základný prístup do BlinQ.','Start with BlinQ':'Začni s BlinQ','Core predictions':'Hlavné predikcie','Core predictions + expanded daily board.':'Hlavné predikcie a rozšírený denný prehľad.','Advanced analytics':'Pokročilá analytika','Expanded analytical access for users who follow more matches and context.':'Rozšírený analytický prístup pre používateľov, ktorí sledujú viac zápasov a kontextu.','Maximum public access':'Najvyšší verejný prístup','The highest publicly available BlinQ tier.':'Najvyššia verejne dostupná úroveň BlinQ.','Private all-access':'Súkromný plný prístup','Lifetime access · All BlinQ features. Private top-tier access for selected members.':'Doživotný prístup · Všetky funkcie BlinQ. Súkromná najvyššia úroveň pre vybraných členov.','Choose Rookie':'Vybrať Rookie','Upgrade to PRO':'Prejsť na PRO','Choose Elite':'Vybrať Elite','Choose Legend':'Vybrať Legend',
      'Tournament':'Turnaj','Market':'Trh','Projection pick':'Projektovaný tip','Proj.':'Proj.','Opp. proj.':'Proj. súpera','Overall sample':'Celková vzorka','Surface sample':'Vzorka na povrchu','Avg Odds':'Priem. kurz','Sample':'Vzorka','Accuracy':'Presnosť','Log loss':'Log loss','Brier score':'Brier skóre','Published and scored':'Publikované a vyhodnotené','filtered settled sample':'filtrovaná vyhodnotená vzorka','no issued odds':'bez publikovaných kurzov','flat 1u on issued odds':'rovná stávka 1u na publikované kurzy','profit · flat 1u stake':'zisk · rovná stávka 1u','settled published rows':'vyhodnotené publikované záznamy','Production artifact':'Produkčný artefakt','Chronological holdout':'Chronologický holdout','Evaluation report':'Vyhodnocovací report','Negative is better':'Záporné je lepšie','Data window':'Dátové obdobie','Model':'Model',
      'TBA':'Bude určené','ending':'končí'
    },
    cz: {
      'Skip to content':'Přeskočit na obsah','Dashboard':'Přehled','Prime Picks':'Prime tipy','Top Bets':'Top tipy','Value Picks':'Value tipy','Doubles':'Čtyřhra','Ace Picks':'Esa','S/G Picks':'Sety / hry','Results':'Výsledky','Plans':'Plány','Level':'Úroveň','Remaining':'Zbývá','Account':'Účet','Account & membership':'Účet a členství','Profile, access and plans':'Profil, přístup a plány','Sign out':'Odhlásit se','End this session':'Ukončit tuto relaci',
      'Welcome back.':'Vítej zpět.','Sign in to your tennis intelligence workspace.':'Přihlas se do svého tenisového analytického prostoru.','Create your BlinQ account.':'Vytvoř si účet BlinQ.','Create an account to access your BlinQ workspace.':'Vytvoř si účet a získej přístup do BlinQ.','Restore access.':'Obnov přístup.','We will send a password recovery link to your email.':'Na e-mail ti pošleme odkaz pro obnovu hesla.','Set a new password.':'Nastav nové heslo.','Choose a password with at least eight characters.':'Zvol heslo s minimálně osmi znaky.','Email':'E-mail','Password':'Heslo','Enter your email':'Zadej svůj e-mail','Enter your password':'Zadej své heslo','Show':'Zobrazit','Hide':'Skrýt','Show password':'Zobrazit heslo','Hide password':'Skrýt heslo','Sign in':'Přihlásit se','Create account':'Vytvořit účet','Back to sign in':'Zpět na přihlášení','Forgot password':'Zapomenuté heslo','Resend verification email':'Poslat ověřovací e-mail znovu','Send recovery link':'Poslat odkaz pro obnovu','Save password':'Uložit heslo',
      'Your account':'Tvůj účet','YOUR ACCOUNT':'TVŮJ ÚČET','CURRENT ACCESS':'AKTUÁLNÍ PŘÍSTUP','Email verified':'E-mail ověřen','Email not verified':'E-mail není ověřen','Telegram nick':'Telegram nick','Avatar style':'Typ avatara','Default':'Výchozí','Male':'Muž','Female':'Žena','Save profile':'Uložit profil','Reset password':'Obnovit heslo','BLINQ MEMBERSHIP':'BLINQ ČLENSTVÍ','Available plans':'Dostupné plány','Current plan':'Aktuální plán','CURRENT PLAN':'AKTUÁLNÍ PLÁN','ONLINE PURCHASE NOT OPEN YET':'ONLINE NÁKUP ZATÍM NENÍ DOSTUPNÝ','INVITE ONLY':'JEN NA POZVÁNKU','Invite only':'Jen na pozvánku','Request invite':'Požádat o pozvánku','Lifetime access':'Doživotní přístup','Active':'Aktivní','No active access':'Bez aktivního přístupu','Rookie Trial':'Rookie zkušební verze','Lifetime':'Doživotně','Active membership':'Aktivní členství','Expired':'Expirované','Access':'Přístup','Validity':'Platnost','Member since':'Člen od','Security':'Zabezpečení','Verified email':'Ověřený e-mail','Verification required':'Vyžaduje se ověření',
      'Refresh':'Obnovit','Auto-refresh on':'Automatické obnovení zapnuto','picks':'tipů','published':'publikovaných','settled':'vyhodnocených','See more':'Zobrazit více','See more →':'Zobrazit více →','All Tours':'Všechny okruhy','All Tournaments':'Všechny turnaje','All Surfaces':'Všechny povrchy','All Confidence':'Všechny úrovně jistoty','Unlock this pick':'Odemkni tento tip','Upgrade to unlock →':'Upgrade pro odemknutí →','Odds':'Kurz','Model edge':'Výhoda modelu','Category':'Kategorie','All published':'Všechny publikované','Tour':'Okruh','Surface':'Povrch','Period':'Období','All time':'Celé období','7 days':'7 dní','30 days':'30 dní','90 days':'90 dní','Date':'Datum','Match':'Zápas','Pick':'Tip','Probability':'Pravděpodobnost','Result':'Výsledek','Units':'Jednotky','WON':'VÝHRA','LOST':'PROHRA','Record':'Bilance','Hit rate':'Úspěšnost','Settled predictions':'Vyhodnocené predikce','TENNIS INTELLIGENCE':'TENISOVÁ ANALYTIKA','MATCH WINNER':'VÍTĚZ ZÁPASU','CONFIDENCE FIRST':'JISTOTA NA PRVNÍM MÍSTĚ','VALUE EDGE':'VALUE VÝHODA','SETTLED PICKS':'VYHODNOCENÉ TIPY','BLINQ MEMBERS':'BLINQ ČLENSTVÍ','LEARN':'INFO','How BlinQ Works':'Jak funguje BlinQ','Methodology':'Metodika','Model & Data':'Model a data','Responsible Use':'Zodpovědné používání','BlinQ Pick':'BlinQ tip','LANGUAGE':'JAZYK',
      'COMMUNITY':'KOMUNITA','Join our Telegram Community':'Přidej se do Telegram komunity','News · Picks · Discussions':'Novinky · Tipy · Diskuse','JOIN':'PŘIDAT SE','Premium Picks':'Prémiové tipy','Higher value. Better decisions.':'Vyšší hodnota. Lepší rozhodnutí.','OPEN':'OTEVŘÍT','RESULTS & STATS':'VÝSLEDKY A STATISTIKY','Track performance':'Sleduj výkonnost','Transparent. Verified.':'Transparentní. Ověřené.','VIEW':'ZOBRAZIT','Data. Analysis.':'Data. Analýza.','Better Decisions.':'Lepší rozhodnutí.','Advanced tennis intelligence for informed players.':'Pokročilá tenisová analytika pro informovaná rozhodnutí.','Join the BlinQ':'Přidej se do BlinQ','Telegram Community':'Telegram komunity','Track performance.':'Sleduj výkonnost.','Stay informed.':'Měj přehled.','Transparent model results and published statistics.':'Transparentní výsledky modelu a publikované statistiky.','SEE RESULTS':'VÝSLEDKY','✓ Email verified':'✓ E-mail ověřen','! Email not verified':'! E-mail není ověřen','← Dashboard':'← Přehled','Loading current model predictions…':'Načítám aktuální predikce modelu…','Data could not be refreshed. Please try again.':'Data se nepodařilo obnovit. Zkus to znovu.','Published data is older than 12 hours. Check prediction creation times before evaluating them.':'Publikovaná data jsou starší než 12 hodin. Před vyhodnocením zkontroluj čas vytvoření predikcí.','Prime Pick':'Prime tip','Value Pick':'Value tip','Ace / DF Pick':'Esa / dvojchyby','Set / Game Pick':'Set / hra','Top Bet':'Top tip','Projection only · no odds':'Pouze projekce · bez kurzu','VERY HIGH':'VELMI VYSOKÁ','HIGH':'VYSOKÁ','MEDIUM':'STŘEDNÍ','LOW':'NÍZKÁ','PROJECTION':'PROJEKCE','No published picks are available in this section yet.':'V této sekci zatím nejsou dostupné publikované tipy.','Both Teams To Score':'Oba týmy dají gól','Data not connected':'Data nejsou připojena','No demo or fabricated picks are shown.':'Nezobrazují se žádné demo ani vymyšlené tipy.','BETA · FOOTBALL':'BETA · FOTBAL',
      'Entry access to the BlinQ workspace.':'Základní přístup do BlinQ.','Start with BlinQ':'Začni s BlinQ','Core predictions':'Hlavní predikce','Core predictions + expanded daily board.':'Hlavní predikce a rozšířený denní přehled.','Advanced analytics':'Pokročilá analytika','Maximum public access':'Nejvyšší veřejný přístup','The highest publicly available BlinQ tier.':'Nejvyšší veřejně dostupná úroveň BlinQ.','Private all-access':'Soukromý plný přístup','Lifetime access · All BlinQ features. Private top-tier access for selected members.':'Doživotní přístup · Všechny funkce BlinQ. Soukromá nejvyšší úroveň pro vybrané členy.','Tournament':'Turnaj','Market':'Trh','Projection pick':'Projektovaný tip','Opp. proj.':'Proj. soupeře','Overall sample':'Celkový vzorek','Surface sample':'Vzorek na povrchu','Avg Odds':'Prům. kurz','Sample':'Vzorek','Accuracy':'Přesnost','Brier score':'Brier skóre','Published and scored':'Publikované a vyhodnocené','Data window':'Datové období',
      'TBA':'Bude určeno','ending':'končí'
    }
  };
  function publicText(value){
    const raw=String(value??'');
    if(locale==='en')return raw;
    const dict=PUBLIC_TRANSLATIONS[locale]||{};
    if(Object.prototype.hasOwnProperty.call(dict,raw))return dict[raw];
    let m=raw.match(/^(\d+) picks$/);if(m)return `${m[1]} ${locale==='cz'?'tipů':'tipov'}`;
    m=raw.match(/^(\d+) published$/);if(m)return `${m[1]} ${locale==='cz'?'publikovaných':'publikovaných'}`;
    m=raw.match(/^(\d+) settled$/);if(m)return `${m[1]} ${locale==='cz'?'vyhodnocených':'vyhodnotených'}`;
    m=raw.match(/^Showing (\d+) of (\d+) published picks?\.$/);if(m)return locale==='cz'?`Zobrazeno ${m[1]} z ${m[2]} publikovaných tipů.`:`Zobrazených ${m[1]} z ${m[2]} publikovaných tipov.`;
    m=raw.match(/^Available with (.+)\.$/);if(m)return locale==='cz'?`Dostupné s ${m[1]}.`:`Dostupné s ${m[1]}.`;
    m=raw.match(/^(\d+)d (\d+)h$/);if(m)return `${m[1]} d ${m[2]} h`;
    m=raw.match(/^(\d+)h$/);if(m)return `${m[1]} h`;
    return raw;
  }
  const lcopy=(en,sk,cz=sk)=>locale==='sk'?sk:locale==='cz'?cz:en;
  function translatePublicDom(root=document){
    if(locale==='en'||!root)return;
    const shouldSkip=node=>{const el=node?.parentElement;return Boolean(el?.closest?.('.admin-route,.admin-canvas,.admin-inspector,.admin-toolbar,.admin-tabbar,.admin-accounts-grid,.admin-plan-grid'))};
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(node=>{if(shouldSkip(node))return;const raw=node.nodeValue||'';const core=raw.trim();if(!core)return;const translated=publicText(core);if(translated!==core)node.nodeValue=raw.replace(core,translated);});
    root.querySelectorAll?.('[placeholder],[aria-label],[title]').forEach(el=>{if(el.closest?.('.admin-route,.admin-canvas,.admin-inspector,.admin-toolbar,.admin-tabbar'))return;['placeholder','aria-label','title'].forEach(attr=>{if(!el.hasAttribute(attr))return;const raw=el.getAttribute(attr);const translated=publicText(raw);if(translated!==raw)el.setAttribute(attr,translated);});});
  }
  const dashboardPickSectionKeys=['prime','top_daily','value','doubles','ace','sg'];
  const dashboardSectionKeys=[...dashboardPickSectionKeys,'results','btts'];
  const dashboardSectionFallback={
    prime:{label:'Prime Picks',panel_id:'predictionsPanel',sidebar_element:'SIDEBAR_PRIME',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:1,preview_limit:5},
    top_daily:{label:'Top Bets',panel_id:'topDailyPanel',sidebar_element:'SIDEBAR_TOP_DAILY',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:2,preview_limit:5},
    value:{label:'Value Picks',panel_id:'valuePanel',sidebar_element:'SIDEBAR_VALUE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:3,preview_limit:5},
    doubles:{label:'Doubles',panel_id:'doublesPanel',sidebar_element:'SIDEBAR_DOUBLES',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:4,preview_limit:5},
    ace:{label:'Ace Picks',panel_id:'acePanel',sidebar_element:'SIDEBAR_ACE',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:5,preview_limit:5},
    sg:{label:'S/G Picks',panel_id:'sgPanel',sidebar_element:'SIDEBAR_SG',sidebar_enabled:true,dashboard_enabled:true,dashboard_order:6,preview_limit:5},
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
          // Merge the new release schema around the already-published settings.
          // User-managed order, visibility, banner images/links and rotation must
          // survive an application update instead of silently reverting to repo defaults.
          state.ui.ui_revision=state.uiSource.ui_revision;
          state.ui.dashboard=mergeConfig(state.uiSource.dashboard||{},runtime.config.dashboard||{});
          state.ui.dashboard.user_switches=false;
          state.ui.dashboard.show_disabled_strip=false;
          state.ui.content_rows=mergeConfig(state.uiSource.content_rows||{},runtime.config.content_rows||{});
          state.ui.header_cta=mergeConfig(state.uiSource.header_cta||{},runtime.config.header_cta||{});
          state.ui.hero_banner=mergeConfig(state.uiSource.hero_banner||{enabled:true,slot_count:1,rotation_seconds:10,auto_rotate:true,show_dots:true,pause_on_hover:true},runtime.config.hero_banner||{});
        }
      }
    } catch {}
    try {
      const links = await getJSON('/membership-links.json');
      Object.entries(links?.plans||{}).forEach(([id,row])=>{
        const url=safeExternalUrl(typeof row==='string'?row:(row?.payment_url||row?.url));
        if(url&&state.ui?.plans?.[id]) state.ui.plans[id].url=url;
      });
    } catch {}
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
    if(state.adminTab==='feeds')state.adminTab='layout';
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
    if($('overviewDescription'))$('overviewDescription').textContent=lcopy('Picks and model projections, all in one place.','Prehľad tipov a modelových projekcií na jednom mieste.','Přehled tipů a modelových projekcí na jednom místě.');
    const top=$('bannerTop'),mid=$('bannerMid'),bottom=$('bannerBottom');if(top)top.style.order='10';if(mid)mid.style.order='45';if(bottom)bottom.style.order='80';
    const prefs=dashboardVisibilityState(),max=Math.max(1,Number(state.ui?.dashboard?.visible_slots)||4);
    const orderedKeys=orderedDashboardKeys();const configured=orderedKeys.filter(key=>{const cfg=dashboardSectionConfig(key);return prefs[key]&&cfg.sidebar_enabled!==false&&elementAccess(cfg.sidebar_element)!=='hidden';}).slice(0,max);
    const countFor=key=>marketRows(key).length;
    let active=[...configured];
    if(state.ui?.dashboard?.auto_replace_empty_sections!==false){
      const replacements=orderedKeys.filter(key=>{const cfg=dashboardSectionConfig(key);return !active.includes(key)&&cfg.sidebar_enabled!==false&&elementAccess(cfg.sidebar_element)!=='hidden'&&countFor(key)>0;});
      active=active.map(key=>countFor(key)>0?key:(replacements.shift()||key));
    }
    dashboardPickSectionKeys.forEach(key=>{
      const cfg=dashboardSectionConfig(key),panel=$(cfg.panel_id);if(!panel)return;
      panel.hidden=!active.includes(key);panel.style.order=String(20+active.indexOf(key)*10);
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
    return `<article class="prediction-card dashboard-locked-card" data-upgrade-plan="${escapeHtml(plan)}" data-upgrade-section="${escapeHtml(section.label||key)}"><div class="locked-ghost"><span></span><i>VS</i><span></span></div><div class="locked-pick-copy"><b aria-hidden="true">⌑</b><strong>Unlock this pick</strong><small>Available with ${escapeHtml(label)}.</small><button type="button" class="btn btn-primary">Upgrade to unlock →</button></div></article>`;
  }
  function translateSignalLabel(label){
    const raw=String(label||'Model signal');
    const legacy={'Celková výkonnosť':'Overall performance','Sila na povrchu':'Surface strength','Aktuálna forma':'Recent form','Vzájomné zápasy':'Head to head','Výkonnosť':'Performance','Forma':'Recent form'};
    const canonical=legacy[raw]||raw; return publicText(canonical);
  }

  function renderNavigation(){
    const navIcons={prime:'✦',top_daily:'★',value:'◇',doubles:'◈',ace:'♠',sg:'▥',results:'✓',btts:'⚽'};
    const orderedSections=[...dashboardSectionKeys].sort((a,b)=>sectionPlanOrder(a)-sectionPlanOrder(b)||Number(dashboardSectionConfig(a).dashboard_order||99)-Number(dashboardSectionConfig(b).dashboard_order||99));
    const primaryNav=[['predictions','Dashboard','⌂'],...orderedSections.map(id=>[id,dashboardSectionConfig(id).label||id,navIcons[id]||'•'])];
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
      [...(state.ui?.navigation?.learn||[])].filter(x=>x.enabled!==false).sort((a,b)=>Number(a.order||0)-Number(b.order||0)).forEach(item=>{
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
    if(text.startsWith('#')||text.startsWith('/')||/^https?:\/\//i.test(text))return text;
    return fallback;
  }
  function isExternalLink(value){ return /^https?:\/\//i.test(String(value||'')); }
  function safeExternalUrl(value){
    const text=String(value||'').trim();
    if(!text||!/^https?:\/\//i.test(text))return '';
    try{const parsed=new URL(text);return ['http:','https:'].includes(parsed.protocol)&&parsed.host?parsed.href:'';}catch{return '';}
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
    return elementList('hero_banner','hero').filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden').slice(0,requested);
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
    return `<a class="dashboard-hero hero-slide theme-${escapeHtml(theme)}${index===state.heroIndex?' is-active':''}${showCopy?'':' hero-image-only'}${clickable?'':' is-link-locked'}" href="${escapeHtml(finalHref)}" ${clickable&&external?'target="_blank" rel="noopener"':''} ${clickable&&route&&!external?`data-route="${escapeHtml(route)}"`:''} ${!clickable?`data-upgrade-plan="${escapeHtml(lockedPlan)}" data-upgrade-section="${escapeHtml(c.headline||item.label||'Premium banner')}"`:''} data-hero-index="${index}" data-ui-element="${escapeHtml(item.id)}" ${bannerAttrs(item,c)} aria-hidden="${index===state.heroIndex?'false':'true'}">${sponsored}${image}${copy}${art}${watermarkHtml(item)}</a>`;
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
    host.innerHTML=items.map((item,index)=>heroSlideHtml(item,index)).join('')+(cfg.show_dots!==false&&items.length>1?`<div class="hero-dots" aria-label="Main banner slides">${items.map((_,index)=>`<button type="button" data-hero-dot="${index}" class="${index===state.heroIndex?'is-active':''}" aria-label="Show banner ${index+1}" aria-current="${index===state.heroIndex?'true':'false'}"></button>`).join('')}</div>`:'');
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
      node.classList.remove('ui-state-active','ui-state-locked','ui-state-blurred','ui-state-hidden');
      node.classList.add(`ui-state-${mode}`); node.dataset.uiState=mode;
      node.dataset.uiStateLabel=mode==='active'?'':`${mode.toUpperCase()} · ${accessLabel()}`;
      node.setAttribute('aria-disabled',mode==='active'?'false':'true');
    });
  }
  function refreshTopPlanCta(){
    const label=$('topUpgradeLabel');if(!label)return;
    const purchasable=Object.entries(state.ui?.plans||{}).some(([id,p])=>!['trial','expired','goat'].includes(id)&&p?.enabled!==false&&Boolean(safeExternalUrl(p?.url)));
    label.textContent=publicText(purchasable?'Upgrade':'Plans');
  }
  function updateLanguageLinks(){
    document.querySelectorAll('#footerLanguages [data-lang],#authLanguages [data-lang]').forEach(link=>{const lang=link.dataset.lang||'sk';link.href=link.closest('#authLanguages')?`?lang=${encodeURIComponent(lang)}`:`?lang=${encodeURIComponent(lang)}#${encodeURIComponent(state.route||'predictions')}`;link.classList.toggle('active',lang===locale);});
  }
  function renderAllUiContent(){ if(state.bannerObserver){state.bannerObserver.disconnect();state.bannerObserver=null;}state.bannerTimers=new WeakMap();renderNavigation(); renderHeaderSlots(); renderHeroBanner(); renderBanners(); renderSidebarPromos(); renderMarketSections(); renderDashboardResultsPreview(); renderDashboardComposition(); refreshTopPlanCta(); updateLanguageLinks(); applyAccessStates(); translatePublicDom(document.body); }

  function auth(mode='login'){
    feedGeneration++;
    window.BlinqUI.closeMenu(false); $('appShell').hidden=true;
    state.authMode=mode; $('authMessage').textContent=''; if($('resendVerification'))$('resendVerification').hidden=true;
    $('nameLabel').hidden=mode!=='signup'; $('emailLabel').hidden=mode==='recovery'; $('passwordLabel').hidden=mode==='reset';
    $('authEmail').required=mode!=='recovery'; $('authPassword').required=mode!=='reset'; $('authName').required=mode==='signup';
    $('authPassword').autocomplete=mode==='login'?'current-password':'new-password';
    $('authTitle').textContent=publicText({login:'Welcome back.',signup:'Create your BlinQ account.',reset:'Restore access.',recovery:'Set a new password.'}[mode]);
    $('authSubtitle').textContent=publicText({login:'Sign in to your tennis intelligence workspace.',signup:'Create an account to access your BlinQ workspace.',reset:'We will send a password recovery link to your email.',recovery:'Choose a password with at least eight characters.'}[mode]);
    $('authSubmit').textContent=publicText({login:'Sign in',signup:'Create account',reset:'Send recovery link',recovery:'Save password'}[mode]);
    $('switchSignup').textContent=publicText(mode==='login'?'Create account':'Back to sign in'); $('switchReset').hidden=mode!=='login';
    $('authSubmit').disabled=!state.authEnabled;
    if(!state.authEnabled) $('authMessage').textContent=publicText('Authentication is temporarily unavailable.');
    $('appShell').hidden=true; translatePublicDom(document.body);
    if(!$('authDialog').open) $('authDialog').showModal();
  }

  async function handleAuthSubmit(event){
    event.preventDefault(); const button=$('authSubmit'); button.disabled=true; $('authMessage').textContent=publicText('Working…');
    const email=$('authEmail').value.trim(), password=$('authPassword').value;
    try{
      if(state.authMode==='reset'){ await BlinqAuth.reset(email); $('authMessage').textContent=publicText('If the account exists, check your email for the recovery link.'); return; }
      if(state.authMode==='recovery') await BlinqAuth.update({password});
      else if(state.authMode==='signup'){
        const result=await BlinqAuth.signUp(email,password,$('authName').value.trim());
        if(result?.verification_required){
          auth('login');$('authEmail').value=email;$('authPassword').value='';
          $('authMessage').textContent=publicText('Verification email sent. Open the link in your inbox, then sign in.');
          return;
        }
      } else await BlinqAuth.signIn(email,password);
      $('authPassword').value=''; if($('authDialog').open) $('authDialog').close(); await loadFeed();
    } catch(error){
      const verification=String(error.code||'').toUpperCase()==='EMAIL_NOT_VERIFIED'||String(error.code||'').toLowerCase()==='email_not_verified';
      $('authMessage').textContent=verification?publicText('Your email is not verified yet. Open the verification link or resend the email.'):publicText(error.message);
      if($('resendVerification'))$('resendVerification').hidden=!verification;
    }
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
  function marketProbability(row){const raw=row?.probability??row?.win_probability??row?.model_probability??row?.confidence_probability;const value=Number(raw);return Number.isFinite(value)?(value>1?value/100:value):null;}
  function marketPreviewCard(row,key,index=0,locked=false,compact=false){
    if(locked)return lockedPickCard(key,index);
    const p1=row?.player1||{},p2=row?.player2||{};const probability=marketProbability(row);const pick=row?.pick||row?.selection||row?.prediction||'—';const odds=Number(row?.odds),edge=Number(row?.edge),ev=Number(row?.expected_value);
    const projection=Number(row?.projection),opponentProjection=Number(row?.opponent_projection),projectionGap=Number(row?.projection_gap),projectionConfidence=Number(row?.projection_confidence);const samples=row?.projection_samples||{};const projectionOnly=row?.price_status==='projection_only'&&Number.isFinite(projection);
    let badge='',mainValue='—',confidenceClass='low',pickLabel=publicText(key==='prime'?'Prime Pick':key==='value'?'Value Pick':key==='ace'?'Ace / DF Pick':key==='sg'?'Set / Game Pick':'Top Bet'),note='',metrics=[];
    if(projectionOnly){
      const marketLabel=row?.market_type||String(row?.market||'Projection').replaceAll('_',' ');const sampleText=Number.isFinite(Number(samples.player1))&&Number.isFinite(Number(samples.player2))?`${publicText('Data')} ${samples.player1}/${samples.player2}`:'';const unit=String(row?.projection_unit||'count');const reference=Number(row?.reference_projection??row?.baseline_projection);
      if(key==='sg'&&unit==='probability'){mainValue=`${pct(projection)}<small> proj.</small>`;metrics=[[lcopy('Baseline','Základ','Základ'),Number.isFinite(reference)?pct(reference):'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${(projectionGap*100).toFixed(1)} pp`:'—'],[lcopy('Score','Skóre','Skóre'),Number.isFinite(projectionConfidence)?`${Math.round(projectionConfidence*100)}/100`:'—']];pickLabel=lcopy('Sets projection','Projekcia setov','Projekce setů');}
      else if(key==='sg'&&unit==='games'){mainValue=`${projection.toFixed(1)}<small> games</small>`;metrics=[[lcopy('Baseline','Základ','Základ'),Number.isFinite(reference)?reference.toFixed(1):'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${projectionGap.toFixed(1)}`:'—'],[lcopy('Score','Skóre','Skóre'),Number.isFinite(projectionConfidence)?`${Math.round(projectionConfidence*100)}/100`:'—']];pickLabel=lcopy('Games projection','Projekcia hier','Projekce her');}
      else{mainValue=`${projection.toFixed(1)}<small> proj.</small>`;metrics=[[lcopy('Opponent','Súper','Soupeř'),Number.isFinite(opponentProjection)?opponentProjection.toFixed(1):'—'],[lcopy('Gap','Rozdiel','Rozdíl'),Number.isFinite(projectionGap)?`${projectionGap>=0?'+':''}${projectionGap.toFixed(1)}`:'—'],[lcopy('Score','Skóre','Skóre'),Number.isFinite(projectionConfidence)?`${Math.round(projectionConfidence*100)}/100`:'—']];pickLabel=lcopy('Ace / DF projection','Projekcia es / dvojchýb','Projekce es / dvojchyb');}
      badge=publicText('PROJECTION');confidenceClass=Number.isFinite(projectionConfidence)?confidenceBand(projectionConfidence):'medium';note=[marketLabel,sampleText,publicText('Projection only · no odds')].filter(Boolean).join(' · ');
    }else{
      if(key==='top_daily'){const depth=Number(row?.data_depth),q=row?.quality||{},s1=Number(q?.player1?.surface_matches),s2=Number(q?.player2?.surface_matches);metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Data','Dáta','Data'),Number.isFinite(depth)?`${Math.round(depth*100)}%`:'—'],[publicText('Surface'),Number.isFinite(s1)&&Number.isFinite(s2)?`${Math.min(s1,s2)}+`:'—']];}
      else{metrics=[[publicText('Odds'),Number.isFinite(odds)?odds.toFixed(2):'—'],[lcopy('Edge','Výhoda','Výhoda'),Number.isFinite(edge)?`${edge>0?'+':''}${(edge*(Math.abs(edge)<=1?100:1)).toFixed(1)} pp`:'—'],['EV',Number.isFinite(ev)?`${ev>0?'+':''}${(ev*(Math.abs(ev)<=1?100:1)).toFixed(1)}%`:'—']];}
      badge=probability==null?publicText('MODEL'):confidenceLabel(confidenceBand(probability));mainValue=probability==null?'—':pct(probability);confidenceClass=probability==null?'low':confidenceBand(probability);
    }
    const p1Photo=safePhotoUrl(p1.photo_url),p2Photo=safePhotoUrl(p2.photo_url),fallback=playerFallbackUrl(row?.tour);const avatar=(photo,name)=>{const src=photo||fallback;return src?`<span class="player-avatar has-photo"><img src="${escapeHtml(src)}" alt="" loading="lazy" /></span>`:`<span class="player-avatar">${escapeHtml(initials(name))}</span>`};const p1Name=p1.name||row?.player1_name||'Player 1',p2Name=p2.name||row?.player2_name||'Player 2';
    const metricHtml=metrics.map(([label,value])=>{const raw=String(value??'');const tone=raw.trim().startsWith('+')?' metric-positive':raw.trim().startsWith('-')?' metric-negative':'';return `<span class="card-metric${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(raw)}</strong></span>`}).join('');
    const footer=`<div class="card-metrics-bar match-kpi-bar">${metricHtml}<button class="card-more-link" type="button" data-route="${escapeHtml(key)}">${escapeHtml(publicText('See more →'))}</button></div>`;
    const optionalNote=note&&!compact?`<div class="market-card-note">${escapeHtml(note)}</div>`:'';
    return `<article class="prediction-card featured market-card match-card-v3${projectionOnly?' projection-card':''}${compact?' dashboard-preview-card':''}"><div class="card-meta match-card-meta"><span class="tour">${escapeHtml(String(row?.tour||'').toUpperCase())} ${escapeHtml(row?.tournament||row?.competition||'')}</span><span class="time">${escapeHtml(fmtTime(row?.scheduled_at||row?.date))}</span><span class="surface">${escapeHtml(String(row?.surface||key).replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row match-players-row"><div class="player">${avatar(p1Photo,p1Name)}<strong class="player-name">${escapeHtml(p1Name)}</strong><small class="player-rank">${escapeHtml(playerMetaLabel(p1.rank,p1.country_code))}</small></div><div class="vs match-vs">VS</div><div class="player">${avatar(p2Photo,p2Name)}<strong class="player-name">${escapeHtml(p2Name)}</strong><small class="player-rank">${escapeHtml(playerMetaLabel(p2.rank,p2.country_code))}</small></div></div><div class="pick-row match-pick-row"><div class="pick-copy"><small>${escapeHtml(pickLabel)}</small><strong class="pick-name">${escapeHtml(pick)}</strong></div><div class="pick-score"><div class="probability">${mainValue}</div><span class="confidence ${confidenceClass}">${escapeHtml(badge)}</span></div></div>${optionalNote}${footer}</article>`;
  }

  function renderMarketSection(key,hostId,emptyText){
    const host=$(hostId);if(!host)return;
    const rows=marketRows(key),ent=dashboardPlanEntitlement(key);
    const serverTotal=Number(ent?.total);
    const total=Number.isFinite(serverTotal)?Math.max(rows.length,serverTotal):rows.length;
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
    const count=$(key==='top_daily'?'topDailyCount':`${key}Count`);if(count)count.textContent=locale==='en'?`${rows.length} ${rows.length===1?'pick':'picks'}`:`${rows.length} ${locale==='cz'?'tipů':'tipov'}`;
    const seeCount=$(key==='top_daily'?'topDailySeeAllCardCount':`${key}SeeAllCardCount`);if(seeCount)seeCount.textContent=publicText(`${rows.length} published`);
    const shell=host.closest('.market-carousel-shell');if(shell){const prev=shell.querySelector('[data-market-prev]'),next=shell.querySelector('[data-market-next]');if(prev){prev.hidden=pageCount<=1;prev.disabled=state.marketPage[key]<=0;}if(next){next.hidden=pageCount<=1;next.disabled=state.marketPage[key]>=pageCount-1;}}
  }
  function renderMarketSections(){renderMarketSection('top_daily','topDailyGrid',publicText('No Top Bets available yet. New qualifying picks appear automatically.'));renderMarketSection('value','valueGrid',publicText('No Value Picks available yet. We are waiting for qualifying opportunities.'));renderMarketSection('doubles','doublesGrid',publicText('No Doubles picks have been published yet.'));renderMarketSection('ace','aceGrid',publicText('No Ace Picks available yet. New projections appear automatically.'));renderMarketSection('sg','sgGrid',publicText('No Sets / Games picks available yet. New projections appear automatically.'));translatePublicDom(document.body);}

  function signalMeta(signal,m){ const id=String(signal?.player_id ?? signal?.favours_player_id ?? ''); const favours=id===String(m.pickId); const label=translateSignalLabel(signal?.label||signal?.factor||'Model signal'); return {label,favours}; }
  function renderSignal(signal,m){ const s=signalMeta(signal,m); return `<div class="signal-row"><span>${escapeHtml(s.label)}</span><div class="signal-meter"><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i class="${s.favours?'positive':'counter'}"></i><i></i><i></i></div></div>`; }
  function setPlayerIdentity(box,name,rank,country,photo,tour){
    const avatar=box.querySelector('.player-avatar'),fallbackText=initials(name),fallback=playerFallbackUrl(tour),safe=safePhotoUrl(photo);
    avatar.textContent=fallbackText;avatar.classList.remove('has-photo');
    const install=src=>{if(!src)return;const img=document.createElement('img');img.src=src;img.alt='';img.loading='lazy';img.addEventListener('error',()=>{if(src!==fallback&&fallback){install(fallback);return;}avatar.classList.remove('has-photo');avatar.textContent=fallbackText},{once:true});avatar.textContent='';avatar.classList.add('has-photo');avatar.replaceChildren(img);};
    install(safe||fallback);
    box.querySelector('.player-name').textContent=name;box.querySelector('.player-rank').textContent=playerMetaLabel(rank,country);
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
    const bettingRow=card.querySelector('.betting-row');if(bettingRow){bettingRow.hidden=false;const oddsNode=card.querySelector('.betting-odds'),edgeNode=card.querySelector('.betting-edge'),evNode=card.querySelector('.betting-ev');if(oddsNode)oddsNode.innerHTML=`<small>${escapeHtml(publicText('Odds'))}</small><strong>${Number.isFinite(m.odds)&&m.odds>1?m.odds.toFixed(2):'—'}</strong>`;if(edgeNode){edgeNode.classList.toggle('metric-positive',Number.isFinite(m.edge)&&m.edge>=0);edgeNode.classList.toggle('metric-negative',Number.isFinite(m.edge)&&m.edge<0);edgeNode.innerHTML=`<small>${escapeHtml(lcopy('Edge','Výhoda','Výhoda'))}</small><strong>${Number.isFinite(m.edge)?`${m.edge>=0?'+':''}${(m.edge*100).toFixed(1)} pp`:'—'}</strong>`;}if(evNode){evNode.classList.toggle('metric-positive',Number.isFinite(m.expectedValue)&&m.expectedValue>=0);evNode.classList.toggle('metric-negative',Number.isFinite(m.expectedValue)&&m.expectedValue<0);evNode.innerHTML=`<small>EV</small><strong>${Number.isFinite(m.expectedValue)?`${m.expectedValue>=0?'+':''}${(m.expectedValue*100).toFixed(1)}%`:'—'}</strong>`;}}
    // Dashboard is intentionally a lightweight preview. Full section pages contain 3–5 picks.
    const signals=card.querySelector('.signals');if(signals){signals.hidden=true;signals.innerHTML='';}
    const analysis=card.querySelector('.analysis-link');if(analysis){analysis.hidden=false;analysis.dataset.route='prime';analysis.textContent=publicText('See more →');analysis.onclick=null;}
    return template;
  }


  function renderDots(pageCount){ const host=$('carouselDots'); if(!host)return; host.innerHTML=''; if(pageCount<=1)return; for(let i=0;i<pageCount;i++){const b=document.createElement('button');b.type='button';b.className=i===state.page?'active':'';b.setAttribute('aria-label',`Show Prime Picks page ${i+1}`);b.onclick=()=>{state.page=i;renderPredictions()};host.appendChild(b)} }
  function renderPredictions(){
    const allRows=rankedPredictions(),ent=dashboardPlanEntitlement('prime'),serverTotal=Number(ent?.total),total=Number.isFinite(serverTotal)?Math.max(allRows.length,serverTotal):allRows.length,limit=dashboardPreviewLimit('prime',total||1),previewCount=Math.min(total,limit),grid=$('predictionGrid'),size=dashboardCardsPerPanel();if(!grid)return;
    $('matchCount').textContent=total;const primeSeeCount=$('primeSeeAllCardCount');if(primeSeeCount)primeSeeCount.textContent=publicText(`${total} published`);
    const pageCount=Math.max(1,Math.ceil(previewCount/size));state.page=Math.min(state.page,pageCount-1);const start=state.page*size,end=Math.min(previewCount,start+size);
    grid.classList.remove('show-all');grid.innerHTML='';
    if(!previewCount)grid.innerHTML='<div class="state-card">No Prime Picks available yet. This board updates automatically when new picks qualify.</div>';
    else for(let absoluteIndex=start;absoluteIndex<end;absoluteIndex++){const m=allRows[absoluteIndex];if(m)grid.appendChild(renderCard(m,Number.isInteger(m.accessIndex)?m.accessIndex:absoluteIndex));else grid.insertAdjacentHTML('beforeend',lockedPickCard('prime',absoluteIndex));}
    grid.style.setProperty('--visible-cards',String(Math.max(1,end-start)));window.BlinqUI.pager(grid,state.page,pageCount);
    $('prevPick').hidden=pageCount<=1;$('nextPick').hidden=pageCount<=1;$('prevPick').disabled=state.page<=0;$('nextPick').disabled=state.page>=pageCount-1;renderDots(pageCount);renderDashboardComposition();applyAccessStates(grid);translatePublicDom(grid);
  }

  function openMatch(m){ const signalRows=m.signals.length?m.signals.map(s=>{const meta=signalMeta(s,m);const favoursId=String(s?.player_id??s?.favours_player_id??'');const favours=favoursId===String(m.p1Id)?m.p1:favoursId===String(m.p2Id)?m.p2:'—';return `<div class="dialog-signal"><span>${escapeHtml(meta.label)}</span><strong>${escapeHtml(favours)}</strong><small>${meta.favours?'supports pick':'counter-signal'}</small></div>`}).join(''):'<p class="signal-empty">No secondary signals are available.</p>'; const betting=Number.isFinite(m.odds)&&m.odds>1?`<div class="dialog-section dialog-market"><h3>Current market snapshot</h3><div class="dialog-market-grid"><span>Odds <strong>${m.odds.toFixed(2)}</strong></span><span>Model edge <strong>${Number.isFinite(m.edge)?`${m.edge>=0?'+':''}${(m.edge*100).toFixed(1)} pp`:'—'}</strong></span><span>EV <strong>${Number.isFinite(m.expectedValue)?`${m.expectedValue>=0?'+':''}${(m.expectedValue*100).toFixed(1)}%`:'—'}</strong></span></div></div>`:''; $('dialogContent').innerHTML=`<div class="dialog-eyebrow">${escapeHtml(m.tour)} · ${escapeHtml(m.tournament)}</div><h2>${escapeHtml(m.p1)} <span>vs</span> ${escapeHtml(m.p2)}</h2><div class="dialog-pick"><div><small>BlinQ Pick</small><strong>${escapeHtml(m.pick)}</strong></div><div class="dialog-prob">${pct(m.probability)} <span class="confidence ${m.confidence}">${m.confidence==='very-high'?'VERY HIGH':m.confidence.toUpperCase()}</span></div></div>${betting}<div class="dialog-section"><h3>Model signals</h3>${signalRows}</div><div class="dialog-meta"><span>${escapeHtml(String(m.surface).replaceAll('_',' '))}</span><span>${fmtDate(m.date)} · ${fmtTime(m.date)}</span><span>Model ${escapeHtml(m.model||'—')}</span></div>`; $('matchDialog').showModal(); }

  const routeMetaEn={
    predictions:['TENNIS INTELLIGENCE','Dashboard','Prime Picks, daily selections, market picks and current BlinQ intelligence.'],prime:['MATCH WINNER','Prime Picks','Accuracy-first Match Winner picks; preferred odds 1.20–1.50, without a hard odds band.'],top_daily:['CONFIDENCE FIRST','Top Bets','Strongest remaining Match Winner picks, ranked by model probability and data quality.'],value:['VALUE EDGE','Value Picks','Higher-priced model-vs-market opportunities with stricter edge and EV guardrails.'],doubles:['DOUBLES','Doubles','Separate doubles model and team-pair intelligence.'],ace:['ACES + DOUBLE FAULTS','Ace Picks','Top Aces and Double Faults market selections.'],sg:['SETS + GAMES','S/G Picks','Top Sets and Games market selections.'],results:['SETTLED PICKS','Results','Settled selections, hit rate, ROI, units and related performance statistics.'],btts:['FOOTBALL · BETA','BTTS Bonus','Both Teams To Score is prepared as a separate BlinQ beta module.'],account:['BLINQ MEMBERS','Account','Profile, security, membership and access.'],admin:['BLINQ CONTROL','Admin Control Center','Internal model performance, backtests, publishing, access and workspace configuration.'],how_blinq_works:['LEARN','How BlinQ Works','How the BlinQ workflow turns point-in-time tennis data into probabilities.'],methodology:['LEARN','Methodology','The principles used to keep predictions point-in-time and auditable.'],model_data:['LEARN','Model & Data','What the published feed exposes about data and model state.'],faq:['LEARN','FAQ','Common questions about probabilities, results and model output.'],responsible_use:['LEARN','Responsible Use','Use probabilities as information, never as guarantees.']
  };
  const routeMetaSk={
    predictions:['TENISOVÁ ANALYTIKA','Prehľad','Prime tipy, denné výbery, trhové tipy a aktuálna BlinQ analytika.'],prime:['VÍŤAZ ZÁPASU','Prime tipy','Tipy na víťaza zápasu orientované na presnosť; preferovaný kurz 1,20–1,50 bez pevného kurzového pásma.'],top_daily:['ISTOTA NA PRVOM MIESTE','Top tipy','Najsilnejšie zostávajúce tipy na víťaza zápasu zoradené podľa pravdepodobnosti modelu a kvality dát.'],value:['VALUE VÝHODA','Value tipy','Príležitosti s vyšším kurzom, kde model nachádza výhodu oproti trhu a používa prísnejšie EV pravidlá.'],doubles:['ŠTVORHRA','Štvorhra','Samostatný model štvorhry a inteligencia dvojíc/tímov.'],ace:['ESÁ + DVOJCHYBY','Esá','Najlepšie projekcie pre esá a dvojchyby.'],sg:['SETY + HRY','Sety / hry','Najlepšie projekcie pre sety a počet hier.'],results:['VYHODNOTENÉ TIPY','Výsledky','Vyhodnotené tipy, úspešnosť, ROI, jednotky a súvisiace štatistiky výkonu.'],btts:['FUTBAL · BETA','BTTS Bonus','Both Teams To Score je pripravený ako samostatný beta modul BlinQ.'],account:['BLINQ ČLENSTVO','Účet','Profil, zabezpečenie, členstvo a prístup.'],how_blinq_works:['INFO','Ako funguje BlinQ','Ako BlinQ mení point-in-time tenisové dáta na pravdepodobnosti.'],methodology:['INFO','Metodika','Princípy, ktoré udržujú predikcie point-in-time a auditovateľné.'],model_data:['INFO','Model a dáta','Čo publikovaný feed ukazuje o dátach a stave modelu.'],faq:['INFO','FAQ','Najčastejšie otázky o pravdepodobnostiach, výsledkoch a výstupe modelu.'],responsible_use:['INFO','Zodpovedné používanie','Pravdepodobnosti používaj ako informáciu, nikdy nie ako záruku.']
  };
  const routeMetaCz={
    predictions:['TENISOVÁ ANALYTIKA','Přehled','Prime tipy, denní výběry, tržní tipy a aktuální BlinQ analytika.'],prime:['VÍTĚZ ZÁPASU','Prime tipy','Tipy na vítěze zápasu orientované na přesnost; preferovaný kurz 1,20–1,50 bez pevného kurzového pásma.'],top_daily:['JISTOTA NA PRVNÍM MÍSTĚ','Top tipy','Nejsilnější zbývající tipy na vítěze zápasu seřazené podle pravděpodobnosti modelu a kvality dat.'],value:['VALUE VÝHODA','Value tipy','Příležitosti s vyšším kurzem, kde model nachází výhodu oproti trhu a používá přísnější EV pravidla.'],doubles:['ČTYŘHRA','Čtyřhra','Samostatný model čtyřhry a inteligence dvojic/týmů.'],ace:['ESA + DVOJCHYBY','Esa','Nejlepší projekce pro esa a dvojchyby.'],sg:['SETY + HRY','Sety / hry','Nejlepší projekce pro sety a počet her.'],results:['VYHODNOCENÉ TIPY','Výsledky','Vyhodnocené tipy, úspěšnost, ROI, jednotky a související statistiky výkonu.'],btts:['FOTBAL · BETA','BTTS Bonus','Both Teams To Score je připraven jako samostatný beta modul BlinQ.'],account:['BLINQ ČLENSTVÍ','Účet','Profil, zabezpečení, členství a přístup.'],how_blinq_works:['INFO','Jak funguje BlinQ','Jak BlinQ mění point-in-time tenisová data na pravděpodobnosti.'],methodology:['INFO','Metodika','Principy, které udržují predikce point-in-time a auditovatelné.'],model_data:['INFO','Model a data','Co publikovaný feed ukazuje o datech a stavu modelu.'],faq:['INFO','FAQ','Nejčastější otázky o pravděpodobnostech, výsledcích a výstupu modelu.'],responsible_use:['INFO','Zodpovědné používání','Pravděpodobnosti používej jako informaci, nikdy ne jako záruku.']
  };
  const routeMeta=locale==='sk'?{...routeMetaEn,...routeMetaSk}:locale==='cz'?{...routeMetaEn,...routeMetaCz}:routeMetaEn;

  function setRoute(route,push=true){ if(!routeMeta[route]) route='predictions'; if(route==='admin'&&!isAdminAccount()) route='predictions'; const section=dashboardSectionKeys.includes(route)?dashboardSectionConfig(route):null; if(section&&route!=='predictions'&&elementAccess(section.sidebar_element)!=='active'&&state.route!=='admin'){showUpgradePrompt(firstUnlockPlan(route,0,true),section.label||route);route='predictions';} if(route==='admin') state.previewPlan=null; const routeChanged=state.route!==route;state.route=route;if(routeChanged)state.page=0;const meta=routeMeta[route]; const overview=route==='predictions'; const routeHeading=$('routeHeading'); if(routeHeading) routeHeading.hidden=overview; $('pageEyebrow').textContent=meta[0]; $('pageTitle').textContent=meta[1]; $('pageSubtitle').textContent=meta[2]; const topbar=document.querySelector('.dashboard-topbar'); if(topbar) topbar.classList.toggle('overview-mode',overview); $('predictionsView').hidden=!overview; $('routePanel').hidden=overview; renderNavigation(); if(overview){renderPredictions();renderMarketSections();renderDashboardResultsPreview();applyAccessStates();} else renderRoute(route); if(push&&location.hash!==`#${route}`) history.pushState(null,'',`#${route}`); window.BlinqUI.routeChanged(route,push); updateLanguageLinks(); document.title=`${meta[1]} · BlinQ`; if(route!=='admin')translatePublicDom(document.body); }

  function metricCards(items){ return `<div class="metric-cards">${items.map(([label,value,note])=>`<div class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note||'')}</span></div>`).join('')}</div>`; }
  function issuedMarketPublications(row){
    return (Array.isArray(row?.market_publications)?row.market_publications:[]).filter(p=>p&&p.issued_at&&p.result&&!p.excluded_reason);
  }
  function resultTags(row){
    const tags=[];
    issuedMarketPublications(row).forEach(p=>{const section=String(p.section||'');if(section&&!tags.includes(section))tags.push(section);});
    return tags;
  }
  function resultCategoryLabel(value){const en=({all:'All published',prime:'Prime',top_daily:'Top Bet',value:'Value',doubles:'Doubles',ace:'Aces',double_faults:'Double Faults',sets:'Sets',games:'Games'})[value]||String(value||'').replaceAll('_',' ');if(locale==='sk')return ({'All published':'Všetky publikované','Top Bet':'Top tip','Doubles':'Štvorhra','Aces':'Esá','Double Faults':'Dvojchyby','Sets':'Sety','Games':'Hry'})[en]||en;if(locale==='cz')return ({'All published':'Všechny publikované','Top Bet':'Top tip','Doubles':'Čtyřhra','Aces':'Esa','Double Faults':'Dvojchyby','Sets':'Sety','Games':'Hry'})[en]||en;return en;}
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
    return `<div class="results-filter-bar"><label>${escapeHtml(publicText('Category'))}<select id="resultsCategory">${['all','prime','top_daily','value','doubles','ace','double_faults','sets','games'].map(v=>option(v,resultCategoryLabel(v),filters.category||'all')).join('')}</select></label><label>${escapeHtml(publicText('Tour'))}<select id="resultsTour">${option('',publicText('All Tours'),filters.tour||'')}${tours.map(v=>option(v,v,filters.tour||'')).join('')}</select></label><label>${escapeHtml(publicText('Surface'))}<select id="resultsSurface">${option('',publicText('All Surfaces'),filters.surface||'')}${surfaces.map(v=>option(v,v.replaceAll('_',' '),filters.surface||'')).join('')}</select></label><label>${escapeHtml(publicText('Period'))}<select id="resultsWindow">${[['all',publicText('All time')],['7',publicText('7 days')],['30',publicText('30 days')],['90',publicText('90 days')]].map(([v,l])=>option(v,l,filters.window||'all')).join('')}</select></label></div>`;
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
    if(plan.lifetime)return 'Unlimited / lifetime';
    const days=Number(plan.duration_days); return Number.isFinite(days)&&days>0?`${days} days`:'Manual expiration';
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
    const hero=heroItems().map(item=>adminMiniBlock(item.id,true)).join('')||'BANNER OFF';
    const ordered=orderedDashboardKeys(state.adminPlan);
    const sections=ordered.map(key=>{const cfg=dashboardSectionConfig(key);const id=Object.keys({PRIME_PICKS_PANEL:'prime',TOP_DAILY_PANEL:'top_daily',VALUE_PICKS_PANEL:'value',DOUBLES_PANEL:'doubles',ACE_PICKS_PANEL:'ace',SG_PICKS_PANEL:'sg'}).find(x=>adminDashboardSectionKeyForElement(x)===key);return id?adminMiniBlock(id,false,'',`ORDER ${sectionPlanOrder(key,state.adminPlan)}`):'';}).join('');
    const extra=adminMiniBlock('RESULTS_PANEL')+adminMiniBlock('BTTS_BONUS_PANEL');
    return `<div class="admin-canvas admin-canvas-v658"><div class="admin-canvas-header"><div class="admin-logo-lock">BLINQ LOGO<br><small>FIXED</small></div><div class="admin-header-slots row-count-${headerCount}">${headerBlocks||'<div class="admin-row-off-label">TOP CTA OFF</div>'}</div><div class="admin-account-lock">PLANS · USER<br><small>FIXED</small></div></div><div class="admin-topnav-map"><b>TOP NAVIGATION</b><div>${nav}</div></div><div class="admin-canvas-main admin-canvas-main-full"><div class="admin-hero-lock admin-hero-rotator"><strong>MAIN ROTATING BANNER</strong><span>${hero}</span><small>${Math.max(3,Math.min(300,Number(state.ui?.hero_banner?.rotation_seconds)||10))} sec rotation · up to 5 slides</small></div><div class="admin-row-caption"><span>DASHBOARD SECTIONS · ${escapeHtml(accessLabel(state.adminPlan))}</span><b>Drag-free ordering via ORDER field</b></div><div class="admin-dashboard-section-map">${sections}</div><div class="admin-functional-row">${extra}</div></div></div>`;
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
    if(!['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind)) return '<p class="admin-muted">Functional dashboard element. Use the Dashboard display block below to configure its public placement and pick visibility.</p>';
    const sidebarDestination=item.kind==='sidebar_promo'?`<div class="admin-link-callout span-2"><div><strong>Sidebar banner destination</strong><span>The whole banner is clickable. Use an external https:// URL or an internal #route.</span></div><label>Banner click URL<input data-admin-content="link" value="${escapeHtml(c.link||'')}" placeholder="https://... or #account"></label></div>`:'';
    const standardDestination=item.kind!=='sidebar_promo'?`<label>Destination URL / link<input data-admin-content="link" value="${escapeHtml(c.link||'')}" placeholder="https://... or #account"></label>`:'';
    return `<div class="admin-field-grid">
      ${sidebarDestination}
      <label>Content type<select data-admin-content="type"><option value="internal"${c.type==='internal'?' selected':''}>Internal</option><option value="advertisement"${c.type==='advertisement'?' selected':''}>Advertisement</option><option value="image"${c.type==='image'?' selected':''}>Image</option><option value="promo"${(!c.type||c.type==='promo')?' selected':''}>Promo</option></select></label>
      <label>Theme<select data-admin-content="theme">${['violet','blue','purple','green','gold'].map(v=>`<option value="${v}"${v===(c.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label>
      <div class="field-hint-box span-2">${escapeHtml(item.kind==='large_banner'?`The outer zone width is fixed. Active banners divide it equally. Current creative: ${creativeSpecText(item)}.`:`Fixed creative: ${creativeSpecText(item)}.`)}</div>
      <label class="check-field"><input type="checkbox" data-admin-content="enabled" ${c.enabled!==false?'checked':''}> Content enabled</label>
      <label>Campaign<select data-admin-content="campaign_id">${campaignOptions(String(c.campaign_id||''))}</select></label>
      <label>Advertiser ID<input data-admin-content="advertiser_id" value="${escapeHtml(c.advertiser_id||'')}" placeholder="inline / fallback advertiser"></label>
      <label>Plan avatar<select data-admin-content="plan_id"><option value="">None</option>${['rookie','pro','elite','legend','goat'].map(v=>`<option value="${v}"${v===String(c.plan_id||'').toLowerCase()?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label>Icon / emoji<input data-admin-content="icon" value="${escapeHtml(c.icon||'')}" placeholder="✈"></label>
      <label>Eyebrow<input data-admin-content="eyebrow" value="${escapeHtml(c.eyebrow||'')}"></label>
      <label>Headline<input data-admin-content="headline" value="${escapeHtml(c.headline||'')}"></label>${item.kind==='hero_banner'?`<label>Accent line<input data-admin-content="accent_text" value="${escapeHtml(c.accent_text||'')}" placeholder="Better Decisions."></label>`:''}
      <label class="span-2">Text<textarea data-admin-content="text" rows="3">${escapeHtml(c.text||'')}</textarea></label>
      <label>CTA text<input data-admin-content="button_text" value="${escapeHtml(c.button_text||'')}"></label>
      ${standardDestination}
      <label>Internal route (optional)<input data-admin-content="route" value="${escapeHtml(c.route||'')}"></label>
      ${item.kind==='hero_banner'?`<div class="admin-link-callout span-2 hero-image-callout"><div><strong>Main banner image</strong><span>Replace the hero creative here. Use /assets/filename.webp for a repo asset or a full https:// image URL. The mobile image is optional.</span></div></div><label class="check-field"><input type="checkbox" data-admin-content="show_copy" ${c.show_copy!==false?'checked':''}> Show text over banner</label><label>Creative mode<select data-admin-content="creative_mode"><option value="split"${(c.creative_mode||'split')==='split'?' selected':''}>Split · image + copy</option><option value="full"${c.creative_mode==='full'?' selected':''}>Full image creative</option></select></label>`:''}
      <label class="span-2">${item.kind==='hero_banner'?'Main desktop image path / URL':'Desktop image path / URL'}<input data-admin-content="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/... or https://..."></label>
      <label class="span-2">Mobile image (optional)<input data-admin-content="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="Optional mobile-specific creative"></label>
      ${item.kind==='hero_banner'&&c.image_url?`<div class="admin-hero-image-preview span-2"><img src="${escapeHtml(safeLink(c.image_url,''))}" alt="Current main banner preview"><small>Current main banner image</small></div>`:''}
      <label>Image fit<select data-admin-content="image_fit"><option value="cover"${(c.image_fit||'cover')==='cover'?' selected':''}>Cover · fill slot</option><option value="contain"${c.image_fit==='contain'?' selected':''}>Contain · show whole image</option></select></label>
      <label>Image position<select data-admin-content="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(c.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label>Show from · optional<input data-admin-content="active_from" type="datetime-local" value="${escapeHtml(c.active_from||'')}"></label>
      <label>Show until · optional<input data-admin-content="active_until" type="datetime-local" value="${escapeHtml(c.active_until||'')}"></label>
      <label>When ad is unavailable<select data-admin-content="ad_hidden_fallback">${['auto','image','internal'].map(v=>`<option value="${v}"${v===(c.ad_hidden_fallback||'auto')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
      <label class="check-field"><input type="checkbox" data-admin-content="sponsored" ${c.sponsored?'checked':''}> Sponsored label</label>
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
    const rows=accessContexts.map(plan=>{const ent=cfg.plans?.[plan]||cfg.plans?.rookie||{},options=choices.map(v=>`<option value="${escapeHtml(v)}"${String(ent.visible_picks).toUpperCase()===String(v).toUpperCase()?' selected':''}>${escapeHtml(v)}</option>`).join(''),order=Number(ent.order||cfg.dashboard_order||99);return `<div class="admin-plan-rule" data-dashboard-plan-row="${escapeHtml(plan)}"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</b><label>Visible picks<select data-dashboard-matrix-field="visible_picks">${options}</select></label><label>Order<input type="number" min="1" max="20" data-dashboard-matrix-field="order" value="${order}"></label><label class="check-field"><input type="checkbox" data-dashboard-matrix-field="blur_remaining" ${ent.blur_remaining!==false?'checked':''}> Blur rest</label><label class="check-field"><input type="checkbox" data-dashboard-matrix-field="see_all" ${ent.see_all?'checked':''}> See more</label></div>`;}).join('');
    return `<div class="admin-section dashboard-inspector-section" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-title"><strong>Section rules · ${escapeHtml(cfg.label||key)}</strong><span>Set visibility, teaser depth and order independently for every membership level.</span></div><div class="admin-field-grid"><label class="check-field"><input type="checkbox" data-dashboard-field="sidebar_enabled" ${cfg.sidebar_enabled!==false?'checked':''}> Show in top navigation</label><label class="check-field"><input type="checkbox" data-dashboard-field="dashboard_enabled" ${cfg.dashboard_enabled!==false?'checked':''}> Section enabled</label><label>Preview pool<select data-dashboard-field="preview_limit">${preview}</select></label></div><div class="admin-plan-rules">${rows}</div><small class="field-hint">Visible picks = 0 + Blur rest means the section remains visible but every pick is blurred. Order can be different for ROOKIE, PRO, ELITE, LEGEND and GOAT.</small></div>`;
  }
  function bannerAudienceEditor(item){
    if(!['header_slot','hero_banner','large_banner','sidebar_promo'].includes(item.kind))return '';
    item.click_access=item.click_access||{};
    return `<div class="admin-section"><div class="admin-section-title"><strong>Audience / link access</strong><span>Choose who can see this banner and who may open its link.</span></div><div class="admin-audience-grid">${accessContexts.map(plan=>{const visible=elementAccess(item.id,plan)!=='hidden',click=item.click_access?.[plan]!==false;return `<div class="admin-audience-row"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</b><label><input type="checkbox" data-banner-visible-plan="${escapeHtml(plan)}" ${visible?'checked':''}> Visible</label><label><input type="checkbox" data-banner-click-plan="${escapeHtml(plan)}" ${click?'checked':''}> Link active</label></div>`;}).join('')}</div><small class="field-hint">Example: keep a PRO Telegram banner visible to ROOKIE, but disable its link. ROOKIE sees the offer with a lock instead of entering the premium group.</small></div>`;
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
    const choices=state.ui?.admin?.dashboard_preview_choices||[0,1,2,3,4,5,'ALL'];
    return choices.map(v=>`<option value="${escapeHtml(v)}"${String(selected).toUpperCase()===String(v).toUpperCase()?' selected':''}>${String(v).toUpperCase()==='ALL'?'ALL':v}</option>`).join('');
  }
  function adminSectionRouteAccess(key,plan){
    const id=dashboardSectionConfig(key).sidebar_element;
    return id?elementAccess(id,plan):'active';
  }
  function adminSectionAccessOptions(selected){
    const normalized=selected==='blurred'?'locked':selected;
    const choices=[['active','OPEN'],['locked','VISIBLE · LOCKED'],['hidden','HIDDEN']];
    return choices.map(([value,label])=>`<option value="${value}"${value===normalized?' selected':''}>${label}</option>`).join('');
  }
  function adminSectionPresetButtons(key){
    const plan=state.adminPlan,label=state.ui?.plans?.[plan]?.label||plan.toUpperCase();
    return `<div class="admin-section-presets"><span>Quick setup · ${escapeHtml(label)}</span><div><button type="button" data-section-preset="full" data-section-key="${escapeHtml(key)}">Full access</button><button type="button" data-section-preset="teaser" data-section-key="${escapeHtml(key)}">1 visible + blur</button><button type="button" data-section-preset="blurred" data-section-key="${escapeHtml(key)}">All blurred</button><button type="button" data-section-preset="hidden" data-section-key="${escapeHtml(key)}">Hide for level</button></div></div>`;
  }
  function adminSectionRuleRow(key,plan,compact=false){
    const cfg=dashboardSectionConfig(key),ent=cfg.plans?.[plan]||cfg.plans?.rookie||{};
    const order=Number(ent.order||cfg.dashboard_order||99),routeAccess=adminSectionRouteAccess(key,plan);
    return `<div class="admin-section-rule-row${compact?' compact':''}" data-dashboard-plan-row="${escapeHtml(plan)}"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}</b><label><span>Page access</span><select data-dashboard-route-access>${adminSectionAccessOptions(routeAccess)}</select></label><label><span>Visible picks</span><select data-dashboard-matrix-field="visible_picks">${adminVisiblePickOptions(ent.visible_picks)}</select></label><label><span>Order</span><input type="number" min="1" max="20" data-dashboard-matrix-field="order" value="${order}"></label><label class="admin-toggle-line"><input type="checkbox" data-dashboard-matrix-field="blur_remaining" ${ent.blur_remaining!==false?'checked':''}><span>Blur rest</span></label><label class="admin-toggle-line"><input type="checkbox" data-dashboard-matrix-field="see_all" ${ent.see_all?'checked':''}><span>See more</span></label></div>`;
  }
  function renderAdminSectionCard(key){
    const cfg=dashboardSectionConfig(key),ent=cfg.plans?.[state.adminPlan]||cfg.plans?.rookie||{};
    const enabled=cfg.dashboard_enabled!==false,nav=cfg.sidebar_enabled!==false;
    const order=Number(ent.order||cfg.dashboard_order||99);
    return `<article class="admin-section-card" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-card-head"><div><small>ORDER ${order}</small><h3>${escapeHtml(cfg.label||key)}</h3></div><div class="admin-section-card-switches"><span>GLOBAL</span><label><input type="checkbox" data-dashboard-field="dashboard_enabled" ${enabled?'checked':''}> Site</label><label><input type="checkbox" data-dashboard-field="sidebar_enabled" ${nav?'checked':''}> Navigation</label></div></div>${adminSectionPresetButtons(key)}${adminSectionRuleRow(key,state.adminPlan,true)}<details class="admin-all-levels"><summary>All membership levels</summary><div class="admin-all-level-rules">${accessContexts.map(plan=>adminSectionRuleRow(key,plan)).join('')}</div></details></article>`;
  }
  function adminPageAccessRow(key,plan){
    const access=adminSectionRouteAccess(key,plan);
    return `<div class="admin-page-access-row" data-dashboard-plan-row="${escapeHtml(plan)}"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}${plan==='goat'?'<small>TOP</small>':''}</b><label><span>Page access</span><select data-dashboard-route-access>${adminSectionAccessOptions(access)}</select></label></div>`;
  }
  function renderAdminPageCard(key){
    const cfg=dashboardSectionConfig(key);
    return `<article class="admin-section-card admin-page-card" data-dashboard-section="${escapeHtml(key)}"><div class="admin-section-card-head"><div><small>NAVIGATION PAGE</small><h3>${escapeHtml(cfg.label||key)}</h3></div><div class="admin-section-card-switches"><label><input type="checkbox" data-dashboard-field="sidebar_enabled" ${cfg.sidebar_enabled!==false?'checked':''}> Top nav</label></div></div>${adminPageAccessRow(key,state.adminPlan)}<details class="admin-all-levels"><summary>All membership levels</summary><div class="admin-all-level-rules">${accessContexts.map(plan=>adminPageAccessRow(key,plan)).join('')}</div></details></article>`;
  }
  function renderAdminLayout(){
    const copyOptions=accessContexts.filter(id=>id!==state.adminPlan).map(id=>`<option value="${id}">${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</option>`).join('');
    const ordered=orderedDashboardKeys(state.adminPlan);
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>PAGE CONTROL</small><h2>Sections & access</h2><p>Pick a membership level and edit only what that member should see. Global switches affect everyone; use HIDDEN to hide a section for one level only.</p></div><button class="btn btn-ghost" type="button" data-admin-action="preview">Preview as ${escapeHtml(accessLabel(state.adminPlan))}</button></div><div class="admin-level-picker"><span>Edit rules for</span>${adminLevelChips(state.adminPlan,'admin-plan-chip',true)}</div><div class="admin-copy-strip"><label>Copy this level from<select id="adminCopyFrom">${copyOptions}</select></label><button class="btn btn-ghost" type="button" data-admin-action="copy-plan">Copy all rules → ${escapeHtml(accessLabel(state.adminPlan))}</button><small>Copies page access, pick counts, order, blur rules and banner permissions.</small></div><div class="admin-subsection-heading"><div><strong>Dashboard pick sections</strong><span>Use Quick setup for common cases, or fine-tune visible picks, order and blur below it.</span></div></div><div class="admin-section-list">${ordered.map(renderAdminSectionCard).join('')}</div><div class="admin-subsection-heading"><div><strong>Other pages</strong><span>OPEN = accessible, VISIBLE · LOCKED = shown but gated, HIDDEN = removed for that level.</span></div></div><div class="admin-section-list admin-page-list">${['results','btts'].map(renderAdminPageCard).join('')}</div></section>`;
  }


  function simpleBannerAudienceRows(id,item){
    item.click_access=item.click_access||{};
    return accessContexts.map(plan=>{
      const visible=elementAccess(id,plan)!=='hidden',click=item.click_access?.[plan]!==false;
      const label=state.ui?.plans?.[plan]?.label||plan.toUpperCase();
      return `<div class="simple-banner-audience-row"><b>${escapeHtml(label)}</b><label><input type="checkbox" data-simple-banner-visible="${escapeHtml(plan)}" ${visible?'checked':''}> Visible</label><label><input type="checkbox" data-simple-banner-click="${escapeHtml(plan)}" ${click?'checked':''}> Link active</label></div>`;
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
      <div class="admin-simple-banner-head"><div><small>${isHero?'MAIN SLIDE':'TOP CTA'} ${index}</small><h3>${escapeHtml(c.headline||item.label||id)}</h3></div><label class="admin-switch"><input type="checkbox" data-simple-banner-field="enabled" ${c.enabled!==false?'checked':''}><span>Enabled</span></label></div>
      ${simpleBannerPreview(id,item,kind)}
      <div class="admin-simple-banner-fields">
        <label>Eyebrow<input data-simple-banner-field="eyebrow" value="${escapeHtml(c.eyebrow||'')}" placeholder="COMMUNITY"></label>
        <label>Title<input data-simple-banner-field="headline" value="${escapeHtml(c.headline||'')}" placeholder="Join our Telegram community"></label>
        ${isHero?`<label>Accent line<input data-simple-banner-field="accent_text" value="${escapeHtml(c.accent_text||'')}" placeholder="Telegram komunita"></label>`:''}
        <label class="span-2">Subtitle<input data-simple-banner-field="text" value="${escapeHtml(c.text||'')}" placeholder="News · Picks · Discussions"></label>
        <label>Button text<input data-simple-banner-field="button_text" value="${escapeHtml(c.button_text||'')}" placeholder="JOIN"></label>
        <label>${isHero?'Destination / Telegram URL':'Telegram / destination URL'}<input data-simple-banner-field="link" value="${escapeHtml(c.link||'')}" placeholder="https://t.me/... or #results"></label>
        ${!isHero?`<label>Icon / emoji<input data-simple-banner-field="icon" value="${escapeHtml(c.icon||'')}" placeholder="✈"></label>`:''}
        <label>Theme<select data-simple-banner-field="theme">${themes.map(v=>`<option value="${v}"${v===(c.theme||'blue')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label>
        <label class="span-2">Desktop image URL / path<input data-simple-banner-field="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/banner.webp or https://..."></label>
        ${isHero?`<label class="span-2">Mobile image URL / path<input data-simple-banner-field="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="Optional mobile-specific image"></label><label class="admin-switch"><input type="checkbox" data-simple-banner-field="show_copy" ${c.show_copy!==false?'checked':''}><span>Show text over image</span></label>`:''}
      </div>
      <details class="simple-banner-access"><summary>Audience & link access</summary><div class="simple-banner-audience-grid">${simpleBannerAudienceRows(id,item)}</div><p>Visible can stay ON while Link active is OFF. Example: ROOKIE sees the premium Telegram banner but cannot open the group.</p></details>
    </article>`;
  }
  function bannerLibraryButton(id,index,kind){
    const item=elements()?.[id];if(!item)return '';
    const c=item.content||{},selected=state.selectedElement===id,active=c.enabled!==false,link=String(c.link||'').trim();
    return `<button type="button" class="admin-banner-library-card${selected?' selected':''}" data-admin-element="${escapeHtml(id)}"><span class="admin-banner-index">${index}</span><span><small>${kind==='hero'?'MAIN SLIDE':'TOP CTA'}</small><strong>${escapeHtml(c.headline||item.label||id)}</strong><em>${active?'ACTIVE':'OFF'}${link?' · LINKED':''}</em></span><b>›</b></button>`;
  }
  function bannerPreviewForPlan(id,item,kind,plan){
    const visible=elementAccess(id,plan)!=='hidden',click=bannerClickAllowed(item,plan),label=state.ui?.plans?.[plan]?.label||plan.toUpperCase();
    return `<div class="admin-banner-preview-wrap">${simpleBannerPreview(id,item,kind)}<div class="admin-banner-preview-state ${!visible?'hidden-state':!click?'locked-state':'active-state'}"><strong>${escapeHtml(label)}</strong><span>${!visible?'Hidden':!click?'Visible · link locked':'Visible · link active'}</span></div></div>`;
  }
  function renderBannerAccessMatrix(id,item){
    item.click_access=item.click_access||{};
    return `<div class="admin-banner-access-matrix">${accessContexts.map(plan=>{const visible=elementAccess(id,plan)!=='hidden',click=item.click_access?.[plan]!==false;return `<div class="admin-banner-access-row"><b>${escapeHtml(state.ui?.plans?.[plan]?.label||plan.toUpperCase())}${plan==='goat'?'<small>TOP</small>':''}</b><label><input type="checkbox" data-simple-banner-visible="${escapeHtml(plan)}" ${visible?'checked':''}><span>Visible</span></label><label><input type="checkbox" data-simple-banner-click="${escapeHtml(plan)}" ${click?'checked':''}><span>Link active</span></label></div>`;}).join('')}</div>`;
  }
  function renderBannerEditor(id){
    const item=elements()?.[id];if(!item)return '<div class="admin-empty-panel">Choose a banner.</div>';
    const c=item.content=item.content||{},isHero=item.kind==='hero_banner',kind=isHero?'hero':'header',themes=['blue','green','gold','purple','violet'];
    return `<article class="admin-banner-editor" data-simple-banner="${escapeHtml(id)}"><div class="admin-banner-editor-head"><div><small>${isHero?'MAIN ROTATING BANNER':'TOP CTA BANNER'}</small><h2>${escapeHtml(c.headline||item.label||id)}</h2><p>${escapeHtml(id)}</p></div><label class="admin-master-switch"><input type="checkbox" data-simple-banner-field="enabled" ${c.enabled!==false?'checked':''}><span>Enabled</span></label></div><div class="admin-banner-preview-toolbar"><span>Preview as</span>${adminLevelChips(state.adminBannerPreviewPlan,'admin-banner-preview-plan',true)}</div>${bannerPreviewForPlan(id,item,kind,state.adminBannerPreviewPlan)}<div class="admin-form-section"><div class="admin-form-section-title"><strong>Content</strong><span>Everything the visitor sees.</span></div><div class="admin-form-grid"><label>Eyebrow<input data-simple-banner-field="eyebrow" value="${escapeHtml(c.eyebrow||'')}" placeholder="COMMUNITY"></label><label>Theme<select data-simple-banner-field="theme">${themes.map(v=>`<option value="${v}"${v===(c.theme||'blue')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label class="span-2">Headline<input data-simple-banner-field="headline" value="${escapeHtml(c.headline||'')}" placeholder="Join our Telegram community"></label>${isHero?`<label class="span-2">Accent line<input data-simple-banner-field="accent_text" value="${escapeHtml(c.accent_text||'')}" placeholder="Telegram komunita"></label>`:''}<label class="span-2">Subtitle<input data-simple-banner-field="text" value="${escapeHtml(c.text||'')}" placeholder="News · Picks · Discussions"></label><label>Button text<input data-simple-banner-field="button_text" value="${escapeHtml(c.button_text||'')}" placeholder="JOIN"></label>${!isHero?`<label>Icon / emoji<input data-simple-banner-field="icon" value="${escapeHtml(c.icon||'')}" placeholder="✈"></label>`:''}</div></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Link</strong><span>Telegram, website or an internal BlinQ page.</span></div><label class="admin-wide-field">Destination URL / link<input data-simple-banner-field="link" value="${escapeHtml(c.link||'')}" placeholder="https://t.me/... or #results"></label></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Image</strong><span>Optional. Repo assets can use /assets/filename.webp.</span></div><div class="admin-form-grid"><label class="span-2">Desktop image<input data-simple-banner-field="image_url" value="${escapeHtml(c.image_url||'')}" placeholder="/assets/banner.webp or https://..."></label>${isHero?`<label class="span-2">Mobile image<input data-simple-banner-field="mobile_image_url" value="${escapeHtml(c.mobile_image_url||'')}" placeholder="Optional mobile image"></label><label class="admin-toggle-line"><input type="checkbox" data-simple-banner-field="show_copy" ${c.show_copy!==false?'checked':''}><span>Show text over image</span></label>`:''}</div></div><div class="admin-form-section audience-section"><div class="admin-form-section-title"><strong>Who can see and open it?</strong><span>Visibility and click access are separate on purpose.</span></div><div class="admin-banner-presets"><button type="button" class="btn btn-ghost" data-banner-preset="all">Everyone</button><button type="button" class="btn btn-ghost" data-banner-preset="teaser-pro">Visible to all · link PRO+</button><button type="button" class="btn btn-ghost" data-banner-preset="pro-only">PRO+ only</button><button type="button" class="btn btn-ghost" data-banner-preset="goat-only">GOAT only</button></div>${renderBannerAccessMatrix(id,item)}</div><details class="admin-advanced"><summary>Advanced options</summary><div class="admin-form-grid"><label>Active from<input type="datetime-local" data-simple-banner-field="active_from" value="${escapeHtml(String(c.active_from||'').replace('Z','').slice(0,16))}"></label><label>Active until<input type="datetime-local" data-simple-banner-field="active_until" value="${escapeHtml(String(c.active_until||'').replace('Z','').slice(0,16))}"></label></div>${watermarkEditor(item)}</details></article>`;
  }
  function renderAdminBanners(){
    const headerCount=Math.max(0,Math.min(3,Number(state.ui?.header_cta?.slot_count??3)||0));
    const heroCfg=state.ui?.hero_banner||{},heroCount=Math.max(0,Math.min(5,Number(heroCfg.slot_count??1)||0)),heroSeconds=Math.max(3,Math.min(300,Number(heroCfg.rotation_seconds)||10));
    const countOptions=(selected,max)=>[0,...Array.from({length:max},(_,i)=>i+1)].map(v=>`<option value="${v}"${Number(selected)===v?' selected':''}>${v===0?'OFF':v}</option>`).join('');
    const selected=elements()?.[state.selectedElement]&&['header_slot','hero_banner'].includes(elements()[state.selectedElement].kind)?state.selectedElement:'HEADER_BANNER_1';if(selected!==state.selectedElement)state.selectedElement=selected;
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>CONTENT CONTROL</small><h2>Banners & links</h2><p>Choose a banner on the left. Every setting for that banner appears in one editor.</p></div></div><div class="admin-banner-workspace"><aside class="admin-banner-library"><div class="admin-banner-group"><div class="admin-banner-group-head"><div><strong>Top CTA</strong><span>1–3 equal banners</span></div><select data-admin-header-count>${countOptions(headerCount,3)}</select></div>${[1,2,3].map(i=>bannerLibraryButton(`HEADER_BANNER_${i}`,i,'header')).join('')}</div><div class="admin-banner-group"><div class="admin-banner-group-head"><div><strong>Main banner</strong><span>Rotating full-width slides</span></div><select data-admin-hero-count>${countOptions(heroCfg.enabled===false?0:heroCount,5)}</select></div><div class="admin-rotation-controls"><label>Every <input type="number" min="3" max="300" step="1" data-admin-hero-seconds value="${heroSeconds}"> sec</label><label><input type="checkbox" data-admin-hero-rotate ${heroCfg.auto_rotate!==false?'checked':''}> Auto</label><label><input type="checkbox" data-admin-hero-dots ${heroCfg.show_dots!==false?'checked':''}> Dots</label></div>${[1,2,3,4,5].map(i=>bannerLibraryButton(`HERO_BANNER_${i}`,i,'hero')).join('')}</div></aside>${renderBannerEditor(selected)}</div></section>`;
  }


  function renderAdminPlans(){
    if(!membershipHierarchy.includes(state.adminPlanId))state.adminPlanId='rookie';
    const id=state.adminPlanId,p=state.ui?.plans?.[id]||{};
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>MEMBERSHIP</small><h2>Plans</h2><p>Fixed hierarchy: ROOKIE → PRO → ELITE → LEGEND → GOAT. GOAT is always the highest level.</p></div></div><div class="admin-plan-hierarchy">${membershipHierarchy.map((pid,i)=>`<button type="button" class="admin-plan-level${pid===id?' active':''}${pid==='goat'?' top-tier':''}" data-admin-plan-select="${pid}"><span>${i+1}</span><b>${escapeHtml(state.ui?.plans?.[pid]?.label||pid.toUpperCase())}</b>${pid==='goat'?'<small>TOP</small>':''}</button>`).join('<i>→</i>')}</div><article class="admin-plan-editor" data-plan-card="${escapeHtml(id)}"><div class="admin-plan-editor-preview">${planAvatarHtml(id,p)}<div><small>${escapeHtml(id.toUpperCase())}</small><h3>${escapeHtml(p.label||id.toUpperCase())}</h3><span>${escapeHtml(planTermLabel(id))}</span></div><label class="admin-master-switch"><input type="checkbox" data-plan-field="enabled" ${p.enabled!==false?'checked':''}><span>Visible / enabled</span></label></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Plan card</strong><span>Public name, description and action.</span></div><div class="admin-form-grid"><label>Plan name<input data-plan-field="label" value="${escapeHtml(p.label||id.toUpperCase())}"></label><label>Avatar artwork<select data-plan-field="avatar">${membershipHierarchy.map(v=>`<option value="${v}"${v===(p.avatar||id)?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label class="span-2">Description<textarea data-plan-field="description" rows="3">${escapeHtml(p.description||p.note||'')}</textarea></label><label>CTA label<input data-plan-field="cta_label" value="${escapeHtml(p.cta_label||'Open plan')}"></label><label>External plan URL<input data-plan-field="url" value="${escapeHtml(p.url||'')}" placeholder="https://..."></label>${id==='goat'?`<label class="span-2">GOAT invite / Telegram URL<input data-plan-field="invite_url" value="${escapeHtml(p.invite_url||'')}" placeholder="https://t.me/..."></label>`:''}</div></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Access term</strong><span>Default validity assigned when this plan is granted.</span></div><div class="admin-form-grid">${id==='goat'?`<div class="admin-fixed-term span-2"><strong>Unlimited / lifetime</strong><span>GOAT is the permanent highest tier. This cannot be downgraded here.</span></div>`:`<label>Duration (days)<input data-plan-field="duration_days" type="number" min="1" value="${p.duration_days??''}"></label><div class="admin-fixed-term"><strong>Timed membership</strong><span>Change the default number of days on the left.</span></div>`}</div></div></article></section>`;
  }
  function userDateValue(value){ if(!value)return ''; const d=new Date(value); if(Number.isNaN(d.getTime()))return ''; const pad=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
  function renderAdminUserEditor(user){
    if(!user)return '<div class="admin-user-empty">Select an account to manage its access.</div>';
    const self=String(user.id)===String(state.feed?.account?.id);
    const selectedPlan=user.plan&& !['expired','admin'].includes(user.plan)?user.plan:'';
    return `<form id="adminUserForm" class="admin-user-editor admin-user-editor-v6522"><div class="admin-user-editor-head"><span class="avatar">${escapeHtml(initials(user.name||user.email||'U'))}</span><div><small>${escapeHtml(user.id)}</small><h3>${escapeHtml(user.name||user.email||'User')}</h3><p>${escapeHtml(user.email||'')}${user.telegram_nick?` · ✈ ${escapeHtml(user.telegram_nick)}`:''}</p></div><span class="admin-current-access">${escapeHtml(user.plan_label||user.plan||'NO PLAN')} · ${escapeHtml(user.status||'—')}</span></div><div class="admin-form-section"><div class="admin-form-section-title"><strong>Membership access</strong><span>Choose a tier and validity. GOAT is the highest level.</span></div><div class="admin-form-grid"><label>Plan<select id="adminUserPlan">${planSelectOptions(selectedPlan,true)}</select><small class="field-hint" id="adminPlanTerm">${escapeHtml(selectedPlan?planTermLabel(selectedPlan):'No paid plan')}</small></label><label>Status<select id="adminUserStatus">${statusSelectOptions(user.status||'expired')}</select></label><label class="span-2">Expires at<input id="adminUserExpires" type="datetime-local" value="${escapeHtml(userDateValue(user.expires_at))}" ${user.status==='lifetime'?'disabled':''}></label></div><div class="admin-account-plan-shortcuts">${membershipHierarchy.filter(id=>state.ui?.plans?.[id]?.enabled!==false).map(id=>`<button type="button" class="admin-plan-shortcut${id==='goat'?' top-tier':''}" data-admin-user-plan="${escapeHtml(id)}"><b>${escapeHtml(state.ui?.plans?.[id]?.label||id.toUpperCase())}</b><small>${escapeHtml(planTermLabel(id))}${id==='goat'?' · TOP':''}</small></button>`).join('')}</div></div><details class="admin-advanced"><summary>Role & internal reference</summary><div class="admin-form-grid"><label>Role<select id="adminUserRole" ${self?'disabled':''}><option value="user"${user.role!=='admin'?' selected':''}>USER</option><option value="admin"${user.role==='admin'?' selected':''}>ADMIN</option></select></label><label>Payment / manual reference<input id="adminPaymentReference" maxlength="120" value="${escapeHtml(user.payment_reference||'')}" placeholder="order, note, transaction id..."></label></div></details><div class="admin-user-savebar"><div>${user.telegram_nick?`<span>Telegram: ✈ ${escapeHtml(user.telegram_nick)}</span>`:''}<span>Created ${escapeHtml(fmtDate(user.created_at))}</span><span>Last login ${escapeHtml(fmtDate(user.last_sign_in_at))}</span></div><p id="adminUserMessage" class="form-message"></p><button class="btn btn-primary" type="submit">Apply account changes</button></div>${self?'<small class="admin-muted admin-self-note">Your own ADMIN role is protected from accidental removal.</small>':''}</form>`;
  }
  function renderAdminAccounts(){
    const users=Array.isArray(state.adminUsers)?state.adminUsers:[];
    const list=state.adminUsersLoading?'<div class="state-card">Loading accounts…</div>':users.length?users.map(user=>`<button type="button" class="admin-user-row${state.adminSelectedUser?.id===user.id?' selected':''}" data-admin-user="${escapeHtml(user.id)}" data-search="${escapeHtml(`${user.email||''} ${user.name||''} ${user.telegram_nick||''} ${user.plan||''}`.toLowerCase())}"><span class="avatar">${escapeHtml(initials(user.name||user.email||'U'))}</span><span><strong>${escapeHtml(user.name||'Member')}</strong><small>${escapeHtml(user.email||'')}</small></span><b>${escapeHtml(user.plan_label||user.plan||'—')}</b><em>${escapeHtml(user.status||'—')}</em></button>`).join(''):'<div class="admin-user-empty">No accounts loaded. Admin account management is not configured in the runtime.</div>';
    return `<section class="admin-ux-section"><div class="admin-ux-heading"><div><small>MEMBERS</small><h2>Accounts</h2><p>Account changes are applied directly to the selected member; they do not require Publish changes.</p></div></div><div class="admin-accounts-toolbar"><label class="search-box"><span>⌕</span><input id="adminUserSearch" type="search" placeholder="Search by name, email or Telegram…"></label><button class="btn btn-ghost" type="button" data-admin-action="refresh-users">↻ Refresh users</button></div><div class="admin-accounts-grid"><div class="admin-user-list">${list}</div>${renderAdminUserEditor(state.adminSelectedUser)}</div></section>`;
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
    const spec1=specs.large_1||{},spec2=specs.large_2||{},spec3=specs.large_3||{},spec4=specs.large_4||{};
    const editor=selected?`<form id="adminCampaignForm" class="campaign-editor"><div class="admin-inspector-head"><small>${escapeHtml(state.adminCampaignId)}</small><h3>${escapeHtml(selected.name||state.adminCampaignId)}</h3><span>Campaign creative and scheduling</span></div><div class="admin-field-grid"><label>Name<input data-campaign-field="name" value="${escapeHtml(selected.name||'')}"></label><label>Advertiser<select data-campaign-field="advertiser_id">${advertiserOptions(String(selected.advertiser_id||''))}</select></label><label class="check-field"><input type="checkbox" data-campaign-field="enabled" ${selected.enabled!==false?'checked':''}> Enabled</label><label class="check-field"><input type="checkbox" data-campaign-field="sponsored" ${selected.sponsored!==false?'checked':''}> Sponsored label</label><label>Creative mode<select data-campaign-field="creative_mode"><option value="full"${(selected.creative_mode||'full')==='full'?' selected':''}>Full image banner</option><option value="split"${selected.creative_mode==='split'?' selected':''}>Image + BlinQ text</option></select></label><label class="check-field"><input type="checkbox" data-campaign-field="show_copy" ${selected.show_copy!==false?'checked':''}> Show headline / CTA over creative</label><label>Theme<select data-campaign-field="theme">${['violet','blue','purple','green'].map(v=>`<option value="${v}"${v===(selected.theme||'violet')?' selected':''}>${v}</option>`).join('')}</select></label><label>Eyebrow<input data-campaign-field="eyebrow" value="${escapeHtml(selected.eyebrow||'SPONSORED')}"></label><label class="span-2">Headline<input data-campaign-field="headline" value="${escapeHtml(selected.headline||'')}"></label><label class="span-2">Text<textarea data-campaign-field="text" rows="3">${escapeHtml(selected.text||'')}</textarea></label><label>CTA text<input data-campaign-field="button_text" value="${escapeHtml(selected.button_text||'Open')}"></label><label>Destination URL<input data-campaign-field="link" value="${escapeHtml(selected.link||'')}"></label><div class="field-hint-box">Prepare all useful formats below. The outer banner zone stays fixed; 1 / 2 / 3 / 4 active blocks divide that zone equally and BlinQ selects the matching creative automatically.</div><label class="span-2">1-column · ${escapeHtml(spec1.aspect_ratio||'4:1')} · rec ${escapeHtml(spec1.recommended||'1200 × 300 px')} · min ${escapeHtml(spec1.minimum||'800 × 200 px')} · safe ${escapeHtml(spec1.safe_area||'center 80%')}<input data-campaign-image="1" value="${escapeHtml(images['1']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">2-column · ${escapeHtml(spec2.aspect_ratio||'8:1')} · rec ${escapeHtml(spec2.recommended||'2400 × 300 px')} · min ${escapeHtml(spec2.minimum||'1600 × 200 px')} · safe ${escapeHtml(spec2.safe_area||'center 85%')}<input data-campaign-image="2" value="${escapeHtml(images['2']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">3-column · ${escapeHtml(spec3.aspect_ratio||'2:1')} · rec ${escapeHtml(spec3.recommended||'400 × 180 px')} · min ${escapeHtml(spec3.minimum||'320 × 144 px')} · safe ${escapeHtml(spec3.safe_area||'center 84%')}<input data-campaign-image="3" value="${escapeHtml(images['3']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">4-column · ${escapeHtml(spec4.aspect_ratio||'5:3')} · rec ${escapeHtml(spec4.recommended||'300 × 180 px')} · min ${escapeHtml(spec4.minimum||'240 × 144 px')} · safe ${escapeHtml(spec4.safe_area||'center 82%')}<input data-campaign-image="4" value="${escapeHtml(images['4']||'')}" placeholder="/assets/... or https://..."></label><label class="span-2">Fallback desktop image<input data-campaign-field="image_url" value="${escapeHtml(selected.image_url||'')}" placeholder="Used when a size-specific image is empty"></label><label class="span-2">Mobile image (optional)<input data-campaign-field="mobile_image_url" value="${escapeHtml(selected.mobile_image_url||'')}" placeholder="Optional mobile creative"></label><label>Image fit<select data-campaign-field="image_fit"><option value="cover"${(selected.image_fit||'cover')==='cover'?' selected':''}>Cover · centered crop</option><option value="contain"${selected.image_fit==='contain'?' selected':''}>Contain · full image</option></select></label><label>Image position<select data-campaign-field="image_position">${['center','left','right','top','bottom'].map(v=>`<option value="${v}"${v===(selected.image_position||'center')?' selected':''}>${v.toUpperCase()}</option>`).join('')}</select></label><label>Active from<input data-campaign-field="active_from" type="datetime-local" value="${escapeHtml(selected.active_from||'')}"></label><label>Active until<input data-campaign-field="active_until" type="datetime-local" value="${escapeHtml(selected.active_until||'')}"></label></div><div class="admin-actions-row"><button class="btn btn-ghost danger" type="button" data-admin-action="delete-campaign" data-entity-id="${escapeHtml(state.adminCampaignId)}">Delete campaign</button></div></form>`:'<div class="admin-user-empty">Create a campaign, then assign it to any fixed content slot.</div>';
    return `<div class="admin-note"><strong>Banner campaigns · optional</strong><span>For reusable or scheduled ads. Create a campaign once, then assign it to any banner slot without losing impression/click history. For simple Telegram or BlinQ CTA banners, Layout & slots is enough.</span></div><div class="admin-toolbar"><button class="btn btn-ghost" type="button" data-admin-action="add-advertiser">+ Advertiser</button><button class="btn btn-primary" type="button" data-admin-action="add-campaign">+ Campaign</button><span class="admin-toolbar-spacer"></span><button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save browser draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish changes</button></div><div class="campaign-admin-grid"><section><div class="admin-section-title"><strong>Advertisers</strong><span>Partner identity is separate from campaign history.</span></div><div class="entity-grid">${advertiserCards}</div></section><section><div class="admin-section-title"><strong>Banner campaigns</strong><span>Reusable creatives can move between slots without losing analytics.</span></div><div class="campaign-workspace"><div class="campaign-list">${campaignRows}</div>${editor}</div></section></div>`;
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
    return `<div class="admin-note"><strong>Model Quality</strong><span>Use this when we evaluate prediction quality: live settled accuracy, holdout metrics and historical backtests. It does not change public picks or layout.</span></div>${metricCards([['Model',String(feed.model?.version||'—'),'production artifact'],['Settled',String(p.n??0),'published results'],['Live accuracy',p.accuracy!=null?pct(p.accuracy):'—','settled feed'],['Holdout n',String(holdout.n??'—'),'chronological evaluation'],['Holdout accuracy',holdout.accuracy!=null?pct(holdout.accuracy):'—','model report'],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—','negative is better']])}<div class="route-sub static-copy"><h3>Backtests</h3><p>Historical walk-forward validation is retained inside Model Quality. Latest embedded report: ${escapeHtml(backtest.method||report.method||'available when published with the model artifact')}.</p></div>`;
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
    const tabs=[['layout','Sections & access','Visibility, pick counts and ordering'],['banners','Banners & links','Top CTA, Telegram links and main rotating banner'],['plans','Plans','Membership names and validity'],['accounts','Accounts','Members, roles and subscriptions']];
    if(!['layout','banners','plans','accounts'].includes(state.adminTab))state.adminTab='layout';
    const panel=state.adminTab==='layout'?renderAdminLayout():state.adminTab==='banners'?renderAdminBanners():state.adminTab==='plans'?renderAdminPlans():renderAdminAccounts();
    const configActions=state.adminTab==='accounts'?`<div class="admin-account-direct-note"><span>●</span> Account edits apply immediately</div>`:`${state.adminTab==='layout'?'<button class="btn btn-ghost" type="button" data-admin-action="preview-demo">Demo board</button>':''}<button class="btn btn-ghost" type="button" data-admin-action="save-draft">Save draft</button><button class="btn btn-primary" type="button" data-admin-action="publish-config">Publish changes</button><details><summary>More</summary><button type="button" data-admin-action="export">Export JSON</button><button type="button" data-admin-action="reset">Reset draft</button></details>`;
    return `<div class="admin-console admin-console-v6522"><header class="admin-control-header"><div><small>BLINQ CONTROL</small><h1>Admin Control Center</h1><p>${state.adminTab==='accounts'?'Manage member access directly.':'Simple controls for the live site. Changes stay local until you publish.'}</p></div><div class="admin-global-actions">${configActions}</div></header><nav class="admin-tabs admin-tabs-v6522">${tabs.map(([id,label,hint])=>`<button type="button" class="${state.adminTab===id?'active':''}" data-admin-tab="${id}"><strong>${label}</strong><small>${hint}</small></button>`).join('')}</nav><div class="admin-panel admin-panel-v6522">${panel}</div></div>`;
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
  function updateSelectedWatermark(field,target){ const item=elements()?.[state.selectedElement];if(!item)return;item.watermark=item.watermark||{enabled:false,text:'COMING SOON',preset:'default'};let value=target.type==='checkbox'?target.checked:target.value;if(['opacity','size'].includes(field))value=Number(value);item.watermark[field]=value;renderAllUiContent(); }
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
      const planChip=event.target.closest('[data-admin-plan-chip]');if(planChip){state.adminPlan=planChip.dataset.adminPlanChip;rerenderAdmin();return;}
      const bannerPreviewChip=event.target.closest('[data-admin-banner-preview-plan]');if(bannerPreviewChip){state.adminBannerPreviewPlan=bannerPreviewChip.dataset.adminBannerPreviewPlan;rerenderAdmin();return;}
      const planSelect=event.target.closest('[data-admin-plan-select]');if(planSelect){state.adminPlanId=planSelect.dataset.adminPlanSelect;rerenderAdmin();return;}
      const sectionPreset=event.target.closest('[data-section-preset]');if(sectionPreset){const key=sectionPreset.dataset.sectionKey,plan=state.adminPlan,cfg=key?state.ui?.dashboard?.sections?.[key]:null,id=cfg?.sidebar_element,item=id?elements()?.[id]:null;if(cfg&&item&&plan){cfg.plans=cfg.plans||{};cfg.plans[plan]=cfg.plans[plan]||{};item.access=item.access||{};const ent=cfg.plans[plan],preset=sectionPreset.dataset.sectionPreset;if(preset==='full'){item.access[plan]='active';ent.visible_picks='ALL';ent.blur_remaining=false;ent.see_all=true;}else if(preset==='teaser'){item.access[plan]='active';ent.visible_picks=1;ent.blur_remaining=true;ent.see_all=true;}else if(preset==='blurred'){item.access[plan]='locked';ent.visible_picks=0;ent.blur_remaining=true;ent.see_all=false;}else if(preset==='hidden'){item.access[plan]='hidden';ent.visible_picks=0;ent.blur_remaining=true;ent.see_all=false;}if(plan==='rookie'){item.access.trial=item.access[plan];cfg.plans.trial=clone(ent);}state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();showStatus(`${cfg.label||key} · ${accessLabel(plan)} preset applied.`);}return;}
      const bannerPreset=event.target.closest('[data-banner-preset]');if(bannerPreset){const item=elements()?.[state.selectedElement];if(item){item.access=item.access||{};item.click_access=item.click_access||{};const preset=bannerPreset.dataset.bannerPreset;accessContexts.forEach(plan=>{let visible=true,click=true;if(preset==='teaser-pro')click=['pro','elite','legend','goat'].includes(plan);if(preset==='pro-only'){visible=['pro','elite','legend','goat'].includes(plan);click=visible;}if(preset==='goat-only'){visible=plan==='goat';click=visible;}item.access[plan]=visible?'active':'hidden';item.click_access[plan]=click;});item.access.trial=item.access.rookie;item.click_access.trial=item.click_access.rookie;renderAllUiContent();rerenderAdmin();}return;}
      const element=event.target.closest('[data-admin-element]');if(element){setSelectedElement(element.dataset.adminElement);return;}
      const userButton=event.target.closest('[data-admin-user]');if(userButton){state.adminSelectedUser=(state.adminUsers||[]).find(x=>String(x.id)===String(userButton.dataset.adminUser))||null;rerenderAdmin();return;}
      const campaignButton=event.target.closest('[data-admin-campaign]');if(campaignButton){state.adminCampaignId=campaignButton.dataset.adminCampaign;rerenderAdmin();return;}
      const quick=event.target.closest('[data-admin-user-plan]');if(quick){const select=$('adminUserPlan');if(select&&[...select.options].some(o=>o.value===quick.dataset.adminUserPlan)){select.value=quick.dataset.adminUserPlan;setAdminPlanDefaults(select.value);}return;}
      const actionNode=event.target.closest('[data-admin-action]');const action=actionNode?.dataset.adminAction;if(!action)return;
      if(action==='save-draft')saveDraft();
      else if(action==='publish-config')await publishUiConfig();
      else if(action==='export')exportUiConfig();
      else if(action==='reset'){localStorage.removeItem(draftKey());state.ui=clone(state.uiSource);state.selectedElement='HEADER_BANNER_1';renderAllUiContent();rerenderAdmin();showStatus('Reset to repository defaults. Publish if you want this reset live.');}
      else if(action==='copy-plan'){const source=$('adminCopyFrom')?.value,target=state.adminPlan;if(source&&target){Object.values(elements()).forEach(item=>{item.access=item.access||{};item.access[target]=item.access[source]||'active';if(item.click_access){item.click_access[target]=item.click_access[source]!==false;}if(target==='rookie'){item.access.trial=item.access[target];if(item.click_access)item.click_access.trial=item.click_access[target];}});Object.keys(state.ui?.dashboard?.sections||{}).forEach(key=>{const cfg=state.ui.dashboard.sections[key];cfg.plans=cfg.plans||{};if(cfg.plans[source])cfg.plans[target]=clone(cfg.plans[source]);if(target==='rookie'&&cfg.plans.rookie)cfg.plans.trial=clone(cfg.plans.rookie);});state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();showStatus(`All rules copied from ${accessLabel(source)} to ${accessLabel(target)}.`);}}
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
      if(t.dataset.adminHeaderCount!==undefined){const count=Math.max(0,Math.min(3,Number(t.value)||0));state.ui.header_cta=state.ui.header_cta||{};state.ui.header_cta.enabled=count>0;state.ui.header_cta.slot_count=count;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHeroCount!==undefined){const count=Math.max(0,Math.min(5,Number(t.value)||0));state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.enabled=count>0;state.ui.hero_banner.slot_count=count;state.heroIndex=0;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminHeroSeconds!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.rotation_seconds=Math.max(3,Math.min(300,Number(t.value)||10));renderHeroBanner();rerenderAdmin();return;}
      if(t.dataset.adminHeroRotate!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.auto_rotate=t.checked;renderHeroBanner();rerenderAdmin();return;}
      if(t.dataset.adminHeroDots!==undefined){state.ui.hero_banner=state.ui.hero_banner||{};state.ui.hero_banner.show_dots=t.checked;renderHeroBanner();rerenderAdmin();return;}
      const simpleBanner=t.closest('[data-simple-banner]');
      if(simpleBanner&&t.dataset.simpleBannerField){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id];if(item){item.content=item.content||{};item.content[t.dataset.simpleBannerField]=t.type==='checkbox'?t.checked:t.value;renderAllUiContent();rerenderAdmin();}return;}
      if(simpleBanner&&t.dataset.simpleBannerVisible){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id],plan=t.dataset.simpleBannerVisible;if(item){item.access=item.access||{};item.access[plan]=t.checked?'active':'hidden';if(plan==='rookie')item.access.trial=item.access[plan];renderAllUiContent();rerenderAdmin();}return;}
      if(simpleBanner&&t.dataset.simpleBannerClick){const id=simpleBanner.dataset.simpleBanner,item=elements()?.[id],plan=t.dataset.simpleBannerClick;if(item){item.click_access=item.click_access||{};item.click_access[plan]=t.checked;if(plan==='rookie')item.click_access.trial=t.checked;renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.adminRowCount){const zone=t.dataset.adminRowCount,count=Math.max(0,Math.min(4,Number(t.value)||0));state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].enabled=count>0;state.ui.content_rows[zone].slot_count=count;state.ui.content_rows[zone].preset=String(count||1);renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminRowEnabled){const zone=t.dataset.adminRowEnabled;state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].enabled=t.checked;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.adminRowPreset){const zone=t.dataset.adminRowPreset;state.ui.content_rows=state.ui.content_rows||{};state.ui.content_rows[zone]=state.ui.content_rows[zone]||{};state.ui.content_rows[zone].preset=t.value;renderAllUiContent();rerenderAdmin();return;}
      if(t.dataset.dashboardGlobalField){state.ui.dashboard=state.ui.dashboard||{};let value=t.type==='checkbox'?t.checked:Number(t.value);state.ui.dashboard[t.dataset.dashboardGlobalField]=value;state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();return;}
      const dashboardRow=t.closest('[data-dashboard-section]');
      if(dashboardRow&&t.dataset.dashboardField){const key=dashboardRow.dataset.dashboardSection;state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});let value=t.type==='checkbox'?t.checked:(t.dataset.dashboardField==='preview_limit'&&String(t.value).toUpperCase()!=='ALL'?Number(t.value):t.value);if(t.dataset.dashboardField==='dashboard_enabled'){const pickKeys=dashboardPickSectionKeys;cfg.dashboard_enabled=value;if(pickKeys.includes(key)&&value){const enabled=pickKeys.filter(k=>(state.ui.dashboard.sections[k]||dashboardSectionFallback[k]||{}).dashboard_enabled!==false);const max=Number(state.ui.dashboard.visible_slots||6);if(enabled.length>max){const victim=[...enabled].reverse().find(k=>k!==key);if(victim)state.ui.dashboard.sections[victim].dashboard_enabled=false;}}state.dashboardVisibility=null;}else cfg[t.dataset.dashboardField]=value;renderAllUiContent();rerenderAdmin();return;}
      if(dashboardRow&&t.dataset.dashboardPlanField){const key=dashboardRow.dataset.dashboardSection;state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});cfg.plans=cfg.plans||{};cfg.plans[state.adminPlan]=cfg.plans[state.adminPlan]||{};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.dashboardPlanField==='visible_picks'&&String(value).toUpperCase()!=='ALL')value=Number(value);cfg.plans[state.adminPlan][t.dataset.dashboardPlanField]=value;if(state.adminPlan==='rookie')cfg.plans.trial=clone(cfg.plans.rookie);renderAllUiContent();rerenderAdmin();return;}
      const matrixRow=t.closest('[data-dashboard-plan-row]');
      if(matrixRow&&t.dataset.dashboardRouteAccess!==undefined){const sectionRow=t.closest('[data-dashboard-section]'),key=sectionRow?.dataset.dashboardSection,plan=matrixRow.dataset.dashboardPlanRow,id=key?dashboardSectionConfig(key).sidebar_element:'';const item=id?elements()?.[id]:null;if(item&&plan){item.access=item.access||{};item.access[plan]=t.value;if(plan==='rookie')item.access.trial=t.value;state.dashboardVisibility=null;renderAllUiContent();rerenderAdmin();}return;}
      if(matrixRow&&t.dataset.dashboardMatrixField){const sectionRow=t.closest('[data-dashboard-section]'),key=sectionRow?.dataset.dashboardSection,plan=matrixRow.dataset.dashboardPlanRow;if(key&&plan){state.ui.dashboard=state.ui.dashboard||{};state.ui.dashboard.sections=state.ui.dashboard.sections||{};const cfg=state.ui.dashboard.sections[key]=state.ui.dashboard.sections[key]||clone(dashboardSectionFallback[key]||{});cfg.plans=cfg.plans||{};cfg.plans[plan]=cfg.plans[plan]||{};let value=t.type==='checkbox'?t.checked:t.value;if(t.dataset.dashboardMatrixField==='visible_picks'&&String(value).toUpperCase()!=='ALL')value=Number(value);if(t.dataset.dashboardMatrixField==='order')value=Math.max(1,Math.min(20,Number(value)||Number(cfg.dashboard_order||99)));cfg.plans[plan][t.dataset.dashboardMatrixField]=value;if(plan==='rookie')cfg.plans.trial=clone(cfg.plans.rookie);renderAllUiContent();rerenderAdmin();return;}}
      if(t.dataset.bannerVisiblePlan){const item=elements()?.[state.selectedElement],plan=t.dataset.bannerVisiblePlan;if(item){item.access=item.access||{};item.access[plan]=t.checked?'active':'hidden';if(plan==='rookie')item.access.trial=item.access[plan];renderAllUiContent();rerenderAdmin();}return;}
      if(t.dataset.bannerClickPlan){const item=elements()?.[state.selectedElement],plan=t.dataset.bannerClickPlan;if(item){item.click_access=item.click_access||{};item.click_access[plan]=t.checked;if(plan==='rookie')item.click_access.trial=t.checked;renderAllUiContent();rerenderAdmin();}return;}
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
    const form=$('adminUserForm');if(form)form.onsubmit=async event=>{event.preventDefault();const user=state.adminSelectedUser;if(!user)return;const message=$('adminUserMessage');message.textContent=publicText('Saving…');try{const rawExpiry=$('adminUserExpires').value,status=$('adminUserStatus').value;if(status==='trial')throw new Error('Choose ACTIVE, EXPIRED or SUSPENDED before saving an automatic trial.');const payload={role:$('adminUserRole').disabled?'admin':$('adminUserRole').value,plan:$('adminUserPlan').value,status,expires_at:rawExpiry?new Date(rawExpiry).toISOString():null,payment_reference:$('adminPaymentReference').value.trim()};const updated=await BlinqAuth.adminUpdateAccess(user.id,payload);state.adminUsers=(state.adminUsers||[]).map(row=>row.id===updated.id?updated:row);state.adminSelectedUser=updated;message.textContent='Applied.';setTimeout(()=>rerenderAdmin(),450);}catch(error){message.textContent=error.message;}};
  }
  function planAvatarHtml(id,p={}){
    const style=String(p.avatar||id||'').toLowerCase(),src=marketingAvatarUrl(style);
    const glyph={rookie:'○',pro:'◇',elite:'✦',goat:'♛',legend:'♛'}[style]||'◇';
    return `<span class="plan-card-avatar plan-${escapeHtml(style)}${src?' has-photo':''}" aria-label="${escapeHtml((p.label||id).toUpperCase())} avatar">${src?`<img src="${escapeHtml(src)}" alt="" loading="lazy">`:`<b aria-hidden="true">${glyph}</b>`}</span>`;
  }
  function renderPlanCardsForAccount(){
    const current=accountPlan();
    const plans=Object.entries(state.ui?.plans||{}).filter(([id,p])=>!['trial','expired'].includes(id)&&p.enabled!==false).sort((a,b)=>Number(a[1]?.order||99)-Number(b[1]?.order||99));
    return `<div class="account-plan-grid">${plans.map(([id,p])=>{const url=safeExternalUrl(p.url),active=current===id,restricted=Boolean(p.invite_only||p.verified_only),title=active?'Current plan':(p.card_title||p.description||'BlinQ membership');let action='';if(active)action='<span class="membership-current">CURRENT PLAN</span>';else if(restricted){const invite=safeExternalUrl(p.invite_url||p.url);action=invite?`<a class="btn btn-ghost membership-cta invite-only" href="${escapeHtml(invite)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Request invite')} →</a>`:`<button class="btn btn-ghost membership-cta invite-only" type="button" data-goat-request>${escapeHtml(p.cta_label||'Request invite')}</button>`;}else if(url)action=`<a class="btn btn-primary membership-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(p.cta_label||'Open plan')} →</a>`;else action='<span class="membership-unavailable">ONLINE PURCHASE NOT OPEN YET</span>';return `<article class="membership-card plan-${escapeHtml(id)}${active?' current-plan':''}${restricted?' restricted-plan':''}">${planAvatarHtml(id,p)}<div class="membership-card-copy"><small>${escapeHtml(p.label||id.toUpperCase())}</small><strong>${escapeHtml(title)}</strong><p>${escapeHtml(p.description||p.note||'')}</p></div>${restricted?'<span class="membership-badge">INVITE ONLY</span>':''}${action}</article>`}).join('')}</div>`;
  }
  function renderAccountPage(){
    const a=state.feed?.account||{},status=String(a.status||'expired').toLowerCase(),plan=accountPlan(),planLabel=a.plan_label||state.ui?.plans?.[plan]?.label||plan;
    const expiry=status==='lifetime'?publicText('Lifetime access'):a.expires_at?`${remainingLabel(a.expires_at)} ${locale==='cz'?'zbývá':'zostáva'}`:(status==='active'?publicText('Active'):publicText('No active access'));
    const verified=a.email_verified===true;
    const legacyAdminUnverified=!verified && Boolean(a.is_admin||String(a.role||'').toLowerCase()==='admin');
    return `<section class="account-overview">
      <article class="account-profile-card">
        <div class="account-profile-head"><span class="avatar account-page-avatar" id="accountPageAvatar">${escapeHtml(accountAvatarFallback(a))}</span><div><span class="account-card-kicker">YOUR ACCOUNT</span><h2>${escapeHtml(a.name||'BlinQ Member')}</h2><p>${escapeHtml(a.email||'—')}</p></div><span class="account-verified ${verified?'is-verified':'needs-verification'}">${escapeHtml(publicText(verified?'✓ Email verified':legacyAdminUnverified?'! Legacy admin · verify email':'! Email not verified'))}</span></div>
        <form id="accountProfileForm" class="account-profile-form"><label><span class="telegram-label"><span aria-hidden="true">✈</span> Telegram nick</span><input id="accountTelegramNick" maxlength="33" value="${escapeHtml(a.telegram_nick||'')}" placeholder="@username"></label><label>Avatar style<select id="accountAvatarVariant"><option value=""${!a.avatar_variant?' selected':''}>Default</option><option value="m"${a.avatar_variant==='m'?' selected':''}>Male</option><option value="w"${a.avatar_variant==='w'?' selected':''}>Female</option></select></label><div class="account-profile-actions"><button class="btn btn-primary" type="submit">Save profile</button><button class="btn btn-ghost" id="accountPasswordReset" type="button">Reset password</button></div><p class="form-message" id="accountProfileMessage"></p></form>
      </article>
      <article class="account-access-card"><div class="account-access-top"><span class="account-card-kicker">CURRENT ACCESS</span>${planAvatarHtml(plan,state.ui?.plans?.[plan]||{})}</div><h2>${escapeHtml(planLabel)}</h2><p class="account-access-status">${escapeHtml(status==='trial'?'Rookie Trial':status==='lifetime'?'Lifetime':status==='active'?'Active membership':'Expired')}</p><div class="account-facts"><span><small>Access</small><strong>${escapeHtml(expiry)}</strong></span><span><small>Member since</small><strong>${escapeHtml(a.created_at?fmtDate(a.created_at):'—')}</strong></span><span><small>Security</small><strong>${verified?'Verified email':legacyAdminUnverified?'Legacy admin access':'Verification required'}</strong></span></div><button class="btn btn-ghost account-signout" id="accountSignOut" type="button">Sign out</button></article>
    </section><section class="account-membership-page"><div class="account-membership-heading"><div><small>BLINQ MEMBERSHIP</small><h2>Available plans</h2></div><p>Choose the access level that fits your workflow. Plans without an active checkout stay visible but cannot be purchased online yet.</p></div>${renderPlanCardsForAccount()}</section>`;
  }
  function wireAccountPage(){
    const a=state.feed?.account||{};setAccountAvatar($('accountPageAvatar'),a);
    const form=$('accountProfileForm');if(form)form.onsubmit=async event=>{event.preventDefault();const message=$('accountProfileMessage');message.textContent=publicText('Saving…');try{await BlinqAuth.update({data:{telegram_nick:$('accountTelegramNick').value.trim(),blinq_avatar_variant:$('accountAvatarVariant').value}});message.textContent=publicText('Profile updated.');await loadFeed(false);}catch(error){message.textContent=error.message;}};
    const reset=$('accountPasswordReset');if(reset)reset.onclick=async()=>{const message=$('accountProfileMessage');message.textContent=publicText('Sending recovery email…');try{await BlinqAuth.reset(a.email);message.textContent=publicText('Password reset email sent.');}catch(error){message.textContent=error.message;}};
    const logout=$('accountSignOut');if(logout)logout.onclick=signOutCurrentSession;
    document.querySelectorAll('[data-goat-request]').forEach(button=>button.onclick=()=>{const nick=String(state.feed?.account?.telegram_nick||'').trim();const input=$('accountTelegramNick');const message=$('accountProfileMessage');if(!nick){if(message)message.textContent='Add your Telegram nick first, save the profile, then request GOAT access.';input?.focus();return;}if(message)message.textContent=`GOAT is invite-only. Your Telegram ${nick.startsWith('@')?nick:`@${nick}`} is saved; configure the GOAT invite contact URL in Admin → Membership to make this button open the request chat.`;});
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
    host.innerHTML=`<div class="results-preview-metrics"><span><small>${escapeHtml(publicText('Record'))}</small><strong>${wins}-${losses}</strong></span><span><small>${escapeHtml(publicText('Hit rate'))}</small><strong>${hit==null?'—':pct(hit)}</strong></span><span><small>ROI</small><strong>${Number.isFinite(roi)?pct(roi):'—'}</strong></span><span><small>${escapeHtml(publicText('Units'))}</small><strong>${Number.isFinite(units)?`${units>=0?'+':''}${units.toFixed(2)}u`:'—'}</strong></span></div>`;
    const count=$('resultsPreviewCount');if(count)count.textContent=publicText(`${rows.length} settled`);const cardCount=$('resultsSeeAllCardCount');if(cardCount)cardCount.textContent=publicText(`${rows.length} settled`);
  }

  function resultsSummary(){
    const rows=filteredResults(),category=state.resultsFilters?.category||'all',m=localResultMetrics(rows,category);
    return metricCards([[publicText('Record'),`${m.wins}-${m.losses}`,lcopy('wins - losses','výhry - prehry','výhry - prohry')],[publicText('Hit rate'),m.hit==null?'—':pct(m.hit),lcopy('filtered settled sample','filtrovaná vyhodnotená vzorka','filtrovaný vyhodnocený vzorek')],[publicText('Avg Odds'),m.avgOdds==null?'—':m.avgOdds.toFixed(2),m.oddsSample?lcopy(`${m.oddsSample} odds-backed picks`,`${m.oddsSample} tipov s kurzom`,`${m.oddsSample} tipů s kurzem`):publicText('no issued odds')],['ROI',m.roi==null?'—':pct(m.roi),publicText('flat 1u on issued odds')],[publicText('Units'),m.oddsSample?`${m.profit>=0?'+':''}${m.profit.toFixed(2)}u`:'—',publicText('profit · flat 1u stake')],[publicText('Sample'),String(m.sample),publicText('settled published rows')]]);
  }

  function primeDetailCard(m,index=0){
    const photo1=safePhotoUrl(m.p1Photo)||playerFallbackUrl(m.tour),photo2=safePhotoUrl(m.p2Photo)||playerFallbackUrl(m.tour);
    const avatar=(src,name)=>src?`<span class="player-avatar has-photo"><img src="${escapeHtml(src)}" alt="" loading="lazy"></span>`:`<span class="player-avatar">${escapeHtml(initials(name))}</span>`;
    const metrics=[[publicText('Odds'),Number.isFinite(m.odds)?m.odds.toFixed(2):'—'],[lcopy('Edge','Výhoda','Výhoda'),Number.isFinite(m.edge)?`${m.edge>=0?'+':''}${(m.edge*100).toFixed(1)} pp`:'—'],['EV',Number.isFinite(m.expectedValue)?`${m.expectedValue>=0?'+':''}${(m.expectedValue*100).toFixed(1)}%`:'—']];
    const metricHtml=metrics.map(([label,value])=>{const raw=String(value);const tone=raw.trim().startsWith('+')?' metric-positive':raw.trim().startsWith('-')?' metric-negative':'';return `<span class="card-metric${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(raw)}</strong></span>`}).join('');
    return `<article class="prediction-card featured detail-pick-card match-card-v3"><div class="card-meta match-card-meta"><span class="tour">${escapeHtml(m.tour)} ${escapeHtml(m.tournament)}</span><span class="time">${escapeHtml(fmtTime(m.date))}</span><span class="surface">${escapeHtml(String(m.surface||'').replaceAll('_',' ').toUpperCase())}</span></div><div class="players-row match-players-row"><div class="player">${avatar(photo1,m.p1)}<strong class="player-name">${escapeHtml(m.p1)}</strong></div><div class="vs match-vs">VS</div><div class="player">${avatar(photo2,m.p2)}<strong class="player-name">${escapeHtml(m.p2)}</strong></div></div><div class="pick-row match-pick-row"><div class="pick-copy"><small>${escapeHtml(lcopy('BlinQ pick','Náš tip','Náš tip'))}</small><strong class="pick-name">${escapeHtml(m.pick)}</strong></div><div class="pick-score"><div class="probability">${pct(m.probability)}</div><span class="confidence ${escapeHtml(m.confidence)}">${escapeHtml(confidenceLabel(m.confidence))}</span></div></div><div class="card-metrics-bar match-kpi-bar">${metricHtml}</div></article>`;
  }
  function detailCards(rows,key){
    const cap=Math.max(3,Math.min(5,Number(state.ui?.dashboard?.detail_pick_limit)||5));
    const list=(rows||[]).slice(0,cap);
    if(!list.length)return `<div class="state-card">${escapeHtml(publicText('No published picks are available in this section yet.'))}</div>`;
    const cards=key==='prime'?list.map(primeDetailCard).join(''):list.map((row,index)=>marketPreviewCard(row,key,index,false)).join('');
    return `<div class="detail-picks-grid">${cards}</div><div class="detail-picks-foot"><span>${escapeHtml(publicText(`Showing ${list.length} of ${(rows||[]).length} published pick${(rows||[]).length===1?'':'s'}.`))}</span><button type="button" class="btn btn-ghost" data-route="predictions">${escapeHtml(publicText('← Dashboard'))}</button></div>`;
  }

  function renderRoute(route){
    const host=$('routePanel'),feed=state.feed,p=feed.performance||{},history=feed.history||{},report=feed.model?.report||{}; let body='';
    if(route==='admin'){host.innerHTML=renderAdminRoute();wireAdmin();if(state.adminTab==='accounts')loadAdminUsers();if(state.adminTab==='analytics')loadBannerAnalytics();return;}
    if(route==='prime'){
      const r=state.ui?.market_rules?.prime||{};
      const desc=lcopy(`Accuracy first · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · depth ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · surface ${Number(r.min_surface_matches||5)}+/player · preferred odds ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)}, no hard odds band · reject materially negative EV.`,`Presnosť na prvom mieste · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · hĺbka dát ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasov/hráč · preferovaný kurz ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)} bez pevného pásma · výrazne negatívne EV sa odmieta.`,`Přesnost na prvním místě · model ${Math.round(Number(r.min_win_probability||.85)*100)}%+ · hloubka dat ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasů/hráč · preferovaný kurz ${Number(r.preferred_min_odds||1.20).toFixed(2)}–${Number(r.preferred_max_odds||1.50).toFixed(2)} bez pevného pásma · výrazně negativní EV se odmítá.`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Prime rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(primeTableRows(),'prime')}`;
    }
    else if(route==='top_daily'){
      const r=state.ui?.market_rules?.top_daily||{},day=state.feed?.market_selection?.odds_report?.betting_day||'current';
      const desc=lcopy(`BlinQ betting day ${day} · adaptive confidence cascade 80% → 78% → 76% → 74% → 72% → 70% → 68% until at least ${Number(r.target_count||10)} remaining picks qualify · depth ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · surface ${Number(r.min_surface_matches||5)}+/player · odds floor ${Number(r.min_odds||1.20).toFixed(2)}. Edge/EV are diagnostic only.`,`BlinQ stávkový deň ${day} · adaptívny rebrík istoty 80% → 78% → 76% → 74% → 72% → 70% → 68%, kým sa nekvalifikuje aspoň ${Number(r.target_count||10)} zostávajúcich tipov · hĺbka dát ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasov/hráč · minimálny kurz ${Number(r.min_odds||1.20).toFixed(2)}. Edge/EV sú iba diagnostické.`,`BlinQ sázkový den ${day} · adaptivní žebřík jistoty 80% → 78% → 76% → 74% → 72% → 70% → 68%, dokud se nekvalifikuje alespoň ${Number(r.target_count||10)} zbývajících tipů · hloubka dat ${Math.round(Number(r.min_data_depth||.80)*100)}%+ · povrch ${Number(r.min_surface_matches||5)}+ zápasů/hráč · minimální kurz ${Number(r.min_odds||1.20).toFixed(2)}. Edge/EV jsou pouze diagnostické.`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Top Bets rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(marketRows('top_daily'),'top_daily')}`;
    }
    else if(route==='value'){
      const r=state.ui?.market_rules?.value||{},tiers=Array.isArray(r.fallback_tiers)?r.fallback_tiers.length:0;
      const desc=lcopy(`EV-first selection. Primary target: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · odds ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+. ${tiers?`${tiers} configured fallback tiers may widen market thresholds while preserving model/data guardrails.`:'No fallback tier is configured.'}`,`Výber podľa EV. Hlavný cieľ: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · kurz ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+. ${tiers?`${tiers} nastavených fallback úrovní môže rozšíriť trhové limity, pričom ostávajú zachované pravidlá modelu a dát.`:'Fallback úroveň nie je nastavená.'}`,`Výběr podle EV. Hlavní cíl: model ${Math.round(Number(r.min_probability||.55)*100)}%+ · kurz ${Number(r.min_odds||1.80).toFixed(2)}+ · edge ${Math.round(Number(r.min_edge||.05)*100)} pp+ · EV ${Math.round(Number(r.min_expected_value||.08)*100)}%+. ${tiers?`${tiers} nastavených fallback úrovní může rozšířit tržní limity při zachování pravidel modelu a dat.`:'Fallback úroveň není nastavena.'}`);
      body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Value rule'))}</strong><span>${escapeHtml(desc)}</span></div>${detailCards(marketRows('value'),'value')}`;
    }
    else if(route==='ace') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Aces / Double Faults'))}</strong><span>${escapeHtml(lcopy(`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time count projections from stored event statistics. Projection score is not a calibrated win probability; odds/ROI stay blank until a verified price source exists.`,`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time projekcií z uložených štatistík zápasov. Skóre projekcie nie je kalibrovaná pravdepodobnosť výhry; kurz/ROI ostávajú prázdne, kým nebude dostupný overený zdroj kurzov.`,`Top ${Number(state.ui?.market_rules?.ace?.limit)||10} point-in-time projekcí z uložených statistik zápasů. Skóre projekce není kalibrovaná pravděpodobnost výhry; kurz/ROI zůstávají prázdné, dokud nebude dostupný ověřený zdroj kurzů.`))}</span></div>${detailCards(marketRows('ace'),'ace')}`;
    else if(route==='sg') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Sets / Games'))}</strong><span>${escapeHtml(lcopy('Point-in-time projections from structured historical set/game scores. Sets use long-match probability; Games use projected total versus the ATP/WTA best-of baseline. No odds/ROI are inferred yet.','Point-in-time projekcie zo štruktúrovaných historických skóre setov/hier. Sety používajú pravdepodobnosť dlhého zápasu; hry používajú projektovaný celkový počet oproti ATP/WTA baseline. Kurz/ROI sa zatiaľ neodvodzujú.','Point-in-time projekce ze strukturovaných historických skóre setů/her. Sety používají pravděpodobnost dlouhého zápasu; hry používají projektovaný celkový počet oproti ATP/WTA baseline. Kurz/ROI se zatím neodvozují.'))}</span></div>${detailCards(marketRows('sg'),'sg')}`;
    else if(route==='doubles') body=`<div class="route-sub route-rules"><strong>${escapeHtml(publicText('Doubles model'))}</strong><span>${escapeHtml(lcopy('Separate pair/team model only. Pair identity, pair history, individual strength, surface form and pair chemistry stay isolated from singles probabilities.','Iba samostatný model dvojíc/tímov. Identita dvojice, spoločná história, individuálna sila, forma na povrchu a súhra zostávajú oddelené od pravdepodobností dvojhry.','Pouze samostatný model dvojic/týmů. Identita dvojice, společná historie, individuální síla, forma na povrchu a souhra zůstávají oddělené od pravděpodobností dvouhry.'))}</span></div>${detailCards(marketRows('doubles'),'doubles')}`;
    else if(route==='results') body=renderResultsFilters()+resultsSummary()+`<div class="route-sub results-section-head"><div><h3>${escapeHtml(publicText('Settled predictions'))}</h3><p>${escapeHtml(lcopy('Only successfully published pre-match records are graded. ROI uses the odds snapshot that was actually published and a flat 1u stake.','Vyhodnocujú sa iba úspešne publikované pre-match záznamy. ROI používa kurz, ktorý bol skutočne publikovaný, a rovnú stávku 1u.','Vyhodnocují se pouze úspěšně publikované pre-match záznamy. ROI používá kurz, který byl skutečně publikován, a rovnou sázku 1u.'))}</p></div>${renderResults()}</div>`;
    else if(route==='tournaments'){const names=[...new Set((feed.upcoming||[]).map(x=>x.tournament).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):escapeHtml(publicText('No upcoming tournament coverage is currently published.'))}</div>`;}
    else if(route==='players'){const names=[...new Set((feed.upcoming||[]).flatMap(x=>[x.player1?.name,x.player2?.name]).filter(Boolean))].sort();body=`<div class="static-copy">${names.length?names.map(x=>`<span class="data-pill">${escapeHtml(x)}</span>`).join(''):escapeHtml(publicText('No upcoming players are currently published.'))}</div>`;}
    else if(route==='stats') body=metricCards([[publicText('Settled predictions'),String(p.n??0),publicText('Published and scored')],[publicText('Accuracy'),p.accuracy!=null?pct(p.accuracy):'—',publicText('Observed results')],['Log loss',number(p.log_loss),publicText('Lower is better')],[publicText('Brier score'),number(p.brier_score),publicText('Probability quality')]])+`<div class="route-sub"><h3>${escapeHtml(publicText('Results'))}</h3>${renderResults()}</div>`;
    else if(route==='model'||route==='backtests'){const h=report.holdout||{},delta=report.delta_vs_elo||{};body=metricCards([[publicText('Model'),String(feed.model?.version||'—'),publicText('Production artifact')],['Holdout n',String(h.n??'—'),publicText('Chronological holdout')],['Holdout accuracy',h.accuracy!=null?pct(h.accuracy):'—',publicText('Evaluation report')],['Δ log loss vs Elo',delta.log_loss!=null?number(delta.log_loss):'—',publicText('Negative is better')]])+`<div class="route-sub static-copy"><h3>${escapeHtml(publicText('Data window'))}</h3><p>${escapeHtml(history.start?fmtDate(history.start):'—')} → ${escapeHtml(history.end?fmtDate(history.end):'—')} · ${escapeHtml(lcopy(`${history.matches??'—'} historical matches in the current serving metadata.`,`${history.matches??'—'} historických zápasov v aktuálnych metadátach.`,`${history.matches??'—'} historických zápasů v aktuálních metadatech.`))}</p><p>${escapeHtml(lcopy('No result here is presented as a guarantee. Holdout metrics describe a specific historical evaluation period.','Žiadny výsledok tu nie je prezentovaný ako záruka. Holdout metriky opisujú konkrétne historické obdobie vyhodnotenia.','Žádný výsledek zde není prezentován jako záruka. Holdout metriky popisují konkrétní historické období vyhodnocení.'))}</p></div>`;}
    else if(route==='btts') body=`<section class="btts-beta-page"><span class="btts-beta-badge">${escapeHtml(publicText('BETA · FOOTBALL'))}</span><h2>${escapeHtml(publicText('Both Teams To Score'))}</h2><p>${escapeHtml(publicText('The BlinQ BTTS module is prepared, but live football data and published picks are not connected in this repository yet.'))}</p><div class="btts-beta-state"><i></i><span><strong>${escapeHtml(publicText('Data not connected'))}</strong><small>${escapeHtml(publicText('No demo or fabricated picks are shown.'))}</small></span></div></section>`;
    else if(route==='account') body=renderAccountPage();
    else {
      const copyEn={how_blinq_works:'BlinQ processes point-in-time tennis history, builds model features without using future results, publishes pre-match probabilities, and later evaluates those same published records against real outcomes.',methodology:'The core rules are chronological evaluation, immutable first-published probabilities, explicit missing-data handling, and honest probability metrics. A prediction is informative only when it existed before the match.',model_data:`Current serving metadata reports ${history.matches??'—'} historical matches. The web application reads only the authenticated published serving feed; it does not fabricate missing tennis data.`,faq:'Probabilities are not certainties. Confidence is derived from the model probability, and performance should always be read together with sample size and coverage.',responsible_use:'Use BlinQ as analytical information. Do not treat any probability as a guaranteed outcome, and do not infer certainty from a high-confidence label.'};
      const copySk={how_blinq_works:'BlinQ spracúva point-in-time tenisovú históriu, vytvára modelové príznaky bez použitia budúcich výsledkov, publikuje predzápasové pravdepodobnosti a neskôr porovnáva tie isté publikované záznamy so skutočnými výsledkami.',methodology:'Základom je chronologické vyhodnocovanie, nemenné prvé publikované pravdepodobnosti, explicitné spracovanie chýbajúcich dát a poctivé pravdepodobnostné metriky. Predikcia má informačnú hodnotu iba vtedy, ak existovala pred zápasom.',model_data:`Aktuálne metadáta obsahujú ${history.matches??'—'} historických zápasov. Web číta iba autentifikovaný publikovaný feed a nevymýšľa chýbajúce tenisové dáta.`,faq:'Pravdepodobnosti nie sú istoty. Úroveň istoty vychádza z pravdepodobnosti modelu a výkon treba vždy čítať spolu s veľkosťou vzorky a pokrytím.',responsible_use:'BlinQ používaj ako analytickú informáciu. Žiadnu pravdepodobnosť nepovažuj za garantovaný výsledok a vysokú úroveň istoty nezamieňaj s istotou.'};
      const copyCz={how_blinq_works:'BlinQ zpracovává point-in-time tenisovou historii, vytváří modelové příznaky bez použití budoucích výsledků, publikuje předzápasové pravděpodobnosti a později porovnává stejné publikované záznamy se skutečnými výsledky.',methodology:'Základem je chronologické vyhodnocování, neměnné první publikované pravděpodobnosti, explicitní zpracování chybějících dat a poctivé pravděpodobnostní metriky. Predikce má informační hodnotu pouze tehdy, pokud existovala před zápasem.',model_data:`Aktuální metadata obsahují ${history.matches??'—'} historických zápasů. Web čte pouze autentizovaný publikovaný feed a nevymýšlí chybějící tenisová data.`,faq:'Pravděpodobnosti nejsou jistoty. Úroveň jistoty vychází z pravděpodobnosti modelu a výkon je potřeba vždy číst spolu s velikostí vzorku a pokrytím.',responsible_use:'BlinQ používej jako analytickou informaci. Žádnou pravděpodobnost nepovažuj za garantovaný výsledek a vysokou úroveň jistoty nezaměňuj s jistotou.'};
      const copy=locale==='sk'?copySk:locale==='cz'?copyCz:copyEn;body=`<div class="static-copy"><p>${escapeHtml(copy[route]||lcopy('This section is available in the BlinQ workspace.','Táto sekcia je dostupná v BlinQ.','Tato sekce je dostupná v BlinQ.'))}</p></div>`;
    }
    host.innerHTML=`<div class="route-card route-card-clean">${body}</div>`; if(route!=='admin')translatePublicDom(host); window.BlinqUI.prepareRoute(host); if(route==='results')wireResultsFilters(); if(route==='account')wireAccountPage(); applyAccessStates(host);
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
  function showUpgradePrompt(planId='pro',sectionLabel='this content'){
    window.BlinqUI.closeMenu(false);
    const dialog=$('upgradeDialog'),host=$('upgradeDialogContent');if(!dialog||!host)return;
    const plan=state.ui?.plans?.[planId]||state.ui?.plans?.pro||{},url=safeExternalUrl(plan.url),facts=upgradePlanFacts(planId,plan);
    const factHtml=facts.map(([label,value])=>`<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(publicText(value))}</strong></span>`).join('');
    host.innerHTML=`<div class="upgrade-dialog-eyebrow">UNLOCK MORE WITH BLINQ</div><div class="upgrade-dialog-plan">${planAvatarHtml(planId,plan)}<div><h2 id="upgradeDialogTitle">Unlock ${escapeHtml(sectionLabel)}</h2><p>${escapeHtml(publicText(plan.description||plan.note||`Available with ${upgradePlanLabel(planId)}.`))}</p></div></div><div class="upgrade-dialog-benefits upgrade-dialog-account-facts">${factHtml}</div>${url?`<a class="btn btn-primary upgrade-dialog-cta" href="${escapeHtml(url)}" target="_blank" rel="noopener">Upgrade to ${escapeHtml(String(plan.label||planId).replace(/^BlinQ\s+/i,''))} →</a>`:`<button class="btn btn-primary upgrade-dialog-cta" type="button" data-route="account">View membership options →</button>`}`;
    if(locale!=='en')translatePublicDom(dialog); if(!dialog.open)dialog.showModal();
  }
  async function signOutCurrentSession(){feedGeneration++;await BlinqAuth.signOut();state.feed={upcoming:[],results:[],performance:{},history:{},model:null};auth('login');}
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
      $('profilePlan').textContent=planLabel;
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
      $('staleNotice').hidden=!feed.stale; $('staleNotice').textContent=feed.stale?publicText('Published data is older than 12 hours. Check prediction creation times before evaluating them.'):''; $('appShell').hidden=false; if($('authDialog').open)$('authDialog').close();
      if(state.route==='admin'&&!isAdminAccount())state.route='predictions'; setRoute(state.route,false); applyAccessStates();window.BlinqUI.sync(feed.stale?'stale':'ready',feed.generated_at);
    }catch(error){if(generation!==feedGeneration)return;if(error.status===401){BlinqAuth.clear();auth('login');return;}if(error.status===403&&String(error.code||'').toLowerCase()==='email_not_verified'){auth('login');$('authMessage').textContent=publicText('Verify your email before opening BlinQ. You can resend the verification email below.');$('resendVerification').hidden=false;return;}window.BlinqUI.sync(navigator.onLine?'error':'offline');if(showLoading)showStatus(publicText('Data could not be refreshed. Please try again.'));if(!$('appShell').hidden&&state.route==='predictions')renderPredictions();throw error;}finally{feedLoading=false;window.BlinqUI.refreshFinished();}
  }
  async function refreshWorkspace(showLoading=false){await loadUiConfig();return loadFeed(showLoading);}

  function updateHeaderClock(){const date=$('headerDate'),time=$('headerTime');if(date)date.textContent=fmtToday();if(time)time.textContent=fmtClock();}

  function showStatus(message){const n=$('statusBanner');n.textContent=message;n.hidden=!message;if(message)setTimeout(()=>{n.hidden=true},5000)}

  function setupEvents(){
    $('authDialog').addEventListener('cancel',e=>e.preventDefault()); $('authForm').addEventListener('submit',handleAuthSubmit); $('switchSignup').onclick=()=>auth(state.authMode==='login'?'signup':'login'); $('switchReset').onclick=()=>auth('reset');
    $('resendVerification').onclick=async()=>{const node=$('authMessage');node.textContent=publicText('Sending verification email…');try{await BlinqAuth.resendVerification();node.textContent=publicText('Verification email sent again. Check your inbox and spam folder.');}catch(error){node.textContent=error.message;}};
    $('authPasswordToggle').onclick=()=>{const input=$('authPassword'),button=$('authPasswordToggle'),show=input.type==='password';input.type=show?'text':'password';button.textContent=publicText(show?'Hide':'Show');button.setAttribute('aria-pressed',show?'true':'false');button.setAttribute('aria-label',publicText(show?'Hide password':'Show password'));};
    $('refreshButton').onclick=()=>refreshWorkspace(true).catch(()=>{});$('syncRefresh').onclick=()=>refreshWorkspace(false).catch(()=>{}); ['tourFilter','tournamentFilter','surfaceFilter','confidenceFilter'].forEach(id=>$(id).addEventListener('change',()=>{state.page=0;state.showAll=false;renderPredictions()})); $('searchInput').addEventListener('input',()=>{state.page=0;state.showAll=false;renderPredictions()});
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
      const target=e.target.closest('[data-route]');if(!target)return;const route=target.dataset.route;if(!routeMeta[route])return;e.preventDefault();const upgradeDialog=$('upgradeDialog');if(upgradeDialog?.open&&target.closest('#upgradeDialog'))upgradeDialog.close();const matchDialog=$('matchDialog');if(matchDialog?.open&&target.closest('#matchDialog'))matchDialog.close();setRoute(route);
    });
    let resizeTimer,lastCardCapacity=dashboardCardsPerPanel(); window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{const capacity=dashboardCardsPerPanel();if(capacity===lastCardCapacity)return;lastCardCapacity=capacity;if(state.route==='predictions'){state.page=0;Object.keys(state.marketPage||{}).forEach(k=>{state.marketPage[k]=0;});renderPredictions();renderMarketSections();renderDashboardComposition();}},120)});
  }

  function setupLiveRefresh(){
    let lastAttempt=Date.now();
    const refresh=()=>{
      if(document.hidden||!navigator.onLine||document.activeElement?.matches('input,select,textarea')||$('appShell').hidden||state.route==='admin'||state.demoMode||document.querySelector('dialog[open]')||Date.now()-lastAttempt<60000)return;
      lastAttempt=Date.now();refreshWorkspace(false).catch(()=>{});
    };
    setInterval(refresh,5*60*1000);
    document.addEventListener('visibilitychange',refresh);
    window.addEventListener('online',()=>{lastAttempt=0;refresh();});
    window.addEventListener('offline',()=>window.BlinqUI.sync('offline'));
    window.addEventListener('popstate',()=>{if(!$('appShell').hidden)setRoute(location.hash.slice(1)||'predictions',false);});
    window.addEventListener('hashchange',()=>{const route=location.hash.slice(1)||'predictions';if(!$('appShell').hidden&&route!==state.route)setRoute(route,false);});
  }

  async function boot(){ setupEvents();window.BlinqUI.init();setupLiveRefresh(); updateHeaderClock(); setInterval(updateHeaderClock,30000); await loadUiConfig(); const hash=location.hash.replace(/^#/,''); if(routeMeta[hash])state.route=hash; try{const cfg=await BlinqAuth.init();state.authEnabled=Boolean(cfg.enabled);if(cfg.recovery){auth('recovery');return;}const session=await BlinqAuth.restore();if(session)await loadFeed();else auth('login');}catch(error){showStatus(error.message);auth('login');} }
  boot();
})();
