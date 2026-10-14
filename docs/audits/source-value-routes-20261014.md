# Source value routes, 2026-10-14

Read-only execution against 995,143 CDB rows in 78 checksum-verified partitions.
Canonical manifest SHA-256: `036be275bfb526761c9a06233036b5a272dc3e561328577959a2ff8898664493`.
Input candidate ledger SHA-256: `969a4257316d1fe75fd9e14f0b6bd7b7e2ca02eea9ffc56c43be395feeda0fcf`.

## Measured routes

| Route | Matches | Cells |
|---|---:|---:|
| Missing complementary rates derived from existing CDB rates | 287,894 | 1,149,296 |
| Existing PbP candidate cells covered by those derivations | — | 772,579 |
| Remaining PbP candidate cells requiring external values | — | 652,241 |
| Reconstructed historical ID + stored Sackmann file/category/event provenance + original scoped player IDs | 88,774 | 169,865 external cells |
| Same historical provenance, but remapped player IDs | 82,644 | 158,265 external cells |
| Reconstructed historical key without all provenance checks | 3,718 | 7,052 external cells |
| No exact historical lineage | 38,154 | 317,059 external cells |

The last four cell categories sum to 652,241, and their match categories sum to
213,290. Of 772,579 overlapping derived cells, 772,506 agree with source proposals
within 1e-6; 73 differ. Those differences are not automatically replaced with the
external value. The audit excluded 1,685 records with inconsistent complementary
rates and 931 non-completed records from the complement route.

## Recommended order

1. Review derived first/second serve-return complements as a separate additive
   CDB recovery. No external player linking is needed for that arithmetic. This
   adds no independent information and is not evidence of improved model accuracy.
2. Prioritize the 88,774 historical records with original scoped IDs. Review the
   actual import provenance as same-source lineage instead of trying to translate
   every historical record into a live provider namespace. These are review
   candidates, not independently attested provider matches.
3. Resolve already-remapped historical players using the original crosswalk
   evidence; do not derive identity from the statistics being imported.
4. Use the common alias resolver as candidate discovery for the genuinely
   unresolved remainder. Keep event identity and player identity as separate gates.
5. Preserve Match Charting under its native point-sample scope. Never promote
   internally balanced partial points into whole-match totals. Use only completed
   prior observations for any future feature work, with a separately approved
   frozen-input training/rollback procedure.

## Reproduction

Run `scripts/audit_source_value_routes.py` with `--cdb`, `--source`,
`--candidates`, `--audit`, and `--out` pointing to private pinned inputs/output.
The existing schema-2 PbP audit report provides the exact candidate, partition,
and CSV digests. Outputs contain private event-level review ledgers; never commit
them to this public repository. Run
`python -m unittest discover -s tests -p test_source_value_routes.py -v`.

The independent local read-back re-counted all 287,894 derived records and
1,149,296 cells, verified each complement against its recorded source value,
checked unique targets, and verified both output SHA-256 digests. This verifies
the research artifact, not production publication. No writer, scheduler, model
training, production feature switch, or API quota consumption is introduced.
