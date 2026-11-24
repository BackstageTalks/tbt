# Offline audit repozitárov TBT — 2026-11-24

## Rozsah a dôkazy

- **TBT, snímka E22** — používateľom dodaný export z Downloads, `tbt-main 22-11-26.zip`, SHA-256 `1089775572d5503f8eebad5e1e43aa1898e8fff9f51348cd65e9bf50d2548d1e`. Nahrádza zálohu „pred Claude PRO“ ako zdroj kódu a riadkov.
- Porovnanie obsahu pred pomocnými testami ukázalo **58 pridaných, 102 odstránených a 33 zmenených súborov**. Export nemá Git metadata. Dokumenty v ňom sú podklady na porovnanie. Ich tvrdenia o stave GitHubu nie sú overením revízie exportu.
- **tbt-data** — lokálny `origin/main` `6894e857`, iba statické čítanie stromu, workflowov a vybraných vzorov v histórii. História dostupná v starom klone TBT končí pre jeho lokálny `origin/main` na `c6b949ea`. Tieto kontroly nepreukazujú históriu nového exportu.
- Kontrola prešla cez rozdiely súborov, kľúčové prevádzkové toky a vybrané regresné testy. Nepokrýva každú vykonateľnú vetvu, živú produkciu ani prihlásený web.
- Všetky kontroly prebehli lokálne. Žiadne volania aplikačných, športových ani GitHub API, tréning, dispatch, publikovanie či zápis do CDB. P0 znamená kritický dopad, P1 vážny dopad na ponuku, dáta alebo prevádzku, P2 obmedzený dopad a P3 údržbu. Potvrdený P0 chýba v skúmaných dôkazoch.

## Mapa tokov

| Tok | Vstup a výstup |
| --- | --- |
| Ranný refresh | `.github/workflows/morning-refresh.yml:5,24,112` — 05:15 Bratislava pri povolených natívnych schedules, alternatívne dispatch. Denná poistka pred ďalším plateným behom. `data.yml:642–651` → `scripts/pipeline.py` → model, ceny, výber sekcií, ledger a feed. `scripts/morning_clock.py:12–47` rozlišuje reálny čas a čas výberu/publikácie. `data.yml:1154–1250` pripraví feed, overí ho pred nasadením a potvrdí publikáciu po readbacku. |
| Hodinový pipeline | `data-hourly-quota-gapfill.yml:9–11,316–352` → dispatch `data.yml` v režime statistics → writer lock na `data.yml:438`, downloader a adaptívny fallback v tom istom workflowe, uvoľnenie locku na :1034. Samostatná kontrola stavu v `match-status.yml:5,55` reconciliuje výsledky a spúšťa Telegram report. |
| Tréning | `admin-training-worker.yml:5–6,37–40` → `admin_training_worker.py` / `admin_model_lab_worker.py`. Chránený kandidát `protected-frozen-cdb-candidate.yml:118–155` overí backup, frozen vstupy a leakage, potom volá `pipeline.py train`. ďalšie kroky publikujú dôkazy, vyhodnotí readiness a spúšťa shadow. Ranný wrapper vie vyžiadať kandidáta na `morning-refresh.yml:234`. |
| Telegram | `telegram-daily-offer.yml:52,180,211–217` a `telegram-offer.yml:58,88–93` → `telegram_offer_publisher.py` queue/prepare/send/mark-sent. `match-status.yml:55` → `telegram-results.yml:84–125` → `telegram_daily_results.py` vyberie vydané tipy a vyžaduje autoritatívny výsledok. Daily offer používa zamrazený snapshot a kontrolu pred odoslaním. |
| Web/admin | `web/index.html:20–37` → `auth.js`, `app.js`, mobilné a admin vrstvy. `api/function_app.py:1617–1627` skladá autorizovaný feed a Results, globálnu Azure úroveň `ANONYMOUS` dopĺňajú kontroly v handleroch. Admin účty od :3885 a admin ponuka od :2989. |
| tbt-data | Read-only export je samostatný `.github/workflows/blinq-private-cdb-readonly-export.yml:6`. Import drive PBP vyžaduje dispatch z main a writer lock (`import-drive-pbp-exact.yml:33,55,67`). `cdb-global-writer-contract.yml:30–31` kontroluje lock a pokrytie writer workflowov. Tieto definície dokladajú zamýšľaný kontrakt. |

### Dosiahnuteľnosť

`rg -l -F <stem> .github tests scripts api tools ops -g "!<stem>.py"` v E22 nenašiel spotrebiteľa pre `audit_tbt_pro_legacy`, `generate_webpush_keys` ani `probe_secondary_ranking_api`. Prvé dva sú kandidáti na manuálne nástroje, tretí na izolovaný platený probe. Absencia odkazu v repozitári nevylučuje externé alebo manuálne spustenie. Rovnaký grep našiel workflow aj test pre `replay_top_ranked_morning`. `match-popout.js` je používaný cez `web/app.js:3540` → `web/match-popout.html:9`, s testom `tests/test_r41_match_popout_runtime.js:49`. Service worker má dynamickú registráciu na `web/app.js:8748`.

### Zmeny v novom exporte

- Ranný refresh načíta admin offer flags pred spustením pipeline a pri chybe použije workflow defaults (`data.yml:642–651`). Shadow sa skladá v `pipeline.py:771–784`, virtual rows sa pripájajú k candidate snapshotu. V príprave es existujú aj samostatné line-first nástroje, kandidátske tipy treba rozlišovať od vydaných.
- Chránený tréning obnovuje voliteľný ročný checkpoint pred fitom (`protected-frozen-cdb-candidate.yml:126–155`) a po behu ukladá cache (:235–247). Workflowy pre gapfill/staging a kanonický import sú oddelené. Nové importy bulk odds a opravy orientácie staticky používajú writer lock (`cdb-bulk-odds-import.yml:73,342`, `cdb-stats-orientation-fix.yml:74,335`). Nespúšťali sa.
- Odstránený Drive archív Prop-Line zahŕňa `scripts/propline_drive_archive.py`, jeho test a volanie z evening workflowu. Inventúra odhalila aj odstránené DIL a jednorazové workflowy. Odstránenie z exportu samo nepreukazuje stav externých plánovačov.

## Overené opravy z predchádzajúcich auditov

| Stav | Dôkaz v tomto exporte |
| --- | --- |
| AUD-01 opravený | `market_selection.py:1339–1341` vyradí z TOP len `issued_value`. Pôvodný strict test skončil ako XPASS. V aktuálnom balíku už medzi XFAIL nie je. |
| Admin FILL má prioritu | `market_selection.py:1048–1056` skúša FILL pred FLOOR. Test z `tests/test_audit_20261124.py:6` prešiel. Ostáva prekrytá definícia (AUD-04). |
| Neplatný počet es ostáva bez settle | Existujúci test s nekonečnom prešiel (`tests/test_audit_20261124.py:12`). |
| Duplicitný virtuálny vklad sa započíta raz | `offer_shadow.py:314–322` deduplikuje kontrakty v rámci variantu. Existujúci test prešiel (`tests/test_audit_20261124.py:19`). |
| Zmena súboru cache invaliduje obnovu | `feature_checkpoints.py:36–50,89–110` hashujú zdroj balíka aj bajty cache. Existujúci test po zmene súboru prešiel (`tests/test_audit_20261124.py:28`). Integrita jednotlivých súborov a dôvera v pôvod archívu sú samostatné vlastnosti (AUD-20). |

## Nálezy

| ID | Závažnosť a miesto | Dôkaz a dopad | Návrh opravy a riziko |
| --- | --- | --- | --- |
| AUD-02 | P2 · `api/tbt/services/market_selection.py:917–923,971–987` | Kľúč s prázdnym event ID ostáva pravdivý reťazec. Priamy test prideľovača prijme takú kartu. Nález je potvrdený na hranici helpera, dosiahnuteľnosť z produkčných vstupov ostáva neoverená. | Validovať segmenty podľa typu trhu pred vytvorením kľúča, merať odmietnutia. **Nízke až stredné**. Zohľadniť staršie riadky bez betting day. |
| AUD-03 | P2 · `web/app.js:2255–2260,3824–3831` | Seed ukážky odčíta šesť uplynutých hodín. 29. marca o 06:30 CEST použije predchádzajúci deň a 25. októbra o 05:30 CET použije nový deň. Výsledkový helper už pracuje s lokálnou hodinou. | Zdieľať `bratislavaBettingDayKey` pre seed a filtre, pridať paritu s `betting_day_bounds`. **Nízke**. |
| AUD-04 | P3 · `api/tbt/services/market_selection.py:1038–1060,1249–1250,1341–1358`, `offer_flags.py:31` | Účinná definícia číta admin FILL pred workflow FLOOR. Prvú definíciu rovnakého mena prekryje druhá. Zoznam `top_fallback` ostáva prázdny, lacnejší TOP fill má vlastný pool a konfiguráciu. | Odstrániť prekrytú definíciu a oddeliť v audite počet tipov z odds fill, emergency a core. **Nízke** pre čistenie a diagnostiku. |
| AUD-05 | P2 · `scripts/telegram_daily_results.py:226–252,255–283` | Aces porovnáva line a smer cez `str`, takže 8 a 8.0 skončia ako rozdielne riadky. Dve zhodné autoritatívne položky vyhodia RuntimeError aj pri identickom settle. `prepare` vyhodnocuje report hromadne na :525–546. | Normalizovať line podľa kanonického trhu, zhody deduplikovať podľa stabilnej identity a obsahu, konflikty ponechať pending s dôvodom. **Stredné**. Dôležité je zachovať presnú hranicu a vydaný kurz. |
| AUD-06 | P2 · `api/tbt/services/ace_selection.py:664–715,794–814`, `sg_selection.py:369–400,539–558` | Dve implementácie adaptívneho výberu pre esá/DF a sety/gamy, samostatné per-market a celkové limity. Pri zásahu do radenia, prahov alebo capov môžu sekcie zmeniť správanie nezávisle. Konkrétny nesprávny tip z dostupných dát nebol potvrdený. | Zdieľať adaptívne radenie a capy cez konfigurovateľné pravidlá, fixture parity pre každý trh. **Stredné**. |
| AUD-07 | P1 · `api/tbt/providers/rapidapi.py:109–139,286–305,795–803` | Fail-closed podmienka závisí od rovnosti s `RAPIDAPI_KEY` z prostredia a od prítomnosti ľubovoľného callbacku. Pri explicitnom Settings s iným kľúčom staticky existuje cesta bez shared reservation. Živý caller s takouto konfiguráciou nebol potvrdený. | Produkčný klient musí dostať explicitnú zdieľanú rezerváciu bez ohľadu na pôvod kľúča. Offline testy použiť výhradne s mock transportom. **Stredné**. Preveriť všetkých konštruktorov. |
| AUD-08 | P2 · `api/tbt/services/propline_live.py:100–139`, `scripts/propline_evening_odds.py:73–116,310–337`, `propline_clv_collect.py:228–241,355–358`, `propline_nightly_closeout.py:455–532` | Klienti majú vlastné stropy, rezervy, prípadne počítadlo snapshotov. Každý proces začína s vlastným stavom. Hlavička remaining je pozorovanie po requeste. Kód týchto klientov nepreukazuje spoločnú atomickú rezerváciu ani zdieľanú deduplikáciu event detail medzi workflowmi. | Samostatný Prop-Line ledger pred requestom a krátkodobá cache podľa provider event/market/endpointu. **Stredné až vysoké**. Zaviesť pozorovaním, oddeliť closing odds a ranný refresh. |
| AUD-09 | P2 · `api/tbt/services/projection_odds.py:472–481,540–555`, `scripts/pipeline.py:2210–2221` | Projection odds zachytáva široké výnimky ako chýbajúcu cenu a agregované chyby. Chyba kontraktu alebo regresia môže vyzerať ako slabé pokrytie. Naopak, chyba unikajúca z refreshu zámerne zadrží celý nový feed. | Oddeľovať chýbajúci trh, kvótu, dočasnú chybu a programovú regresiu v počítadlách a diagnostike. Zachovať atómový publish. **Nízke** pre telemetriu. |
| AUD-10 | P2 · `scripts/release_store.py:15,30` | Retry klasifikuje chyby podľa návratového výstupu. `subprocess.run` neobmedzuje dobu jedného čakania, takže zamrznutý proces sa k ďalšiemu pokusu nedostane. | Timeout per operácia, ohraničený retry iba pri čítaní. Pri nejednoznačnom zápise najprv readback. **Stredné**. |
| AUD-11 | P2 · `web/config/banners.json:18`, `web/ui-config.json:715` | Obe konfigurácie odkazujú na `/assets/tennis-hero-v6524.webp`. E22 súbor neobsahuje a offline navigácia na troch mobilných/tabletových šírkach zaznamenala 404. Októbrová Git snímka asset obsahuje. | Opraviť referenciu alebo vrátiť schválený asset a pridať kontrolu existencie lokálnych odkazov. **Nízke**. |
| AUD-12 | P2 · `web/app.js:12–14,4837–4839` | Neprázdny neplatný dátum prejde až do `Intl.DateTimeFormat.format` a vyhodí RangeError. Výsledková šablóna volá formátovače priamo pri renderovaní riadka. Základný odhlásený offline shell tento vstup nedostal. | Jeden bezpečný formátovač s fallbackom pre neplatný čas, test historického poškodeného riadka. **Nízke**. |
| AUD-13 | P3 · `web/index.html:20–37`, `web/app.js:1`, `web/blinq-app.css:1` | Počiatočná stránka načítava aj admin kód a štýly. Na disku app.js 986 025 B, auth.js 43 545 B, blinq-app.css 911 420 B, blinq-mobile.css 109 227 B. Ide o surové bajty, bez kompresie a runtime coverage. | Odložiť admin JS/CSS po otvorení adminu, pred zmazaním selektorov zmerať coverage na route a viewporte. **Stredné**. |
| AUD-14 | P3 · `scripts/audit_tbt_pro_legacy.py:1`, `scripts/generate_webpush_keys.py:1`, `scripts/probe_secondary_ranking_api.py:1` | Nulové odkazy z workflowov, testov a prehľadávaného kódu. Príkazy možno spustiť manuálne. | Pridať vlastníka a manuálny vstup do existujúcej mapy skriptov, až potom rozhodnúť o vyradení. **Nízke**. |
| AUD-15 | P2 · `api/function_app.py:194,569–578,537,3885` | Azure routy majú host-level ANONYMOUS. Health verejne vracia verziu, release a auth provider. Serving readback kontroluje worker token a admin routy majú aplikačný guard. Samotný inventár dekorátorov nedokladá obídenie autorizácie. Nový handler môže guard vynechať bez platformovej chyby. | CI matica verejné/užívateľské/admin/interné a kontrola, že príslušný guard prebehne pred I/O, s mockovanými závislosťami. **Nízke** pre kontrolu, **stredné** pre zmenu dispatchu. |
| AUD-16 | P2 · `api/tbt/services/auth_email.py:233–247,268–277`, `api/function_app.py:888–897` | SMTP audit pracuje s adresátom a subjectom v úložisku activity auditu. Pri výnimkách sa na vybraných miestach loguje traceback. Prítomnosť reálnych adries alebo tajomstiev v produkčnom logu sa offline nedá potvrdiť. Telegram send chybu sanitizuje explicitne na `telegram_offer_publisher.py:874–878`. | Zjednotiť sanitizáciu chýb pre auth/SMTP a obmedziť prístup a retenciu auditu obsahujúceho adresy. **Nízke až stredné**. |
| AUD-17 | P2 · `api/tbt/services/engine.py:492,603,727,1002`, `match_status.py:785,955`, `scripts/telegram_daily_results.py:255–283`, `web/app.js:3833–3842,4837–4839` | Historický a runtime settlement majú samostatné vetvy. Telegram odvodzuje jednotky zo zmrazeného a archívneho kurzu a má výnimku pre lokálne kalibrované esá. Web skladá stav a jednotky pri renderovaní. AUD-05 je konkrétne miesto, kde sa môžu rozísť. | Zdieľaný nemenný výsledkový kontrakt s event/market/line/direction, identitou publikácie, zdrojom, stavom, cenou pri vydaní a jednotkami. Feed, Telegram aj web sú adaptéry. **Vysoké**. Nasadiť najprv paralelným porovnaním. |
| AUD-18 | P2 · `scripts/release_store.py:30–41` | Retry zapisuje prvých 220 znakov stderr z gh bez lokálnej sanitizácie. Podľa príkazu môže stderr obsahovať názvy privátnych objektov alebo URL. Výskyt credentialu v reálnych logoch nebol overený. | Logovať iba kategóriu chyby, pokus a návratový kód. **Nízke**. |
| AUD-19 | P2 · `api/tbt/services/offer_shadow.py:184–201,243–249` | Extra variant obchádza pripravený slate, časový náskok a validáciu identity. Offline test vložil riadok s eventom mimo pripravenej ponuky a capture ho uložil. Dopad je na shadow vyhodnotenie. | Validovať aj extra varianty proti tomu istému `by_event`, trhu a času. **Nízke až stredné**. |
| AUD-20 | P1 · `.github/workflows/protected-frozen-cdb-candidate.yml:126–136,235–247`, `api/tbt/models/feature_checkpoints.py:89–110` | Workflow obnovuje meniteľnú cache z release. Manifest s digestmi je súčasťou tej istej cache a neoveruje jej pôvod. Tréning používa pickle. Statický nález sa týka hranice dôvery medzi release zapisovateľom a tréningom. | Pred obnovou overiť pôvod celej nemennej generácie mimo archívu a použiť formát bez vykonateľnej deserializácie. **Stredné až vysoké**. |
| AUD-21 | P2 · `scripts/backfill_daily_bulk_odds.py:32–49,60–63` | Výnimka providera zastaví zvyšok obdobia. CLI po aspoň jednom úspešnom dni skončí kódom 0 a dôvod ostane v reporte. Zelený stav preto môže označiť čiastočné pokrytie. | Oddeliť kompletný, čiastočný a zlyhaný beh. Zverejniť sumarizáciu dní a umožniť pokračovanie chýbajúcich dní. **Nízke až stredné**. |
| AUD-22 | P2 · `api/tbt/models/feature_checkpoints.py:82–91,135–145`, `protected-frozen-cdb-candidate.yml:133–135` | Chybný archív môže zastaviť workflow už pri `tar`. Platný JSON nesprávneho tvaru môže zlyhať na `manifest.get` mimo bloku pre chyby čítania. Obnovenie voliteľnej cache tak môže zastaviť tréning. | Extrakciu a validáciu schémy robiť do dočasnej zložky. Pri neplatnej cache pokračovať cold replayom s jasným stavom. **Nízke**. |
| AUD-23 | P1 podmienené platnosťou · `Claude/README.md:73–74` | Dokument odkazuje na skoršie zdieľanie prístupových údajov. Samotný odkaz neoveruje ich platnosť ani rotáciu. Žiadne hodnoty sa neprepisovali do reportu. | Overiť evidenciu rotácie a prístupov. Platné údaje po expozícii vymeniť. **Stredné** kvôli závislým integráciám. |

## Ďalšie kontroly

### API a deduplikácia

- RapidAPI transport je centralizovaný v `rapidapi.py:_get` (:254) a `_get_bytes` (:374). Timeout klienta je na :141–143. JSON request rezervuje pred každým pokusom, 429 používa Retry-After a najviac päť pokusov (:268–362). `guarded_rapidapi.py:25–32,50–80` je samostatný transport pre manuálne backfilly a probe, povinne používa atomický budget. Priamy grep hlavičiek a hostov našiel `manual_serve_return_3000.py:20`, `manual_statistics_backfill.py:18`, `probe_secondary_ranking_api.py:10`, `scripts/research/audit_api50_match_ids.py:126–136` ako používateľov guardu. Na vyhľadanie všetkých zostavovateľov klienta v konkrétnej revízii použiť `rg -n 'RapidTennisClient|GuardedRapidApiHttp|x-rapidapi-(key|host)|rapidapi\.com' api scripts tools .github`. Samostatný `livetennisapi.py` používa iného providera.
- Spoločný RapidAPI kontrakt overuje 15 000 provider/day, 14 500 globálny strop, 500 rezervu, reset 17:09 UTC a pacing 6/s (`shared_budget.py:359–378`). Hodinový cutoff je samostatný a kontroluje ho aj klient pred requestom (`rapidapi.py:275–284`). Downloader má navyše per-run strop podľa AGENTS.md. Rozpočet je obmedzenie počtu, deduplikáciu riešia calleri.
- Pri rannom behu `pipeline.py:1806–1812,1830–1835,2040–2045` zdieľa prefetched provider-1 mapu medzi projekciami a moneyline. `projection_odds.py:531–549` zlúči esá a S/G podľa event ID a s prefetch mapou nezadáva nový call. `market_selection.py:842` môže doplniť moneyline mimo cache. `rapidapi.py:795–803` nemá vlastnú event cache. Opakované pokusy pri chybe, iné provider ID a rôzne endpointy sú samostatné requesty. Deduplikácia naprieč procesmi a behmi ostáva nepreukázaná.
- Priame Prop-Line transporty v E22 našiel `rg -n 'api\.prop-line|X-API-Key' api scripts tools` v `propline_live.py:26,116`, `propline_clv_collect.py:23,80`, `propline_evening_odds.py:25,78`, `propline_nightly_closeout.py:31,482`. Workflows volajú CLV, evening a closeout na `propline-clv-pilot.yml:41`, `propline-evening-odds.yml:89`, `propline-nightly-closeout.yml:46`. Ranný fallback zdieľa jednu sadu event detailov pre viac trhov (`pipeline.py:1826–1840`). Koordinácia rezerv medzi workflowmi je slabšia než pri RapidAPI (AUD-08).

Priame konštruktory v E22 z `rg -n 'RapidTennisClient\(|GuardedRapidApiHttp\(' api scripts tools -g '*.py'`:

| Okruh | Call sites |
| --- | --- |
| Azure a recovery | `api/function_app.py:1292,2066,2674`, `api/tbt/services/telegram_20261103_recovery.py:244` |
| Pipeline a histórie | `scripts/pipeline.py:1391`, `download_tennis_history.py:759`, `enrich_ace_history.py:138`, `enrich_doubles_history.py:118`, `enrich_player_cards.py:525`, `enrich_sg_history.py:321`, `overnight_data_optimizer.py:146`, `import_oct12_three_cdb_and_sidecar.py:257` |
| Audity a probe | `scripts/audit_tennisapi_bulk_cdb_yield.py:328`, `compare_tennis_season_calendar.py:192`, `probe_ranking_history_api.py:53`, `probe_tennisapi_extended_contract.py:1036`, `probe_tennis_provider.py:301`, `probe_viac_es_real_odds.py:237` |
| Guarded transport | `scripts/manual_serve_return_3000.py:93`, `manual_statistics_backfill.py:54`, `probe_secondary_ranking_api.py:36`, `research/audit_api50_match_ids.py:136` |

Runtime calleri môžu dodať callback do lokálneho shared ledgeru. CLI calleri so štandardným kľúčom sú závislí od konfigurácie shared budgetu, prípadne danej kombinácie s callbackom. Prítomnosť konštruktora sama nepotvrdzuje efektívne credentials nasadeného workflowu.

- Noví priami RapidAPI calleri: `scripts/backfill_daily_bulk_odds.py:60`, `itf_week_gapfill_stage.py:140`, `probe_itf_stats_availability.py:82`, `probe_extra_endpoints.py:35`. Prvé tri používajú `RapidTennisClient`, posledný `GuardedRapidApiHttp`. Lokálne stropy nepokrývajú deduplikáciu naprieč workflowmi. Dátumový bulk backfill iteruje po dňoch a používa spoločný transport. Čiastočné ukončenie je AUD-21.

### Web, konzola a mobil

Headless Edge, lokálna obsluha všetkých požiadaviek, service worker blokovaný. Základný shell pri šírkach 360, 390, 768 a 1366 px skončil so scrollWidth rovným viewportu, bez nezachytených JavaScript výnimiek. Na prvých troch šírkach 404 z AUD-11. Odpovede auth config a UI config boli simulované 503. Výsledok pokrýva odhlásený fallback shell, bez overenia prihláseného adminu, výsledkov, reálneho mobilného zariadenia a výkonnosti nasadenia. Obhliadka nepotvrdila nepoužívaný JS/CSS súbor. Dynamicky používané súbory sú uvedené v mape dosiahnuteľnosti.

### Autorizácia a tajomstvá

- Nové routy ponuky a shadow na `function_app.py:2989–3055` majú admin alebo worker guard. Statická kontrola týchto handlerov neukázala novú verejnú admin operáciu.
- Verejné vstupy zahŕňajú `health` (`function_app.py:569`), `v1/auth/config` (:802), `v1/ui-config` (:1451) a `v1/push/config` (:3025). Porovnať ich odpovede s explicitným verejným schématom pri zavádzaní AUD-15. Chránené príklady zahŕňajú interný readback (:574–579), admin accounts (:3885) a autentifikovanú telemetriu (:3861–3882). Produkčné routovanie a oprávnenia neboli volané.
- Lokálny `git grep -Il -E` na októbrovom TBT a tbt-data origin/main hľadal formáty GitHub tokenov, Google API klúča a PEM hlavičky v zdrojových/config súboroch. TBT hit vo `web/auth.js` a akčnom klientskom JS je Firebase web config, ďalšie hity sú testy. Hodnoty sa do výstupu nekopírujú. `git log --all -G … --format= --name-only` na TBT pre GitHub token/PEM vzory vrátil testy. Obmedzený scan tbt-data origin/main zasiahol testy Firebase. E22 má napríklad klientskú konfiguráciu vo `web/auth.js:7`. V E22 samostatný grep na GitHub tokeny a PEM formáty mimo dokumentov a archívov našiel iba dva Firebase contract testy. Odkazy na skoršie zdieľanie sú v AUD-23. Živý tajný credential sa týmito kontrolami nepotvrdil. Scan nezahŕňa GitHub secret store, neprevzaté vetvy, binárne archívy, runtime logy ani všetky vlastné formáty kľúčov.

## Offline reprodukcie

`tests/test_repo_audit_20261124.py` obsahuje šesť prípadov `xfail(strict=True, raises=AssertionError)` pre päť pretrvávajúcich nálezov. Zahrnuté sú dva prechody letného času, neúplná identita, Telegram line, mobilný obrázok a extra shadow riadok mimo slate. Node je potrebný pre DST. Overenie E22 s existujúcimi testami selekcie, shadow, checkpointov, line-first es a S/G skončilo **114 passed, 6 xfailed**. Existujúce štyri testy zo `tests/test_audit_20261124.py` sú súčasťou 114 úspešných prípadov.

```powershell
$env:PYTHONPATH = 'api;scripts'
python -m pytest tests/test_repo_audit_20261124.py -q -rx
python -m pytest tests/test_repo_audit_20261124.py -q --runxfail
```

## Top 10 podľa pomeru prínos/riziko

1. AUD-19 — použiť rovnakú kontrolu slate aj na extra shadow varianty.
2. AUD-20 — overovať pôvod a integritu celej generácie pred obnovou tréningovej cache.
3. AUD-22 — pri neplatnej cache pokračovať cold replayom.
4. AUD-03 — použiť existujúci lokálny výpočet 06:00 pre teaser.
5. AUD-11 — opraviť mobilný obrázok a kontrolovať lokálne odkazy.
6. AUD-05 — normalizovať line pri presnom párovaní Telegram výsledkov.
7. AUD-02 — odmietnuť neúplnú identitu pred prideľovaním sekcie.
8. AUD-09 — odlíšiť nedostupný trh, prevádzkovú chybu a chybu kódu.
9. AUD-12 — ochrániť render pred neplatným dátumom.
10. AUD-21 — sprístupniť čiastočný stav backfillu v stave workflowu.
