# BlinQ: two active data layers — verified migration ledger

**State (2026-11-17): PARTIALLY IMPLEMENTED. This is a migration contract, not authorization to delete canonical source material.**

## Goal

Reduce the active training/normalization graph to exactly two **logical** data layers:

1. **CDB / normalized**: authoritative canonical match IDs, ATP/WTA 2016–2026 match results, match statistics (including serve/return and break points), approved point-in-time historical dimensions, event/player crosswalks and per-value source precedence. Backed by the existing private `tbt-data-v1` release. **Keep the existing single writer, 78 year partitions, manifest CAS, identity checks and NULL-only imports.**
2. **Training / derived**: one reproducible point-in-time feature cohort generated **only** from an immutable, SHA-verified CDB snapshot plus approved and versioned pre-match dimensions. Contains match IDs, labels, feature schema/version, CDB source-manifest SHA, cutoff, chronology/leakage validation, and auditable training-provenance certificate. No independent manual enrichment or canonical corrections in training.

**Source archives are NOT a third active layer.** Preserve immutable originals, attribution, archived rejected records, quarantined conflicts, backup and readback evidence in cold provenance storage. They cannot be used as a competing production data feed.

## Verified live state / issues to resolve BEFORE deletion

- `tbt-data-v1`: existing authoritative private canonical CDB release, 78 `history-YYYY.parquet` partitions; 121 release assets on 2026-11-17. Do **not** delete `training_snapshot.parquet` (2026-09-05) or other release assets before executable reader inventory and tested restore; current release asset deletion is not supported by the connected GitHub actions in this workspace.
- `tbt-training-table-v1`: 13 assets; `training_table.parquet` 238,852,020 bytes, last changed **2026-10-10**, i.e. **older than the canonical CDB updates of 2026-11-17**. Do not equate its age with proof that it is unused; no reader-retirement or new generation has been validated.
- `.github/workflows/training-db-rebuild.yml` currently imports extra ATP leaderboard, WTA season, verified rank and verified weather inputs and publishes `tbt-training-table-v1`. They are **current dependencies** until their validated, point-in-time equivalent is available from the normalized layer.
- `.github/workflows/protected-frozen-cdb-candidate.yml` separately freezes the current CDB with immutable input backup and generates `verified-training-features.parquet` by leakage audit for the actual candidate fit. This **is a second derivation path** today, not proof of one unified training layer. Preserve the existing champion, candidate/rollback evidence and protection gates.
- `tbt-data/research/training_l2`, `research/source-layers`, `research/source-lake`, private release sidecars, review and provenance logs are **not approved for deletion en masse**: no comprehensive active-reader/reference-and-backup proof exists yet. Move them out of active feature generation only when their inputs have been reconciled, versioned and independently verified.
- Current CDB release and training release inventories contained **zero identical release asset SHA-256 hashes across the two releases**; their assets cannot be deleted simply by deduplicating SHA metadata.
- Private Git tree contained one exact duplicate Git blob: `audit/alimoh89-preparation-latest.json` and `research/historical_market/alimoh89_2014_2025/manifest.json` (Git blob `0400d052073cf3b8bd3fdac94724a9048dfc2c60`). The redundant audit copy was deleted by commit `f01088308a0316812d86eb27b9c5e85c7f1138f3` after readback and the canonical manifest remained byte-identical. The legacy double-writer was removed by `ac58cd4faff4fe16dca777022c11e8440a95ae0d`.

## Mandatory migration and deletion gates

1. **Baseline and ownership**: make a machine-readable inventory of *all* live readers, releasers and writers, current run/lock state, CDB and training assets and source-specific origins. Pin current production champion, API consumption budget and CDB SHA before any larger migration.
2. **Normalized input contract**: route ATP/WTA match/serve/return/BP and point-in-time ranks/venue/weather through the **existing** provider-native stage and CDB authority, without new writer/schema assumptions; source provenance and exact identity checks remain mandatory.
3. **One training build**: make both `training-db-rebuild` and protected candidate fit read the *same* SHA-bound, PIT and leakage-validated training cohort or an exactly equivalent checked build from identical frozen source inputs. The canonical training source cannot be the 2026-10-10 stale table by default.
4. **Parallel proof**: run old and new paths against the *same* frozen CDB input and compare exact match IDs, targets, column schemas, NULL mask, feature values, cohort cutoffs, train/holdout chronology, ATP/WTA cohorts and baseline model predictions. Block if any unexplained regression or leakage.
5. **Safe cutover**: keep champion untouched until authorized model promotion. After reproducible CI and rollback rehearsal, switch readers to one training contract; run a real guarded data import, current training readback, and independent production checks.
6. **Retire only after proof**: remove dead legacy readers and verified duplicate transient files; remove old releases only after independently checked durable backup, **zero** live consumers, reproducible restoration and user-requested cleanup scope. Keep sole raw sources, historical evidence and quarantines. Do not force-delete all releases or modify the existing global CDB lock.

## Observed proof / metrics

- No new provider calls, CDB writes or training promotions were made in this cleanup.
- Exact duplicate eliminated from current private Git tree: **1 file, 6,438 bytes**. Surviving provenance SHA read back exact.
- Current private CDB and training release: **121 and 13 assets respectively**. No cross-release SHA duplicate.
- Production main workflows have **NOT** been redirected to the two-layer contract; full deletion and migration are **NOT DONE**.

## Open blockers / next autonomous phase

- Complete cross-repository runtime consumer inventory (including release metadata, Azure consumers, cron, manual jobs).
- Migrate/replay approved PIT ATP leaderboard, WTA season, rankings, weather into one canonical input contract; preserve precedence and original snapshots.
- Generate current cohort (not stale October snapshot), compare against protected candidate frame, check quality and inference parity.
- Verify independent tested restore + approval scope for removing obsolete non-duplicated release artifacts and private source objects.

**Avoid deleting or disabling daily collection, current CDB, pinned training backups, logs, original source data, lock state or active model files to make the filesystem look simpler.**
