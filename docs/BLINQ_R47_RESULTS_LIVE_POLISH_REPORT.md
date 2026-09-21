# BlinQ 7.3.6 / 736-r47 — Results + LIVE polish

## Scope

r47 is a focused close-out of the visual/results/INFO-LIVE batch built on the CI-green r46 baseline.

### Results
- Projection-only result categories (Aces, Double Faults, Sets, Games and combined Sets & Games) use the same clean projection layout.
- Games retain a human-readable Over/Under + model reference line instead of the old `High Total Games` / `Low Total Games` copy.
- Projection and settled values now carry their unit (`Aces`, `Dvojchyby`, `Sety`, `Games`) so bare numbers are not ambiguous.
- Aces/Double Faults actuals keep the opponent comparison because those current models are player-vs-player projection models; no bookmaker O/U line is invented.
- Projection-only result summaries no longer show meaningless odds/ROI cards.

### Background + watermarking
- The login background family remains shared by the normal site and loading splash.
- Three subtle fixed BlinQ watermarks remain enabled outside Admin; they are pointer-events none and reduced further on mobile.

### INFO audience
- `VŠETCI` remains a literal all-level audience (ROOKIE/FREE, PRO, ELITE, LEGEND, GOAT).
- LIVE keeps its separate minimum-level authorization gate.

### Set 2 LIVE
- The existing conditional Set-2 model is kept fail-closed: historical conditional probability is panel-only until a real provider Set-2 price exists; durable Set-2 signal/push additionally requires the configured evidence/value thresholds.
- Public LIVE radar payload now reports Set-2 candidate, priced and eligible counts plus the threshold contract.
- User LIVE drawer shows a Set-2 health strip.
- Admin LIVE status now uses the canonical `prime_eligible / prime_total` fields and shows Set-2 priced/value counts.

### FREE / account copy
- Internal plan id remains `rookie`; public label remains `FREE`.
- FREE is offered to an EXPIRED member as the recovery path, while active paid members are not shown a downgrade CTA.
- Account membership cards use the Admin detailed description; the separate upgrade/membership presentation retains the internal note as its benefits heading (e.g. `Obsahuje:`).
