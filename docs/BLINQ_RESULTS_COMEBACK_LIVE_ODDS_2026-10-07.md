# Results comeback + LIVE max odds

Release note for 2026-10-07.

- Results player names wrap instead of truncating with ellipsis.
- Short Odds wins where the predicted player lost set 1 show a compact orange comeback icon.
- Missing player portraits keep a deterministic ATP/WTA fallback layer, including ITF women event detection.
- LIVE Radar reuses its already-budgeted provider odds payload for the current Match Winner price after a first-set loss.
- The highest observed LIVE price is persisted as display/research evidence and carried into settled Results as an inline `MAX x.xx` value when it exceeds the immutable published pre-match price.
- ROI, units, model selection and training data continue to use the original published pre-match odds.
- No additional provider request is introduced by the LIVE max-odds tracking path.
