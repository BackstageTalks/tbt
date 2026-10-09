# Shared Tennis RapidAPI quota — rollout

## Capacity and scope

The provider plan is treated as **15,000 requests per provider billing day**.
BlinQ enforces a fail-closed **14,550 request global ceiling** and permanently
keeps **450 requests (3%)** as provider headroom.

The durable ledger is aligned to the verified provider-day reset used by the
runtime guard: **19:10 Europe/Bratislava**. Usage is stored in five-minute
buckets, but the accounting window is the current provider day, not a generic
rolling 24-hour window.

| Purpose | Provider-day allocation |
| --- | ---: |
| LIVE Radar | 3,000 |
| Match Status | 2,500 |
| Refresh (including presentation enrichment) | 5,500 |
| History/backfill opportunistic ceiling | 14,550 |
| **Combined, hard** | **14,550** |
| **Provider reserve kept untouched** | **450** |
| **Provider plan** | **15,000** |

LIVE, Match Status and Refresh retain bounded purpose allocations. History/backfill
may opportunistically use any provider-day headroom left by those workloads, up to
the same 14,250 global ceiling. The global ceiling is always authoritative, so the
450 provider reserve remains untouched.

An API request is reserved **before every billable upstream attempt, including
retries**. Cancelled, timed-out or ambiguous requests are never refunded:
overcounting one uncertain request is safer than allowing an uncounted paid
request.

The ledger protects only callers instrumented through the BlinQ shared budget
guard. Direct/manual use of the same RapidAPI key outside BlinQ is not visible to
this ledger, which is why the 450-request provider reserve remains mandatory.

## Runtime source of truth

The authoritative values live in
`api/tbt/providers/shared_budget.py`:

- `PROVIDER_PLAN_LIMIT = 15000`
- `PROVIDER_RESERVE = 450`
- `GLOBAL_CEILING = 14550`
- reset: `19:10 Europe/Bratislava`
- `PURPOSE_CAPS = {live: 3000, match: 2500, refresh: 5500, history: 14250}`
  (`history` is opportunistic; the shared 14,250 global ceiling still applies)

CI contains a documentation contract test so future edits must keep this file
synchronized with those runtime constants.

## Production operation

1. Confirm `BLINQ_LIVE_WORKER_TOKEN` exists in both GitHub Actions secrets and
   Azure Functions application settings.
2. Admin diagnostics must be able to read the shared budget store. If storage is
   unavailable or unreadable, paid callers intentionally fail closed.
3. Before enabling or changing a paid scheduler, inspect both the BlinQ ledger
   and the provider's own remaining allowance. The BlinQ ledger cannot account
   for out-of-band key usage.
4. Match Status currently uses the **match** allocation and is triggered by the
   external scheduler at its configured cadence. LIVE Radar uses the **live**
   allocation.
5. Refresh jobs use the **refresh** allocation. History/statistics/autofill jobs
   use the **history** class, which can consume otherwise-unused global headroom
   but can never exceed the 14,250 global ceiling.
6. The Ops journal records 80% and 95% threshold crossings for both the global
   budget and the active purpose cap.

## Failure and recovery

- Shared storage unavailable, missing budget credentials, malformed ledger or
  reservation API failure: **fail closed**, do not send paid provider requests.
- Purpose cap or global ceiling exhausted: stop the paid workload and preserve
  the last verified production state.
- A timeout after reservation may overcount usage. Do not automatically refund.
- The next provider day starts at **19:10 Europe/Bratislava** and old buckets are
  excluded automatically.
- If an external/manual caller uses the provider key outside the shared guard,
  its requests are not visible to BlinQ. Keep the provider reserve intact and
  reconcile against the provider dashboard when investigating quota mismatch.
