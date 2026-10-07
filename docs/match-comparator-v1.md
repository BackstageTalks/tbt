# BlinQ Match Comparator V1

## Product contract

V1 compares two canonical singles players on **today's pre-match information state**.

Inputs:
- tour: ATP or WTA
- player A
- player B
- surface: hard, clay, grass, indoor hard
- match format: BO3, plus BO5 for ATP

Outputs:
- predicted winner
- player win probabilities and model-implied fair odds
- data-confidence band
- key comparison statistics (overall/surface Elo, sample sizes, recent form, serve/return quality)
- up to five strongest directional factors
- model version and point-in-time cutoff

Historical-date simulation is deliberately not part of V1. It may only be enabled after a replay/snapshot store can prove that every feature existed before the selected historical cutoff.

## Safety and leakage rules

The comparator uses the same conservative production convention as Match Winner prediction:
1. current comparison time is converted to UTC;
2. the cutoff is start of the current UTC day;
3. only canonical completed matches strictly before that cutoff are replayed;
4. canonical history passes the existing history audit;
5. historical ranks without explicit point-in-time provenance are stripped;
6. the synthetic comparison is snapshotted only after replay is complete;
7. the synthetic matchup is never written to canonical history.

Player identity is fail-closed. Names are normalized only for lookup. A missing name returns not-found; a normalized name mapping to more than one canonical player returns ambiguous. No fuzzy guess is promoted to a canonical ID.

## API budget

A comparison itself performs **zero external provider requests**.

The target serving path is:

```
canonical history + current champion + verified priors
              |
              v
scheduled comparator snapshot/build
              |
              v
read-only serving artifact/cache
              |
              v
user comparison request
```

User traffic must never call RapidAPI directly. Current ranking/odds/weather may be added later only through scheduled shared refreshes and persisted point-in-time snapshots.

## Runtime constraint

The public Azure Functions runtime intentionally excludes pandas/scikit-learn/pyarrow. V1 core therefore lives in the offline/model stack and must not be imported eagerly by `function_app.py`.

Before public activation, serving must use one of these governed approaches:
- a compact verified serving artifact evaluated without the training stack, or
- a separately deployed inference service with an explicit resource/cold-start budget.

Adding the entire training dependency set to the existing public API is not an acceptable shortcut.

## Data confidence

Initial confidence thresholds:
- HIGH: both players >=25 historical matches and >=10 on selected surface
- MEDIUM: both players >=10 historical matches and >=4 on selected surface
- LOW: otherwise

This is a **data confidence** indicator, separate from model probability. A high model probability does not imply high data confidence.

## V1 acceptance gates

Backend:
- canonical-history-only identity directory
- unknown identity fail-closed
- ambiguous identity fail-closed
- same-player comparison rejected
- unsupported tour/surface/format rejected
- current-UTC-day leakage guard
- no provider client imported/called by comparator core
- orientation/symmetry regression test
- finite probability and fair odds
- model version and cutoff exposed in result

Serving:
- request path is read-only
- 0 provider requests per comparison
- rate limiting and short result cache
- comparator artifact/model version coherence check
- stale artifact is visible to UI and fails closed beyond the agreed freshness limit
- no canonical writer introduced

Frontend:
- two player searches with canonical selection IDs
- tour + surface + format controls
- winner/probability/fair-odds result
- confidence + sample-size disclosure
- factor explanation
- clear unavailable/ambiguous/insufficient-data states
- mobile layout and keyboard accessibility
- no historical-date selector until the historical replay gate is implemented

## Production rollout

1. merge the core only after CI succeeds;
2. build and verify a serving-artifact path without changing the champion model;
3. add protected API endpoints and caching;
4. add UI behind a disabled feature flag;
5. run smoke tests against the deployed artifact;
6. enable the feature flag.

No production model promotion is part of Match Comparator V1.

## Integration revalidation

Before merge, the pull request must be revalidated against the current main branch. Merge only when the current pull-request merge build is green; the independent WTA rank-history source audit is not a Match Comparator acceptance gate.
