# BlinQ v7.2.6 — final product rules

## TOP daily dynamic fallback

CORE remains `P >= 68%` and decimal odds `>= 1.50`.
If fewer than five TOP selections remain after VALUE priority, BlinQ relaxes only as far as needed:

- 67% / 1.50
- 66% / 1.49
- 65% / 1.49
- 64% / 1.48
- 63% / 1.48
- 62% / 1.47
- 61% / 1.46
- 60% / 1.45

The process stops immediately at the first tier that yields at least five eligible TOP picks. It never relaxes below 60% / 1.45. Existing data-depth/surface/identity safeguards still apply. Fallback rows retain internal `selection_tier`, `fallback_step`, `fallback_min_probability` and `fallback_min_odds` audit fields.

## LIVE Radar

LIVE remains one product with two explicitly separate tabs/signals:

- Comeback — WATCH / CONFIRMED full-match comeback radar.
- 2. set — independent conditional `P(win set 2 | lost set 1)` support model.

A Set-2 browser push is created only when the model has medium/high quality, sufficient samples, a real live Set-2 price, positive edge and positive EV. Otherwise the projection can appear in the LIVE panel but no push is sent.

## Premium Info

Premium Info is a one-way chronological information channel. ELITE+ remains the default audience, but Admin can deliberately target ROOKIE, any selected levels, or ALL. LIVE automated messages remain ELITE+ server-side.

## ESA — Aces / Double Faults

ESA is consistently called a PROJECTION, not a prediction. Projection identity explicitly records scope and metric, for example:

- HRÁČ · ESÁ
- HRÁČ · DVOJCHYBY
- SPOLU ZÁPAS · ESÁ (reserved contract for total projections)
- SPOLU ZÁPAS · DVOJCHYBY (reserved contract for total projections)

The current model publishes PLAYER comparative ESA projections. Total-match scope is represented by the contract/UI but is not fabricated without an actual total projection/line definition.

From v7.2.6 onward, published ESA cards are frozen in the deployment publication ledger and settled against post-match provider statistics. Results show projection, actual count, HIT/MISS/VOID and DATA DEPTH. They do not invent odds, stake, units or ROI.

Historical ESA cards from an older deployment cannot be reconstructed as "published" unless their exact old feed/snapshot still exists; v7.2.6 starts the auditable archive prospectively.

## UI

- Final calmer topbar treatment: less boxed navigation, active underline, aligned compact controls.
- Results render projection-specific columns for ESA categories and omit ROI/units there.
- Set-2 detail wording explicitly states it is an independent support signal, not the Comeback signal itself.

## Validation

- Focused v7.2.6 / market / publication / detail suite: 45 PASS.
- Broad locally runnable suite excluding Azure-runtime and parquet-only files: 374 PASS.
- Python compileall: PASS.
- `node --check web/app.js`: PASS.
- Local environment does not contain Azure runtime packages or `pyarrow`; GitHub CI is expected to install repository requirements.
