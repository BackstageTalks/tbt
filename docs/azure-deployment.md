# Azure / GitHub deployment

## Secrets already recognised from the current setup

- `AZURE_STATIC_WEB_APPS_API_TOKEN_AGREEABLE_SKY_011A7FE10`
- `BLINQ_FUNCTION_PUBLISH_PROFILE`
- `RAPIDAPI_KEY`
- `SUPABASE_ANON_KEY`
- `SUPABASE_URL`
- `TGBOT` (optional Telegram alerts)
- `TGCHID` (optional Telegram alerts)

## Add these two production secrets

- `SUPABASE_SERVICE_ROLE_KEY` — server-only key for secure history/model writes. Do not put it in the frontend.
- `TBT_ADMIN_API_KEY` — random long string protecting the manual refresh endpoint.

The existing anon key remains useful for read-only access. The SQL migration intentionally does not grant anonymous writes.

## First deployment

1. Run `supabase/migrations/001_init.sql` in Supabase SQL Editor.
2. Add the two secrets above in GitHub Actions secrets.
3. Push this repository to `main`. CI and deployment workflows will run.
4. In GitHub Actions, manually run **Bootstrap tennis history**. Start with 2020 or 2021 for a quick first model; later extend backwards to 2018 if the provider plan has the history.
5. Run **Retrain, backtest and deploy** manually. It creates `api/artifacts/model.joblib`, evaluates it, then publishes the exact tested artifact to the Function App.
6. Open `/api/health`; `model_artifact_present` and `secure_server_writes_configured` should both be `true`.
7. Point Blinq to `/api/blinq/predictions` on the Function App.

## Function App settings

GitHub secrets are available to Actions, but they are **not automatically application settings inside Azure Functions**. Ensure these are also set in the Function App Configuration / Environment Variables:

`RAPIDAPI_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `TBT_ADMIN_API_KEY`, and optionally `TGBOT`, `TGCHID`.

`RAPIDAPI_HOST` defaults to `tennis-api-atp-wta-itf.p.rapidapi.com`. If your current RapidAPI subscription is a different tennis product, set `RAPIDAPI_HOST` and `RAPIDAPI_BASE_URL` accordingly.
