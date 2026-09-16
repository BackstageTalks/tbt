# BlinQ v5.4 — S/G Picks

## What this version adds

v5.4 completes the first real Sets / Games data path without inventing a
bookmaker line or price.

- Structured TennisApi `homeScore` / `awayScore` per-set fields are normalized
  into auditable whole-match facts:
  - `p1_sets_won`, `p2_sets_won`
  - `p1_games_won`, `p2_games_won`
  - `p1_first_set_won`, `p2_first_set_won`
  - `total_sets`, `total_games`
  - `tiebreak_sets`, `straight_sets`, `deciding_set`
- Only structured `period1..period5` scores are accepted. Human-readable score
  strings are not parsed. Contradictory, partial, retirement, walkover, or
  unsupported match-tiebreak shapes fail closed instead of creating fake data.
- Historical category/event payloads automatically retain structured score facts
  when they already contain them.
- A targeted `sg-scores` history job can fetch event detail only for recent
  historical matches involving players on the current BlinQ board.
- The score enrichment marker is `_tbt_score` schema `1`; unavailable or
  unsupported rows are cached to avoid repeated API waste.

## S/G projection output

`S/G Picks` publishes at most 5 Sets and 5 Games cards (10 combined).

### Sets

- Best-of-3: projects the long-match tendency used for `Over / Under 2.5 Sets`.
- Best-of-5: projects the long-match tendency used for `Over / Under 3.5 Sets`.
- The selector needs historical score depth for both players and a meaningful
  distance from a neutral 50/50 long-match tendency.

### Games

- Projects the expected total games from both players' recent structured score
  history.
- The projection is compared with the ATP/WTA + best-of historical baseline.
- A card is emitted only when the deviation from that baseline is material and
  the sample-depth/confidence guardrail passes.
- The card is labelled `High Total Games` or `Low Total Games`; it is not yet a
  bookmaker Over/Under bet because no verified market line has been attached.

Recent observations are exponentially weighted, estimates are shrunk toward
ATP/WTA + best-of baselines, and surface-specific history is blended only with
sufficient samples.

## Point-in-time boundary

The projection index uses only matches scheduled before the current UTC day.
Same-day completed matches are excluded because the canonical history does not
store a trustworthy exact completion timestamp for every match. This is the
same conservative anti-leakage boundary used by Ace Picks.

`best_of` is now preserved in newly generated predictions. Existing pending
ledger rows may safely receive a missing `best_of` value during reconciliation;
the already committed Match Winner probability is never changed.

## Important boundary: projection only

S/G cards have:

- `price_status = projection_only`
- no bookmaker odds
- no edge
- no EV
- no ROI
- no betting settlement

The market-selection metadata explicitly separates `odds_backed_outputs` from
`projection_only_outputs`.

Top 10 Daily and Value remain odds-backed. Projection-only S/G cards do not enter
Top 10 or Results until a real pre-match Sets/Games price + line mapping is
validated and backtested.

## Efficient data fill

The new workflow mode is **sg-scores**.

Recommended first targeted run after Environment enrichment releases the shared
history-writer lock:

- `mode`: `sg-scores`
- `max_requests`: `2500`
- `sg_target_samples`: `24`
- `sg_lookback_days`: `730`

The job:

1. reads current upcoming player IDs from `tbt-predictions-v1/feed.json`,
2. checks how much structured score history is already present,
3. works newest-to-oldest only on missing relevant historical rows,
4. fetches `/api/tennis/event/{event_id}` through the existing server-side
   RapidAPI client,
5. checkpoints changed yearly parquet partitions every 100 affected matches,
6. uploads `sg_score_report.json` with the current targeted coverage.

It shares the `tbt-history-data-writer` concurrency group with Environment
Enrichment, Ace statistics, normal history writes, and Refresh. Do not run those
writers simultaneously.

After the S/G history job finishes, run **refresh**. The normal refresh itself
uses no extra provider requests to calculate the S/G projections; it reads the
stored structured score facts and publishes the qualifying cards.
