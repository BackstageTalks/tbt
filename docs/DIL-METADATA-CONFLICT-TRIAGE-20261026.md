# DIL secondary — metadata conflict triage and guarded remediation (2026-10-26)

## Grounded outcome
The private full run [40241284119](https://github.com/BackstageTalks/tbt/actions/runs/40241284119), from 2026-10-25, restored all 33 SHA-pinned DIL archive parts and independently verified the SQLite snapshot. Its SHA-pinned full CDB export had 999,464 canonical match IDs, 10,613,405 populated statistic cells, **zero missing CDB match IDs**, **zero divergent effective statistic cells**, **zero canonical core mismatches**, zero SQLite integrity and foreign-key failures. **2,259 populated metadata FIELD comparisons** conflicted; this is not a claim of 2,259 distinct matches. Promotion was correctly blocked. The runner erased all temporary raw data afterwards.

CDB is authoritative; original DIL and its high-quality DIL-only enrichments must remain lossless. The private runner does not publish a persistent DIL artifact or change service pointers.

## Defect remediation in PR #1019
- The previous importer cataloged nested provider-context disagreements but **failed to write scalar populated metadata differences** to its private conflict ledger, even though the downstream parity gate found them. The importer now archives each conflicting scalar pair with the CDB export SHA and leaves the original DIL value unchanged.
- The parity auditor exposes counts grouped only by a **hard-coded set of 11 metadata field names**. Neither IDs nor values are sent to GitHub logs. Case-only discrepancies are counted as *review candidates*, **not** counted as matches.
- NFC Unicode canonical composition and ASCII/Unicode whitespace normalization are interpreted as purely representational equivalence for scalar metadata; this does **not** rewrite source DIL.
- Nested JSON/provider-context leaf comparisons distinguish booleans, numbers and numeric strings. Inferred type coercions are prohibited.

## Risks and decisions
| Risk | Impact | Mitigation / gate |
| --- | --- | --- |
| Populated DIL field disagrees with CDB (name, round, rank, tournament) | Incorrect manual enrichment or stale historical metadata; blindly overwriting loses information | Keep both values in private source-pinned conflict ledger; no auto-override. Review field-level counts and sample cases privately before field-specific policy. |
| Conflicts are concentrated in provider-context JSON | Source providers may use different schemas, date units, bools, aliases or nested keys | Type-strict comparison, leaf-level preservation, no forced JSON coercion. |
| Normalization is too broad | False parity hides meaningful difference | Only NFC and whitespace; case-only changes remain blocked, synonyms never inferred. |
| Canonical match ID, year or UTC epoch unit drift | Wrong match association | Exact identity and UTC second→nanosecond contract; match collision veto; fail closed. |
| CDB release changed between fetch, audit and activation | Stale secondary vs current CDB | Compare all 78 partition digests and before/after/current manifest twice; repeat private full run against most recent source. |
| Input snapshot is damaged or not immutable | Silent corruption | Independent source SHA-256, full SQLite integrity, read-back of versioned candidate, preserved receipts. |
| GitHub public logs leak source match or player identities | Privacy and rights issue | All raw conflicts remain private SQLite; public results restricted to numeric counters for vetted static field names. |
| Ephemeral runner completes but output disappears | No durable operational DIL | Fail closed. Separate private persistence, independent post-publish SHA-256, secondary-only pointer and rollback required. |
| A CDB update fixes or introduces previous conflict | Stale decisions applied to newer source | Every ledger pair keyed by current CDB export digest; never apply previous source's decisions blindly. |

## Operator follow-up
1. Merge the instrumentation only after synthetic unit, code compilation, repository writer-lock and BlinQ CI pass.
2. Run the private full 33-part DIL / 78-part CDB reconciliation on trusted `main`. Record **aggregate-only** per-field counts, source digest, total conflicts and runner result.
3. Investigate non-zero field groups using the private `dil_cdb_finalize_metadata_conflicts` table. Validate provenance and field-specific semantics; choose an explicit lossless resolution policy, with review/quarantine for ambiguous cases. **Never infer that all conflicts may be auto-normalized.**
4. Rebuild a new immutable secondary candidate against the latest CDB. Demand all 13 fail-closed parity indicators zero and full independent `PRAGMA integrity_check` / foreign-key checks.
5. Only then publish to a private persistent store, verify artifact digest and receipts by read-back, and activate the **secondary-only** pointer. Do not change primary CDB, production serving, model training or admin release as part of this workflow.

**Release gate: BLOCKED until newer real-CDB run completes with 100% gated parity and persistent secondary publication/read-back.**
