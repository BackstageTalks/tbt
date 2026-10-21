# Native Jeff Sackmann ATP/WTA -> BlinQ CDB (source-only)

## Goal

Avoid routing original Sackmann CSVs through generic Drive normalizers. Preserve original winner_id, loser_id, tourney_id, match_num, full integer counting stats and SHA-pinned source row identity. Never confuse an ATP/WTA Sackmann ID with a provider-native CDB player ID.

## Supported input

Extract the original 7z archives privately without changing the files. The native stage recognizes atp_matches_YYYY.csv, atp_matches_qual_chall_YYYY.csv, atp_matches_futures_YYYY.csv, wta_matches_YYYY.csv and wta_matches_qual_itf_YYYY.csv. Doubles and rankings are excluded.

Use the new command:

    PYTHONPATH=api:scripts:. python scripts/cdb_native_sackmann_stage.py \
      --source-root ./original-extracted --out-dir ./native-sackmann-stage \
      --start-year 2016 --end-year 2026

The output report.json inventories SHA-256 hashes and native_linker_input CSV paths. Every eligible source row contains a SHA+line based source_record_id, original player IDs, match number, tournament start, round, result and statistics. Duplicate native tourney_id + match_num tuples within the same native source file are quarantined rather than guessed. Exact raw archive row identities are preserved through the offline linker. Invalid serve counts are excluded.

You may run the existing READ-ONLY linker against each generated native_linker_input CSV using --source-csv, --history-dir and --out-dir. This is staging, NOT a CDB import authorization.

## Hard safety rules

1. Both original player IDs and canonical CDB player IDs must remain distinct. Promote no cross-provider identity without independently verified SHA-pinned evidence.
2. The source tourney_date is tournament START, not necessarily actual match day. Never fill canonical scheduled_at from it.
3. Source README states CC BY-NC-SA 4.0; separate use/reuse rights may be required for commercial production. The native stage makes no rights or import authorization claim.
4. Canonical updates must be exact-match verified, NULL-only, conflict-free, under global writer lock with immutable backup, CAS and independent remote readback.
5. Preserve all current Tennis API Pro values and existing API identities. Never import partial point-by-point tapes as full-match serve/return stats, or leak match results into same-match prematch features.

The Grand Slam point-by-point archive is deliberately separate: match metadata may be missing result, exact event ID, actual date or full point coverage. It requires a dedicated QA gate. A research-only derived service-point rate is not automatically CDB-ready.
