# BlinQ 7.2.1 — paired sports ranking evidence protocol (2026-11-16)

## Objective and non-negotiable rules

Product goal: ideally at least three high-quality TOP winner picks per day, **no maximum and no forced minimum**. Only sports data may drive the winner prediction and its ranking. Historical pre-start odds are admitted exclusively as a later minimum **1.50** filter. No PROMO/ACES changes, no bookmaker-derived feature, no EV/value/ROI target, and no production model replacement without verified improvement on real TOP issuance.

## Confirmed starting evidence

- Production model frozen SHA-256: `c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91`.
- Previous 2026-11-16 frozen candidate `blinq-candidate-frozen-43791051682-1` SHA-256 `f6fbc34a1d9786e6c455e4cb556e025270c2fb4ef60a33c31fef6a0b9b0c48f7`, readback verified in private `audit/model-frozen-candidate-latest.json`.
- On 7,107 same-fixture offline holdout rows, candidate accuracy 70.21% vs 69.49%, ROC AUC 0.7720 vs 0.7679; candidate ECE worsened 0.01479 vs 0.01059. These metrics do **not** prove a better >=1.50 TOP selection.
- Latest persisted training evidence explicitly blocks production promotion on `top_market_validation_required`.
- The previous frozen release stored aggregated metrics only. Its per-fixture output cannot be retroactively reconstructed from aggregates.
- Morning selection funnel PR #1646 is an independent read-only quote-depth audit, still open at this protocol's start.

## New isolated research implementation

1. A candidate **future** protected fit serializes the *exact* eligible chronological holdout frame paired with champion/candidate predictions, rechecks winner-side orientation, unique IDs, UTC times, actual labels, the shared pre-match feature frame and feature-vector SHA-256. Versions and holdout fingerprint are explicit.
2. The scored rows go only to the **private immutable candidate release** as `paired_top_holdout.json.gz`. Remote release-store bundle checks plus independent row/digest readback are required before writing the private aggregate attestation. No row-level data enters public repository or routine workflow artifact.
3. A separate read-only script accepts a verified historic pre-start quote on the same oriented fixture, applies sport-derived confidence/depth/surface gating **first**, then side-matched real odds >=1.50, then ranks daily top 3/5/7 and all qualified. Its summary reports both winner ROC AUC and confidence-vs-correctness AUC, including no-pick days. It labels itself research rather than native issued TOP, and refuses ambiguous quote identities.
4. An opt-in sports-only base-estimator variant (`main_tour_2x`) is implemented in the existing ensemble fit: eligible tour/Challenger training fixtures receive 2x sample weight, while ITF/UTR/unknown retain 1x. Both orientations of the same match share the weight. Neither outcome labels nor bookmaker data determine weights. The default unweighted model is byte-path compatible at fit entry. This is a **predeclared experimental training variant**, not evidence of improvement. Protected `workflow_dispatch` has an explicit opt-in input and still uses all immutable-backup, leakage, single-writer and no-promotion gates.
5. No current public selection, production scoring, existing CDB or champion changes. An experimental weighted model is deliberately refused by the serving refit path until a separately validated promotion design exists.

## Pending before a model-logic decision

- Run focused and full protected CI on this branch, check any regression or identity failure, and verify private release readback after the next authorized fail-closed training execution. The first full CI on commit `6e5d2da` passed; the latest weighting experiment must pass independently.
- Attach actual time-proven odds from an independently checked source to the emitted scored rows. Do not treat missing quotes as sub-1.50 prices or invent missing settlements.
- Audit feature coverage and pre-match provenance by competition and surface. Compare existing unweighted candidate against the *predeclared* `main_tour_2x` sport-only candidate after an independently protected fit. Use prior chronological calibration/selection days and a later genuinely prospective shadow; label 2026-10-27 to 2026-11-15 retrospective. Do not tune the tour weight on those inspected results.
- Measure uncertainty by betting day, identical fixtures, real publication eligibility and later prospective shadow TOP issuance. Decide champion switch only when measurable gain and rollback requirements are met.

**Decision:** keep production champion; opt-in weighted fit and paired evaluator remain research-only until price-qualified improvement is demonstrated and independently reproduced.

## Execution evidence — current state

- Protected research fit was **dispatched and entered `frozen-candidate`** on run [43872914492](https://github.com/BackstageTalks/tbt/actions/runs/43872914492), exact pinned code SHA `1d57e7d0793f89dbc2efc2064f7a965cb5e3457d`. `await-cdb-idle` completed successfully; last independently checked active stage was `Freeze ALL current source inputs and independently restore champion`. Do not claim backup restore, completed fitting, new scores, or a successful candidate release before the exact run proves them.
- The branch-specific training push trigger was removed immediately after the one-shot run started. Normal protected workflow policy is main-only or explicit manual dispatch; the public release remains unchanged.
- Read-only exact-price linkage is implemented in `scripts/prepare_paired_top_quotes.py`. It chooses the **first** snapshot generated at or after 06:00 local betting-day time, matches only unique provider event ID + exact unordered player IDs + tour, checks the original and actual scheduled timestamps within 45 minutes, validates two real winner quotes and source/capture times, and handles swapped side orientation. It never joins from names or after observing winners. Duplicate or uncertain records are discarded.
- `.github/workflows/blinq-private-paired-top-replay.yml` is prepared to read the exact verified private candidate release and the pinned October/November private selector assets, run regression tests and upload **aggregate-only** evidence. No quote-matched numbers may be claimed before that separate workflow completes.
- PR [#1652](https://github.com/BackstageTalks/tbt/pull/1652) remains **draft**, protecting main and production from unvalidated model changes. Previous evaluation-layer CI passed on [run 43869755090](https://github.com/BackstageTalks/tbt/actions/runs/43869755090); that does not prove the latest quote matcher/weighting tests or future training.
- Provider API requests for this research are intended to be **zero** and are disabled in the protected workflow. This is not a CDB import or new public offer, and no Telegram messages are sent.

**Decision remains unchanged:** candidate is research-only; keep production champion, no forced TOP count or odds floor change. New price-qualified accuracy/ranking and prospective issued-TOP evidence are still required.

## 2026-11-16 — independently checked continuation

- **Implementation test gate**: complete research CI [43874250914](https://github.com/BackstageTalks/tbt/actions/runs/43874250914) finished **success** on source SHA `0be519bcf095d7114b78f11035d1898dadcf8357`, including backend regression and browser runtime; this does not prove model ranking gain.
- **Initial replay-capable baseline fit**: run [43872914492](https://github.com/BackstageTalks/tbt/actions/runs/43872914492), pinned `1d57e7d0793f89dbc2efc2064f7a965cb5e3457d`, remains in training-history PIT/leakage audit as checked at 13:42 UTC. Immutable backup/champion restore and release of global writer completed. The private candidate release `blinq-candidate-frozen-43872914492-1` exists only as an **empty reservation**, with **zero assets**, not a verified fitted model. Critically this initial branch-push fit has `BLINQ_SPORTS_WEIGHT_PROFILE=none`, so it is the **unweighted baseline** for new per-fixture quote replay rather than the 2x experimental fit.
- **Independent private quote source readback**: read-only [archive contract run 43878010351](https://github.com/BackstageTalks/tbt/actions/runs/43878010351) passed. Exact release `tbt-predictions-v1`, October and November 2026 archived schema=1, with **23 and 21 snapshots**, respectively. Nested fields required by the deterministic crosswalk are present: `event_id`, `tour`, `scheduled_at`, `player1.id`, `player2.id`, `two_way_market.player1_odds`, `player2_odds`, `captured_at`, `provider_id`. No winner labels, names or actual quotes were printed; **same-fixture join coverage and valid price counts are still unmeasured**.
- **Distinct sports-weighted training attempt queued**: [run 43878236229](https://github.com/BackstageTalks/tbt/actions/runs/43878236229), pinned `7a085c5b7170d75413536f77121e50df2ffeb653`, explicit `main_tour_2x` only on that exact research-branch commit. Its immutable-backup/lock concurrency group prevents simultaneous protected runs. This is an **attempt, not a trained candidate**; the exceptional research trigger was removed in the next branch commit to restore normal main-only / explicit workflow-dispatch safety.
- **Production untouched**: private release `tbt-model-production-v1` still serves pinned `model.joblib` SHA256 `c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91`. Research PR remains draft, never merged; no market features, CDB mutations, forced TOP, or provider requests were introduced in the evaluation runner.

**Open decision gate**: First complete the baseline scored release and independent private read-back; run the read-only price crosswalk, report exact joined/missing/ambiguous fixtures, then independently compare sports-weighted and baseline model on compatible time-frozen cohorts, including meaningful day-level uncertainty. No model activation without prospective actually-issued TOP gain.

### Final replay fail-closed gate

The subsequent research-only workflow now explicitly rejects a "successful" private TOP comparison when zero exact time-verified quotes were joined or when neither model has any sport/price-qualified winner pick. The aggregate diagnostic remains uploadable with `if: always()` for troubleshooting. Preflight-only workflow code was removed after its successful readback; normal production and training push restrictions are restored. The historic quote replay itself has **not been executed** on scored candidate rows because the baseline candidate has not finished its PIT audit and asset publication.

### Research-only sports confidence sensitivity: 60% vs 65%

At the user's request, the private same-fixture TOP replay now treats **60% sports-only probability** as the primary experimental confidence eligibility threshold; **65%** is retained as the unchanged reference arm. The independently time-verified, selected-side winner **odds >= 1.50** filter remains exactly the same and comes *after* the sports gate. Neither odds nor market-implied probability enters sports scoring, training, or ranking. No maximum TOP or forced fill is introduced.

Both arms use the same frozen model probabilities, fixture identities, prestart quote observations, sport-depth/surface gates and betting-day clock. The new private aggregate-only output reports separate champion/candidate qualification counts, day-level >=3 coverage, top-3/5/7 accuracy, and additional 60-65%-only price-eligible picks and their correctness. A candidate is not promoted for higher count alone. The live production selector and champion remain unchanged until prospective, actually-issued TOP evidence validates the policy. **Mathematical caution:** 60% true win probability at decimal odds 1.50 is below the ~66.7% stake break-even threshold; 60/40 is a possible sports-confidence cut, not independent evidence of a worthwhile 1.50 bet.

At this decision the completed protected baseline candidate scores and the real historic quote join remain pending. The experiment is IMPLEMENTED, not yet VERIFIED on real matched TOP outcomes.
