# Upratanie a CDB – súpis (23.11.2026, len návrh, nič nezmazané)

## 1. Workflowy na zmazanie (66)
Nebežali 30+ dní, žiadny iný workflow/skript ich nevolá, žiadny test ich nečíta. Majiteľ odklikne → zmažem v samostatnom PR.

| Workflow | Posledný beh |
|---|---|
| `environment-regression.yml` | 2026-10-04 |
| `high-impact-audit.yml` | 2026-10-04 |
| `issued-evidence-audit.yml` | 2026-10-04 |
| `champion-input-audit.yml` | 2026-10-05 |
| `champion-recalibration.yml` | 2026-10-05 |
| `court-speed-ablation.yml` | 2026-10-05 |
| `quality-group-ablation.yml` | 2026-10-05 |
| `quality-walk-forward.yml` | 2026-10-05 |
| `table-market-audit.yml` | 2026-10-05 |
| `research-source-acquisition.yml` | 2026-10-06 |
| `tennis-abstract-elo.yml` | 2026-10-06 |
| `figshare-wimbledon-2023.yml` | 2026-10-07 |
| `livetennisapi-paid-history.yml` | 2026-10-07 |
| `livetennisapi-player-profiles.yml` | 2026-10-07 |
| `wimbledon-1992-1995-pbp.yml` | 2026-10-07 |
| `wimbledon-2023-advanced.yml` | 2026-10-07 |
| `blinq-tennisexplorer-private-cloud.yml` | 2026-10-09 |
| `blinq-three-sources-private-cloud.yml` | 2026-10-09 |
| `blinq-cdb-atptour-archive-stage.yml` | 2026-10-10 |
| `blinq-cdb-oddstrader-offline-stage.yml` | 2026-10-10 |
| `blinq-cdb-private-handoff.yml` | 2026-10-10 |
| `blinq-cdb-source-completion.yml` | 2026-10-10 |
| `blinq-failed-historical-retry.yml` | 2026-10-10 |
| `blinq-failed-source-recovery.yml` | 2026-10-10 |
| `blinq-oddstrader-odds-qa.yml` | 2026-10-10 |
| `existing-data-value-audit.yml` | 2026-10-10 |
| `oddstrader-current-readback.yml` | 2026-10-10 |
| `wimbledon-2023-cdb-stage.yml` | 2026-10-10 |
| `wimbledon-2023-exact-import.yml` | 2026-10-10 |
| `wta-doubles-four-id-audit.yml` | 2026-10-10 |
| `atp-weekly-rank-2021-2023-gap.yml` | 2026-10-11 |
| `atp-weekly-rank-cdb-gap.yml` | 2026-10-11 |
| `blinq-atp2015-2020-exact-rank-gaps.yml` | 2026-10-11 |
| `blinq-audited-uploaded-score-import.yml` | 2026-10-11 |
| `blinq-cdb-shard-autorecovery.yml` | 2026-10-11 |
| `blinq-manual-servestats-current-cdb-preflight.yml` | 2026-10-11 |
| `blinq-wta2016-2020-guarded-rank-import.yml` | 2026-10-11 |
| `blinq-wta2025-guarded-rank-import.yml` | 2026-10-11 |
| `blinq-wta2026-guarded-rank-import.yml` | 2026-10-11 |
| `txe-atp2023-score-import.yml` | 2026-10-11 |
| `txe-atp2023-score-stage.yml` | 2026-10-11 |
| `txe-singles-multiyear-stage.yml` | 2026-10-11 |
| `txe-singles-retry-additions-stage.yml` | 2026-10-11 |
| `txe-singles-retry-score-import.yml` | 2026-10-11 |
| `txe-singles-score-import.yml` | 2026-10-11 |
| `txe-wta2024-score-import.yml` | 2026-10-11 |
| `txe-wta2024-score-stage.yml` | 2026-10-11 |
| `wimbledon-2024-additive-stage.yml` | 2026-10-11 |
| `wimbledon-2024-exact-import.yml` | 2026-10-11 |
| `wta2024-score-observations.yml` | 2026-10-11 |
| `wta2026-verified-rank-rebase.yml` | 2026-10-11 |
| `blinq-season-2022-2025-cdb-audit.yml` | 2026-10-12 |
| `tml-official-three-way-witness.yml` | 2026-10-12 |
| `blinq-cdb-enrichment-coverage.yml` | 2026-10-14 |
| `blinq-pbp-source-vs-current-cdb.yml` | 2026-10-14 |
| `cdb-lock-liveness-readonly-qa.yml` | 2026-10-16 |
| `blinq-cdb-live-pairwise-current-readonly.yml` | 2026-10-17 |
| `blinq-drive-atp-2020-2021-native-cdb-audit.yml` | 2026-10-17 |
| `blinq-reconciled-results-readonly-pr.yml` | 2026-10-17 |
| `blinq-drive-atp-2017-2019-native-cdb-audit.yml` | 2026-10-18 |
| `wta-official-2026-import.yml` | 2026-10-19 |
| `cdb-atp-drive-match.yml` | 2026-10-20 |
| `cdb-wta-drive-match.yml` | 2026-10-20 |
| `cdb-wta-snapshot-preflight.yml` | 2026-10-20 |
| `audit-cdb-sackmann-bp-count-gap.yml` | 2026-10-21 |
| `model-721-odds-research.yml` | 2026-10-21 |

Ďalších 17 nebežalo 30+ dní, ale čítajú ich testy – rušiť spolu s testami, po kontrole.

## 2. DIL
- Podľa majiteľa môže ísť preč. DIL nie je v Git strome tbt-data ako DB súbor; žije v Release assetoch / Drive a v skriptoch `scripts/*dil*`, workflowoch `dil-*`. Najprv súpis assetov a skriptov, potom zmazanie po OK (nevratné).

## 3. Sackmann a iné voľné zdroje → CDB
Prečo to dnes nejde:
1. **Identita:** Sackmann má vlastné ID hráčov a turnajov; CDB používa ID z RapidAPI. Párovanie mien je hlavná prekážka.
2. **Dátum:** Sackmann má dátum začiatku turnaja, nie zápasu; CDB vyžaduje presný čas zápasu.
3. **Licencia: CC BY-NC-SA 4.0 = zákaz komerčného použitia.** BlinQ má platené členstvá → pred použitím v produkčnom modeli treba súhlas autora alebo len výskum. ⚠️ RIZIKO.

Návrh jednoduchšieho plnenia:
- Nie zapisovať voľné zdroje priamo do kanonickej CDB, ale do **samostatnej výskumnej vrstvy** (`research_matches`): vlastné ID zdroja + tabuľka párovania hráčov (meno + krajina + dátum narodenia → RapidAPI ID), dátum = začiatok turnaja + kolo.
- Model a testy môžu čítať obe vrstvy; kanonická CDB ostáva čistá.
- Jeden univerzálny prevodník CSV → `research_matches` so zoznamom stĺpcov (mapovanie na `stats_json`), namiesto samostatného skriptu pre každý zdroj.

## 4. API pre CDB
- Denné kurzy: `events/odds/{deň}` = 1 volanie na celý deň (≈ 994 zápasov) → workflow v PR #1773 (čaká na zlúčenie).
- Štatistiky ITF chýbajú pri ≈ 214 tisíc zápasoch; najprv test výhody na kurzoch, potom rozhodnúť, či ich dopĺňať (50k/deň od 5. v mesiaci).
