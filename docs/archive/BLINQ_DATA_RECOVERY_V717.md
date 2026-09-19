# BlinQ data recovery v7.1.7

- Reopens `download_progress.json` dates automatically when an explicitly requested history range belongs to a physically missing yearly partition.
- Prevents a targeted 2026 recovery from being skipped merely because stale progress metadata says those dates were already completed.
- Healthy yearly partitions are not reopened.
- Manifest recovery now surfaces progress years whose physical parquet partition is missing.

Recommended recovery after the 2026 partition loss:
- mode: `history`
- start: `2026-01-01`
- end: blank (yesterday UTC)
- max_requests: `2000`
- promote: false

Then run `history-audit`, followed by `production-preflight`.
