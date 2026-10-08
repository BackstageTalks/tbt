# BlinQ — model experimentation, promotion and rollback policy

Effective 2026-10-08. Standing project rule.

## Default: test rapidly, safely
- Prefer reproducible practical experiments and chronological out-of-sample / forward shadow testing over prolonged speculative discussion.
- Research candidate models on the same fixtures as the current production champion; compare accuracy, log loss, Brier score, calibration, segment results, coverage, published selection yield/ROI with adequate sample sizes and confidence intervals.
- No leakage: only as-of pre-match data; in-play, outcome, same-match statistics and timestamp-unknown closing odds excluded from pre-match features.
- Candidate training, evaluation, shadow predictions, branches, PRs and safe read-only workflows may proceed autonomously, respecting quota and single-writer controls.
- **Never promote, replace, activate or deploy a new production model without explicit operator approval.**

## Mandatory gate before operator-approved promotion
1. Identify the exact serving champion version, immutable artifact digest, configuration and feature/schema dependencies. Back up the complete serving bundle durably; document accessible location and checksums.
2. Build candidate as an independently versioned, immutable artifact. Record training provenance, input release, feature schema, hyperparameters and holdout definition.
3. Run chronological same-fixture comparison, leakage/identity checks, and shadow checks. Fail closed if improvement is unproven, key segments regress materially, or baseline is not comparable.
4. Demonstrate a rollback **without changing the live serving model**, using a staging or isolated environment: restore the saved champion artifacts/configuration and verify predictions/health checks match its reference. Record command/run ID, time, hashes, result, and expected recovery steps.
5. Write an operator-readable promotion proposal including baseline, candidate metrics, guardrails, exact rollback procedure and evidence. **Ask for explicit authorization before production model switch.**
6. After an approved promotion verify current serving version and real prediction outputs, monitor post-deploy health and key metrics, retain the prior champion and rollback pointer.
7. If regression or health issue occurs, use the verified rollback procedure subject to production-change authorization/policy and verify read-back of the restored version. Never rewrite historical published prediction records.

## Evidence principle
Commit != deployment; passing CI != production verification; retained version name != working rollback. If any evidence is absent, explicitly mark the gate as not verified and **do not promote**.

### Baseline recorded 2026-10-08
- Existing production champion in audit: `v201-20260925T204608601094Z`.
- Shadow candidate `v201-20261005T201258172391Z` was rejected; production model unchanged per model-shadow-promotion audit.
- Previous artifact's full integrity and rehearsal of rollback are **not yet verified**. Do not claim otherwise.
