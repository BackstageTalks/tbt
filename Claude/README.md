# Claude – poznámky k úpravám BlinQ

## 2026-11-23 – Esá line-first kandidát (PR, champion nezmenený)

- `scripts/aces_line_first.py`: samostatný kandidát z overeného existujúceho Prop-Line archívu. Model počíta oba hráčske počty, aj keď sa ich projekcie zhodujú; nepoužíva shortlist ani superiority gap trhu Viac es. Zachované sú turnajové/rankingové brány a minimum histórie existujúceho count modelu. Žiadny tréning.
- Hranica musí byť skutočne ponúknutá v Prop-Line. Prednosť má over s rezervou ≥1,5, potom under; vyberá sa najbližšia vyhovujúca ponúknutá hranica. Príklady: 5 → over 3,5; 10,5 → under 12,5, ak je to vhodná ponuka. Celé hranice s možným pushom a DFS multiplikátory sú v kandidátovi vylúčené. N+ je explicitne ekvivalent over N−0,5.
- Kurz pre presný kontrakt hráč/hranica/smer: existujúca RapidAPI cache → Prop-Line → nezmenený `working_ace_odds` (1,60–1,80). Aj reálny kurz 2,00 je prípustný v kandidátovi. Lokálny kurz nesmie vytvoriť hranicu. Chýbajúca alebo nevyhovujúca ponuka = diagnostika `bez ponuky`, bez tipu.
- `scripts/pipeline.py` ukladá výsledok len do `odds_attachment.line_first_candidate`; nijaký kandidát nenahrádza publikované tipy. TOP, Value, ostatné trhy, KPI, KURZ, grafika a push zostávajú bez zmeny. Neprázdnosť oficiálneho denného výstupu ostáva na existujúcich trhoch; Esá bez ponuky nemajú umelé dopĺňanie.
- Zapnutie výpočtu kandidáta: obe Actions Variables `TBT_ACES_LINE_FIRST_CANDIDATE_OWNER_APPROVED=true` a `TBT_ACES_LINE_FIRST_CANDIDATE=true`. Predvolene OFF. Návrat: zrušiť ktorýkoľvek prepínač alebo revert PR. Tento prepínač nikdy neaktivuje produkčný výber.
- `scripts/propline_evening_odds.py` deduplikuje provider event ID pred detailovým volaním; konfliktné identity preskočí. Kandidát aj opakovaný výpočet čítajú uložený archív, takže nepridávajú žiadne RapidAPI ani Prop-Line volanie. Existujúci večerný zber zostáva 1 bulk + najviac 1 detail na unikátny zápas v behu, s existujúcou rezervou poskytovateľa. Globálnu deduplikáciu nezávislých existujúcich live/večerných zberov tento PR nezavádza.
- CDB: `scripts/stage_aces_offer_cdb.py --day YYYY-MM-DD --out work/aces-offers` pripraví lokálny dátovaný sidecar `aces-offers-YYYY-MM-DD.json`, nie štatistiky do tréningového Parquetu. `--report` znovu použije už zachytený zdroj. Explicitný `--apply` používa globálny writer lock (max. 15 min čakania) a release `tbt-data-v1`, overuje nezmeniteľnosť existujúceho súboru a nezávislé stiahnutie po zápise. Ranný kandidát najprv číta sidecar s kontrolou SHA256/veľkosti proti CDB manifestu, potom pôvodný archív. Pozorovania sa uchovajú aj po začiatku zápasu; predikčný čitateľ vyberá len ešte nezačaté zápasy.
- Dokončenie majiteľ povolil následným „dokonci“. Workflow `propline-evening-odds.yml` má manuálny vstup `candidate_cdb=true`: presne 1 bulk dotaz, **0 detailových dotazov na zápasy**, zápis ponúk a read-back, bez tréningu či publikovania tipov. Pri opakovaní zápisu zadať `source_capture_run=ID` – obnoví uložený artefakt bez ďalšieho volania Prop-Line. Neopakovať nový zber len kvôli obsadenému CDB zámku. Automatický večerný režim a ranný plán zostávajú nezmenené.
- Dnešný nový zdroj: beh `45247747261`, captured_at `2026-11-23T19:19:49.603042+00:00`, **7 cieľových zápasov / 165 reálnych N+ kontraktov**, 1 bulk, 0 detailov, RapidAPI 0, Prop-Line remaining 531. Natívne identity/hash a presná reprodukcia stagingu overené lokálne. Prvý zápis správne odmietol obsadený CDB zámok; beh `45247946568` obnovuje rovnaký artefakt bez nového zberu. Výsledok zápisu a nezávislého read-back je zaznamenaný v PR #1798. Pôvodný nočný archív s nulou ponúk už nepopisuje večernú dostupnosť.
- Kontrola existujúceho feedu `2026-11-23T07:38:14.354709+00:00`: 2 TOP a 1 Value tip. Zo zdrojových ponúk sa 6 zápasov jednoznačne páruje; všetkých 6 vylučuje existujúca brána `excluded_atp_below_250`. Táto brána sa nemení a uloženie ponuky neznamená jej publikáciu ako tipu.
- Riziká/manuálne overenie: pokrytie reálnych sportsbook ponúk, zhodnosť hráča/začiatku a settlementu N+, kalibrácia pravdepodobnosti (existujúca provizórna count distribúcia), frekvencia under, čas výpočtu pri rannom behu. Živý kandidátsky ranný beh ani presnosť na novom holdoute sa netvrdia. Produkčná aktivácia vyžaduje samostatné rozhodnutie. Rollback nemaže už zachytené zdrojové ponuky.
- Testy `tests/test_aces_line_first.py`: oba príklady, bez ponuky, zachovanie TOP/Value a vstupov, oba hráči, rovnaké projekcie, presná priorita kurzu, lokálny kurz na reálnej hranici, neplatné hranice, duplicity/konflikty, nulové volania pri opakovaní, staging a mock writer/read-back/idempotencia.
- Lokálne overenie dokončenia: 185 regresných testov prešlo; nové testy overujú aj CDB manifest, odmietnutie nesprávneho hashu a identický staging pred/po začiatku zápasu. Žiadne nové projektové závislosti.

## Pravidlá spolupráce (dohodnuté 23.11.2026)
- Claude zlučuje PR do main len po „OK“ majiteľa v chate a po zelenom CI.
- Pred zlúčením: zhrnutie zmeny, riziká (najprv), spôsob návratu.
- Prepínače (Variables) zapína majiteľ, vždy po jednom.
- UI, zobrazenie kurzov, KPI a lokálny kurzový fallback sa nemenia bez výslovného súhlasu.

## Denník nasadení a návrat
| Dátum | PR / commit | Čo | Návrat |
|---|---|---|---|
| 2026-11-23 | (PR itf-auto) | ITF zber pokračuje automaticky od posledného dokončeného týždňa (assety `itf-auto-*`), 2016–2024; externý cron len zavolá workflow bez vstupov; max 5 000/beh; beží len cez deň 11:00–17:59 (Bratislava); globálny strop podľa hodiny: 11h 5 000, 12h 6 600, 13h 8 200, 14h 9 800, 15h 11 400, 16h 13 050 (90 %), 17:30 dobitie na 14 500; v noci nič | revert PR |
| 2026-11-23 | (PR itf-gapfill) | ITF gap-fill staging: párovanie hist-js ITF zápasov na RapidAPI (týždenný kalendár, oba priezviská, jednoznačne) + štatistiky do release `itf-gapfill-staging-v1` v tbt-data; CDB bez zmeny; ranné okno 04:00–07:30 chránené | zmazať workflow a release |
| 2026-11-23 | #1778 | zmazaný DIL kód (skripty, testy, workflowy, docs); DIL DB na Drive maže majiteľ | `git revert` PR |
| 2026-11-23 | (PR cleanup) | zmazaných 66 nepoužívaných workflowov (zoznam v UPRATANIE.md) | `git revert` PR obnoví všetky |
| 2026-11-23 | (PR identity) | HOTFIX: zmena hráča v zápase (lucky loser) už nezastaví celé ranné zverejnenie; nezverejnená predikcia sa nahradí, zverejnená ostane | revert PR |
| 2026-11-23 | (PR bulk odds) | read-only workflow: denné kurzy RapidAPI do artefaktu, 1 volanie/deň, bez zápisu do CDB | zmazať workflow; nič iné sa nemení |
| 2026-11-23 | (tento PR) | Value: prah podanie+príjem ≥ 0,06 (`TBT_VALUE_SERVE_RETURN_MIN`) | vrátiť PR alebo zmazať `TBT_VALUE_SERVE_RETURN_OWNER_APPROVED` |
| 2026-11-23 | #1766 → `c4ed468` | opravy + prepínače (všetky OFF) | `git revert -m 1 c4ed468` alebo zrušiť príslušnú `_OWNER_APPROVED` premennú |

Jeden súbor, jeden riadok = jedna zmena. Stav: PR = otvorený draft, MAIN = zlúčené, TODO = nezačaté.
Všetky nové prepínače sú predvolene VYPNUTÉ a zapína ich len majiteľ (GitHub → Settings → Variables → Actions).

## Zmeny
| Dátum | Stav | Čo | Prečo | Prepínač |
|---|---|---|---|---|
| 2026-11-22 | MAIN (#1766) | `finalize_dil_from_cdb_v2.py`: ATTACH cez `as_uri()` + `uri=True` | 16 testov padalo (`unable to open database`) | – |
| 2026-11-22 | MAIN (#1766) | `probe_tennisapi_extended_contract.py`: import `ProviderError` | `NameError` pri chybe | – |
| 2026-11-22 | MAIN (#1766) | `market_selection._confidence`: odstránený nedosiahnuteľný kód | nedefinovaná premenná | – |
| 2026-11-22 | MAIN (#1766) | Testy workflowov zosúladené s `oneoff_global_limit` | testy zaostali za workflowom | – |
| 2026-11-22 | MAIN (#1766) | TOP minimum picks + emergency fill z mäkkých pravidiel | systém nesmie mlčať; tvrdé pravidlá (kurz ≥ 1,50, identita, predštart, súťaže) sa nemenia | `TBT_TOP_MIN_PICKS` + `_OWNER_APPROVED`, `TBT_TOP_EMERGENCY_FILL` + `_OWNER_APPROVED` |
| 2026-11-22 | MAIN (#1766) | Viac es: tipy s gapom ≥ prah idú prednostne, ostatné len doplnia (nikdy prázdne) | vlastné výsledky 9.–20.11. (n=360): gap ≥ 1,3 → 85,5 % vs 80,6 % (+5,2 pp, CI +1,5..+9,3); top 3/deň podľa gapu 94,4 %, top 5/deň 91,7 % (12 dní) | `TBT_ACES_MIN_GAP` (napr. 1.3) + `_OWNER_APPROVED` |
| 2026-11-22 | MAIN (#1766) | Esá O/U: ak Prop-Line/RapidAPI ponúka reálnu hranicu, ktorá nevyhovie (p < 0,60 alebo EV < 0), tip sa NEnahradí ľahšou modelovou hranicou | vlastné výsledky: 124 z 218 tipov Esá malo modelovú hranicu (≈ projekcia − 1,5), reálna hranica len 103 (PrizePicks 87, Underdog 6); úspešnosť rovnaká (81,5 % vs 81,6 %), takže reálne hranice nestoja úspešnosť | `TBT_ACES_REAL_LINE_STRICT` + `_OWNER_APPROVED` |
| 2026-11-22 | MAIN (#1766) | data.yml: zápis readiness do tbt-data s 5 opakovaniami pri 409 | ranný beh 20.11. skončil `failure` kvôli súbehu zápisov (tipy sa publikovali) | – |
| 2026-11-22 | MAIN (#1766) | Pauza Setov (manuálna) | 62,7 %, pokles 66 → 59 % | `TBT_SETS_SUSPENDED` + `_OWNER_APPROVED` |
| 2026-11-22 | MAIN (#1766) | Pauza Gamov | 47,9 %, ROI −12,1 %, projekcia o 2,3 gamu nad realitou | `TBT_GAMES_SUSPENDED` + `_OWNER_APPROVED` |

## Odporúčané zapnutie (po zlúčení)
1. `TBT_MARKET_ANCHORED_OWNER_APPROVED=true`, `TBT_RANK_SOURCE=market_anchored` (poradie TOP podľa trhu: replay 49,6 → 57,4 %).
2. `TBT_TOP_MIN_PICKS_OWNER_APPROVED=true`, `TBT_TOP_MIN_PICKS=5` + emergency fill.
3. `TBT_GAMES_SUSPENDED_OWNER_APPROVED=true`, `TBT_GAMES_SUSPENDED=true`.
Vrátenie: zrušiť príslušnú `_OWNER_APPROVED` premennú.

## Čo je overené (vlastné výsledky 8.10.–20.11.2026)
- Viac es n=360 80,6 % ROI +31 %; Esá 81,7 %; ACCA 86,4 %; Štvorhra 75,5 %; Sety 62,7 % (klesá); Value 50,0 %; Gamy 47,9 %; TOP 49,6 %.
- Cena Viac es/Esá/Gamy/Sety je modelový indikatívny kurz, nie reálny bookmaker, takže ROI nie je ROI v peniazoch.
- TOP/Value 70 %+ pri kurze ≥ 1,50 nie je dosiahnuteľné výberom: strop je ≈ 59 % (TOP) a ≈ 52–55 % (Value).

## TODO (nezačaté, každé za prepínačom)
- Sety: manuálny vypínač hotový; automatická pauza podľa priebežnej úspešnosti zatiaľ nie (selektor nemá prístup k výsledkom).
- Štvorhra: zbierať do ~150 tipov, potom vyhodnotiť.
- Viac es / Esá: nemeniť. Segmenty (antuka 86 %, 1. kolo 32 = 84,6 %) zatiaľ len pozorovanie, nie návrh.
- Zber všetkých zápasov (`BLINQ_MARKET_A0_OWNER_APPROVED`) + export CDB na test signálu nad trhom (kritérium: log loss lepší o ≥ 0,005, CI < 0, ≥ 5 000 testovacích zápasov, ATP a WTA zvlášť).
- Value: `VALUE_MIN_ODDS = 1.80` v kóde vs. zadanie 1,70 – produktové rozhodnutie majiteľa.

## Bezpečnostné pripomienky
- Zrušiť PAT vložený v chate.
- Zmeniť heslo záloh a odstrániť `backup/CDB_OFFSITE_ZIP_PASSWORD_*.txt` z histórie až po rotácii hesla.
- Skontrolovať vykreslenie `selection_tier=emergency_fill` v UI.

## Ako spustiť testy
`PYTHONPATH=api:scripts python -m pytest tests -q` (potrebné: pyarrow, zstd). Stav 22.11.: 5 674 prešlo.

## Cieľ 3–5 tipov / kategória, 75 %+ (overené 22.11.)
| Kategória | 3–5/deň | Úspešnosť | Stav |
|---|---|---|---|
| Viac es | top 3–5 podľa gapu | 92–94 % (12 dní, n=36–60) | dosiahnuteľné, `TBT_ACES_MIN_GAP` |
| Esá | top 3–5 podľa istoty | 83–84 % (39 dní) | už teraz nad 75 % |
| TOP (kurz ≥ 1,50) | top 5 podľa trhu | ≈ 57–59 % | 75 % pri tejto cene nie je možné (strop trhu) |
| Value (kurz ≥ 1,70) | – | ≈ 50–55 % | 75 % pri tejto cene nie je možné |
Ranný beh: štart 05:15, hotovo ≈ 06:20 (Bratislava). Deň tipov sa zámerne uvoľňuje až po 06:01 (stávkový deň od 06:00) a Telegram ide o 06:20; posun spúšťača by čas zverejnenia nezmenil.

## Esá – zdroj hraníc (zistené 22.11.)
- Viac es (kto dá viac es): žiadna kancelária v dátach to neponúka → ostáva modelový tip bez kurzu.
- Esá O/U: reálna hranica z Prop-Line (PrizePicks, Underdog = DFS, nie klasická stávková kancelária) len 20 z 39 dní, ≈ 4,7 tipu/deň.
- Prop-Line closeout 18.–19.11.: player_aces takmer chýba (7 a 0 záznamov) → pokrytie, nie logika, je hlavný limit.
- Ďalší krok: overiť, či RapidAPI tennisapi1 vracia player aces O/U pre ATP/WTA 250+ (dnes primárny zdroj, Prop-Line fallback).

## Zosúladenie s GPT exportom (22.11., main bd3b450)
- TOP: min p 0,60, data_depth 0,30, max 5, minimum 3 je cieľ, nie záruka → `TBT_TOP_MIN_PICKS` to rieši.
- Esá: GPT pilot Prop-Line N+ (shadow od 23.11.) je oddelený; `TBT_ACES_REAL_LINE_STRICT` sa ho nedotýka.
- Večerný Prop-Line zber 23:00 je hlavný zdroj reálnych hraníc es; pokrytie overiť v `tbt-data/research/propline-evening-odds/`.

## Prístupy a secrets (kontrola 22.11., len názvy, bez hodnôt)
- Nepoužité v kóde ani workflowoch: `ADMIN_UID`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` → odporúčam zmazať (service role key je najcitlivejší a nič ho nepotrebuje).
- Používané: `TBT_DATA_GH_TOKEN` (184 workflowov), `RAPIDAPI_KEY`, `PROPL` (Prop-Line), `TGB`/`TGCH` (Telegram), `BLINQ_*_TOKEN`, `BLINQ_DRIVE_READER_JSON`, `LIVE_TENNIS_API_KEY`, `THE_ODDS_API_KEY` (1 workflow).
- Azure Functions čítajú nastavenia z Azure (Configuration → Application settings), workflowy ich nenastavujú. Kód očakáva 40 názvov, napr. `RAPIDAPI_KEY`, `RAPIDAPI_HOST`, `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`, `BLINQ_STORAGE_CONNECTION_STRING`, `BLINQ_ADMIN_STORAGE_CONNECTION_STRING`, `BLINQ_LIVE_WORKER_TOKEN`, `BLINQ_ACCOUNT_WORKER_TOKEN`, `BLINQ_SHARED_API_BUDGET_URL/TOKEN`, `BLINQ_SMTP_*`, `BLINQ_WEBPUSH_*`, `BLINQ_TRAINING_GITHUB_TOKEN`. Overenie v Azure z tohto prostredia nie je možné.
- Azure Function App má (22.11., screenshot) 16 nastavení. Chýbajúce a ich dopad: `BLINQ_WEBPUSH_*` → push notifikácie vypnuté; `BLINQ_TRAINING_GITHUB_TOKEN`/`_DISPATCH_TOKEN` → tréning z Adminu nefunguje; `BLINQ_SHARED_API_BUDGET_*` → OK, meranie kvóty ide cez Azure Table; `BLINQ_ADMIN_STORAGE_*`, `BLINQ_MEDIA_*` → fallback na `BLINQ_STORAGE_CONNECTION_STRING`; `LIVE_TENNIS_API_KEY` → live provider len z GitHubu. `BLINQ_DEFAULT_FREE_PREDICTIONS` v Azure kód nepoužíva.
- Tréning z Adminu: Azure tokeny NEpotrebuje (požiadavka → Azure Table → `admin-training-worker.yml` na GitHube, beží každých ~15 min, OK). Oprava v PR #1766: push-triggered „skipped“ behy tréningového workflowu posúvali `base` fronty, takže uložená požiadavka sa stratila. Teraz sa ignorujú.
- Prop-Line: predtým sa pre esá/dvojchyby uložila len PRVÁ kancelária; ostatné sa zahodili. Teraz sa uchovajú všetky (`other_books`) a model skúša hranice postupne, klasické kancelárie pred DFS (PrizePicks, Underdog). Bez prepínača – len pridáva reálne hranice, nič nové nevymýšľa.
- Blokér nasadenia: CI na main padal na 3 zastaraných testoch → web sa nenasadzoval (watchdog, issue #1765). PR #1766 to opravuje.

- Rozhodnutie majiteľa 22.11.: lokálny kurzový fallback, KPI (ROI/yield/auto) a stĺpec KURZ sa nemenia. `TBT_ACES_REAL_LINE_STRICT` ostáva vypnutý.
- Esá – pravidlo rezervy majiteľa (`TBT_ACES_CUSHION_RULE` + `_OWNER_APPROVED`, default OFF): z reálnych hraníc (aj jednostranných „N+“) Over len ak projekcia − hranica ≥ 1,5; Under len ak hranica − projekcia ≥ 1,5 (symetricky, rozhodnutie majiteľa 22.11.); z vyhovujúcich najvyšší kurz ≥ 1,50. Smer vyberá podľa ponuky. Platí pre hráča vybraného modelom (Viac es); oboch hráčov rieši line-first (GPT prompt).
- Value – podanie+príjem (`TBT_VALUE_SERVE_RETURN` + `_OWNER_APPROVED`, default OFF): zverejní len Value, kde vybraný hráč má lepší súčet kvality podania a príjmu (povrch, inak celkovo). Neoverené na histórii; majiteľ chce test v praxi. Engine pridáva `serve_return_edge` ku každej predikcii.

## Stratégia výberu (dohodnuté 23.11.)
- TOP: ísť S trhom (poradie podľa kurzu, nikdy proti trhu). Strop ≈ 59–64 %. Ranné kurzy 6:00 stačia (presnosť 67,1 % vs. záverečné 67,3 %).
- Value: ísť PROTI trhu len so signálom podanie+príjem ≥ 6 p.b. (CDB 1 877 vyrovnaných zápasov: 56,5 % pri n=356, zisková hranica pri 1,90 je 52,6 %).
- Esá: vlastná projekcia proti hraniciam kancelárií, rezerva 1,5 esa (simulácia 78,7 %).

## Výsledky 23.11.
- Denné kurzy RapidAPI: 1 000 dní (27.2.2024–22.11.2026), 527 184 zápasov, 1 000 volaní (artefakt behu 45135311353, 90 dní).
- ITF test: RapidAPI pozná ~95 % hist-js ITF zápasov, štatistiky 20/20 (104 volaní). Pred veľkým zberom overiť podanie/príjem na prvých 200.

## 2026-11-23 – CDB importy bez API (zdroj → zápasy) a rollback
Všetko NULL-only (okrem opravy orientácie), guarded workflow: lock, prewrite backup release, CAS, full readback, 2. beh = 0.
Rollback: obnov partície z releasu `blinq-cdb-*-prewrite-<run_id>-1` v tbt-data (history-YYYY.parquet + manifesty).
| PR | Čo | Zápasy | Write run |
|---|---|---|---|
| #1787/#1788 | Sackmann/TML štatistiky Challenger/ATP | 11 240 | 45198536085 |
| #1789 | ITF ženy štatistiky 2025-26 | 17 513 | 45208319247 |
| #1790 | oprava prehodených p1/p2 štatistík (Sackmann-potvrdené) | 5 688 | 45211682760 |
| #1791 | ITF muži + WTA štatistiky | 6 412 | 45220670690 |
| #1795 | bulk kurzy bet365 → `_tbt_market_history` | 133 888 | 45241241201 |
| #1796 | rebríčky ATP/WTA (Sackmann weekly) | 150 653 | 45243990048 |
| #1797 | gemy/sety zo skóre (parser `parse_event_score`) | 346 361 | 45246930046 |
| #1801 | konsenzus kurzov HF minmaxxxer → `_tbt_market_consensus` | 9 643 | 45253782831 |
ITF zber: #1783 (budget fix), #1784 (CDB-ready staging), #1786 (skip duplicít), #1792 (večerný owner cap).
Zistenie: ledger vs provider rozdiel ~1 000/deň; ochrana = provider reserve 500 v klientovi.

### Večerný zber a admin Shadow testing
Večerný workflow najprv skontroluje denný súbor v CDB. Ak existuje, skončí bez zápisu a bez volania poskytovateľa. Existujúci research archív použije pred novým zberom. Pred jediným súhrnným dotazom rezervuje deň v súkromnom research adresári. Pri páde po rezervácii skontrolovať pôvodný artefakt, aby sa platený dotaz neopakoval. Ponuky ukladá pod globálnym CDB zámkom. Drive sa nepoužíva.
Variant `aces_line_first` je predvolene vypnutý a jeho virtuálne tipy sa ukladajú do admin Shadow testing. Under vyžaduje overený pár. Vyrovnanie používa počet es vybraného hráča podľa identity v CDB. Chýbajúci počet ostáva nevyhodnotený. Vypnutie ktoréhokoľvek existujúceho prepínača kandidáta zastaví nové virtuálne tipy. Návrat večerného workflowu: revert tejto zmeny verzus main.

### 24.11 – Esá line-first napojené na Shadow testing (Claude, merge s #1815)
- Shadow záznamy `aces_line_first` vznikajú vždy (nepublikujú sa), nezávisle od `TBT_ACES_LINE_FIRST_CANDIDATE`; ten prepínač ostáva len pre prípadné budúce zverejnenie.
- Vyhodnotenie: počet es vybraného hráča v CDB vs. ponúknutá hranica; presná zhoda = neplatné.
- Vypnutie: `TBT_OFFER_SHADOW_DISABLED=true`. Revert: revert merge commitu.

## 06:00 – spoľahlivosť ranného zverejnenia (kandidát v PR)

Neúspešný ranný data.yml má jeden pokus o obnovu z posledného kompletného prediction release/ledger cez režim deploy-current. Používa rovnakú produkčnú concurrency skupinu. Supervízor čaká na terminálny stav prvého behu a lokálnych 06:20 v Bratislave. Pri neskoršom zlyhaní pokračuje hneď po jeho zistení. Druhý pokus nespúšťa platený refresh. Pred nasadením sa musí potvrdiť dnešný použiteľný cache s TOP alebo Value. Ak prvý beh padol pred uložením kompletného feedu a ledgeru, obnova nevytvorí nové predikcie z čiastkových dát.

Alarm má samostatný plán na 06:30 Europe/Bratislava. Kontroluje denný kľúč, čerstvosť, viditeľné počty a identitu vydaného TOP alebo Value na nasadenej službe. Prázdny, starý či neoveriteľný feed = červený (zlyhaný) beh; GitHub o ňom pošle e-mail majiteľovi (Settings → Notifications → Actions). Žiadny Telegram, žiadne ďalšie tajomstvá. GitHub môže plánovaný čas oneskoriť.

Ranná prognóza hlási izolované chyby vstupu, príznakov, skórovania a priradenia kurzu cez row_quarantine (počet, identita, fáza, typ výnimky) v refresh_report.json. Chybný hromadný vstup modelu skúša opätovne po riadkoch lokálne. Globálna chyba modelu ostáva zlyhaním. Platné riadky idú do existujúcich selektorov.

Návrat: revert PR; samostatný alarm sa dá vypnúť v Actions. Manuálne overiť súkromné doručenie na správny chat, produkčný readback a simulovaný neúspech po uložení cache. Opakovanie pridáva 0 RapidAPI a 0 Prop-Line volaní. Alarm používa jeden produkčný readback a pri probléme jednu Telegram správu.

### 24.11 – odstránenie duplicitných hist-js zápasov (pripravené, čaká na schválenie)
- `scripts/cdb_dedupe_hist_js.py` + workflow `cdb-dedupe-hist-js.yml`: hist-js riadok sa odstráni len ak natívny riadok má rovnaký ISO týždeň, rovnakú dvojicu ID hráčov a rovnakého víťaza (jednoznačne). Štatistiky, ktoré má len kópia, sa najprv presunú (NULL-only, správna orientácia).
- `release_store`: poistky počtu riadkov a identít povolia odstrániť **presne** schválený zoznam ID (inak blokujú ako doteraz).
- Zápis až po `approved_by_operator: true` v `.github/cdb-dedupe-request.json`.
- Návrat: obnova z release `blinq-cdb-dedupe-prewrite-<run_id>-1`.

- 2026-11-25: Frozen-candidate: readiness po fite sťahuje aktuálnu CDB do `.cache/tbt/readiness-history`, nie do zmrazenej `.cache/tbt/history` (inak shadow gate padol na „input changed“).
