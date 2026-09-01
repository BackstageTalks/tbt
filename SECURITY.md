# Security notes

- Never commit RapidAPI, Supabase service-role, Azure publish-profile or Telegram secrets.
- `SUPABASE_SERVICE_ROLE_KEY` is server-only. It must never appear in browser JavaScript.
- The migration grants `anon` read access only to prediction/evaluation tables; history writes remain server-side.
- Protect manual operational endpoints with `TBT_ADMIN_API_KEY`.
- Rotate a secret immediately if its value is ever printed in a GitHub log or committed to history.
- Use Azure Function App environment variables for runtime secrets; GitHub Actions secrets alone do not configure the deployed runtime.
