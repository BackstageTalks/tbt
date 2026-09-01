# TBT v200

Production-oriented tennis prediction stack for **Blinq + Azure**.

The repository is built around one rule: a probability is useful only if it survives a strict out-of-time test. TBT v200 therefore treats data leakage, winner-first provider ordering, calibration and reproducibility as core engineering problems rather than afterthoughts.

## What is included

- Azure Functions prediction API with a stable Blinq compatibility endpoint.
- RapidAPI tennis ingestion with request throttling/retries and ATP/WTA normalisation.
- Supabase schema for historical matches, model versions, predictions and backtests.
- Point-in-time feature engine with overall/surface Elo, decayed form, opponent-adjusted form, H2H shrinkage, rest/layoff, ranking and optional serve/return statistics.
- Regularised logistic + gradient-boosting ensemble.
- Out-of-time probability calibration and symmetric inference.
- Chronological holdout evaluation plus yearly walk-forward backtesting.
- Precomputed predictions so frontend traffic does not burn the upstream API quota.
- GitHub Actions for CI, history bootstrap, model retraining/backtesting and Azure deployment.
- Optional static `web/` Blinq-style dashboard.
- Telegram failure notifications using the existing `TGBOT` / `TGCHID` secrets.

## Repository layout

```text
api/
  function_app.py              Azure Functions entry point
  tbt/
    models/                    feature engine, Elo, ensemble, metrics, artifact
    providers/                 RapidAPI adapter
    repositories/              Supabase/PostgREST persistence
    services/                  training, backtest, inference, sync, contracts
scripts/                       bootstrap/train/backtest/manual refresh tools
supabase/migrations/           database schema + RLS
web/                           optional Blinq-style static dashboard
tests/                         leakage, provider, model-contract and metric tests
docs/                          methodology, architecture, deployment, Blinq contract
.github/workflows/             CI + Azure deployment + model lifecycle
```

## Existing secrets used

The workflows recognise the secret names already present in the current repository:

```text
AZURE_STATIC_WEB_APPS_API_TOKEN_AGREEABLE_SKY_011A7FE10
BLINQ_FUNCTION_PUBLISH_PROFILE
RAPIDAPI_KEY
SUPABASE_ANON_KEY
SUPABASE_URL
TGBOT
TGCHID
```

### Add two production secrets

```text
SUPABASE_SERVICE_ROLE_KEY
TBT_ADMIN_API_KEY
```

`SUPABASE_SERVICE_ROLE_KEY` is required because the database migration intentionally does **not** allow anonymous writes. The service-role key must only exist in GitHub/Azure server configuration, never in `web/`.

`TBT_ADMIN_API_KEY` should be a long random value and protects `POST /api/v1/admin/refresh`.

> GitHub Actions secrets and Azure Function App environment variables are separate. Add the runtime secrets to the Function App Configuration as well. See `docs/azure-deployment.md`.

## First production bootstrap

### 1. Database

Run:

```text
supabase/migrations/001_init.sql
```

in the Supabase SQL Editor.

### 2. Push the repo

Push to `main`. The API and static web workflows use the two Azure secrets already shown above. The Function App name is derived from the publish-profile XML, so an additional app-name secret is not required.

### 3. Historical tennis data

Run the GitHub workflow **Bootstrap tennis history** manually.

A practical first run is 2021 → current year. Once the first model is live, extend back to 2018 if the RapidAPI plan exposes that history.

The adapter defaults to:

```text
RAPIDAPI_HOST=tennis-api-atp-wta-itf.p.rapidapi.com
RAPIDAPI_BASE_URL=https://tennis-api-atp-wta-itf.p.rapidapi.com
```

If the existing RapidAPI subscription uses another Tennis API host/product, override those settings in Azure/GitHub. If its JSON schema differs materially, only `api/tbt/providers/rapidapi.py` needs a provider-specific mapper; the statistical pipeline stays unchanged.

### 4. Train + backtest + deploy

Run **Retrain, backtest and deploy** manually.

The workflow:

1. runs unit tests;
2. trains a model from Supabase history;
3. creates a chronological untouched holdout report;
4. runs yearly walk-forward backtesting;
5. uploads the reports as a GitHub Actions artifact;
6. deploys the exact tested `model.joblib` together with the Azure Function App.

No synthetic/fake production model is shipped in this repository. Until real historical data has been trained, `/api/health` deliberately reports that the model artifact is absent instead of publishing invented predictions.

## API

### Health

```http
GET /api/health
```

### Rich upcoming predictions

```http
GET /api/v1/predictions/upcoming?days=3
GET /api/v1/predictions/upcoming?days=3&tour=atp
```

### Blinq compatibility endpoint

```http
GET /api/blinq/predictions?days=3
```

This is the endpoint intended to replace Thinq/Corq as Blinq's data source. Keep UI-specific field-name changes inside `api/tbt/services/contracts.py` rather than changing the model.

### Latest model and backtest

```http
GET /api/v1/model/status
GET /api/v1/backtest/latest
```

### Manual prediction refresh

```http
POST /api/v1/admin/refresh
x-admin-key: <TBT_ADMIN_API_KEY>
```

## Model quality controls

The project explicitly protects against several common ways sports models accidentally look better than they are:

- historical provider archives that always put the winner in `player1`;
- random train/test splitting across time;
- same-day result leakage when only a date is known;
- current ranking values copied into historical rows;
- tiny H2H samples treated as strong evidence;
- uncalibrated confidence percentages;
- evaluating a model on the same data used to select/calibrate it.

Read `docs/model-methodology.md` for details.

## Operational schedule

- Azure timer: refresh upcoming predictions every 30 minutes.
- Azure timer: reconcile current-year completed results daily.
- GitHub Actions: retrain, backtest and deploy weekly, plus manual runs at any time.
- Blinq: reads precomputed predictions from Supabase through Azure Functions; page traffic does not trigger a RapidAPI call.

## Local commands

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
pip install -r api/requirements.txt pytest

# env vars must be set first
python scripts/bootstrap_history.py --start-year 2021
python scripts/train.py
python scripts/backtest.py
python scripts/refresh_predictions.py

PYTHONPATH=api pytest
```

## Acceptance criteria before calling a model "production"

Do not judge a version by accuracy alone. At minimum inspect:

- holdout and walk-forward log loss;
- Brier score;
- calibration bins / ECE;
- accuracy and ROC-AUC;
- ATP vs WTA performance;
- hard/clay/grass subgroups;
- delta against the internal Elo baseline;
- sample count in high-confidence predictions.

If a more complex version cannot improve out-of-time probability metrics reliably, keep the simpler model.
