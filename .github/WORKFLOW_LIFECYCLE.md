# GitHub Actions workflow lifecycle (21 October 2026)

## Operational policy

Keep distinct workflows only for recurring production orchestration, the CDB single-writer/identity/provenance controls, essential CI, live data refresh and import, model-training/shadow/promotion controls, and reusable manual maintenance.

A completed, run/date/SHA-pinned research experiment or emergency one-shot **must not remain as a permanent Actions entry**. Prefer reusable, parameterized `workflow_dispatch` handlers where appropriate. Do not merge or delete an actively referenced workflow without an explicit dependency review.

## Cleanup

Retired 42 historical workflows from `.github/workflows/`; retained 186. Historical definitions remain recoverable in Git before this change, on base commit `ad5fc135478f32c8d3ee21d23fd326cb82c68714`. No scripts, tests, data, source artifacts, canonical CDB assets, or provider quotas were changed.

The 2026-10-20 post-morning calibration handler still received a `workflow_run` event after its expiration even though it refused dispatch; it was retired. A fully SHA-pinned avatar emergency release produced skipped push runs; it was retired as well.

Production workflows such as `ci.yml`, `data.yml`, `morning-refresh.yml`, `match-status.yml`, `cdb-drive-inbox.yml`, `cdb-global-writer-validation.yml`, `data-hourly-quota-gapfill.yml`, `admin-training-worker.yml`, `protected-frozen-cdb-candidate.yml`, `activate-shadow-candidate.yml`, `ui-hotfix-deploy.yml`, and all generic provider-native CDB writers stay intact.

## Retired files

- `.github/workflows/audit-fix4-current-cdb-once.yml`
- `.github/workflows/blinq-api50-provider-event-id-proof-once.yml`
- `.github/workflows/blinq-atp1000-cc0-review-once.yml`
- `.github/workflows/blinq-atp195-cc0-review-once.yml`
- `.github/workflows/blinq-cdb-sofa-provider-id-spotcheck-once.yml`
- `.github/workflows/blinq-cdb-sofascore-wikidata-research-once.yml`
- `.github/workflows/blinq-cdb-source-identity-probe-once.yml`
- `.github/workflows/blinq-cdb2025-exact-id-hypothesis-once.yml`
- `.github/workflows/blinq-charting-13-cell-witness-once.yml`
- `.github/workflows/blinq-charting-cdb-context-recovery-once.yml`
- `.github/workflows/blinq-charting-cdb-crosswalk-once.yml`
- `.github/workflows/blinq-charting-cdb-field-gap-audit-once.yml`
- `.github/workflows/blinq-charting-cdb-field-gate-once.yml`
- `.github/workflows/blinq-charting-final-import-decision-once.yml`
- `.github/workflows/blinq-charting-native-cdb-once.yml`
- `.github/workflows/blinq-charting-rich-source-preflight-once.yml`
- `.github/workflows/blinq-deferred-source-archive-triage-once.yml`
- `.github/workflows/blinq-drive-cdb-gap-once.yml`
- `.github/workflows/blinq-drive-qa50-once.yml`
- `.github/workflows/blinq-oct12-cdb-exact-crosswalk.yml`
- `.github/workflows/blinq-oct12-three-cdb-identity-readback-once.yml`
- `.github/workflows/blinq-oct12-three-cdb-secondary-once.yml`
- `.github/workflows/blinq-private-drive-report-summary-once.yml`
- `.github/workflows/blinq-rejected-drive-evidence-once.yml`
- `.github/workflows/blinq-rejected-drive-private-verify-once.yml`
- `.github/workflows/blinq-rich-charting-cdb-null-once.yml`
- `.github/workflows/blinq-sackmann-current-cdb-source-value-once.yml`
- `.github/workflows/blinq-sackmann2025-cdb-readonly-once.yml`
- `.github/workflows/blinq-sofa50-native-id-once.yml`
- `.github/workflows/blinq-source-evidence-lake-once.yml`
- `.github/workflows/blinq-uploaded-crosswalk-recheck-once.yml`
- `.github/workflows/cdb-audit25-exact-once.yml`
- `.github/workflows/cdb-source-layer-upload-20261015.yml`
- `.github/workflows/deploy-avatar-fallback-isolated.yml`
- `.github/workflows/match-status-evidence-once.yml`
- `.github/workflows/one-shot-20261018-morning-recovery.yml`
- `.github/workflows/one-shot-20261020-post-morning-calibration.yml`
- `.github/workflows/one-shot-frozen-721-bootstrap.yml`
- `.github/workflows/one-shot-frozen-721-segments.yml`
- `.github/workflows/one-shot-frozen-721-unseen-overlap.yml`
- `.github/workflows/recover-orphan-cdb-lock-39130345960-once.yml`
- `.github/workflows/recover-orphaned-721-cdb-lock-once.yml`

## Recovery

To recover a specific experiment, inspect its file at commit `ad5fc135478f32c8d3ee21d23fd326cb82c68714` and explicitly reintroduce only the required logic after reviewing up-to-date CDB evidence, single-writer controls, API reserve, and dependencies. Do not resurrect old pinned writers wholesale.
