# Uploaded ATP 2025 enriched CSV → CDB source-only intake

This source is **not native Jeff Sackmann**, even though its statistics reuse the
Sackmann column names. Its 8-character player and match identifiers and opaque tournament IDs are
an **opaque source-local namespace**; do not map them to provider or canonical IDs
by appearance, name similarity, tournament/start date or score alone.

## Run privately

Keep the original uploaded CSV in private storage; do not commit it or JSONL
outputs to GitHub. Verify its original SHA-256 independently before invoking:

```bash
python scripts/cdb_uploaded_2025_source_stage.py \
  --source "/private/atp_matches_2025.csv" \
  --expected-sha256 958cd93216075165895b5764d63499193a91993bb30dc00822f262713f7b31e1 \
  --out-dir "/private/atp2025-source-stage"
```

Output directory must be empty. Generated files are `source_only.jsonl`,
`review.jsonl`, `quarantine.jsonl`, and a completion `report.json`
with source/stage digests and aggregate counters. The completion report is
written **last**; any interrupted run or duplicate key leaves no successful
manifest and must be discarded, not resumed as a trusted stage.

## Trust boundaries

- Every source-only record has `import_ready=false`, independent canonical
  identity `false` and a SHA+source-line record ID.
- Explicit winner/loser serve counts must pass basic integer arithmetic. A
  derived 0–1 rate is emitted only where a valid positive denominator exists.
  A 0/0 break-point count is **missing**, not a fabricated 0% success rate.
- Missing context, invalid UTC start, incomplete/retired/irregular scores,
  arithmetic errors and identity collisions fail closed to review/quarantine.
  Tournament start `tourney_date` is preserved separately from the
  source-claimed match `start_time_utc`. The latter is not independently attested.
- Current-match post-result stats are not predicative pre-match features for
  the same event. Historical winner/loser prices in the source are not
  automatically accepted as timestamp-verified bookmaker quotes.
- Never feed `source_only.jsonl` directly into
  `import_offline_linked_serve_return.py` or generic native Sackmann staging.
- Before *any* CDB import: independent source-player/event crosswalk in a
  verified namespace, current SHA-pinned CDB snapshot, winner, score, round,
  date, surface and event proof; existing verified linker with crosswalk,
  NULL-only dry-run and field precedence, conflict quarantine, global writer
  lock, CAS, immutable backup, single writer and remote independent read-back.

## Observed uploaded input (1 Nov 2026)

Local read-only run on uploaded input SHA
`958cd93216075165895b5764d63499193a91993bb30dc00822f262713f7b31e1`:

| Measure | Count |
| --- | ---: |
| Raw source rows | 3,001 |
| Strict source-only complete rows | 2,501 |
| Source-only derived/player stat observations | 39,546 |
| Rows sent to review | 500 |
| Verified canonical CDB links | 0 |
| Confirmed CDB net-new matches | 0 |
| Written and read-back CDB cells | 0 |
| Provider API calls | 0 |

No canonical CDB snapshot was supplied to that local run. A zero in the
canonical linked/net-new columns means **not certified or written**, not a
claim that the current CDB has no gaps. No production/model changes occurred.

The earlier `atp_tennis.csv` archive has a separate historical odds linker
(`link_offline_match_winner_odds.py`); do not relabel its odds as bookmaker
opening/closing quotes without observation-time evidence. The
`matches.csv`/Elo archive is a separate provider namespace and Elo should
remain research/shadow until point-in-time corroboration.
