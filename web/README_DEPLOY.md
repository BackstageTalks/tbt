# BlinQ real dashboard update

This package is a drop-in update for the existing BlinQ/TBT dashboard.

## Frontend files

Replace the current web files with:

- `index.html`
- `styles.css`
- `app.js`
- `config.js`
- `ui-config.json`

The frontend first calls:

`GET /api/v1/predictions/upcoming?days=3`

and falls back to:

`GET /api/blinq/predictions?days=3`

No RapidAPI call is triggered by page traffic; the UI reads precomputed TBT predictions.

## Backend contract change

Replace:

`api/tbt/services/contracts.py`

with the supplied `api/tbt/services/contracts.py`.

The only new public data is the already-computed numeric `features` dictionary stored with each prediction, plus rank/round/generated metadata in the flat compatibility response.

The UI uses those features for the six visual bars:

- Overall Strength -> `elo_diff`
- Surface Strength -> `surface_elo_diff` + `surface_form_diff`
- Recent Form -> `recent_form_diff` + `opponent_adjusted_form_diff`
- Head-to-Head -> `h2h_advantage`
- Rest / Workload -> `rest_advantage`, `layoff_advantage`, `fatigue_3d_advantage`, `fatigue_7d_advantage`
- Data Depth -> `data_depth`

Bars are normalized display indicators from the predicted winner's perspective. They are intentionally **not** labelled as probabilities, bookmaker edge, market odds, or externally supplied Elo.

## Tests

The package also includes an updated contract test:

`api/tests/test_contracts.py`

Run in the repository root:

```bash
python -m compileall -q api
PYTHONPATH=api pytest -q api/tests/test_contracts.py
```

For the frontend JavaScript, `node --check app.js` can be used when Node.js is available.

## Ads

Both ad placements are controlled in `ui-config.json`:

- `banners.home_banner_top` — wide sponsored banner below filters
- `ads.lower_right` — small lower-right ad card

They can be disabled with `"enabled": false` or have their copy/link changed without touching `app.js`.


## Dashboard without preview login

`config.js` now uses `authMode: "none"`, so the predictions dashboard opens immediately. The login markup remains available for later production authentication but is hidden by default.
