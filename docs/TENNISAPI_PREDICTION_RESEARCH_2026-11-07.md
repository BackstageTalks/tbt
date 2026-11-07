# TennisApi prediction-source research — 2026-11-07

## Goal, scope and evidence

Test whether tournament match history, draw seed, previous-match duration and
provider odds improve ATP/WTA pre-match predictions. Do not change the current
7.2.1 champion, training pipeline, active frozen training, canonical CDB writer,
daily ingestion or shared RapidAPI budget. Current approved task is **offline
research and identity/temporal validation**, not a new production model.

Already implemented in main before this change:
- Native daily category/events discovery, match detail/statistics, point-by-point,
  provider-1 event odds, bounded provider-5 fallback and current rankings.
- Historical point-in-time Elo, surface form, opponent-adjusted form,
  rest/fatigue, sets/games workload and tournament round/form in FeatureBuilder.
- Guarded tournament season-last, date and venue research client methods.
- Existing canonical CDB source-specific import paths and global writer lock.

New read-only code:
- `scripts/audit_tennisapi_prediction_signals.py`: validate native historical
  ATP/WTA finished singles; flag ITF and doubles out of this task; deduplicate
  provider event IDs and quarantine conflicts; snapshot 7-day **observed**
  completed-match time only from previous UTC days; capture seeds as research
  metadata. Optional monthly `dailyUniqueTournaments` cross-check never marks
  a day complete or suppresses daily provider-native discovery. Optional
  read-only CDB reconciliation requires source-native `event.id`, same tour,
  UTC date and unordered native player IDs. Canonical `match_id` must never be
  inferred from provider event ID alone.
- `scripts/evaluate_tennisapi_prediction_signals.py`: research-only
  chronological 60/20/20 date partition, baseline-logit recalibration versus
  baseline-plus-signal, log loss/Brier/ECE; requires independently time-stamped
  pre-match baseline probabilities and exact linked native identities.
  Source snippets do not have complete workload history and the audit
  sets `historical_duration_window_complete=false`, so absence must not be
  misrepresented as zero fatigue. Quote comparison accepts only independently
  time-verified pre-match market probabilities. No model artifacts/promotions.

## Reproducible offline commands

```bash
PYTHONPATH=api:scripts python scripts/audit_tennisapi_prediction_signals.py \
  --source "Prilepený text(20261106-201342).txt" \
  --source "Prilepený text(20261106-201404).txt" \
  --out .cache/tbt/tennisapi-prediction-research

# Only on a locally available, verified, read-only canonical snapshot:
PYTHONPATH=api:scripts python scripts/audit_tennisapi_prediction_signals.py \
  --source "Prilepený text(20261106-201342).txt" \
  --history-dir .cache/tbt/history \
  --out .cache/tbt/tennisapi-prediction-research

# Only with an independently as-of timestamped, oriented canonical
# baseline CSV; never infer historical prices from the latest odds snapshot:
PYTHONPATH=api:scripts python scripts/evaluate_tennisapi_prediction_signals.py \
  --baseline-csv .cache/tbt/research/verified-asof-baseline.csv \
  --signals-jsonl .cache/tbt/tennisapi-prediction-research/source-native-signals.jsonl \
  --out .cache/tbt/tennisapi-prediction-research/ablation.json
```

The first command needs no API key and makes **zero provider requests**.
Do not commit raw provider rows, private CDB partitions, player-level odds,
credentials or output sidecars. All outputs are local research artifacts.

## Concrete supplied-source boundaries

- `getTournamentMatchesByRound` operator sample: 32 unique ended ATP singles
  Australian Open 2023 events, 32 with `time.periodN` fields, 28 with at least
  one numeric draw seed. These are **post-match source observations**, not
  verified point-in-time pre-match odds or complete prior player history.
- `getTournamentMatchesByDate` operator sample: 17 unique finished
  ITF Monastir 2025 events; no sampled `time.periodN` or draw seed.
  ITF is out of ATP/WTA research scope here.
- `getTennisCalendarForMonth` July 2026 operator sample:
  31 days, 447 distinct unique tournament IDs, 2541 tournament/day
  associations. Does not provide any event IDs/statistics, does not prove
  any date is complete or offer guaranteed daily API savings.
- Neither supplied sample proves CDB net-new entries, pre-match performance,
  historical bookmaker timestamps or route pagination completeness.
  `getTournamentMatchesByRound`, `getTournamentMatchesByDate`,
  `getMatchWinningOdds` and `getMatchBettingOdds` were given as API
  operation names, not independently confirmed provider paths. Do **not**
  invent HTTP paths or dispatch paid calls until their exact provider-native
  routes, ID semantics and payload contracts are verified. Established
  provider-1 odds and event-by-date routes remain in place.

## Readiness and rollback

Implemented here: research-only scripts, tests, optional exact CDB
read-back, no production wiring. Expected successful offline tests do **not**
prove accuracy improvements. Run the real CDB comparison later with the
global lock/active consumer state checked; any candidate canonical
NULL supplementation must use the existing provider-native importer with
QUALITY/PROVENANCE/SCHEMA/IDENTITY/LEAKAGE/DRY-RUN/READ-BACK gates.
Any ambiguous identities, absent historical windows or untrusted quote
timestamps remain **review-only**.

Promotion threshold is independent prospective chronological evidence on
log loss/Brier/calibration and TOP/value selection after the existing
7.2.1 release work is finished. Rollback is trivial because no runtime
wiring or canonical writes are introduced.
