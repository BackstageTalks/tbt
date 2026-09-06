# BlinQ web/admin deployment checklist

1. Deploy this repository version normally through the existing Azure Static Web Apps workflow.
2. Keep the existing Supabase settings (`SUPABASE_URL`, `SUPABASE_ANON_KEY`).
3. Server-side admin account management requires `SUPABASE_SERVICE_ROLE_KEY` in Azure runtime settings. Never expose it in `web/`.
4. Make at least one account ADMIN either through trusted `app_metadata.role=admin` or by setting `BLINQ_ADMIN_EMAILS` to a comma-separated list of admin emails.
5. Runtime UI config + banner analytics use `AzureWebJobsStorage` automatically. If a separate storage account is desired, set `BLINQ_ADMIN_STORAGE_CONNECTION_STRING`.
6. Sign in as ADMIN and open **Admin** in the left navigation.
7. Configure:
   - **Layout & slots** — access states, fixed 4-unit row presets, slot content, watermark.
   - **Campaigns** — advertisers and reusable advertising campaigns.
   - **RSS feeds** — normally 1–2 tennis RSS URLs.
   - **Plans** — price/display metadata and future payment links.
   - **Accounts** — manual plan/role/expiry assignment.
   - **Banner analytics** — impressions, uniques, clicks and CTR.
8. Use **Preview as Rookie/PRO/Elite/GOAT/Legend** before publishing access changes.
9. Publish the runtime config from Admin. Repository `web/ui-config.json` remains the safe fallback/default.

Current public plan defaults:
- ROOKIE: €5.99/month; automatic first 72 hours free.
- PRO: €14.99/month.
- ELITE: €99/year.
- GOAT: €199 lifetime.
- LEGEND: hidden/disabled reserve.
- ADMIN: separate role, not a plan.
