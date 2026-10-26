# Candidate 7.2.2: accuracy experiment

Admin → Model Lab → prepare data → select **BlinQ 7.2.2 · presnosť** → train.
The selection survives automatic status refreshes. The confirmation and queued
request use the same captured profile. The existing worker starts the protected
workflow on main; it may take up to the next worker tick. Candidate publication,
offline comparison and optional shadow gates remain separate from production.

The `accuracy-7.2.2` profile retains 7.2.1 point-in-time features and the 2024+
learning window, with chronological 70/15/15 whole-day partitions. It adds:

- A small blend search ranked by accuracy on early calibration days. Candidates
  must not worsen log loss or Brier there. One selected blend is accepted only
  when later calibration days improve pooled accuracy by at least 0.2 percentage
  points and do not regress accuracy, log loss or Brier overall or on ATP/WTA.
  Insufficient groups or failed validation retain the log-loss baseline.
- Smooth pooled calibration: identity or positive-slope Platt. Isotonic plateaus
  and tour-specific isotonic calibration are excluded for this experiment.
  This preserves the raw favourite ordering rather than turning scores into ties.

Existing ATP blend validation remains in place. Final holdout is never passed
to the new selector. Report `evaluation_model.accuracy_blend_validation` records
the accepted/rejected experiment; `smooth_calibration_only` identifies calibration
policy. A refreshed fit can still be worse than the deployed 7.2.1: no improvement
is claimed until measured on the eligible untouched holdout and forward shadow.

Production artifacts and published bets are unchanged by selecting this profile.
Frozen input/rollback verification, leakage audit, publication readback and
automatic shadow quality gates are unchanged. No new scheduler or provider use.
