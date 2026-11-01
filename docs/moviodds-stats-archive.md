# MoviOdds tennis statistics archive — operating contract

The source archive is separate from the canonical CDB. The operator-selected
Google Drive folder **MoviOdds** is
https://drive.google.com/drive/folders/13kDDxOaQ0L1Jr5ZjbSNjbDFJiNSz9uwx
(folder ID \`13kDDxOaQ0L1Jr5ZjbSNjbDFJiNSz9uwx\`).

## Capture

- LIVE workflow collects \`/odds?sport=tennis&in_play=1&groups=67&stats=1\`
  into \`BlinQMoviOddsStats\` (existing Azure Table Storage) using source
  \`stats.updated_at\` as an immutable observation identity.
- Match-status workflow collects finished \`/results?stats=1\` for today
  and yesterday UTC, storing complete final records under a separate key.
- Both collectors use the *existing* external clocks and worker token, require
  persisted SHA-256 readback, and cost **zero Tennis API Pro requests**.
  Provider outage is isolated from the existing LIVE/match-status workflow.
- A corrected final record with an existing different hash is flagged as a
  conflict; the source value does not silently overwrite the first final.
  Live snapshots are not eligible for CDB import.
- All records preserve provider fixture ID, full names, source timestamp,
  raw statistics, score, provenance, and final status. Missing values stay
  missing; percentages are never confused with point-count statistics.

## Drive

- The \`moviodds-drive-archive.yml\` workflow exports a verified UTC date via
  \`/api/v1/internal/moviodds-stats-worker?date=YYYY-MM-DD\`.
- The archived JSON contains finalized source records **only**. The Azure
  journal retains denser intermediate live observations.
- Filename is \`moviodds-tennis-final-YYYY-MM-DD-SHA16.json\`.
  Identical bytes are idempotent; a changed dataset gets an additional version.
  Upload is verified by independent Drive binary download and exact SHA-256.
- Automatic daily dispatch uses the existing external Match Status clock
  at 04:00 UTC (exporting the previous UTC date). No extra cron or switch.
- The archive job can reuse existing `BLINQ_DRIVE_READER_JSON` credentials,
  requesting write scope ONLY within its own archive script. The other
  importers retain their existing read-only scope.
- **One-time operator setup:** change the permission on the linked MoviOdds
  folder for `blinq-drive-reader@blinq-drive-audit.iam.gserviceaccount.com`
  from Viewer to Editor. Do not modify any parent or CDB folder permission.
  A separate `BLINQ_DRIVE_WRITER_JSON` remains supported if desired.
- As checked on 2026-11-01, the existing service account has reader access
  only. The daily Drive export will fail until folder Editor access is granted;
  no successful upload is claimed.
- The archive job also retains 14-day troubleshooting artifacts, without
  publishing private source JSON into the public repository.

## CDB (not scheduled)

No automatic daily canonical import is configured. A periodic import requires
an explicit separate guarded batch:

1. Read immutable final JSON snapshots and source digests.
2. Map only exact ATP/WTA matches against the authoritative CDB with verified
   player pair, date/time, final **set score**, and non-ambiguous source ID.
3. Treat raw count-valued aces / double faults as potential CDB candidates.
   First-serve win percentages and break-point conversion percentages are
   provider-native raw measurements, **not** automatic canonical rate/count
   mappings until their denominators and definitions are validated.
4. Quarantine identity collisions and value conflicts; accept only supported
   NULL-only verified fields; never replace higher-quality canonical values.
5. Use the EXISTING single-writer CDB importer, immutable backup, lock, CAS,
   dry-run, remote readback and full affected-year partition integrity check.
6. Report raw / linked / newly-enriched / rejected and independently
   confirmed numbers. A saved JSON is **not** a successful CDB import.

Neither collection nor Drive archive triggers model training or a canonical
writer.
