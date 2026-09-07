# BlinQ / TBT — Decisions, Backlog and Engineering Log

> Living project record. This file is the working source for a later complete technical documentation of BlinQ/TBT.
>
> **Update rule:** every meaningful implementation, architecture decision, data-source discovery, production incident, validation result, UI/content decision and open hypothesis should be appended here while the work is being done. Do not rewrite history just because the implementation later changes; mark old decisions as superseded and link the replacement.

Last updated: **2026-09-07**
Current working line: **v5.x**

---

## 1. Project principles / non-negotiables

1. Real data first. Do not fabricate odds, scores, rankings, Aces/DF, environment, photos, market lines or settlement.
2. Prediction accuracy, calibration and out-of-time validation have priority over visual polish.
3. Never weaken identity/ledger/publication safeguards merely to make a workflow pass.
4. Historical point-in-time correctness matters. Current ranking or post-match data must not silently leak into historical model training.
5. Optional/presentation enrichment must fail soft and must not alter the immutable prediction commitment.
6. Provider request budgets are treated as scarce resources. Prefer caching, targeted enrichment and reusable aggregates.
7. Admin is an internal role, not a paid subscription tier.
8. Singles and future doubles models are separate modelling problems and must not be mixed without explicit validation.

---

## 2. Current production architecture

### Backend

- Azure Functions API.
- Supabase for auth and persisted application data.
- RapidAPI TennisApi PRO as the primary tennis provider.
- Precomputed prediction feeds; browser traffic must not burn provider quota.
- GitHub Actions for refresh, enrichment, training/backtests and deployment.

### Private/release data

- `tbt-data-v1` — canonical/history data and related enrichment state.
- `tbt-predictions-v1` — immutable prediction/publication candidate and ledger-related feed data.
- `tbt-player-assets-v1` — presentation-only player profiles/photos/report.

### Public serving

- `/api/v1/feed`
- legacy/compatibility prediction endpoint retained where required.
- Static BlinQ web dashboard served with the API snapshot.

---

## 3. Provider flow and confirmed endpoints

### Daily event discovery

Confirmed flow:

1. `GET /api/tennis/calendar/{day}/{month}/{year}/categories`
2. For each active category: `GET /api/tennis/category/{id}/events/{day}/{month}/{year}`

The retired flat `/api/tennis/events/{day}/{month}/{year}` endpoint must not be used.

Known category IDs:

- ATP: `3`
- WTA: `6`
- Challenger: `72`
- ITF Women: `213`
- ITF Men: `785`
- WTA 125: `871`
- Grand Slam: `-100`

Qualifying is represented as a round, not a separate category.

### Player/team enrichment already used or confirmed

- current ATP/WTA ranking snapshots
- player ranking endpoint
- previous player matches
- player image endpoint
- event details

### Post-match event statistics

`GET /api/tennis/event/{event_id}/statistics`

Known useful fields include:

- Aces
- double faults
- first/second serve data
- break-point data

Coverage is event-dependent; a 204 can legitimately mean no statistics.

### Pre-match odds

Primary provider flow:

`GET /api/tennis/event/{event_id}/odds/1/all`

Provider `1` is the main/default source for our current use. Other provider IDs frequently return 204 and are not treated as required coverage.

Confirmed useful pre-match markets:

- Full time / Match Winner
- First set winner
- Total games won
- Tie break in match

Useful odds fields:

- `initialFractionalValue` ≈ opening value in the available snapshot
- `fractionalValue` ≈ current value in the available snapshot
- `change` = direction versus that opening snapshot
- `choiceGroup` on Total Games = the market line, e.g. 22.5 / 40.5

Important limitations:

- First set / totals / tie-break are not guaranteed on every event.
- No provider-side full tick history / 24h / 12h / 6h / 2h / closing tape.
- No reliable multi-bookmaker mapping in TennisApi PRO.
- If CLV is required, capture our own snapshots near match start.

---

## 4. Match Winner / market layer — implemented

The Match Winner model probability remains the probability source. Market enrichment does **not** create a new model probability.

Current market process:

- fetch provider-1 pre-match odds for selected upcoming candidates;
- parse Match Winner only for the currently deployed selector;
- require both sides;
- convert odds to raw implied probability;
- de-vig both sides;
- compare the model-selected side against fair implied probability;
- store selected odds, fair implied probability, model probability, edge and expected value.

### Top Daily

- max 10 picks;
- current betting day only;
- quality/data-depth guardrails;
- sorted primarily by expected value and prediction strength.

### Value

- odds threshold above 1.70;
- positive edge required;
- de-vig implied-probability sanity bound;
- ranked by edge / EV / model confidence.

### Latest confirmed live state (2026-09-07)

Successful refresh produced approximately:

- 618 upcoming matches
- Top Daily: 10
- Value: 7
- odds candidates: 85
- odds available: 50
- odds unavailable: 35
- provider errors: 0
- odds coverage: ~58.8%

Publication/deployment confirmation succeeded after the v5.7 fix.

---

## 5. Results / publication ledger — implemented

Results distinguish:

- prediction publication;
- betting pick publication;
- settlement.

A betting pick is settleable only if it was actually deployed before match start.

Current result views include category/time/tour/surface filtering and standard W-L / hit rate / odds / ROI / units metrics. Legacy predictions without valid odds keep ROI unavailable rather than inventing a value.

Flat unit convention:

- win: `odds - 1`
- loss: `-1`

The same underlying pick may appear in category views but must not be double-counted in overall ROI.

---

## 6. Player presentation enrichment — implemented

Player enrichment is presentation-only and must never change prediction identity/probability.

Current pipeline:

1. collect player IDs from current BlinQ feed;
2. fetch ATP/WTA ranking snapshots first;
3. use per-player ranking fallback only where needed;
4. fetch/cache player images;
5. persist player assets privately;
6. attach rank/country/photo to the serving snapshot.

Latest successful player enrichment cached roughly 727 player profiles/photos. The exact number attached to an individual serving snapshot can be lower because only current-feed players are materialized.

### Fallback assets

User-owned assets are linked by filename and are not embedded/recreated by code.

- male player fallback: `missing_foto_m.png`
- female player fallback: `missing_foto_w.png`
- favicon: `blinq_favi.png`
- background: `blinq_background.png`

Plan/avatar assets:

- Rookie: `rookie_m.webp`, `rookie_w.webp`
- PRO: `pro_m.webp`, `pro_w.webp`
- Elite: `elite_m.webp`, `elite_w.webp`
- Legend: `legend_m.webp`, `legend_w.webp`
- GOAT: `goat.webp`

Rule: real player photo wins; fallback only if real photo is missing; initials are the last resort.

---

## 7. Aces / Double Faults — current work

### Implemented direction

Ace/DF predictions are currently **projection-only**, not bookmaker-odds-backed.

Historical source:

`/api/tennis/event/{event_id}/statistics`

Current Ace enrichment workflow mode:

`ace-statistics`

Current run started on 2026-09-07 with:

- `max_requests = 3000`
- `ace_target_samples = 18`
- `ace_lookback_days = 550`

Status at last update: **RUNNING / result not yet confirmed**.

Do not claim Ace coverage or successful enrichment until the run log confirms it.

### ACE optimisation hypothesis — OPEN

RapidAPI UI exposes `getTeamYearStatistics(id, year)` and the response observed on 2026-09-07 contains useful yearly/possibly surface-level aggregates including Aces, double faults and serve/break-point statistics.

**Hypothesis:** yearly player/team aggregates may provide a much cheaper baseline/enrichment source than requesting a large number of event-statistics endpoints individually.

Before replacing event-level enrichment, compare on the same target population:

- API request count;
- player coverage;
- Aces coverage;
- DF coverage;
- surface specificity;
- recency sensitivity;
- availability of opponent context;
- predictive/backtest quality;
- calibration stability.

Decision rule: **do not replace event-level data until coverage and predictive quality are empirically compared.**

Potential future architecture:

- yearly aggregate = low-cost prior/baseline;
- event statistics = targeted recent/detail enrichment;
- shrink sparse event-level samples toward the yearly prior.

---

## 8. Sets / Games — implemented foundation, enrichment pending

S/G selector exists and uses real structured set scores only. Do not infer structured score data from ambiguous free-text score strings.

Derived historical concepts include:

- total sets;
- total games;
- games won by each side;
- first-set winner;
- tie-break set count;
- straight sets;
- deciding set.

Retirements, walkovers and ambiguous/incomplete score structures are excluded.

Current markets:

- BO3: Over/Under 2.5 Sets projection
- BO5: Over/Under 3.5 Sets projection
- High / Low Total Games projection

Current enrichment workflow mode:

`sg-scores`

Latest refresh still showed:

- structured score history: 0 usable in the serving selector
- upcoming `best_of`: missing for the current board

Therefore S/G remains pending until `sg-scores` enrichment plus `best_of` handling is completed and validated.

---

## 9. Extra odds markets — OPEN / next implementation

The existing `/odds/1/all` request already returns more than Match Winner for many events. We should parse and persist the following when available:

1. Match Winner — already implemented.
2. First Set Winner — add.
3. Total Games — add line + both prices.
4. Tie Break in Match — add when provider offers it.

Do not fabricate missing markets. Market availability must be explicit per event.

Potential use:

- enrich Top Daily / Value cross-market selection;
- directly support S/G market comparison;
- model-vs-market diagnostics;
- later own CLV snapshots.

---

## 10. Doubles — API mapping and future model

### Discovery made on 2026-09-07

The current provider adapter already recognises doubles but deliberately excludes them from the singles history/prediction flow.

Existing doubles signals include:

- tournament/event text contains `double` / `doubles`;
- side name contains `/`;
- side contains multiple `subTeams`, `players` or `members`.

This means we should **not** redesign daily discovery. Instead, preserve the event and route it to a separate doubles pipeline.

### RapidAPI operations observed in the UI

The following operations were mapped from the TennisApi RapidAPI interface and are candidates for doubles/team enrichment:

- `getPreviousTeamMatches`
- `getUpcomingTeamMatches`
- `getTeamYearStatistics`
- `getTennisTeamDetails`
- `getTennisTeamIdRankings`
- `getTeamStandingsSeasons`
- `getTennisTeamIdRecentUniqueTournaments`
- `getTennisTeamIdTournamentsLast`
- `getTeamNearMatches`
- `getTeamFeaturedEvent`
- `getTeamImage`
- `getTeamOverallRanks`
- `getTeamSeasonBestResult`

Observed behavior includes legitimate 204 responses on some operations. Exact route/schema must be captured before implementation; do not infer undocumented fields.

### Doubles data model — planned

Add explicit match type:

- `singles`
- `doubles`
- `mixed_doubles`

For a doubles event preserve team/pair identity and member identity separately, e.g.:

- pair/team ID;
- player A ID;
- player B ID;
- opponent pair/team ID;
- opponent member IDs.

### Doubles model — separate from singles

Potential features:

- pair record together;
- pair recent form;
- pair surface form;
- number of matches played together;
- individual strength/ranking of all four players;
- serve/Aces/DF profile;
- opponent pair quality;
- pair-vs-pair H2H;
- rest/workload;
- tournament level / surface;
- market odds where available.

**Pair chemistry/data depth is mandatory.** A new pairing must not be treated as equally known as a pair with dozens of matches together.

Doubles requires its own training, calibration, backtest and publication thresholds. Do not mix doubles observations into the existing singles model dataset.

### Doubles next validation

Capture one real doubles event JSON with `homeTeam` / `awayTeam` plus pair/member identifiers. Use it to finalize pair identity rules before writing doubles history.

---

## 11. Environment / venue enrichment

Environment is implemented as a research/enrichment layer and is **not a blocker** for current market work.

Current design:

- missing-only by default;
- retry unresolved only when explicitly requested;
- force mode separate;
- venue resolution through provider facts + conservative geocoding;
- historical archive weather labelled post-hoc research;
- historical weather is not automatically training eligible.

Important rule: post-hoc historical weather must not silently enter the champion model as if it were genuine pre-match point-in-time weather.

Latest audit before current work showed roughly half of canonical history carrying environment metadata, with venue/weather coverage still being expanded opportunistically.

---

## 12. Match identity incident and fix

### v5.6 — ambiguous identity collision

Production refresh previously failed with:

`Ambiguous match identity collision; refusing to refresh history`

Resolution:

- existing/canonical corruption still fails hard;
- ambiguous collisions introduced only by incoming provider rows are quarantined/skipped;
- no forced merge of distinct provider events;
- remaining refresh continues;
- log includes actionable collision metadata such as provider event IDs.

Known quarantined provider IDs observed during successful refresh:

- `17016570`
- `17016572`

Do not remove this safeguard merely to increase coverage.

---

## 13. Publication confirmation incident and fix

### v5.7 — serving enrichment vs immutable candidate

Deployment succeeded but confirmation failed with:

`Deployed feed does not match the current private publication candidate`

Root cause:

`prepare_feed.py` correctly adds presentation-only player enrichment after the immutable candidate is committed. Confirmation compared the fully enriched serving feed byte-for-byte/logically against the private candidate.

Resolution:

Confirmation ignores only presentation-only fields such as rank/country/photo/player-asset metadata while remaining strict for prediction identity, probabilities, model, market data and publication semantics.

Result: deploy + confirmation subsequently succeeded.

---

## 14. Auth / accounts / subscriptions / admin

### Roles vs plans

Role and subscription plan are separate concepts.

Roles:

- `user`
- `admin`

Plans:

- Rookie
- PRO
- Elite
- GOAT
- Legend reserved/hidden

Admin receives full internal access independent of paid plan.

### Admin bootstrap

Backend recognises admin from Supabase `app_metadata.role = admin`, with `BLINQ_ADMIN_EMAILS` available as an environment bootstrap path.

For test accounts, role can be assigned in Supabase Auth app metadata. The UI/backend already contains Admin → Users access-management functionality for role/plan/status management.

### Logout

User reported that explicit logout did not behave as expected during testing, although the account subsequently refreshed into Admin correctly.

Current `web/auth.js` contains session-epoch protection intended to prevent an in-flight token refresh from resurrecting a cleared session. Therefore the remaining logout issue needs live UI/end-to-end reproduction before changing auth semantics.

Status: **needs live verification**.

---

## 15. Membership and access design

Current product direction:

- Rookie: monthly entry tier; registration trial window supported by access design.
- PRO: monthly.
- Elite: annual.
- GOAT: lifetime.
- Legend: reserved/hidden.
- Admin: internal role, not subscription.

Access states are intended to support:

- ACTIVE
- LOCKED
- BLURRED
- HIDDEN

Admin bypasses plan restrictions.

Access Manager and Content Manager are conceptually separate:

- Access Manager controls who sees/uses a slot.
- Content Manager controls what the slot contains.

---

## 16. Dashboard / content decisions

Primary dashboard order:

1. Prime Picks
2. Top 10 Daily Picks
3. Value Picks
4. Ace Picks
5. S/G Picks
6. BTTS Bonus — BETA

Ad/content rows are preserved as explicit geometry so missing paid advertising can fall back to news/RSS/BlinQ promo without collapsing the layout.

Current left navigation includes prediction categories, Results, Tournaments, Players, Stats & Insights, Model Performance, Backtests, BTTS and Account.

Detailed card spacing/height should be finalized only after all real-data sections are populated.

---

## 17. Content-slot / ad architecture

Universal content slot types may include:

- Advertisement
- RSS / News
- Image
- BlinQ Promo
- Telegram
- Announcement

Fallback principle:

paid ad → news/RSS → BlinQ/tennis promo

Do not change page geometry merely because a commercial campaign is absent.

Campaign analytics should be campaign-ID based and eventually track impressions, unique views, clicks, unique clicks and CTR.

---

## 18. Workflow / concurrency decisions

History-mutating jobs must be serialized against each other.

Separate concurrency groups exist for distinct classes of work such as:

- history/data writer;
- production deploy;
- player asset writer;
- environment audit.

Read-only audits should not unnecessarily block independent work.

Any future workflow that writes the canonical history release must join the history writer concurrency group.

---

## 19. Validation policy

For every patch, record exactly what was tested. Do not say “all tests pass” unless they actually ran.

Typical minimum checks where relevant:

- Python compile / `compileall`;
- `node --check web/app.js`;
- workflow YAML parse;
- focused pytest files for changed behavior;
- broader regression suite when dependencies are available.

If a dependency such as `pyarrow` is unavailable locally, record the limitation instead of implying those tests passed.

Production success must be confirmed from actual GitHub/Azure logs, not assumed from local tests.

---

## 20. Patch / implementation chronology

- v5 — real market odds / Top Daily / Value.
- v5.1 — concurrency separation/serialization.
- v5.2 — Results / betting publication settlement ledger.
- v5.3 — Ace/DF projection foundation + statistics enrichment workflow.
- v5.4 — Sets/Games structured-score projection foundation.
- v5.5 — asset-linking / plan avatars / fallback photos; assets remain user-replaceable by filename.
- v5.6 — safe quarantine of ambiguous incoming match identity collisions.
- v5.7 — publication confirmation corrected for presentation-only serving enrichment.

Documentation-only addition after v5.7:

- `docs/DECISIONS_AND_BACKLOG.md` introduced as the living engineering record for eventual technical documentation.

---

## 21. Active backlog — ordered

### Data / predictions

- [RUNNING] Complete Ace statistics enrichment and inspect real coverage.
- [NEXT] Run `sg-scores` enrichment.
- [NEXT] Resolve / populate `best_of` for current upcoming events.
- [NEXT] Re-run refresh and validate live Ace + S/G projections.
- [NEXT] Parse First Set Winner / Total Games / Tie Break from provider-1 odds payload.
- [OPEN] Compare `getTeamYearStatistics` against event-by-event statistics for Ace/DF efficiency and predictive value.
- [OPEN] Capture own odds snapshots for CLV if justified.

### Doubles

- [OPEN] Capture one real doubles event payload with team/member IDs.
- [OPEN] Define stable pair identity schema.
- [OPEN] Preserve doubles instead of dropping them during event ingestion.
- [OPEN] Build separate doubles history and data-depth metrics.
- [OPEN] Train/backtest/calibrate a separate doubles model.
- [OPEN] Validate doubles Match Winner odds and later additional markets.

### Product / web

- [OPEN] Match Detail / View Analysis page: radar/spider, form, surface, opponent quality, rank, Aces/DF, S/G, depth, model probability, odds/edge/EV, environment where available, Why this pick.
- [OPEN] See All tables, filters and sorting.
- [OPEN] Final dashboard card sizing/spacing after all real-data categories populate.
- [OPEN] Reproduce and finish logout behavior.
- [OPEN] Payment-provider integration.
- [OPEN] Admin/content analytics and permission polish.
- [OPEN] Own BlinQ support widget.
- [OPEN] Static/footer pages: How BlinQ Works, Methodology, Model & Data, FAQ, Responsible Use, Privacy, Terms.
- [LATER] Football BTTS branch.

### Documentation

- [ONGOING] Append every material decision/change/result to this file.
- [LATER] Convert this engineering log into formal technical documentation with architecture diagrams, data contracts, runbooks, model methodology, security/auth, deployment, incident history and operational procedures.

---

## 22. Entry template for future work

Append new entries using this structure where practical:

```md
### YYYY-MM-DD — short title

**Why**
Problem / requested behavior / reason for change.

**Decision**
What we decided and why.

**Implementation**
Files/services/workflows changed.

**Data/API impact**
New endpoint, schema, cache, budget or migration implications.

**Validation**
Exact tests/checks/run logs that passed or failed.

**Production result**
Only after confirmed by actual deployment/run output.

**Follow-up**
Remaining work / hypothesis / risk.
```

This preserves enough context to later generate trustworthy technical documentation without reconstructing project history from chat memory.
