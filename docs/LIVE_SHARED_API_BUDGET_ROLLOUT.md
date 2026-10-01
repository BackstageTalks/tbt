# Shared Tennis RapidAPI quota — rollout

## Capacity and scope

The subscription is currently treated as 15,000 requests per provider billing
window. BlinQ enforces a more conservative 12,000 in a **rolling 24h** ledger
(5-minute buckets, keeping an extra boundary bucket). The 3,000 headroom is
reserved for operational uncertainty and calls made outside the metered app.
This is not a guarantee against traffic generated using the same key outside
BlinQ. Confirm the provider's actual billing reset and remaining allowance
before initial activation; start with a clean provider quota window.

| Purpose | Rolling allocation |
| --- | ---: |
| LIVE Radar | 2,500 |
| Hourly Match Status | 1,000 |
| Morning Refresh (including optional enrichment) | 750 |
| History, manual statistics and other enrichment | 7,750 |
| **Combined, hard** | **12,000** |

This allocation keeps the same 12,000 combined ceiling while giving the hourly Match Status worker enough room to operate during normal low-utilization days.\n
An API request is reserved before the paid upstream attempt, including retries.
Cancelled or timed-out calls are never refunded: a lost reservation is safer
than an uncounted billable request. For the initial rollout, all in-repository
paid workflows are instrumented. Other uses of the provider key (external
scripts, users' direct RapidAPI calls, or undocumented third-party jobs) cannot
be measured by the ledger.

## Production rollout (LIVE cron stays disabled until complete)

1. Wait for the shared-quota PR CI, including the fake concurrent reservation
   tests. Changes to paid GitHub workflows must **not** be merged before the
   matching backend API can be deployed in the same release window; otherwise
   paid data jobs intentionally fail closed.
2. Confirm `BLINQ_LIVE_WORKER_TOKEN` exists in BOTH GitHub Actions secrets and
   Azure Functions application settings. The existing working LIVE and Match
   worker tests established that it was configured previously.
3. Deploy the commit containing the shared quota endpoint. A normal CI
   `workflow_dispatch` on `main` runs checks **and** the Azure deploy;
   a regular push may skip deploy when `TBT_DEPLOY_ENABLED` is false.
4. Log in as an admin and inspect `GET /api/v1/admin/api-budget` (or the
   `api_budget` field in the existing admin diagnostics). Both require
   admin authentication. If the store is unavailable, stop the rollout.
5. Check actual RapidAPI remaining requests and planned concurrent ingestion;
   avoid initial activation until enough allowance remains for the 3,000
   reserve and the expected unmetered external usage.
6. Run **two isolated** LIVE workflow_dispatch tests on `main` while
   cron-job.org remains disabled. Verify all six scans, GitHub success, that
   the admin ledger increases by the expected number of upstream attempts,
   candidate odds caching, heartbeat persistence, and provider allowance.
   A quota pause is a deliberate no-spend result, not a successful live scan.
7. Only after those results match, enable a **single** external cron:
   `*/5 * * * *` (Europe/Bratislava). The workflow has its own concurrency
   guard. Keep native GitHub LIVE scheduling disabled. Match Status can remain
   on `30 * * * *` after its existing successful production check.
8. Inspect the first hour and first complete 24h. The Ops journal records
   global/purpose 80% and 95% threshold crossings. The admin diagnostics
   endpoint also exposes current spent and remaining counts.

## Failure and recovery

- Shared storage unavailable, missing budget credentials, or reservation API
  failure: **fail closed**, do not send paid provider requests.
- Budget exhausted: return a normal LIVE pause with
  `provider_skipped_reason=shared_budget_exhausted`, never invent signals.
  The heartbeat is marked stale; browsing must not trigger paid fallback scans
  during an intentional pause.
- A timeout after a reservation can overcount usage; do not automatically
  refund. A new five-minute/rolling window recovers credits naturally.
- The backend does not dynamically infer the provider billing reset from
  unverified headers. The initial shared ledger must be synchronized with
  current provider usage operationally.
- If you cannot verify that all callers of the provider key are instrumented,
  leave the LIVE cron disabled until the scope is reconciled.
