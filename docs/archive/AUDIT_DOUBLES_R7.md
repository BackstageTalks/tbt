# BlinQ 7.3.6-r7 — Doubles v1

## Scope

Adds a real, isolated doubles pipeline. Doubles does **not** reuse the singles model.

### Provider / data
- Adds `RapidTennisClient.doubles_for_day()` and `doubles_upcoming()`.
- Keeps ATP/WTA doubles separate from canonical singles history.
- Mixed doubles stays fail-closed for now because it needs its own calibration.
- Uses stable provider team IDs plus explicit member arrays when available.

### Separate doubles history
- New release: `tbt-doubles-data-v1`.
- New workflow mode: `doubles-data`.
- New script: `scripts/enrich_doubles_history.py`.
- Backfill resumes backwards from the oldest stored doubles date instead of re-spending quota on the same newest dates.

### Doubles model
- `DOUBLES-ELO-v1` is a separate pair/member/surface Elo model.
- Activation gate: minimum historical doubles volume + >=90% member-identity coverage.
- Candidate requires pair/member history and data-depth thresholds.
- A pick is published only when a real provider Match Winner price exists and probability/price/EV guardrails pass.
- No market price is used to create the model probability; odds are attached only after the model signal exists.

### Publication / Results
- Doubles rows join the immutable publication ledger only after selection.
- Doubles Match Winner publications are confirmed only after successful deploy.
- Settlement uses the actual completed doubles event and team identity.
- Results/ROI use the `doubles` section already supported by the unified Results ledger.
- Singles accuracy/calibration metrics explicitly exclude doubles rows.

### Presentation
- Existing DOUBLES tab and SEE ALL integration are used.
- Player-card enrichment now includes doubles member IDs so member photos/profile metadata can be cached where available.

## One-time activation run
After deploying this repo, run:

- Workflow: `Tennis data and predictions`
- mode: `doubles-data`
- lookback_days: `365`
- max_requests: `10000`
- start/end: blank

The run is resumable. If the quota ends before the 365-day window is complete, run the same mode again; it continues older than the oldest stored doubles day.

After the history gate is ready, normal `refresh` automatically:
1. updates the latest 7 days of doubles results,
2. discovers upcoming doubles,
3. builds `DOUBLES-ELO-v1` probabilities,
4. requests current Match Winner odds for up to `doubles_odds_max_events` (default 40),
5. publishes qualifying doubles picks,
6. settles them into Results after completion.

## Validation
- Python compileall: PASS
- `web/app.js` syntax: PASS
- workflow YAML parse: PASS
- focused regression suite: 46/46 PASS
- broader local suite excluding Azure smoke: 509 PASS, 1 skipped; 8 local failures are only missing `pyarrow` parquet support in this container.
