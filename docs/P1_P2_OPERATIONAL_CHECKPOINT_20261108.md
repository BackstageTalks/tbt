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

## Verified continuation checkpoint — 2026-11-09 (14:35 UTC)

This appendix supersedes dated operational states above; it does **not** supersede the binding safety decisions.

### MERGED / independently VERIFIED
- Native exact-SHA guarded CDB write: [PR #1495](https://github.com/BackstageTalks/tbt/pull/1495), [workflow 42580292332](https://github.com/BackstageTalks/tbt/actions/runs/42580292332). The writer acquired the global lock, created an immutable verified backup, passed manifest CAS, committed only 2022/2023/2026 year partitions, then **independently downloaded** the published complete canonical CDB to verify **1,006,232 matches, 1,056 enriched, 4,178 newly filled NULL fields, 0 existing values overwritten, 0 unverified identities**. The 1,685 contradictory rates were excluded before import; the source-native BP stage added **0** values. This is evidence at import time, **not** proof that the later CDB snapshot has identical content.
- Obsolete SHA-bound [PR #1491](https://github.com/BackstageTalks/tbt/pull/1491) was closed *unmerged* after superseding safe write; never replay.
- Live web/API deployment of prior main `92f69f67ed4c090598068b55a4491e79fdc3eae3`: [CI/deploy 42586053633](https://github.com/BackstageTalks/tbt/actions/runs/42586053633), [independent frontend watchdog 42632938260](https://github.com/BackstageTalks/tbt/actions/runs/42632938260). Exact HTML/JS/CSS stamp passed. Serving snapshot showed 673 raw upcoming, 1,000 Results, 3 raw TOP, issuance `confirmed` with 688 keys and 755 durable keys. At **08:36 UTC** the verified shared RapidAPI gate showed 2,186 spent and 12,314 remaining (global cap 14,500, reserved headroom 500); it is a timestamped observation, **not** current or total provider consumption.
- Champion 7.2.1 and 70% TOP `priority_tours_top_v19` unchanged. No automatic promotion or model threshold change.

### Newly implemented; production verification still mandatory
- A new Match Status failure emerged after the 06:00 9 Nov rollover: last successful [match-status 42570512949](https://github.com/BackstageTalks/tbt/actions/runs/42570512949) persisted 92 verified rollover market entries; from [42571924643](https://github.com/BackstageTalks/tbt/actions/runs/42571924643) onwards workers return HTTP 503 `match_status_worker_failed: ValueError` in seconds. Existing code had both a strict 180-row cap and a **silent** `[:180]` persistence truncate. The hypothesis of combined old+new issued rows exceeding 180 is grounded in persisted counts but awaits server-side confirmation by live recovery.
- [PR #1502](https://github.com/BackstageTalks/tbt/pull/1502) **MERGED** on main at `f8ce18db223a09101f4108af5b7725a10b35e4d2` after [PR CI 42634429009](https://github.com/BackstageTalks/tbt/actions/runs/42634429009) passed. Minimal fix raises only the verified 72h receipt window cap to 600, eliminates silent truncation, and refuses to persist overflow before any write. Tests cover 220 authenticated rollover receipts, 220 entry Azure storage readback and fail-closed >600. **Deploy, next real externally scheduled worker and readback are not marked VERIFIED** at this checkpoint. [Main CI/deploy 42635551324](https://github.com/BackstageTalks/tbt/actions/runs/42635551324) pending at this writing.
- Another data producer [42630547736](https://github.com/BackstageTalks/tbt/actions/runs/42630547736) held the global canonical writer lock during this work. No new provider job, CDB importer or scheduler was started; do not interrupt this writer.
- `tbt-data-v1` CDB history manifest digest later changed to `ba98984792c68d4bd85c12e8e6f5e0e0882cb7e18430ff753470ece10fb1ef20` at 14:15 UTC from subsequent legitimate operations. Every *new* CDB analysis/import must independently pin the current coherent manifest, never use stale ones.

### OPEN / evidence limits
- Latest Results most-aces financial read-only audit attempted with [workflow 42528010571 attempt 2](https://github.com/BackstageTalks/tbt/actions/runs/42528010571). Unit tests passed but the actual private asset download returned **GitHub HTTP 500**, so it generated **no current ROI report**; no blind retry, no new provider calls. Older source-qualified audit showed `settled_priced=0`, `roi=null` and `member_render_verified=false`. VIAC ES **must not** be reported as profitable or conclusively verified without a stable exact-SHA source, actual issued/settled priced `most_aces` results, KPI accounting parity, and authenticated member readback.
- Broader ATP/WTA 2016–2026 serve/return and especially break-point coverage, frozen same-fixture model quality and end-to-end morning-time performance remain separate ongoing evidence gaps. Do not claim completion from the 4,178 partial rate complements or a single successful deploy.
- Next gates: (1) full guarded deploy #42635551324; (2) independent current live SHA/backend contract readback; (3) first genuine external Match Status worker return 200 with persisted full rollover and no budget violation; (4) repeat no-provider VIAC ES ROI audit only once private release access is stable; (5) use current manifest for further source-native coverage audits. If any gate fails, keep production mutation paused and diagnose, no bypass.

### Safety decisions retained
No automatic model promotion, no change to TOP 70%, no new job or provider refresh, no alternate CDB writer, no lock bypass, no repeated failed deploy, no scheduler migration. Full completion is **NOT YET VERIFIED** until all relevant end-to-end checks pass.


## Completion-gate evidence — 2026-11-09 17:00 UTC (supersedes 14:35 UTC open-state entries)

### Verified in production
- [Main CI/deploy #42635551324](https://github.com/BackstageTalks/tbt/actions/runs/42635551324): 4,879 Python tests passed; production deployment and its independent live-serving readback succeeded on SHA \`f8ce18db223a09101f4108af5b7725a10b35e4d2\`. Post-deploy publication confirmation returned \`status=confirmed\`, \`confirmed_keys=490\`, \`durable_keys=755\`. Those are mixed-market identities, **not** a count of Most Aces offers.
- [PR #1505](https://github.com/BackstageTalks/tbt/pull/1505), [PR #1506](https://github.com/BackstageTalks/tbt/pull/1506) merged and subsequently deployed. Independent HTTP 200 readback of Azure \`/deployment.json\` returned production SHA \`62287c2335eceda49f74dbb56dc3bfe467d77fb1\`, including the Results/ELITE clarity fix and strict durable-finance readback service.
- **External** \`workflow_dispatch\` [Match Status #42657968831](https://github.com/BackstageTalks/tbt/actions/runs/42657968831) finished SUCCESS after that deployment; protected worker reported \`schedule_readback_verified=true\`, \`rollover_issued_rows=189\`, \`results_archive.verified=true\`, \`added=1\`, \`updated=0\`, no degraded flag. Its independent persisted \`category_readback\`: 1,598 settled market publications all time; \`ace_winner=21\` all time and \`ace_winner=10\` for current Bratislava betting day. Old 180-entry silent rollover truncation is no longer reproduced.
- Same trusted archive response \`ace_winner_finance\` (no new provider requests for this audit): \`source=durable_results_archive\`, \`status=VERIFIED_ACCOUNTING\`, \`observed_publications=21\`, \`settled_priced=19\`, \`wins=13\`, \`losses=6\`, \`void=2\`, \`profit_units=1.8\`, \`roi=0.09473684210526316\` (+9.47%). This validates strict frozen-price financial arithmetic **for the observed archive sample**, not necessarily exact frontend dashboard parity or member rendering.
- Independent public HTTPS \`/api/v1/ui-config\` shows \`runtime_configured=true\`, separate \`ace_winner\` enabled, ELITE/LEGEND/GOAT \`visible_rows=ALL\` and \`exclude_from_stats=false\`; Results navigation is active for ELITE. Unauthenticated \`/api/v1/feed\` returns HTTP 401 as required. Public configuration is not proof of the number of live member-authorized \`market=most_aces\` picks.

### Exact remaining acceptance gates
- **OPEN**: authenticated ELITE/admin \`/api/v1/feed\` readback and actual mobile/desktop rendering, confirming exact count and identities of issued \`market=most_aces\` and Results category including a same-period ELITE-vs-ALL comparison. No Firebase member token or authenticated browser session is available to this read-only audit. Never substitute mock-role tests, public UI config or worker readback for actual member authorization.
- **OPEN**: independently reconcile frontend dashboard financial KPI scalar(s) with the same frozen 19 priced archive entries; a zero-difference parity certificate is not yet present. Do not manufacture historic bets, retroactively issue ESÁ ball signals or rewrite results.
- **Independent unrelated CI blocker**: [main CI #42660405761](https://github.com/BackstageTalks/tbt/actions/runs/42660405761) on newer \`537f0ffe...\` failed in \`verify_audit_only_diff.py\` because new test path \`tests/test_security_boundary_20261109.py\` is not audit-only allowlisted. This is a push-audit gate issue, **not** evidence that deployed VIAC ES issuance/Results failed. Do not bypass the gate or claim latest main CI green. The running production deployment remains at the separately verified \`62287c23...\`.

### Safety and disposition
Prior VIAC ES market, UI, issue→Results and finance PRs #1457, #1483, #1487, #1489, #1505 and #1506 are merged. This checkpoint is documentation only, no CDB writes, external request budget changes, new Telegram sends, model training or historic archive mutation. Status: **PRODUCTION ISSUANCE/SETTLEMENT/ARCHIVE FINANCE VERIFIED; MEMBER/UI AND END-TO-END DASHBOARD PARITY NOT YET VERIFIED**.

### Guarded no-provider serving promotion requested after PR #1508
- PR #1508 changed the ELITE Results category-scoped cohort and issued-only sample counting; PR CI [#42661585696](https://github.com/BackstageTalks/tbt/actions/runs/42661585696) passed and it merged at `9292aa0ed75507095b28829578584a8776cbd534`.
- The original push deploy was cancelled when the docs-only checkpoint superseded `main`. An empty `[deploy-current]` commit did not trigger `ci.yml` because it changed no paths. This *non-empty documentation checkpoint* requests the existing guarded CI + no-provider app deploy, and changes no application behavior, prediction artifacts, provider calls, CDB, Telegram or historical bets.
- Do not mark the new runtime serving SHA or member-view gate VERIFIED until its exact guarded deployment and independent Azure read-back complete.
