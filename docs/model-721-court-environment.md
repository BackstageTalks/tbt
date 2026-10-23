# Court speed and environment: isolated experiment protocol

Goal: improve paired winner accuracy; no odds/EV. Do not change running ATP/WTA study or activate a candidate based on this preparation.

## Current verified engineering changes
CourtSpeedHistory now snapshots an entire UTC day before applying its results. Match start time does not prove completion of an earlier event. Tour-specific surface baselines and player keys isolate ATP from WTA. Eight court-speed and ablation tests passed. Existing proxy is NOT the Tennis Abstract opponent-adjusted ace metric and must not be labelled as such.

## External source
scripts/capture_court_speed_source.py captures the supplied Tennis Abstract ATP page, raw HTML plus SHA and observed availability time. Current page is not eligible for historical backfill; event date/displayed update date alone is not proof of historical availability. Parser/verified venue identity mapping remain required before model use. ATP speed data are not automatically WTA measurements. Preserve source snapshots; do not infer unknown aliases.

## Environment
Existing code includes static venue altitude/indoor/travel and a pinned previous-day forecast loader. Loader checks SHA, schema, lead and reference but actual forecast issuance/availability, event alignment, coverage and training eligibility must be audited before weather is enabled. Reanalysis/observed weather is not a pre-match forecast. The champion excludes historical weather inputs; do not change this exclusion silently.

## Fixed experiment arms
Use the same governed frozen inputs and temporal train/calibration/selection/test splits as the ATP/WTA study. Arms: unchanged baseline; corrected historical speed proxy; verified environment; both. Interactions: speed with serve/return strength; altitude with serve profile; weather only for outdoor fixtures with verified pre-match availability. Missing data remain explicit. Do not double-count reported speed and its weather components without paired ablation. Keep production artifacts unchanged.

Report paired accuracy, LL/Brier, tour/surface/competition/data-coverage segments and sample counts. Historical Tennis Abstract snapshots are only eligible if availability predates the prediction; today's snapshot supports future research only. Require fresh prospective evidence before promotion. No new fit has been launched for this experiment yet.
