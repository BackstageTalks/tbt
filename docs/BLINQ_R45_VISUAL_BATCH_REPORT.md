# BlinQ 7.3.6-r45 — Predictions visual/data clarity batch

## Scope

This batch is intentionally frontend/data-presentation only. The r44 account lifecycle behaviour is unchanged.

### Prediction cards
- Added compact date below match time (`DD.MM.YY`) across the prediction hub and card surfaces.
- Increased prediction/rating readability without changing entitlement or ranking logic.
- Unified player photo resolution across supported API fields and retained the local ATP/WTA repo fallbacks before initials.
- Fixed SHORT ODDS labelling so the internal `PRIME` key is not shown as the public card label.
- Renamed the public Aces surface to `ACES` / `Aces` consistently.

### Aces / Double Faults / Games / Sets
- Aces and Double Faults show player + `Over/Under` + line when a verified provider line exists.
- If the provider side is absent for Aces/Double Faults, direction can be derived only when both projection and verified line are present.
- Games show `Over/Under` + the model reference line, preserving their projection-only semantics and not inventing bookmaker odds.
- Sets retain their existing `Over/Under` selection semantics and now share the same visual presentation as Games.
- Projection details use the same displayed selection logic as their cards.
- Doubles remains an existing category and is not populated artificially when there are no qualifying picks.

## Runtime identity
- Release: `7.3.6`
- Patch: `736-r45`
- Asset revision: `7360`
- Cache patch: `p=45`

## Verification
- Repository contract audit: PASS.
- JavaScript syntax checks: PASS.
- Frontend JS regression/runtime contracts: PASS.
- r45 visual contract: 6/6 PASS.
- Relevant legacy UI contracts updated for the intentional `ESA` -> `ACES` product rename and PASS.
- Broad Python suite available in this environment: `693 passed, 1 skipped, 8 deselected`.
- The 8 deselected tests are the already-known parquet tests that require the unavailable local `pyarrow` dependency.
- The Azure Functions smoke import is not run locally because this environment does not provide `azure.functions`.
