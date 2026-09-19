# BlinQ 7.3.6-r8 — autonomous LIVE Comeback worker

## What changed
- Added a secret-protected server endpoint: `POST /api/v1/internal/live-radar-worker`.
- Added `.github/workflows/live-radar.yml`: GitHub starts it every 5 minutes; each run performs 6 scans spaced by 50 seconds.
- The browser is no longer the production scheduler. `/api/v1/live-radar` reads the fresh persisted worker snapshot and only falls back to an on-demand cached scan if the worker heartbeat is stale.
- Worker heartbeat/candidate/signal counts are persisted in the existing admin storage and shown in **Admin → System → LIVE WORKER**.
- Admin accounts already have operational LIVE access. Admin browser-push subscriptions are stored as GOAT/lifetime operational subscriptions, so automated ELITE+ LIVE alerts are also delivered to subscribed admin devices.

## One-time production settings
Use the same long random value in both places:
1. Azure Static Web App / API app setting: `BLINQ_LIVE_WORKER_TOKEN`
2. GitHub Actions secret: `BLINQ_LIVE_WORKER_TOKEN`

Also set GitHub Actions variable `TBT_LIVE_RADAR_ENABLED=true`.
Optional: `BLINQ_PUBLIC_BASE_URL` if a custom production domain should be used instead of the current Azure Static Web Apps hostname.

## Scan cadence
GitHub cron has a minimum 5-minute cadence, so one scheduled job stays alive for ~4m10s and calls the protected worker six times at 50-second intervals. The next scheduled run continues the cycle. No browser needs to be open.
