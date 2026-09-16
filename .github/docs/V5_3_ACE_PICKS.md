# BlinQ v5.3 — Ace Picks

## What is live in this version

- TennisApi whole-match `Aces` and `Double Faults` are stored as raw counts:
  `p1_aces`, `p2_aces`, `p1_double_faults`, `p2_double_faults`.
- Statistics marker schema is now `2`, so older schema-1 rows are eligible for
  one safe re-enrichment pass and can gain the new count fields.
- `Ace Picks` can publish up to 5 Aces + 5 Double Faults projections from
  point-in-time historical counts.
- The projection uses only history before the current UTC day. Same-day
  post-match statistics are excluded because exact completion timestamps are
  not available.
- Recent observations are exponentially weighted and shrunk toward the tour
  baseline. Surface and best-of context are blended only when sample depth is
  sufficient. Aces also include a conservative opponent-allowance component.
- Small samples and small projection gaps do not publish a card.

## Important boundary

Ace Picks are currently `projection_only`.

The provider has confirmed post-match Aces/DF statistics, but BlinQ has not
verified a dependable pre-match Aces/DF odds/line source. Therefore v5.3 does
**not** fabricate odds, edge, EV, ROI, or a calibrated win probability for
these cards. The UI shows projected count, opponent projection, gap, a
projection score, and sample depth.

Top 10 Daily remains odds-backed only, so projection-only Ace cards do not enter
Top 10 or betting Results yet.

## Efficient data fill

After Environment enrichment is no longer holding the history-writer lock:

1. Open **Tennis data and predictions**.
2. Select mode **ace-statistics**.
3. Start with:
   - `max_requests`: 2500
   - `ace_target_samples`: 18
   - `ace_lookback_days`: 550
4. The job reads the current prediction feed, finds its upcoming player IDs,
   and spends requests only on their recent historical matches until the target
   sample depth is reached or the request cap stops the run.
5. Run **refresh** afterwards to publish the resulting Ace Picks.

The targeted statistics job intentionally shares `tbt-history-data-writer` with
Environment enrichment and normal refresh/history writes. Do not run those
writers simultaneously.
