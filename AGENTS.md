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

### A. Before **every** model training (even shadow/candidate, promote=false)
1. Identify the current serving champion and its exact binary, training report, calibration, feature schema/order, configuration, dependencies, release/tag, application SHA, and model version.
2. Identify and **freeze the input canonical release and training dataset** (all partitions/manifests, provenance and hashes); prevent concurrent writer changes to the training input.
3. Produce a **new, dated, non-overwriting, durable backup** of prior serving model + configuration + relevant source code/metadata + canonical/training inputs. Use BackstageTalks/tbt-data/main/backup/<source>/<YYYY-MM-DD>/<dataset>/ for the inventory, checksums and reference to immutable assets; keep large binary copies in an immutable external release/blob asset, not unbounded Git history.
4. Verify source and backup SHA-256, file inventories, independent persisted read-back, and that the prior serving stack can be restored in isolation with prediction/health parity. Record evidence (run ID, date, digests, reference, restore result). For one-time migration, the first training must wait until the baseline rollback is demonstrated.
5. **Fail closed** before fitting if any mandatory input, backup, checksum or restoration check is unavailable. This gate must be implemented in executable workflow/script; this document alone does not make it true.
6. Only after the gate: candidate training, leakage + identity checks, chronological holdout, ATP/WTA and market-quality gates. Never promote/activate a production model without explicit user permission.

### B. Shared RapidAPI budget and automation (separate task from model backup)
- Do not count a scheduler configuration or successful smoke test as a real scheduled collection.
- Respect effective provider-day **15,000 absolute**, **13,500 guarded ceiling** with **1,500 headroom**, **6 requests/sec**, and provider reset per active verified runtime contract (19:10 Europe/Bratislava at time of this writing). Never spend requests merely to exhaust quota.
- A quota job is **VERIFIED** only after a real scheduled tick, workflow completion, governed writer evidence, source API usage, persisted read-back and coverage/quality delta. Report a blocked or skipped tick as such.
- The external scheduler depends on its actual enabled state, permissions and expected first real run, and is not a substitute for proof of execution.

## Canonical data and destructive actions

- Canonical remains authoritative. Single writer, deterministic fail-closed identity linking, evidence precedence, provenance/license audit, duplicate/overlap checks and point-in-time leakage gates are mandatory.
- New point-by-point / same-match stats belong to post-match history and may only influence *subsequent* pre-match feature calculations. Historical odds require reliable pre-start timestamps.
- Do not delete a sole raw source, uncertain identity or quarantined conflict. Delete only hash-identical proven redundant transient copies after verified durable backup and dependency check.

## Reporting template (compact, not status theatre)

**State:** VERIFIED / PERSISTED_UNVERIFIED / PREPARED / EXECUTING / BLOCKED.
**Observed proof:** exact run/commit/version/read-back/check/digest and result, or "none".
**Impact:** measured before/after, coverage delta, API requests (if relevant), production model status.
**Remaining gate:** concrete unmet check or human decision.

Keep updates short and relevant. Make no claims of successful completion without direct evidence.
