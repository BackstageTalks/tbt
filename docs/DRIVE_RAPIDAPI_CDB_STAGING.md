# Google Drive CSV -> TennisAPI-compatible CDB staging (read-only)

This module converts existing historical tennis CSV statistics from Drive to the
**same parser envelope** as the paid TennisAPI `/event/{id}/statistics`
endpoint: `{"statistics":[{"period":"ALL","groups":[{"statisticsItems":[...]}]}]}`.
The actual parser used for both is `tbt.providers.statistics.parse_statistics`.

## Existing input on Drive

- `match_scores_stats_2016.csv` + `match_scores_stats_column_titles.txt`
  - Drive CSV: `1pm6ehATCeyn7iEXkTnH84F2uNUr46lKR`
  - Header names: `12OE199LeTyWsjSkpT0fdAEXroxBJ8dOq`
- `match_stats_2017_UNINDEXED.csv` + `match_stats_column_titles.txt`
  - Drive CSV: `130BKcm2UQwDZPah45H1X4TSwWwqrEMRi`
  - Header names: `1WvKFBqEhJz8n5jWQcJWMtQEUqjo2rg21`

Both source CSVs are **headerless**. Give their companion `column_titles.txt`
to the converter. The 2017 file lacks canonical player identity and is NOT
automatically mergeable into CDB.

## Modern WTA/ATP 2021–2026 CSV

The Jeff Sackmann-style modern match files have their own CSV header (for
example `w_ace`, `w_df`, `w_svpt`, `w_1stIn`, `w_1stWon`,
`w_2ndWon` and corresponding `l_` fields). They are relevant to the
under-covered years in CDB, not just older ATP archive data.

```bash
PYTHONPATH=api:scripts python scripts/stage_drive_match_statistics.py \
  --format sackmann \
  --input /path/to/wta_matches_2024.csv \
  --source-file-id ORIGINAL_GOOGLE_DRIVE_FILE_ID \
  --out-dir .cache/tbt/offline-drive/wta-2024
```

Direct counts and valid complementary opponent return totals are recovered,
not guessed. Missing values are not set to zero. The source and license remain
distinct from TennisAPI; `import_ready` stays false until CDB reconciliation.

## Offline conversion

```bash
PYTHONPATH=api:scripts python scripts/stage_drive_match_statistics.py \
  --input /path/to/match_scores_stats_2016.csv \
  --header-file /path/to/match_scores_stats_column_titles.txt \
  --source-file-id 1pm6ehATCeyn7iEXkTnH84F2uNUr46lKR \
  --out-dir .cache/tbt/offline-drive/2016
```

Output:
- `stage.jsonl`: one record per valid source row. Contains the exact
  TennisAPI-compatible statistics envelope + normalized **candidate** fields.
- `quarantine.jsonl`: malformed/inconsistent rows with source SHA and line.
- `report.json`: counts, original CSV SHA-256, zero paid requests, zero writes.

**Not a provider response.** `home` and `away` mean source winner and source
loser, respectively; they are synthetic parser sides, not TennisAPI-side IDs.
The staged record has `import_ready:false`, `provider_event_id:null` and
`canonical_match_id:null`. This prevents source impersonation and silently
mapping a different match merely because names look similar.

Before any eventual import, a **separate, audited** CDB reconciliation stage
must prove exact canonical match and both players; align winner/loser with
canonical p1/p2; confirm match dates, tournament and score; check rights;
compare each current CDB cell; never overwrite a conflict; acquire global
writer lock; and independently read back committed data.

This script intentionally contains **no network calls, paid APIs, release
publication, or CDB writes**. Its output is usable input for the future verified
reconciliation step; it is not an automatic approval to promote rows.
