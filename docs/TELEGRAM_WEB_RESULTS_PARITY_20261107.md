# Telegram ↔ BlinQ Results parity — 2026-11-07 incident record

## Goal and acceptance

Every previously **sent** Telegram pick must remain auditable in the
independently persisted Results archive AND the website's exact
same-event/selection/market/O-U-line backend Results view. The Telegram
summary must be reproducible from the original immutable publication
receipt (not a later model prediction or different provider market).

**Complete means:** for every sent day in scope, verified archive and
website-source exact market identities agree on win/loss/void, player
statistic and issued odds; any historical delivery summary agrees with the
premium subset of those original references (FREE is a duplicate check,
not a second wager). Independently verify server-side membership access
and render in a separate authenticated browser QA stage.

## Verified original evidence

- Source ledger: private `BackstageTalks/tbt-data` branch
  `telegram-bot-state`, `ops/telegram-bot-state.json`.
- Read-only strict source audit:
  https://github.com/BackstageTalks/tbt/actions/runs/42353354060.
- Pre-restoration 2026-11-07 audit:

  | Date | Issued refs | Exact archive verified | Exact pending |
  |---|---:|---:|---:|
  | 2026-11-03 | 13 | 4 | 9 |
  | 2026-11-04 | 16 | 11 | 5 |
  | 2026-11-05 | 13 | 6 | 7 |
  | 2026-11-06 | 12 | 4 | 8 |

- 6 November recovery:
  https://github.com/BackstageTalks/tbt/actions/runs/42355671648
  wrote 8 exact frozen ACES rows using existing Results CAS and verified
  12/12 original references with 0 provider calls, 0 CDB writes.
  https://github.com/BackstageTalks/tbt/actions/runs/42355685453
  confirms Telegram results message 742 and durable `sent` receipt.
- 4 November report receipt: premium 8W/7L; 5 November 9W/3L.
  Both were published from ephemeral frozen-status replay documents:
  `scripts/telegram_20261104_verified_replay.py` and
  `scripts/telegram_20261105_verified_replay.py` explicitly set
  `results_archive_write: false`. Their temporary rows were **not**
  durable web Results, causing independent readback parity to diverge.
- 3 November has no confirmed Results message at the time of this
  record; unresolved historical source counts require separate
  evidence-gated restoration, not guessed settlements.

## Root causes distinguished from expected product differences

1. **Real integrity defect:** original Telegram-only
   `local-aces-ou-v1` O/U publication differs from a later source
   model/projection publication for the same match and selected player.
   Web Results cannot substitute that later contract without exact
   source receipt and verified player actual count.
2. **Historical send-before-durable-write:** replay exception workflows
   built complete Telegram summaries from temporary verified witness
   rows, bypassing the native Results archive CAS readback that normal
   `telegram_daily_results.py` already requires.
3. **2026-11-06 rollover:** work queue originally ignored older pending
   fixtures after Bratislava 06:00; repaired prospectively in PR #1416.
4. **Expected comparison denominator differences:** web Results
   includes TOP, VALUE, ACCA, doubles, ACES, etc., membership/day
   filters, exclusions and bounded static feed history. Telegram
   includes only actually delivered TOP/VALUE/ACES plus a duplicate
   FREE reference. All-market web ROI need not match ELITE Telegram
   ROI; **the same frozen bet must always agree**.

## Protected architecture and current implementation

- Original issued daily Telegram ledger and Results CAS archive are
  different sources. Neither may be overwritten to make the other
  seem correct. Provider actual count can grade only exact original
  same-player, same-fixture, same-OU-line publication.
- `scripts/audit_telegram_web_parity.py` compares seven prior
  betting days against verified archive and the website backend's
  own Results assembly. Exact mismatch types are recorded; no names
  or raw IDs appear in workflow logs. Full report keeps short SHA
  identity fingerprints in 14-day workflow artifact.
- `/api/v1/internal/telegram/site-results-parity` requires the
  existing worker token, reads archive, snapshot and admin test
  exclusions, and declares `member_render_verified: false`;
  it is an **admin-level pre-entitlement serving source**, not proof of
  an authenticated member's visible cards.
- New scheduled watchdog runs ~08:32 Europe/Bratislava (DST-aware
  two-UTC-cron design). Failures are visible in GitHub Actions; no
  automated Telegram send, archive repair, CDB mutation, provider call
  or model change. A new data repair requires strict dry-run, immutable
  original issuance, verified source native statistics, CAS append
  and independent result count/odds readback.

## Explicitly open after PR #1422

- Reconcile actual current 3–5 November production discrepancies
  using the new production endpoint; a locally green unit test is
  not a production readback.
- Safely restore 4/5 November exact ACES publication rows (5+7)
  from original immutable sent receipts plus unique stored final
  source player counts. No Telegram resend; old result messages stay
  immutable. Measure net-new rows and exact premium counts.
- Investigate remaining 3 November unavailable exact player result
  evidence and old unsent Results report, using only independent
  verified provider evidence.
- Add authenticated browser QA for a known admin/ELITE Results view.
  No worker-token-only endpoint proves member rendering.
- Review legacy emergency replay workflow gating so no future result
  delivery can rely exclusively on an unpersisted temporary witness.
- No unrelated CDB provider writer, model 7.2.1, paid API allocation,
  or user membership policy may change under this work.
