# BlinQ ELITE Telegram results — after final verified pick

Daily offer remains operator-scheduled at 06:20 Europe/Bratislava. The
operator-approved ELITE auto-results mode explicitly ignores the old Admin
`telegram_bot.enabled` and `results_enabled` schedule switches; existing manual
and legacy results behavior remains unchanged. This
**results** job has **no additional cron**: the existing external 30-minute
`match-status.yml` worker dispatches `telegram-results.yml` only after a
successful status reconciliation and durable match-status snapshot read-back.

## Exact finalization gate

1. Read the *originally sent* Telegram ledger rows, including the FREE mirror
   of its TOP selection. Manual format reposts do not create extra picks.
2. Select the oldest unreported issued betting day (current BlinQ 06:00-day
   or preceding day, for matches that finish after midnight/06:00).
3. Read the existing token-protected internal settlement archive **without
   tennis API calls**, allowing the active 06:00 betting day.
4. Match every TOP/VALUE/ACES/duplicated FREE reference to **exactly one**
   provider-verified `match_status_snapshot` settlement, including publication
   identity, market line, direction and price contract. VOID is final.
5. If **any** reference is pending/ambiguous, **publish nothing** and reserve
   nothing; retry on next 30-minute match-status worker run.
6. When all are finished, generate one ELITE summary (or multiple Telegram
   pages if over limit). Count only the actual premium picks (7 for the
   31 October sample), never add FREE twice. Send only to `TGCH_ELITE`,
   with separate lock-protected reservation and Telegram-ID read-back.
7. If send outcome is ambiguous after a reservation, do not resend blindly:
   examine the channel and ledger first. Telegram lacks idempotency keys.

The existing morning 07:00 `telegram-results-tick` external trigger, if
still configured, becomes an optional redundant **read-only check**, not the
primary trigger. It cannot publish an incomplete report or duplicate a sent
report. Disabling that old external cron avoids redundant work.

## Required setup

Configure GitHub Actions repository secret `TGCH_ELITE` to the exact private
ELITE destination chat ID (and add the `TGB` bot as an administrator with
posting permission). This secret is **required**; there is intentionally
**no fallback** to `TGCH` or `TGCH_FREE`. Other existing secrets are unchanged.

The BlinQ membership directory presently labels the VIP link with
`min_plan: elite`. That page restriction by itself is **not** Telegram
membership enforcement. Set the Telegram group to private and control
admission/revocation separately based on ELITE entitlements; the results
workflow does not grant memberships or expose a join link.

**Note:** status reconciliation is currently scheduled every 30 minutes. Its
completion triggers the results check, so the practical latency is up to
the next 30-minute match-status run + GitHub Actions runtime. Changing the
existing match-status scheduler to every 15 minutes would use more provider
requests. We have not changed that cadence.

No CDB imports, model recalibration, market refresh or extra RapidAPI call is
performed by the results script.
