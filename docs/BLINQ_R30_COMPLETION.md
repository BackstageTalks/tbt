# BlinQ 7.3.6-r30 — prediction/history completion pass

## What this pass fixes

This pass completes the code-side work left after r29. It does not invent historical bets, odds, or outcomes. When production evidence is missing, the application reports the smaller recoverable sample instead of manufacturing history.

### 1. Aces / Double Faults calibration

`ace-count-projection-v4` now models uncertainty of the **next match**, not uncertainty of a historical mean. A chronological walk-forward Aces/DF backtest is rebuilt from the private historical snapshot on refresh. A dependency-free monotone calibrator is enabled only when its chronological validation Brier score is not materially worse than the raw model. Production calibration is conservative: it may reduce displayed confidence but can never inflate it above the raw forecast.

Cards retain `uncalibrated_projection_confidence`, `raw_superiority_confidence` and `projection_uncertainty` for diagnostics. Caps are 93% for Aces and 88% for Double Faults.

### 2. Why Sets / Games disappeared

The production selector was not empty. The 2026-09-20 production refresh selected **10 Sets + 10 Games**, but the final feed contained `sg=0`. The loss happened during publication snapshot restoration: Sets/Games candidates did not carry the same semantic `projection_scope`/`projection_metric` identity used by the immutable market-publication ledger.

r30 gives Sets/Games explicit `match_total` identity and adds a publication integrity gate. If a selector produces Aces, DF, Sets or Games and the same counts do not survive into the final serving feed, refresh now fails instead of silently deploying an empty category.

Games confidence also uses next-match predictive variance instead of dividing historical variance by sample count. Sets/Games confidence is capped at 90%.

### 3. Why Aces appeared empty

The same 2026-09-20 production run selected **8 Aces + 9 Double Faults** from 585 eligible upcoming matches, so Aces were not data-starved at selector level. r29 already separated Aces and DF adaptive fill; r30 additionally verifies selector-to-feed survival explicitly.

### 4. Production-loss audit

New data-workflow mode: `production-audit`.

It reads the private production `feed.json`, immutable `ledger.json`, and historical snapshot directly inside GitHub Actions and produces:

- performance by published section and market;
- descriptive failure slices by tour, surface, and confidence band;
- selector-vs-published counts for Aces/DF/Sets/Games;
- the real Aces/DF walk-forward calibration diagnostics;
- current odds-coverage diagnostics.

Artifacts:

- `.cache/tbt/production-audit/production_prediction_audit.json`
- `.cache/tbt/production-audit/production_prediction_audit.md`

This is deliberately descriptive. Small slices are not treated as causal proof.

### 5. History rebuild

New data-workflow mode: `results-rebuild`.

It downloads the production ledger and full historical snapshot, re-settles every recoverable **actually issued** publication, rebuilds Results and all rolling metrics, uploads the refreshed prediction bundle, deploys it, and confirms the exact deployed publication.

It never creates a historical publication that is absent from immutable ledger evidence. If old issuance was deleted before being retained, that missing history cannot be honestly reconstructed from match results alone.

### 6. Rolling marketing result per category

The backend now computes 3/7/10/14/30-day windows independently for:

- TOP
- SHORT ODDS
- VALUE
- DOUBLES
- ACES
- DOUBLE FAULTS
- SETS
- GAMES

The highlighted result uses the best hit rate only when a window has at least 30 settled rows. Until then, the largest available sample is used instead of cherry-picking a tiny 100% streak. The UI always shows the selected period **and `n`**, and Results still exposes every supported period and custom date filters.

The value is shown in the category tabs/board and directly on prediction cards.

### 7. LIVE Radar

The worker transport and token were verified by a real manual production workflow: it scanned 6–7 live events per pass and persisted heartbeat successfully. The deployed version at the time was still filtering with `min_probability=0.78` and `max_odds=1.35`, producing zero candidates.

r30 defaults are `0.68` and `1.49`, and the response now exposes `prime_total`, `prime_eligible`, and `provider_skipped_reason` so zero-signal runs are diagnosable.

Autonomous scheduled scans remain intentionally opt-in. Set the GitHub repository variable:

`TBT_LIVE_RADAR_ENABLED=true`

The worker secret already existed in the verified manual run. Keeping the schedule behind a variable avoids silently consuming provider quota.

## Production sequence after deploying r30

1. Deploy r30 and confirm CI is green.
2. Run **Tennis data and predictions → `production-audit`**. This consumes stored release data, not Tennis API quota.
3. Run **`results-rebuild`** to recover and re-settle every historical row that immutable publication evidence permits.
4. Run normal **`refresh`**. Aces/DF/Sets/Games publication integrity is now fail-hard.
5. Set `TBT_LIVE_RADAR_ENABLED=true`, then manually dispatch LIVE Radar once. Verify the response reports r30 thresholds (`0.68 / 1.49`) and the new PRIME diagnostics before relying on the schedule.
6. Only if the production audit shows player-stat coverage is still insufficient, run targeted `ace-statistics` / `sg-rebuild`. The last observed selector already had 15,225 Aces/DF history matches and 72,998 structured-score matches, so do not spend requests blindly.

## Important production bottleneck observed

The same production refresh requested Match Winner odds for 81 eligible current-day candidates but received prices for only 28 (about 34.6% coverage). That limits priced TOP/SHORT ODDS/VALUE opportunities independently of model quality. r30 does not hide this limitation or synthesize unavailable odds.
