# BlinQ CDB Drive-wide Import

**Scope:** entire owner-selected [BlinQ_data Drive root](https://drive.google.com/drive/folders/1jzdzztz8cXquO8VDswqE19PHupQau-xM), recursively including CDB_INBOX, source collections, audits and archives. All descendant files are inventoried and assessed; there is no folder allowlist for discovery.

**Root folder ID:** `1jzdzztz8cXquO8VDswqE19PHupQau-xM` (Google Drive, read-only).

**Status:** workflow implementation; a production import is verified only when a real dispatch has completed remote canonical read-back. An empty or read-only run is not a CDB increment. No sports API calls or model training occur.

## What "every file" means

1. List and paginate every reachable descendant folder, within explicit 10,000-folder, 100,000-file and depth 30 safety guards; fail rather than silently claiming a complete inventory if limits or access fail.
2. Record format classification for **every file**, including files in archives, audit folders and nested directories. Unsupported formats, native Sheets, ZIPs beyond validated limits and non-match data are review-only, never coerced into match statistics. Drive originals are never moved, deleted or overwritten.
3. Download up to **100 new or changed supported files** and **256 MiB per successful run**, max 64 MiB each, with SHA-256 and Drive MD5/size verification. **Prioritize ATP/WTA match-named files, the CDB inbox, then match-results and serve/return collections** before odds, rankings, historical archives and aggregate career/52-week files. This is only a scheduling hint: no file is dropped or considered canonical merely because of its name. Remaining supported sources stay checkpoint-pending for subsequent runs; no arbitrary first-100 hard stop.
4. Persist compressed progress metadata only into **private** `BackstageTalks/tbt-data/audit/cdb-inbox-progress.json.gz` using a GitHub Contents SHA/CAS guard. The runner commits progress **only after** the guarded stage/import and any required canonical remote readback have succeeded. A failed run does not advance the persisted checkpoint. Deleted/moved files are removed from the active fingerprint catalog and updates are reprocessed when Drive metadata changes.
5. Current unattended promotion remains **ATP/WTA match-level serve/return only**, when exact tour, date, tournament, winner, orientation, round/surface evidence and positive canonical NULL deltas are proved. Aggregate rolling/career stats, provider-only raw responses, odds, rankings, PBP, biomechanics and other domain-specific files are discovered/reviewed for their dedicated source pipelines; **not** force-fit into per-match stats or silently promoted.
6. Existing global single-writer lock, manifest compare-and-swap, immutable prewrite private backup, exact-stats-only patch and private post-publication readback remain mandatory for canonical mutation. Every row with insufficient identity or contradictory statistics stays review/quarantine.

## Workflow

- Scheduler: existing externally driven `match-status.yml` dispatch at 02:00 and 14:00 UTC (plus manual workflow_dispatch), no second GitHub cron.
- Entry: `.github/workflows/cdb-drive-inbox.yml`, with `INBOX_FOLDER_ID` set to the *BlinQ_data root*.
- Recursive intake: `scripts/cdb_inbox_drive.py`; schema normalization: `scripts/cdb_inbox_adapter.py`; exact candidate gate: `scripts/cdb_inbox_stage.py`.
- Canonical writer: existing `scripts/import_offline_linked_serve_return.py --exact-stats-only` and `ReleaseStore.upload_bundle`, not a new SQL/Parquet writer.
- Source report: inventory files/folders, previous fingerprints, downloaded files/bytes, unsupported/reviewed, pending supported. Report is ephemeral on the private-secrets runner; source identifiers are never sent to public CI artifacts.
- Real success = CDB field count, affected years, **net-new/enriched** counts and independent remote readback; `stage` or green synthetic CI never counts as an import.

## Verification

```bash
PYTHONPATH=.:api:scripts pytest tests/test_cdb_inbox_adapter.py tests/test_cdb_inbox_drive.py tests/test_cdb_inbox_scheduler_bridge.py tests/test_cdb_inbox_wait_resume.py tests/test_cdb_inbox_integration.py -q
```

**Failure handling:** invalid cursor, changed Drive bytes, source identity conflict, invalid canonical bundle, checkpoint CAS mismatch or failed remote CDB readback halt the applicable write. The private checkpoint is advanced only after success; re-running is idempotent against canonical NULL-only checks.

