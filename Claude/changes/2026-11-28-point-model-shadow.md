# Point model v2 (shadow, flag off) - Codex patch 52
Point-level match simulation anchored to the candidate's win probability (|Δ| ≤ 0.00005); calibrated game totals by level/surface; derived sets, exact scores, games O/U, handicap, tiebreak.
Holdout: over 20.5 ECE ATP 0.037, ATP+WTA 0.044 (target < 0.05 met), WTA 0.075, Challenger 0.060; ITF still biased (+16.8 pp overall, data/format issues in ITF quals) -> do not show games for ITF.
New modules only + admin-only endpoint /v1/admin/point-model-shadow (404 while flag off). No change to offer, BlinQ %, KPI.
Revert: revert this PR.
