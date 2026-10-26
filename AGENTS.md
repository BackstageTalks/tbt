# BlinQ agent execution contract (standing rule)

Applies to work on BackstageTalks/tbt and BackstageTalks/tbt-data. This document is an instruction and review contract; it is **not** a substitute for executable CI/runtime safety gates.

## Evidence-based completion — no exceptions

- **Never say "hotovo", "opravené", "nasadené", "funguje", or "zálohované"** for a task unless tools confirmed actual execution and the specific requested outcome through independent read-back or equivalent verification.
- Explicitly distinguish: **PLANNED** (no action), **PREPARED** (local artifact/branch/PR only), **EXECUTING**, **PERSISTED_UNVERIFIED** (write/commit/dispatch only), **VERIFIED** (outcome observed), and **BLOCKED** (specific obstacle).
- Commit is not merge; merge is not deploy; dispatched or queued workflow is not successful completion; successful workflow is not persisted production result; a manifest is not a verified binary backup.
- Every "VERIFIED" claim must identify **what** was tested, **where** it was checked, the exact source/version (commit, run ID, release asset/hash as applicable), and the observed result. No supporting evidence => say **not verified**.
- When asked for status, re-check the **current** state rather than repeat past claims or assume completion based on elapsed time. If only partial progress exists, report the precise last confirmed milestone and remaining gate.
- Do not promise autonomous future work without an actual scheduled task or executing workflow; do not make the operator chase an unverified claim.

## Two independent operational safeguards

### A. Model work: distinguish read-only shadow checks from actual training
1. For actual model fitting, identify and pin the serving champion, frozen training inputs, configuration and feature schema. Read-only shadow evaluation of already-issued outputs does **not** require a new backup or model fit.
2. For fitting, freeze and verify the exact canonical/training inputs and prevent concurrent writer changes to the training input.
3. Preserve a verifiable rollback of the serving model and training inputs before any fit or production change. **The owner maintains originals/backups on the laptop SSD and Google Drive, plus a weekly additional copy on the SSD; do not create more GitHub archival duplicates**. A second copy on the same SSD is not an independently fault-tolerant location. This owner-reported backup arrangement is not independently verified from this workspace. Until the currently enforced GitHub-release-based training backup is replaced by a tested Drive-backed equivalent, obey its executable fail-closed gate. Do not create extra backups for read-only shadow comparisons.
4. Verify the exact relevant backup and restore path with independent read-back; reuse a previously verified immutable backup where an executable gate supports it. Record a compact run/version reference instead of duplicating full inventories in multiple reports. A new backup is mandatory whenever the existing verified rollback would no longer cover the change.
5. **Fail closed** before fitting if any mandatory input, backup, checksum or restoration check is unavailable. This gate must be implemented in executable workflow/script; this document alone does not make it true.
6. Only after the gate: candidate training, leakage + identity checks, chronological holdout, ATP/WTA and market-quality gates. Never promote/activate a production model without explicit user permission.

### B. Shared RapidAPI budget and automation (separate task from model backup)
- Do not count a scheduler configuration or successful smoke test as a real scheduled collection.
- Respect the **runtime shared-budget implementation** as the source of truth: **15,000 provider/day**, **14,700 global BlinQ ceiling**, **300 reserved**, **6 requests/sec**, fixed reset **17:09 UTC** (**18:09 CET / 19:09 CEST**), and the hourly ingestion cutoff **17:07 UTC**. The history downloader also has its separate **12,000 requests/run** bound. Do not reproduce superseded quota values as standing policy. Never spend requests merely to exhaust quota.
- A quota job is **VERIFIED** only after a real scheduled tick, workflow completion, governed writer evidence, source API usage, persisted read-back and coverage/quality delta. Report a blocked or skipped tick as such.
- The external scheduler depends on its actual enabled state, permissions and expected first real run, and is not a substitute for proof of execution.

## Canonical data and destructive actions

- Canonical CDB remains authoritative. Keep a single coordinated writer, reliable match/player identities, deduplication, NULL-only supplementation and point-in-time leakage protection. Original files are retained in the owner's SSD/Drive archives; **do not demand original-file SHA/Drive ID in each CDB record or value**. Project-owner source-use attestation is already recorded; avoid repeated approvals for the same internal use. Keep archive-level source/rights notes; do not assume this independently permits external redistribution.
- New point-by-point / same-match stats belong to post-match history and may only influence *subsequent* pre-match feature calculations. Historical odds require reliable pre-start timestamps.
- Do not delete a sole raw source, uncertain identity or quarantined conflict. Delete only hash-identical proven redundant transient copies after verified durable backup and dependency check.

## Reporting template (compact, not status theatre)

**State:** VERIFIED / PERSISTED_UNVERIFIED / PREPARED / EXECUTING / BLOCKED.
**Observed proof:** exact run/commit/version/read-back/check/digest and result, or "none".
**Impact:** measured before/after, coverage delta, API requests (if relevant), production model status.
**Remaining gate:** concrete unmet check or human decision.

Keep updates short and relevant. Make no claims of successful completion without direct evidence.
