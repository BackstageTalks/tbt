# DIL → CDB reverse NULL-only audit (ATP/WTA 2016–2026)

Read-only private audit of source-valued DIL canonical/overlay statistics absent from a pinned *current* CDB export. The audit **does not write CDB, DIL, models or serving** and never emits match IDs, player names or private raw content. Candidate counts are not import authorization.

## Dependencies

Run after `refresh_dil_secondary.py` passes **full independent CDB → DIL parity**, and after `check_dil_secondary_health.py --verify-live-cdb` confirms current CDB release. The audit checks the 78-part export receipt, SHA of read-only CDB SQLite, parity report, SQL schemas, and NULL-only candidates. The existing parity workflow must re-check CDB freshness after this scan.

## Candidate policy

- `dil_present_cdb_null_cells` are raw *field-level* opportunities, not import-ready rows.
- `type_valid_cdb_null_cells_needing_provenance` pass the existing rate/count type policy and have no conflicting DIL canonical vs. overlay metric, but **still need independent source-field provenance** and exact event/player identity.
- Invalid, unapproved field types and overlay conflicts are counted separately, never staged.
- `already_populated_cdb_cells` count values already present in CDB, not net-new.
- `ready_for_existing_cdb_writer = 0` is intentional. Once field-level evidence is proved, submit private candidate rows through the current `link_offline_serve_return.py` / `import_offline_linked_serve_return.py` and the existing CDB single-writer workflow. This audit must never become a second writer.
- The audit is only valid for the `cdb_manifest_sha256` in its output; on any CDB release change, rerun the complete current-source gate.

## Source-only DIL intake caveat

The 31 October Sackmann extension contains 139,016 raw observations, including 69,062 ATP/WTA 2016–2026 observations. 62,929 source rows have valid complete two-sided serve stats, but have insufficient native player/event ID evidence in that extension. They **cannot** be automatically promoted. The 663 previously verified links and 9,282 already-present metric values are not net-new. Preserve them for proof, but never double count them.

Local tests: `python -m unittest discover -v -s tests -p 'test_audit_dil_to_cdb_null_candidates.py'`
