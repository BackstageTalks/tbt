# BlinQ P1/P2 continuation — evidence and guarded serving deployment (2026-11-08)

## Goal and acceptance
Finish P1 model/TOP quality and P2 API coverage, VIAC ES ROI and CDB/morning performance without changing model 7.2.1, historical issued picks, provider quota or external-cron scheduler. Completion requires exact-code CI, production API/UI serving read-back, real settled VIAC ES prices or an explicit insufficient-evidence result, and independently persisted CDB delta for any write.

## Binding decisions
- Champion 7.2.1 stays live; **no automatic candidate promotion** without separate operator approval and verified rollback.
- Keep approved TOP 70% policy; research replay with low/unequal coverage cannot justify threshold change.
- The canonical private CDB is authoritative. Existing native/guarded NULL-only import only; preserve provenance, global single-writer lock, CAS, raw data, backups and read-back.
- RapidAPI shared ledger: 14,500 ceiling, 500 reserve, 6/s, reset 17:09 UTC; unknown usage is not zero. This deployment triggers **zero new paid provider calls**.
- External cron remains the sole scheduled trigger; do not enable GitHub schedule.

## Evidence at this checkpoint
- Current main 8724907cf808a039c64ec010d38e44695c1c7386 includes performance improvement d7bd186 and VIAC ES/KPI fix 8724907 (#1489).
- Read-only issued-results audit run 42528010571 on main was successful but reported `status=INSUFFICIENT_SETTLED_EVIDENCE`, `settled_priced=0`, `roi=null`, `member_render_verified=false`. Source feed SHA-256: e8d93c25ee279a1c1bb0714fc1ea6c1a58e7bb582a5bbed5fb61bcfb07c145de.
- Production revision watchdog run 42528085433 established that exact frontend assets/HTML correspond to their deployed SHA, but checkout is newer in `api/tbt/data/history_safety.py` and `api/tbt/services/dashboard_kpis.py`. Incident #1490 is **backend release lag**, not proof of corrupt frontend assets.
- Private read-only CDB run 42527261256 verified manifest SHA-256 9edbea70cd3d4ffc8d3b9f2cc8650702b4c896dcb979183bf6af4eac457ab007 and staged 1,056 rows / 4,178 NULL-only service-rate complements in 2022, 2023 and 2026. 1,685 contradictory observed rate pairs were not staged. BP original source-native stage yielded **0** values; 64 conflicts. **Neither stage was imported.**
- Private frozen 7.2.1 settlement run 42528082542: `WAITING_FOR_VERIFIED_CANONICAL_RESULTS`, settled 1,641, void 89, excluded 376, pending 145; 0 provider calls and 0 serving model mutations.
- An older production data run 42527484186 was still active at this checkpoint. It owns the serialized production publishing path; do not bypass or cancel it.
- The old CDB complements write request is pinned to manifest `1a89a4...` and mismatched historic counts; **do not replay** it.

## Current narrow operation
Request an exact-current, **non-promoting, no-new-provider** API/UI deployment through the existing `ci.yml` checks and `tbt-production-deploy` lock using the documented `[deploy-current]` push marker. This file is the checkpoint and deployment trigger; it does not change application logic, CDB or the scheduler.

## Required independent verification after CI deploy
1. Exact deployment `git_sha` equals this triggering commit, live web assets/HTML match, `api/tbt/services/dashboard_kpis.py` change is serving, and existing budget/serving snapshot canaries pass.
2. Rerun VIAC ES accounting against the newly pinned actual Results feed. `settled_priced=0` is an evidence gap, not profitability.
3. After the writer completes, remeasure CDB from a new current manifest; only then prepare a new exact-SHA guarded NULL-only complement writer request and verify post-write persisted delta.
4. Time the next **real externally triggered** morning workflow and its child data run against comparable baseline; function microbenchmark alone does not close the P2 performance item.
5. Continue matched-fixture champion/challenger comparisons and TOP outcome monitoring; do not promote or change approved threshold without statistically valid evidence.

## Status
Documented source/audit: VERIFIED. Production deploy: REQUESTED BY THIS COMMIT, **NOT YET VERIFIED**. VIAC ES ROI / CDB enrichment / whole-morning performance / model quality: OPEN.
