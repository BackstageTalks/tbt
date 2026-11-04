# BlinQ — older-match quality availability gate research, 2026-11-03

**Status:** exploratory and read-only. This is a proposed composition of two existing annual-fold model arms, not a fitted, verified new champion.

## Why this experiment

The existing `audit/quality-walk-forward-latest.json` already contains 2023–2026 strictly chronological annual test predictions for **356,742** matches, with identical universes for models using quality features and without that feature group. The feature group helps in years / segments where it is usable and harms when poorly supported.

Hypothesis frozen for this experiment: use `with_quality` only when `stats_known_both > 0` at pre-match inference; otherwise use `without_quality`. Do **not** use EV, historical winning outcome or price as a gate.

## Exact baseline proof

Private source: BackstageTalks/tbt-data `audit/quality-walk-forward-latest.json`, generated 2026-10-05 15:59 UTC, 356,742 annual holdout predictions (2023–2026). 141,900 have `stats_known_both`, 214,842 do not. Two baseline methods share the identical event population and annual model fit chronology.

Read-only reconstruction combines existing disjoint subgroup means weighted by group n, with independent readback to whole-cohort metrics. This is an *exact aggregation of stored cross-validated outcomes*; it is not a new model fit or previously untouched gate validation.

| Arm | Accuracy | Brier | Log-loss |
| --- | ---: | ---: | ---: |
| With quality everywhere | 0.6945803970 | 0.1961733690 | 0.5743316696 |
| Without quality everywhere | 0.6945243341 | 0.1961411128 | 0.5742272133 |
| **Quality gated by both-known** | **0.6951045854** | **0.1957574732** | **0.5733740263** |
| Reversed gate (negative control) | 0.6940001458 | 0.1965570086 | 0.5751848566 |

**Signal:** ~0.052 percentage points higher accuracy vs always using quality and ~0.000958 lower log-loss. Small, not sufficient for production.

## Governance & integrity

- Regression suite checks disjoint denominators, 2023–2026 fold totals, source status, no writes, independent aggregate consistency and no fabricated year-specific gate scores.
- Read-only GitHub Actions test run: https://github.com/BackstageTalks/tbt/actions/runs/41720833518 — 7/7 regression tests passed; exact source content fetched from private repo and SHA pinned before/after; aggregate experiment artifact uploaded.
- No model fitting or release binary changed. No extra provider API requests, CDB writes, production changes, EV/ROI/CLV optimization, promotion or production selector reordering.
- Important limit: gate was chosen after looking at quality-availability subgroup outcomes **across all 2023–2026**. Therefore 2026 is **not a fresh untouched gate-rule holdout**. The current source does **not** contain per-year availability-conditioned scores, so claiming annual stability or any improvement versus current serving 7.2.1 would be false.
- A further test requires an independently frozen data source and per-year paired predictions (or new full annual fold fits with the existing certified training backup/restore guardrails), verifying `stats_known_both` as true point-in-time serving feature. Only then compare against exact 7.2.1 on the same events and await independent shadow plus owner decision.

## Suggested next stage (not executed)

1. Produce complete per-year quality-known/unknown subcohorts of the existing two annual arms with immutable input pins, **without fitting if row-level original predictions are stored**. If the stored artifacts contain only aggregate metrics, model fits must pass the existing training backup and freeze gates first.
2. Freeze one simple availability gate and test 2026+ separately after preregistration on 2023–2025; account explicitly for the fact that the concept was explored on existing historical outcomes.
3. If supported across ATP/WTA, surfaces, calendar and recent model versions, fit a separate candidate in an isolated certified training workflow. Never auto-promote.
