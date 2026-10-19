# BlinQ CDB Drive Inbox

State: implementation in app repository, first production tick not yet evidenced.
The canonical private CDB is authoritative. This workflow does not call a sports API
or train/publish a model.

## Put external files here

[Google Drive CDB_INBOX](https://drive.google.com/drive/folders/1A0qlX8vXjDwcZYP9fSb8aFHjd9aNcWPJ)

- Folder ID: `1A0qlX8vXjDwcZYP9fSb8aFHjd9aNcWPJ`
- Parent: `BlinQ_data` (`1jzdzztz8cXquO8VDswqE19PHupQau-xM`)
- Existing private Drive reader inherits Viewer permission on this folder.
- Supported sources: .csv, .tsv, .json, .jsonl, single-sheet .xlsx,
  .parquet, .zip (bounded, nonrecursive inner files). Native Google Sheets
  and unrecognized formats are held for review, never quietly coerced.
- Current automatic import is **serve/return enrichment only**. Odds, ranks,
  candidate-only matches and PBP require their existing dedicated pipelines.
- Source rows must contain ATP/WTA, tournament, winner, loser, date and
  count-backed service statistics. Source native `tourney_date` is accepted
  for audit, but automatic writes require an **exact** canonical match date.
  This intentionally excludes many safe-yet-unproven tournament-start rows.
- No generated canonical player IDs, never silently use doubles or infer sides.

## Pipeline

1. Scheduled 02:23 and 14:23 UTC and manual `workflow_dispatch`.
2. Drive reader downloads bounded source content (100 files, max 64 MiB
   each and 256 MiB total) through `BLINQ_DRIVE_READER_JSON`. All input
   remains ephemeral on the runner. Its source manifests are not posted to
   public artifacts or Google Drive.
3. Adapter computes SHA-256, ignores byte-identical duplicates and
   normalizes valid rows to the existing Sackmann-style offline linker
   format. Bad rows/rejected formats go to local review counters.
4. Existing `link_offline_serve_return.py` performs canonical match
   reconciliation. Inbox stage filter additionally requires unique linked
   match, exact date, exact tournament, verified winner, and round/surface
   evidence; any conflict prevents unattended promotion.
5. Existing `import_offline_linked_serve_return.py` runs dry-run against a
   checksum-verified current 2016-2026 snapshot. Zero additions => no lock
   acquisition, no backup, no publication.
6. With a strictly positive delta, acquire private cross-repository global
   writer lock and verify release manifest compare-and-swap.
7. Back up only affected original partitions and both manifests in a private
   immutable prewrite release; download and hash-verify that backup.
8. Existing exact stats-only Parquet writer modifies only missing canonical
   stats, and local partition integrity is read back exhaustively.
9. Publish through existing `ReleaseStore.upload_bundle(..., before_upload=CAS)`.
10. Re-download changed private canonical assets and verify every staged
    record and changed cell against the original CDB, not merely HTTP/CI status.
    Always release writer lock if owned.

## Tests and operational controls

`pytest tests/test_cdb_inbox_adapter.py -q`

This tests normalization, duplicate handling, ZIP size limits, missing
mandatory columns, strict metadata corroboration and conflict quarantine.
PR workflows run only synthetic tests; production secrets are never present.

To inspect live results open the `CDB Drive Inbox - guarded external file import`
GitHub Actions workflow in `BackstageTalks/tbt`. The word VERIFIED may
be used for a data import only after the independent private remote readback
step succeeds. Creating a Drive folder, merging a PR or a successful empty
inbox tick does **not** establish a canonical CDB increase.

## Deliberate boundaries

There is no generic new writer, no direct Drive-to-CDB SQL endpoint,
no overwrite of non-NULL cells, no name-only weak matching promoted,
no automatic trust for user-supplied `import_ready` flags, and no
attempted import of unknown odds timing. Source files stay where the
owner placed them; no deletions or moves are performed.

The initial inbox is empty, so a production import will only happen when
supported, confidently matched, genuinely missing observations arrive.
