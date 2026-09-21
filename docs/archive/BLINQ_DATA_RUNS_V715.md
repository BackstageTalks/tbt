# BlinQ v7.1.5 — resilient data-run publishing

## Fixes
- GitHub CLI operations now retry transient HTTP 429/500/502/503/504 and common temporary network failures with bounded exponential backoff.
- Fixed release lookup to use the same resilient GitHub CLI runner.
- Pinned scikit-learn to 1.9.0 to match the currently persisted model artifacts and remove cross-version unpickle warnings during refresh.
- Added focused regression tests for transient GitHub release failures.

## Why
A refresh on 2026-09-17 completed provider-side work but failed while persisting the history bundle because GitHub returned HTTP 500 for a release asset operation. This patch prevents a brief GitHub outage from wasting an otherwise valid refresh run.
