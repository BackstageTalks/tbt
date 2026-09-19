# BlinQ v7.2.8 — verified SG rebuild hardening

## Goal
Make Sets/Games history deterministic, auditable and safe to rerun. Historical
BO3/BO5 is never guessed from tour names when a finished score exists.

## Data contract
- Provider event identity must match both canonical player IDs.
- Structured set scores are parsed only from period fields; unsupported score
  shapes fail closed.
- Historical BO3/BO5 is a fact: explicit provider `bestOf` when present, else
  the completed structured score proves BO3/BO5 from the winner's set count.
- If provider `bestOf` conflicts with the completed score, the sample is marked
  as a conflict and excluded from S/G training.
- Compact canonical history persists format provenance and verification flags.
- Upcoming fixtures may use conservative, auditable format inference only for
  conventional ATP/WTA/ITF/Challenger singles; non-standard formats fail closed.

## Operations
- `sg-scores`: normal incremental/idempotent top-up. It reuses verified rows and
  local provider-response cache where safe.
- `sg-rebuild`: explicit verification sweep. It includes existing S/G rows for
  current-board players and bypasses the local event-detail cache, so a fresh API
  quota can re-validate identity, score and format facts.
- Every SG run produces `sg_projection_dry_run.json` without extra Tennis API
  calls. This immediately reports whether historical structured scores are usable
  and how many SETS/GAMES projections the current feed would generate.
- `mega-data`: continues to use incremental SG mode. Already verified rows are
  not needlessly re-fetched; unused SG budget rolls forward to later phases.

## Recommended launch sequence
1. Deploy v7.2.8.
2. Run `sg-rebuild` with `max_requests=2000`, `sg_target_samples=24`,
   `sg_lookback_days=730`.
3. Inspect `sg_run_summary.json` and `sg_projection_dry_run.json`.
4. After the API quota reset, run `mega-data` with `max_requests=10000` and the
   standard launch settings.
