# PropLine ACES real sportsbook quotes — isolated audit, 2026-11-01

## Evidence
- GitHub Actions run: https://github.com/BackstageTalks/tbt/actions/runs/41255902993
- UTC captured: 2026-11-01T00:15:24.747749+00:00
- Branch: `audit/propline-aces-50calls-20261101`
- Isolated script: `scripts/propline_aces_quote_probe.py`
- Offline self-test: **PASS**
- Live workflow: **SUCCESS**
- Provider attempts: **10** / hard ceiling **12**, audit allowance **50/day**
- PropLine provider remaining header: **992**, protected reserve **150**
- Event payloads examined: **43** (not necessarily unique events: bulk + targeted event requests may overlap)
- Fully paired, same-bookmaker, same-player, same-line, full-match **non-DFS sportsbook ACES O/U quotes: 0**
- Rejected candidate groups: **45 DFS/fantasy paired groups**, **55 one-sided groups**. These are candidate group counts, not unique event counts; one-sided groups may include DFS and sportsbook sources.
- Actual verified bookmaker name / player / line / over and under prices: **none**. Do not invent a real sportsbook price.
- `writes_to_cdb_or_feed = 0`, `published_picks_changed = 0`; no model, CDB, production pipeline, TG feed, web, historical results or champion changes.

## Interpretation
A functioning provider endpoint and a successful request do not imply a tradable two-sided tennis player-aces market. In this particular sample, no real two-sided quote was verified. The 2.00 DFS payout from PrizePicks is **not** a real standalone bookmaker price and must not be counted as verified sportsbook ROI.

The current production pipeline is odds-first (`scripts/pipeline.py`, `publishable_api_price` filter). Blindly excluding fantasy books from production price attachment **without decoupling model-pick publication** could reduce the published ACES count, contrary to the approved constraint. Therefore **do not merge/deploy an odds-source filter based only on this sample**.

## Smallest safe next step
Without re-running the live test today, inspect existing archived raw payloads or add per-bookmaker, per-market, per-side diagnostic counters for a *future authorized* bounded run. Target actual published model ACES matches and distinguish (a) no player_aces market, (b) DFS-only, (c) sportsbook one-sided, (d) sportsbook complete two-sided quote, and (e) player-name/line/period mismatches. Only after at least one real paired quote is verified should a provider-native ingestion change be considered. Regression gates: existing pick count cannot fall, no DFS odds may be presented as real ROI, exact player/line/period/source matching, model/CDB/champion unchanged, and independent readback after any deployment.
