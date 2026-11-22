# Claude – poznámky k úpravám BlinQ

Jeden súbor, jeden riadok = jedna zmena. Stav: PR = otvorený draft, MAIN = zlúčené, TODO = nezačaté.
Všetky nové prepínače sú predvolene VYPNUTÉ a zapína ich len majiteľ (GitHub → Settings → Variables → Actions).

## Zmeny
| Dátum | Stav | Čo | Prečo | Prepínač |
|---|---|---|---|---|
| 2026-11-22 | PR #1766 | `finalize_dil_from_cdb_v2.py`: ATTACH cez `as_uri()` + `uri=True` | 16 testov padalo (`unable to open database`) | – |
| 2026-11-22 | PR #1766 | `probe_tennisapi_extended_contract.py`: import `ProviderError` | `NameError` pri chybe | – |
| 2026-11-22 | PR #1766 | `market_selection._confidence`: odstránený nedosiahnuteľný kód | nedefinovaná premenná | – |
| 2026-11-22 | PR #1766 | Testy workflowov zosúladené s `oneoff_global_limit` | testy zaostali za workflowom | – |
| 2026-11-22 | PR #1766 | TOP minimum picks + emergency fill z mäkkých pravidiel | systém nesmie mlčať; tvrdé pravidlá (kurz ≥ 1,50, identita, predštart, súťaže) sa nemenia | `TBT_TOP_MIN_PICKS` + `_OWNER_APPROVED`, `TBT_TOP_EMERGENCY_FILL` + `_OWNER_APPROVED` |
| 2026-11-22 | PR #1766 | Viac es: tipy s gapom ≥ prah idú prednostne, ostatné len doplnia (nikdy prázdne) | vlastné výsledky 9.–20.11. (n=360): gap ≥ 1,3 → 85,5 % vs 80,6 % (+5,2 pp, CI +1,5..+9,3); top 3/deň podľa gapu 94,4 %, top 5/deň 91,7 % (12 dní) | `TBT_ACES_MIN_GAP` (napr. 1.3) + `_OWNER_APPROVED` |
| 2026-11-22 | PR #1766 | Esá O/U: ak Prop-Line/RapidAPI ponúka reálnu hranicu, ktorá nevyhovie (p < 0,60 alebo EV < 0), tip sa NEnahradí ľahšou modelovou hranicou | vlastné výsledky: 124 z 218 tipov Esá malo modelovú hranicu (≈ projekcia − 1,5), reálna hranica len 103 (PrizePicks 87, Underdog 6); úspešnosť rovnaká (81,5 % vs 81,6 %), takže reálne hranice nestoja úspešnosť | `TBT_ACES_REAL_LINE_STRICT` + `_OWNER_APPROVED` |
| 2026-11-22 | PR #1766 | data.yml: zápis readiness do tbt-data s 5 opakovaniami pri 409 | ranný beh 20.11. skončil `failure` kvôli súbehu zápisov (tipy sa publikovali) | – |
| 2026-11-22 | PR #1766 | Pauza Setov (manuálna) | 62,7 %, pokles 66 → 59 % | `TBT_SETS_SUSPENDED` + `_OWNER_APPROVED` |
| 2026-11-22 | PR #1766 | Pauza Gamov | 47,9 %, ROI −12,1 %, projekcia o 2,3 gamu nad realitou | `TBT_GAMES_SUSPENDED` + `_OWNER_APPROVED` |

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
