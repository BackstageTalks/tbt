# BlinQ 7.3.6-r6 — public Results reset + all-section publication tracking

## Product decision
Public Results history is reset from **2026-09-19 00:00 UTC**. Private immutable publication ledger and canonical training/history data are intentionally preserved. They remain available for audit/model quality but are no longer exposed as pre-reset public Results.

## From the reset onward
The publication lifecycle now tracks/grades public sections through the shared ledger:
- TOP (`top_daily`)
- Short Odds (`prime`)
- VALUE (`value`)
- DOUBLES (`doubles`, future-ready when the model emits rows)
- ESA / double faults (`ace`)
- SETS (`sets`)
- GAMES (`games`)

SETS/GAMES are now frozen at successful deployment and graded against structured final score totals. Projection-only rows affect hit-rate style metrics but never invent bookmaker ROI.

## Public Results contract
- old/mixed pre-reset Results are hidden from the public feed;
- only successfully published, settled section publications at/after the cutoff are returned;
- old raw ledger/history is not deleted;
- Results metadata exposes `history_cutoff` and `history_reset`;
- frontend shows the reset date instead of claiming an all-time history;
- result filter includes Short Odds in addition to TOP/VALUE/ESA/SG/DOUBLES.

## Consolidated UI from r5
- DOUBLES tab enabled in Daily Hub;
- DOUBLES included in SEE ALL;
- desktop TOP table has no internal vertical scrollbar and is sized for ten rows;
- loader dark-square cleanup remains included;
- patch cache marker is `736-r6` / `p=6`, while release stays `7.3.6` / asset revision `7360`.

## Verification
- focused Results/SG/UI/release suite: 35 passed;
- broad local suite: 506 passed, 1 skipped; 8 parquet tests cannot run locally because `pyarrow` is not installed;
- Azure Functions smoke test cannot run locally without `azure-functions`.
