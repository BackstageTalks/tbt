# BlinQ security + functional code audit — 2026-11-09

## Goal and acceptance
Deep audit of production branch `BackstageTalks/tbt:main` for access controls, browser protections, complexity, issued-pick/Results privacy and release verification. Completion requires evidence of enforced GitHub branch protection, passing regressions, current production deploy/read-back and a negative (unauthenticated) plus positive (real entitlement) member API/UI proof. A static contract check is **not** a penetration test.

## Baseline / binding scope
- Audited source SHA: `75f62daae5a50ed4025059ff89192f4de2e80840` on 2026-11-09.
- Do not change production champion, CDB, native import/lock/CAS, issue/settlement history, paid provider calls, shared quota or externally controlled cron. Do not bulk-refactor the active JS/CSS/API monolith to satisfy this audit.
- This audit's GitHub branch holds **tests/documentation only**; no runtime mutations or deployments requested.

## Evidence, with fact vs open verification
| Surface | Verified source/GitHub observation | Still unverified |
| --- | --- | --- |
| Branch protection (P0) | `GET /repos/BackstageTalks/tbt/branches/main` returned `protected=false`; repo ruleset collection returned `[]`. Connector's protection endpoint returns HTTP 403, and no protection-write action exists. | An actually active and enforced ruleset; see [#1498](https://github.com/BackstageTalks/tbt/issues/1498). |
| API (security) | `api/function_app.py` contains **85** route declarations. **59** start with `v1/admin/` or `v1/internal/`; static review finds early `_admin_user`, `_live_worker_token_ok` or `_account_worker_token_ok` in all 59. `auth.py` checks Firebase ID-token revocation, admin uses server-issued role and suspension check. | Staging/live negative auth, edge behavior, multi-instance abuse throttles; distinguish static control from exploitation testing. |
| Web security | `web/staticwebapp.config.json` configures same-origin `script-src`, no `unsafe-eval`, frame/object/base restrictions, HSTS, X-Frame-Options and nosniff. Existing regression tests cover more browser behavior. | Independent live HTTP response headers, Firebase web-key restrictions, ingress behavior. |
| Complexity | **131** files in `api`, **411** in `scripts`, **680** in `tests`, **205** workflow definitions; `web/app.js` is about 933 KB and `web/blinq-app.css` about 910 KB in Git source. Existing asset optimizer and scoped Ruff workflow already exist. | Full dependency graph, runtime profiling and safe modularization candidates; do not remove workflows based only on count. |
| Issued results | `issued_authority.py` uses exact confirmation/receipt identity for member-serving candidates. Existing `tests/test_issued_serving_authority.py` and `tests/test_serving_artifact_readback.py` test fail-closed and exact SHA/section-count canaries. | Real end-to-end member UI, Viac Es settled priced outcomes, Telegram ↔ Web ↔ Results parity on an actual published betting day. |

### New regression
- [PR #1499](https://github.com/BackstageTalks/tbt/pull/1499) adds a fail-closed static regression for privileged route authorization, Firebase revocation, role validation and CSP.
- Source-only inspection: 59 sensitive routes, no missing early guard at inspected SHA.
- CI is required to verify the new test file itself. No CI/test or live deployment PASS should be claimed before checking its final result.

## Existing operational alert (separate from the five audit surfaces)
- At 2026-11-09 08:00 UTC, [match-status run #42582924096](https://github.com/BackstageTalks/tbt/actions/runs/42582924096) failed. Its worker returned HTTP 503 with `{"error":"match_status_worker_failed","detail":"ValueError"}`; an auxiliary action dispatch also got HTTP 422 because the target workflow lacked `workflow_dispatch`. These are *observations*, not a proven root cause of any specific missing settled result. Do not label this fixed without independent data read-back.

## Next gates
1. Finish #1499 CI and exact-file read-back before merge; ensure no unrelated runtime or CDB change.
2. An authorized repository admin applies and independently verifies #1498. Preserve external dispatch and existing guarded write paths. Treat `protected=false` as **OPEN**, even if PR CI is green.
3. Verify live public/unauthenticated denial and test entitled vs non-entitled **real** feed/Results UI identities; compare exact issued receipts, markets, prices and KPI across web and archive.
4. Continue scoped architecture inventory and operational incident separately; avoid broad refactoring or unsanctioned cron/provider changes.

## Status
Source inventory and existing security controls: **verified statically**.
Regressions: **prepared in PR, pending CI**.
Main protection: **open, administrative action required**.
Production security and functional end-to-end proof: **open**.
