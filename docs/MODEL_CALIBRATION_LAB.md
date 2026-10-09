# BlinQ · Model Calibration Lab

This is the persistent **research branch** for independently evaluating a new
model against the serving production champion. The Admin -> Kalibrácia control
room points here. Do not confuse this branch with a production model version.

## Automatic version rollover

- Every model bundle has an exact immutable version. Private
  `tbt-model-shadow-v1/shadow_report.json` is produced from the exact
  `production_model_version + challenger_model_version` pair.
- As soon as an approved model goes to production, the next candidate is a new
  *version* and gets its own clean shadow cohort. The previous evaluated pair
  and decisions remain archived; never reset or rewrite historical settlements.
- The dashboard has **two deliberately independent counters**:
  1. `shadow.settled`: settled bets for the current exact model pair. Show
     minimum review 200 plus tracking target 1000; compare champion vs candidate
     on identical matches using frozen pre-match probabilities.
  2. `unseen.eligible_rows`: genuinely new completed whole UTC-day canonical
     matches not used by the champion's serving history or any previous
     promotion decision. Gate minimum 200, target 1000, 3 days. May be 0 even
     while an old shadow cohort contains 688 settled rows.
- Do not add these counters, reuse previously tested events, or infer real
  probabilities from currently open bets.
- Accuracy alone is insufficient: log loss, Brier, ECE, ROC AUC, ATP/WTA
  group sample, same-fixture comparison and leakage controls are required.

## Data flows and publication safety

1. External scheduler runs Match Status; its workflow dispatches
   `.github/workflows/model-calibration-monitor.yml` every six hours.
2. The monitor downloads private model *summary* and immutable canonical
   release, runs `scripts/model_promotion_readiness.py` offline, signs the
   validated aggregate snapshot and sends it to
   `POST /api/v1/internal/model-calibration-snapshot`.
3. Backend validates exact model-pair and stores the summary in the private
   Admin Azure Table. A verified administrator reads it only through
   `GET /api/v1/admin/model-calibration`.
4. The Admin tab shows source time, sync time, stale age, missing values and
   last **historical** decision. If no exact pair or legitimate new samples
   exist, show unavailable/zero rather than recycled metrics.
5. A successful Azure deploy seeds the first snapshot; daily/periodic monitor
   refreshes thereafter. No Tennis provider requests or API quota consumption.
6. This control room is **read-only**. It cannot train or promote a model.
   Production switching requires an explicitly authorized, evidenced rollback
   and gate in `docs/MODEL_PROMOTION_ROLLBACK_POLICY.md`.

## Audit navigation (private)

- [Current private shadow release](https://github.com/BackstageTalks/tbt-data/releases/tag/tbt-model-shadow-v1)
- [Promotion readiness audit](https://github.com/BackstageTalks/tbt-data/blob/main/audit/model-promotion-readiness-latest.json)
- [Last shadow decision](https://github.com/BackstageTalks/tbt-data/blob/main/audit/model-shadow-promotion-latest.json)
- [Admin cockpit PR #434](https://github.com/BackstageTalks/tbt/pull/434)

Branch policy: use this branch for candidate calibration experiments and
read-only comparisons, create separately versioned candidates, and do not
push unreviewed training output or release tokens to main.
