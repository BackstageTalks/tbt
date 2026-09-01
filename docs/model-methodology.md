# TBT v200 methodology

## Objective

The model predicts the pre-match probability that either player wins a singles tennis match. The primary optimisation target is **probability quality**, not raw pick count: log loss, Brier score and calibration are first-class metrics, with accuracy and ROC-AUC reported alongside them.

## Leakage controls

TBT v200 is deliberately conservative about time:

1. Player features are snapshotted before the match result updates any state.
2. Historical matches on the same calendar date are snapshotted as a batch before any result from that date is applied. This avoids accidental leakage when the provider only exposes date-level timestamps.
3. Historical provider data can be winner-first. TBT therefore assigns training orientation from a stable hash of the canonical match ID. The target is computed *after* that orientation. Without this step a winner-first archive can produce a useless model with apparently perfect accuracy.
4. Missing historical rankings/stats remain missing/neutral. Current rankings are never copied backwards into old matches.
5. Train/calibration/test splits are chronological. Backtesting is walk-forward by calendar year.

## Feature families

- overall Elo, maintained independently within ATP/WTA IDs;
- partially-pooled surface Elo (hard/clay/grass/indoor hard/etc.);
- short- and medium-horizon exponentially decayed form;
- opponent-adjusted form (actual result minus pre-match Elo expectation);
- surface-specific recent form;
- ranking advantage when point-in-time rankings exist;
- experience / data depth;
- rest and long-layoff effects;
- H2H with a Beta prior so tiny samples are strongly shrunk;
- optional serve and return quality if historical per-match stats are present;
- match context: tour, event level, best-of-five, indoor/outdoor.

## Ensemble and calibration

Two deliberately different models are fitted:

- regularised logistic regression for stability and extrapolation;
- histogram gradient boosting for interactions/non-linearity.

The blend weight is selected on later calibration data, never on training data. Probability calibration is selected out-of-time between identity, Platt scaling and (when enough calibration rows exist) isotonic regression. Inference is symmetrised so `P(A beats B) = 1 - P(B beats A)`.

## Evaluation

The production training command creates an untouched chronological holdout report. The backtest command then trains only on years before each test year and concatenates those truly out-of-time predictions.

Reported metrics include:

- log loss (primary; lower is better),
- Brier score (lower is better),
- expected calibration error,
- calibration bins,
- accuracy,
- ROC-AUC,
- subgroup metrics by ATP/WTA and surface,
- direct comparison with the internal Elo baseline.

Market odds are intentionally not part of the pure model. If bookmaker odds are added later, keep a separate `TBT Market+` experiment so the project can distinguish genuine tennis signal from simply copying the market.
