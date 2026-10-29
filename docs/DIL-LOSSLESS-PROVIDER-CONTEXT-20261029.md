# DIL lossless CDB context resolution — isolated secondary only

## Evidence and scoped decision
A real SHA-pinned private DIL↔CDB audit on 2026-10-26 compared 999,933 canonical matches and 10,619,967 populated CDB stat cells. No missing matches, metric discrepancies, invalid metric cells or canonical core discrepancies were found. Exactly **2,259 canonical field-level mismatches** remained, ALL in `provider_context_json`; none in scalar identity-adjacent metadata. Those counts refer to that historical 78-part CDB release. A newer 78-part CDB release must be audited afresh.

## Strict lossless decision
- CDB is authoritative for the populated **canonical provider-context leaves**. DIL-only keys remain in canonical provider context.
- Before replacing any populated DIL context leaf that differs from the populated CDB source, store **the entire original DIL provider-context SQL value** in the isolated `dil_cdb_provider_context_shadow` table together with source CDB hash, the original value checksum, the CDB context source and the resulting merged context checksum. The original DIL database is never mutated.
- Retain explicit private `dil_cdb_finalize_metadata_conflicts` per-field original/incoming audit entries. No raw values or IDs are ever logged from the private workflow. A fixed allowlist of aggregate counters is permitted.
- Empty/missing CDB context leaves are never authoritative over existing DIL context. No change to canonical match identity, stats, overlays, primary CDB, model training or serving config.
- Populated scalar metadata conflict, invalid shadow integrity, mismatched source SHA, missing stats or identity, SQLite integrity failure or changed CDB release ALWAYS blocks promotion.
- Repeat sync is idempotent; prior-source shadows persist in the next isolated candidate and are revalidated, not overwritten.

## Release verification
1. Verify restored 33-part original DIL snapshot and complete 78-part CDB release, SHA-pinned.
2. Compute candidate on an isolated private runner and verify each changed DIL context value against its ORIGINAL source row, not merely its own shadow hash.
3. Independently audit all canonical matches, stats, metadata and shadow hashes, including source hash and current CDB context.
4. Re-read latest live CDB release. Reject candidate if manifest or any attested source asset changed.
5. Independently read back published candidate hash and all receipts. Activate only **secondary** JSON pointer, not production CDB/model.
6. Public GitHub runner is **ephemeral**: even a PASS does not mean private durable publication. The current workflow deletes the entire output at completion. Durable private hosting and a separately verified private publisher must be connected and checked before operational activation.

## Residual risks
- **Semantic conflicts inside provider context**: a value different from CDB is preserved in a sidecar, not used in the canonical context. Downstream consumers that need DIL-original metadata must explicitly read the sidecar; ordinary canonical queries now see the authoritative CDB value.
- **Unintended context type changes**: `bool`, numeric, string and containers are type-conscious; nested data is preserved. Numeric tolerance and string Unicode normalization may accept representational equalities and should stay bounded by explicit tests.
- **Missing shadow from a legacy prior snapshot**: if the original DIL source lacks the needed history, an audit cannot manufacture evidence. The import verifies all newly changed rows against the original source.
- **Release freshness**: 78-part canonical CDB changes often; current-source parity is point-in-time and must be checked at promotion.
- **Ephemeral durability**: until a suitable encrypted private persistent destination and controlled writer exist, no verified operational release can be claimed.
- **Privacy**: private raw metadata and archive snapshots must remain outside public Actions artifacts/logs, PRs and releases.

Status terms: PREPARED (code), VERIFIED_SYNTHETIC (test-only), VERIFIED_CURRENT_CDB_PARITY (full private real data), SECONDARY_PUBLISHED_PRIVATE (durable read-back), ACTIVE_SECONDARY (pointer and fresh check). Do not conflate them.
