# BlinQ v7.2.7 — SG best-of repair

## Why this patch exists

The 2026-09-18 mega-data run successfully enriched structured set/game history, but the final refresh reported `history_matches_with_structured_score: 0`, `missing_best_of: 141`, `sets_selected: 0`, and `games_selected: 0`. The provider frequently omits `bestOf`, so the projection layer was rejecting otherwise valid structured score rows and every current fixture before model calculation.

## Repair

A central `tbt.match_format.infer_best_of()` normalizer now applies conservative format rules:

- explicit provider BO3/BO5 always wins;
- a structured score with 4+ sets proves BO5;
- WTA and ITF singles infer BO3;
- normal ATP singles infer BO3;
- ATP Grand Slam men's main draw infers BO5;
- ATP Grand Slam qualifying remains BO3;
- Next Gen ATP Finals infer BO5;
- unknown circuits remain unknown/fail-closed.

The rule is used both while normalizing new provider rows and inside the S/G projection layer, so already-stored history with a missing `best_of` becomes usable immediately without rewriting all historical parquet first. Score enrichment also persists an inferred format on newly enriched rows where possible.

## Diagnostics

The S/G report now includes:

- `history_best_of_inferred`
- `history_best_of_inference_sources`
- `upcoming_best_of_inferred`
- `upcoming_best_of_inference_sources`
- existing `missing_best_of`, `history_matches_with_structured_score`, `sets_selected`, `games_selected`

This makes a future provider contract regression visible instead of silently producing an empty S/G feed.

## Validation

- Match-format/provider/S&G/market/workflow focused suite: 53 PASS.
- Broad locally runnable suite excluding Azure runtime collection: 444 PASS, 1 skipped; 8 failures are exclusively local missing `pyarrow` parquet support.
- Python compileall: PASS.
- Full GitHub CI remains the deployment authority because it installs repository runtime/training requirements.
