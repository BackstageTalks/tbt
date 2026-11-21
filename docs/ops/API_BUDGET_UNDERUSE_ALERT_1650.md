# BlinQ — 16:50 RapidAPI underuse notice

Goal: exactly one admin information e-mail if the authenticated shared TennisAPI ledger has used strictly less than 75% of the 15,000 provider allowance at 16:50 Europe/Bratislava, i.e. fewer than 11,250 attempts. At 11,250 or above no mail.

## Execution
- Existing externally scheduled quarter-hour Match Status job dispatches the alert at its 16:45 local tick; the child workflow waits until 16:50 local. The 17:00 tick is a same-day catch-up before 17:06, deduplicated.
- No native GitHub cron, new external scheduler, paid tennis API calls, budget reservations, or CDB writes.
- GitHub workflow: .github/workflows/api-budget-underuse-notify.yml. Endpoint: POST /api/v1/internal/api-budget/underuse-alert, authenticated with the existing BLINQ_LIVE_WORKER_TOKEN.
- The worker reads the existing schema-2 canonical shared provider-day ledger. Verify 15,000 plan, 14,500 shared ceiling, 500 reserve, consistent spent/remaining values, and next reset 17:09 UTC on the same local date. Unknown usage fails closed instead of being interpreted as zero.
- Recipients are existing BLINQ_ADMIN_EMAILS / BLINQ_ADMIN_EMAIL. Delivery uses existing branded BlinQ SMTP, NOT general member Web Push subscriptions.
- Durable, atomic create-only daily claim in BlinQApiUnderuseAlerts prevents duplicate SMTP attempts. Uncertain SMTP outcomes are never retried automatically. Delivery success means accepted by SMTP, not independently proven inbox arrival.
- E-mail includes used calls, percentage, shared remaining headroom, and provider reset clock. It explicitly identifies the ledger as tracked BlinQ use; out-of-band key use remains unknown.

## Completion criteria
- CI: DST winter/summer, 16:50 boundary, strictly-less-than threshold, inconsistent-ledger rejection, SMTP read-back, duplicate suppression, external workflow integration.
- Merge and deploy exact Git revision; independent live deployment metadata read-back.
- Operational status VERIFIED only when an actual external 16:45/17:00 tick has been observed, and if a mail was due, SMTP claim and acceptance/readback are proven. Passing CI alone is not proof the next scheduled run happened.
- Keep all existing quota guards and other external jobs unchanged.

## Rollback
Disable the new Match Status dispatch step if unexpectedly noisy; retain the durable daily mail claims for auditing. No CDB/provider rollback is needed because the alert never writes to CDB or requests paid provider data.
