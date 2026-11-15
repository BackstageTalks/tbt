# Codex 7.2.1 — exact issuance and sports-evidence reconciliation (2026-11-15)

Scope: current `v7.2.1-v201-20261022T134742452543Z`, **read-only**.
Grounding: user-provided immutable `BlinQ-specific-tip-evidence.json`,
`BlinQ-issued-top-current.json`, `BlinQ-serving-model-inspection.json`,
and Codex's bounded release verification report. Historical snapshots are
**not** a fresh production readback and must not be used as training labels.

## Five requested exact published TOP entries

All five rows have `snapshot_valid=true`, `model_version` matching the
production version above and `data_depth=1.0`; all were recorded before
their scheduled starts. The reported model and public confidence are equal
because the old history-count shrink equals identity when depth is 1.0.

| Issued UTC | Event | Fixture (selected player **bold**) | Raw = public p | Paired S/R PIT evidence | Both surface S/R PIT evidence | Overall match history (P1/P2) | Surface history (P1/P2) | Price attached before issue | Settled |
|---|---|---|---:|---|---|---|---|---:|---|
| 2026-11-12 05:13:57 | 17542924 | Michaela Laki / **Julia Adams** | 69.412% | true | true | 166/232 | 116/53 | 1.529101 | LOSS |
| 2026-11-12 05:13:57 | 17540429 | **Matilde Paoletti** / Jennifer Ruggeri | 82.628% | true | true | 109/226 | 92/194 | 1.529101 | LOSS |
| 2026-11-11 05:15:17 | 17535878 | **Oskar Brostrom Poulsen** / Tiago Silva | 71.816% | **not recorded** | **not recorded** | 81/135 | 58/131 | 2.50 | LOSS |
| 2026-11-11 05:15:17 | 17533465 | **Aurora Zantedeschi** / Astrid Lew Yan Foon | 71.816% | **not recorded** | **not recorded** | 277/213 | 225/107 | 1.520833 | WIN |
| 2026-11-11 05:15:17 | 17532974 | **Karim Ibrahim** / Nikita Ianin | 71.816% | **not recorded** | **not recorded** | 259/289 | 242/267 | 2.70 | LOSS |

**Important:** `not recorded` is not evidence that the stats were absent.
For these five `snapshot_valid` published TOP rows, the 65% floor,
old depth/surface gates, confirmed price >=1.50, original side identity and
pre-start snapshot explain eligibility. None of the five match results
proves an identifiable *cause* of any miss. No result was used to change
the model or alter historic issuances.

## Requested high-profile examples

- **Zverev–Jódar** event 17545024: *already predicted and issued in PRIME*,
  not absent from BlinQ. 7.2.1 scored Zverev at **76.456%**,
  `data_depth=1.0`, paired overall and surface serve/return known.
  Verified 2026-11-13 snapshot: PRIME quote **1.380228**,
  2026-11-14 reissue: **1.420168**; both below the TOP **1.50** odds
  boundary. The 2026-11-15 copy contains no priced market. The match
  results were unsettled in the supplied evidence. This is a *price-bucket
  explanation*, not a claim that no sporting prediction existed.
- **Shelton–Fils**: earlier diagnostic reported a 7.2.1 sports score
  **57.42%** and `data_depth=1.0`. That is below TOP's fixed 65% floor,
  independently of accumulated match count. The supplied exact-issuance
  file does not contain a verified Shelton–Fils release snapshot; therefore
  this is a prior diagnostic observation, **not** a new end-to-end live
  publication trace.

## Serving evidence and release boundaries

- Supplied production inspection pins model SHA-256
  `c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91`,
  **125 real feature names**, **0 price features** and **isotonic** model
  calibration. The model is not uncalibrated; the evidence problem is the
  reliability of the **selected issued TOP cohort**, not absence of an
  estimator.
- Independent issued TOP cohort: 57 published, 51 settled, 30W/21L
  (**58.82%**), average issued probability **76.23%** and Brier **0.27845**.
  This small selected cohort does not establish a corrected calibrator.
- The bounded sports replay had 36 morning anchor days, 2,044 eligible
  candidates after time filters, but only **7 comparable model days**;
  13,072 rows lacked usable time evidence. Neither retroactively converted
  candidate predictions nor successful outcomes count as verified issuance.
- Per Codex instruction **no fitting**, calibrator override, champion
  activation, odds-based ranking, new API usage, CDB import, changed TOP
  odds/quality floors, or Telegram/email posting accompanies this report.

**Open evidence:** Full ingest→identity→pre-match-feature→selection→feed
readback for the historical Shelton–Fils absence is unavailable in the
attached release snapshots; independently replayed no-price model calibration
versus a fresh untouched holdout is also not available. Do not claim those
checks completed solely from this historical report.

## Release deployment record

- Codex source PR #1632 merged as `76b7789c2029393c80360938b58ad34030a1bdab`.
- Serving/UI completion PR #1636 merged as `c9bd70bfb7b787e66e3d05af4a1e94b09c98bac8`; exact-head CI `43764875368` passed backend, Node and browser.
- The first full CI deployment run for `c9bd70b` was cancelled by a newer unrelated `main` commit before upload. This marker requests the existing fail-closed Azure UI/API hotfix deploy of the current `main` with exact-revision and asset-hash read-back. **Deployment is not verified by this commit; use the workflow run and live checks.**
- Neither model binary nor serving-model calibration was modified or promoted. Historical issued records remain immutable.
