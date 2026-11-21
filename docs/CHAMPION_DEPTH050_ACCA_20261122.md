# BlinQ — champion count-depth 0.50 experiment (22 Nov 2026)

## Approved outcome
Try a minimum historical-count data_depth of **0.50 (25 historical matches for each player)** for the currently serving BlinQ champion's **match-winner publication eligibility**. Keep calibrated model, champion binary, feature semantics, count-based probability shrink, and pre-match safeguards intact. This applies to TOP, ACCA (legacy internal key `prime`), VALUE and the early winner-odds candidate discovery, so an otherwise valid 0.50-depth candidate is not dropped before quotation.

## Explicit invariants
- New TOP only on main ATP/WTA 250+; never reissue/change frozen old offers.
- No change to ACE/sets/games/doubles and their distinct predictors; no CDB, training, model, provider SDK, scheduler or quota edits.
- Preserve minimum 5 surface matches each for TOP/ACCA; VALUE/pre-quote minimum 3; no weakening of point-in-time evidence, ranking, quote identity/times, probability floors, odds or exclusivity.
- Public name **ACCA**, not PRIME. Preserve internal `prime`, `prime_picks`, `prime_rule`, `PRIME_*` and legacy URLs/identifiers for historical results and client compatibility. The UI config label is ACCA.

## Sources and evidence boundary
Previous read-only [frozen candidate simulation](https://github.com/BackstageTalks/tbt/actions/runs/44962897242) gave no additional price-confirmed TOP picks at 0.50 on 15–21 Nov, but is not a true future provider-requote simulation. This implementation is an owner-authorized prospective change, **not evidence of improved prediction accuracy**. Preserve a specific rollback: revert the scoped PR commit from main after checking immutable same-day offers; never rewrite issued snapshots.

## Acceptance gates
1. Exact branch CI backend + frontend + Chromium and fail-closed morning policy test.
2. Merge only after green checks; production CI/deploy and exact frontend/live rule readback.
3. Confirm next genuine morning issuance under the new depth floor with actual odds budget readback, frozen offer integrity and published/issued counts. Report new vs old depth-eligible pick counts with pre-start evidence, not raw candidates.
4. No claim of full production verification before the next actual issuance.
