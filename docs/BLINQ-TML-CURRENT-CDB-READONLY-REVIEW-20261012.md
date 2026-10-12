# BlinQ — TML ATP 2022–2025 current CDB reconciliation (12 Oct 2026)

**Read-only / no canonical import / no model activation / no provider API use.**
Owner-approved reuse of external data is acknowledged; the remaining blocker is
**canonical event identity**, not source licensing.

## Immutable evidence

- 186 original official ATP/Wikidata QID candidate player links, private SHA
  `ea2a6ebc405104a9afa862ed2a3f30ce92121673cd307946a6ce18eaee8dd30d`.
- TML original 11,933 source rows, private gzip SHA
  `3cdf94b55a19d065cf01141839585245d85d59597c1fe6a7a5ffff96e121a89a`.
- Previously attested player-ID mapping SHA
  `ae61e871a59c9960f00c20cb061bd6d1a90e222dc58b126438d27a14aeedd192`.
- Current canonical 2022–2025 Parquet partitions checksum-verified against the
  original downloaded `_tbt_bundle_manifest.json`, with remote manifest
  independently compared again after audit.
- Full PRIVATE report and SHA readback:
  [blinq-cc0-current-event-review-38248515157-1](https://github.com/BackstageTalks/tbt-data/releases/tag/blinq-cc0-current-event-review-38248515157-1).
  Never reproduce private per-match or per-player rows in public Git commits.

## Observed exact comparisons

| Measurement | Count |
|---|---:|
| Candidate original ATP player IDs | 186 |
| Player mappings still supported by current canonical full names | 175 |
| Name or canonical-ID changes quarantined | 11 |
| TML original observations examined | 11,933 |
| Original source matches with both official player IDs current-linked | 2,415 |
| Unique strict-context event **review** candidates | 298 |
| Failed canonical tournament name | 1,469 |
| Failed equivalent-round check | 8 |
| Failed best-of | 228 |
| Failed surface | 176 |
| Failed date window | 109 |
| Failed winner ID | 1 |
| No canonical pair in years checked | 126 |
| Existing aces/DF cells equal | 1,170 |
| Aces/DF conflicts (no overwrite) | 10 |
| Aces/DF source cells unavailable or invalid | 12 |
| Aces/DF actual NULLs in 298 unique candidates | 0 |
| Derived postmatch rate cells checked with 4 equal aces/DF corroborations | 2,296 |
| Derived rates already equal (rounded tolerance ±0.001) | 2,232 |
| Derived rate conflicts | 36 |
| **Potential NULL derived rate fields, not import approved** | **28** |

The strict-context comparison uses two current-linked participant IDs,
winner ID, tournament-week 0–16 days forward, **exact normalized tournament**,
semantically equivalent draw-round labels, exact surface, best-of and uniqueness.
A tournament's week-start is **not** an event UTC timestamp; `QF` and
`Quarterfinal` are deterministic synonyms, not fuzzy identity. Values with
missing core aces/DF confirmation or implausible service numerators are excluded.

### Why 28 values are not yet an import

`TML tourney_id + match_num` is a **source-native event key**, not the
canonical provider event ID. The 298 unique context proposals still lack
independently corroborated native-event identity or exact score verification.
The utility always publishes `import_ready=false`,
`write_authorized=false`, `score_attested=false`,
`independent_event_id_attested=false`; release data stay private.
No missing rates may be written solely on this metadata comparison.

### Next safety gate

For each provisional NULL, independently match the TML native tournament-match
key to the precise canonical event; verify match score and original provider
ID namespace where obtainable; validate both players and orientation, original
serve arithmetic, source row digest, current CDB year partition SHA, and NULL
value. Then use the existing global writer lock, immutable backup,
compare-and-swap release publication and independent SHA readback.
Retain conflicts in quarantine. Do not train or promote the model.

The audited results are **snapshot-scoped**. Never assume they are fresh after
another CDB release update.
