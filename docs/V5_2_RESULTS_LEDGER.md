# BlinQ v5.2 — Results and market publication ledger

This release makes Results auditable for odds-backed sections without changing the immutable core Match Winner prediction commitment.

## Core prediction vs betting-section publication

A Match Winner probability can be public before provider odds arrive. Top 10 Daily and Value therefore have an independent publication lifecycle:

1. current provider-1 odds create a pending market publication candidate;
2. the candidate is stored in the private prediction ledger;
3. the exact deployed feed is validated against that ledger candidate;
4. only after successful Azure deployment is `issued_at` confirmed;
5. settlement grades only records that were actually issued before the actual match start.

`market_publications[]` contains section, market, selection, odds, probability, edge, EV, betting day and independent publication/result state. The same underlying selection may be present in Top 10 Daily and Value. Section metrics count it in each section; overall betting ROI deduplicates it using `selection_key`.

## Units and ROI

Results use a transparent flat **1 unit** reference stake per issued betting selection:

- win: `profit_units = odds - 1`
- loss: `profit_units = -1`
- ROI: `sum(profit_units) / sum(staked_units)`

No staking strategy is implied or fabricated.

## Results UI

The Results workspace now supports filters for category, tour, surface and period, and shows Record, Hit Rate, Avg Odds, ROI, Units and Sample. The serving feed returns at most the latest 1,000 settled core prediction rows; aggregate betting performance is calculated from the full settled ledger before that presentation cap.
