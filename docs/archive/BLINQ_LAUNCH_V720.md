# BlinQ v7.2.0 — LIVE / INFO / ESA / SG launch day

- Premium Info and Comeback LIVE are enforced server-side for ELITE / Legend / GOAT.
- `live_watch` is a valid persistent insight type (WATCH alerts can now be stored).
- Rookie/PRO see the INFO/LIVE controls as ELITE-locked and do not poll the private feed.
- Historical provider self-match payloads are quarantined instead of aborting a whole day.
- Mega-data no longer runs an automatic history repair. It audits first, performs a small incremental history sync, and prioritises SG + ESA enrichment.
- Recommended launch sequence: history-audit → production-preflight → mega-data(10000) → train/backtest → refresh/promote only after review.
