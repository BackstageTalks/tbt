# BlinQ / TBT — Decisions, Backlog and Engineering Log

> Living project record. This file is the working source for a later complete technical documentation of BlinQ/TBT.
>
> **Update rule:** every meaningful implementation, architecture decision, data-source discovery, production incident, validation result, UI/content decision and open hypothesis should be appended here while the work is being done. Do not rewrite history just because the implementation later changes; mark old decisions as superseded and link the replacement.

Last updated: **2026-09-08**
Current working line: **v5.9**

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

### Top Daily / Value rules used through v5.8 — SUPERSEDED by v5.9

Historical v5.x behavior before the 2026-09-08 cascade decision:

- Top Daily had a max-10 policy and was ranked primarily by EV / prediction strength;
- Value used an odds threshold above 1.70 plus a positive-edge requirement.

These rules are retained here as history only. **v5.9 replaces them** with one common quality pool for Daily/Prime and a separate close-market Value branch; see the 2026-09-08 engineering entry below.

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

Backend recognises admin from Firebase custom claim `role = admin`, with `BLINQ_ADMIN_EMAILS` available as an environment bootstrap path.

Admin → Users manages Firebase role/plan/status custom claims. The Supabase app-metadata path is retained only as the temporary auth rollback fallback.

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

Primary dashboard order after the v5.9 Match Winner cascade update:

1. Daily Picks
2. Prime Picks
3. Value Picks
4. Ace Picks
5. S/G Picks
6. BTTS Bonus — BETA

Daily/Prime/Value are quality-driven. There is **no artificial minimum or quota** used to fill dashboard cards; the dashboard may show fewer than five selections when fewer qualify. The first five are presentation only, with See All available when the qualified set is larger.

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
- v5.8 — Ace statistics enrichment resilience: valid HTTP 200 statistics with no supported fields are cached as unavailable instead of aborting the run.
- v5.9 — Match Winner cascade: shared 78/80/5 quality pool, Daily 1.25–1.50, Prime >1.50, close-market Value branch, edge/EV display-only, and prioritized odds requests. **SUPERSEDED by v6.0.**
- v6.0 — Prime / Top Bets / Value product policy, explicit EV/edge guardrails and mutually exclusive publication (one underlying pick = one public offer).
- v6.1 — Top Bets confidence-first refinement: 72% target, 68% hard floor, edge/EV diagnostic-only, quality-first ranking, odds 1.20 sanity floor.

Documentation-only addition after v5.7:

- `docs/DECISIONS_AND_BACKLOG.md` introduced as the living engineering record for eventual technical documentation.

---

## 21. Active backlog — ordered

### Data / predictions

- [PROD CONFIRMED v6.0 / v6.1 LOCAL] Monitor Prime / Top Bets / Value live volume, hit rate and ROI; deploy v6.1 confidence-first Top Bets refinement.
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

## 22. 2026-09-08 — Match Winner cascade / Daily + Prime + close-market Value (v5.9)

**Why**

The previous Top Daily and Value selectors mixed price, EV and confidence rules and could spend provider requests on a much wider board than the final betting sections needed. Product direction is now to first identify a genuinely strong Match Winner candidate pool, then let the available market price determine whether the pick is presented as lower-risk Daily or higher-priced Prime. Value is intentionally a different strategy: search close bookmaker markets and let the model choose the side.

**Decision**

Shared Match Winner quality pool for Daily/Prime:

- calibrated winner probability `>= 0.78`;
- data depth `>= 0.80`;
- at least `5` surface-history matches for **each** player;
- missing/invalid surface quality fails closed;
- no edge or EV hard filter.

Presentation split after a real provider-1 Match Winner price is available:

- **Daily Picks:** decimal odds `1.25 <= odds <= 1.50`;
- **Prime Picks:** decimal odds `> 1.50`, no artificial upper cap;
- no forced pick count and no quota filling.

Separate **Value Picks** discovery branch:

- model winner probability `>= 0.60`;
- data depth `>= 0.80`;
- surface history `>= 5 / 5`;
- both Match Winner sides must be available so the two-way market can be de-vigged;
- absolute difference between the two fair market probabilities `<= 0.15` (15 percentage points);
- BlinQ keeps the model-selected winner;
- model-vs-market edge and expected value are calculated and displayed as diagnostics, **not used as selection filters**.

The 15pp close-market boundary and 0.60 Value model threshold are working v1 defaults. They must be monitored/backtested and may be tightened after sufficient OOS/live data; they are not profitability guarantees.

**Implementation**

- `api/tbt/services/market_selection.py` — explicit v5.9 policy constants, fail-closed surface gate, common Daily/Prime pool, close-market Value selector, selection diagnostics and odds-request prefilter.
- `api/tbt/services/publication.py` — Prime is a first-class odds-backed publication section.
- `api/tbt/services/engine.py` — Prime betting-performance section while preserving overall deduplication by underlying selection key.
- `api/tbt/services/feed.py` — serving contract includes `prime_picks`.
- `scripts/pipeline.py` / `scripts/prepare_feed.py` — pipeline and player-enrichment handling for Prime; canonical legacy `top_daily_picks` feed key is retained internally for publication compatibility while the product label is Daily Picks.
- `web/app.js`, `web/index.html`, `web/styles.css`, `web/ui-config.json` — Daily/Prime/Value labels, rules, five-card preview geometry, close-market copy and edge shown as `pp`.
- tests updated for exact odds boundaries, 78/80/5 gating, close-market Value behavior, no edge filter, publication memberships and ROI deduplication.

**Data/API impact**

Provider quota is now protected before odds retrieval. Current betting-day rows must first pass the broad Value-discovery gate (`p >= 0.60`, depth `>= 0.80`, surface `>= 5/5`) before `/odds/1/all` is requested. Candidates are ordered by prediction strength/data depth and remain bounded by the existing per-run `max_events` cap. This broad prefilter covers the stricter 78/80/5 Daily/Prime pool and the close-market Value branch without spending odds requests on the entire board.

Publication/settlement semantics remain immutable: Daily/Prime/Value can tag the same underlying Match Winner selection, but overall betting ROI counts that underlying selection only once. Historical high-confidence predictions are not retroactively relabelled as Prime bets.

**Validation**

Local validation against the reconstructed v5.8 main line:

- `python -m compileall -q api scripts` — PASS;
- `node --check web/app.js` — PASS;
- focused Aces/S-G/market/results suite — `18 passed`;
- focused admin/market/results/deploy-flow suite — `33 passed`;
- full suite collected `186` tests; `8` parquet/history tests could not run successfully because the local environment does not have `pyarrow`;
- excluding exactly those pyarrow-dependent tests, the remaining `178` tests passed.

A selector sanity run against the previously captured production feed executed successfully, but that snapshot contains odds for the prior betting day and is **not** treated as a 2026-09-08 volume forecast or production validation.

**Production result**

PENDING. Local code/tests do not prove GitHub/Azure publication success. Confirm from the real refresh/deploy/confirmation logs after v5.9 is applied.

**Open work**

- collect live Daily/Prime/Value hit-rate, odds, units and ROI separately;
- backtest/monitor the 78/80/5 main gate and Value 60/80/5 + 15pp close-market rule;
- collect odds snapshots if CLV analysis is promoted;
- do not turn edge/EV into a hard Value filter unless later OOS evidence supports it.

---


## 24. 2026-09-08 — Prime / Top Bets / Value v6.0 + exclusive pick assignment

**Why**
The v5.9 Daily/Prime price cascade no longer matched the product definition agreed for BlinQ. More importantly, the same underlying Match Winner selection could appear simultaneously in two public offers (for example Prime and Value), which creates a confusing dashboard even though overall ROI was deduplicated later.

**Decision**
Use three distinct working strategies and make their public assignment mutually exclusive:

- **Prime Picks** — accuracy first: model probability `>= 0.85`, data depth `>= 0.80`, surface history `>= 5/5`; odds `1.20–1.50` are the preferred product zone but not a hard band; materially negative EV below `-3%` is rejected; max 30.
- **Top Bets** — balance probability + price: model `>= 0.72`, depth `>= 0.80`, surface `>= 5/5`, odds `>= 1.50`, edge `>= 2pp`, EV `>= 3%`; max 10. The canonical feed/publication key remains `top_daily` / `top_daily_picks` for compatibility, but the product label is Top Bets.
- **Value Picks** — edge/EV first: model `>= 0.55`, depth `>= 0.75`, surface `>= 3/3`, odds `>= 1.80`, edge `>= 5pp`, EV `>= 8%`; max 10.

A pick may qualify for several strategies internally, but it receives exactly one `primary_section`. Default assignment priority follows dashboard order: `Prime -> Top Bets -> Value`. This priority is intentionally explicit/configurable and can later be changed after OOS/live review.

**Implementation**
- `api/tbt/services/market_selection.py`: v2 policy constants, price/EV guardrails, stable selection identity, exclusive-section assignment, duplicate invariant, strategy-specific ranking and one-publication-per-selection ledger candidate.
- `web/ui-config.json`, `web/index.html`, `web/app.js`: Top Bets product naming, v6 working thresholds, exclusive-assignment metadata and updated explanatory copy.
- `scripts/pipeline.py`: wording updated while preserving the canonical `top_daily_picks` compatibility key.
- tests: old v5.9 cascade assertions replaced with v6 strategy tests plus a regression test that a pick qualifying for multiple strategies is published in only one offer.

**Data/API impact**
Pre-price odds discovery now uses the broadest current supported final branch (`p >= 0.55`, depth `>= 0.75`, surface `>= 3/3`) so potentially valid Value candidates are not discarded before price is known. The existing `max_events` provider-request cap remains in force. This may increase eligible odds requests versus v5.9 and must be monitored against quota/coverage.

The existing Match Winner market-publication schema remains `1`; v6 adds `primary_section` as backward-compatible metadata and restricts new candidates to one section. Existing historical publications are not rewritten; old duplicated section tags remain historical facts of what was actually published at that time.

**Validation**
- `python -m compileall -q api scripts` — PASS.
- `node --check web/app.js` and `node --check web/auth.js` — PASS.
- focused market/publication/admin suite — 24 PASS.
- full collection — 186 tests. Exactly 8 parquet/history tests cannot run in the local environment because `pyarrow` is not installed.
- excluding exactly those 8 pyarrow-dependent tests, the remaining 178 tests PASS.
- explicit exclusivity regression confirms one underlying Match Winner selection cannot be present in more than one of Prime / Top Bets / Value.

**Production result**
CONFIRMED for v6.0 on 2026-09-08 from the real GitHub/Azure refresh/deploy/confirmation log: 429 upcoming rows, Prime 3, Top Bets 0, Value 2, 41 odds candidates, 33 odds available (~80.5% coverage), deployment succeeded, and publication confirmation reported 145 newly confirmed predictions with 5 newly confirmed market picks. The zero Top Bets output is the live observation that motivated v6.1; it is not treated as a selector failure.

**Follow-up**
- monitor actual section volumes, hit rate, average odds, units and ROI;
- backtest thresholds and assignment priority OOS rather than tuning from a small live sample;
- monitor provider quota after broadening the pre-price candidate floor;
- keep one-pick/one-offer as a non-negotiable publication invariant.

## 25. 2026-09-08 — Top Bets confidence-first refinement (v6.1)

**Why**
The first confirmed v6.0 production refresh produced 3 Prime Picks and 2 Value Picks but 0 Top Bets. A fixed 72% + price/edge/EV gate made the main daily Top Bets section too brittle: a day with no candidate clearing every market threshold resulted in an empty product section even when several high-quality model picks existed just below 72%. Product direction is that Top Bets should rank the strongest available model-backed betting picks, not act as a second Value filter.

**Decision**
Top Bets becomes confidence-first while keeping the same one-pick/one-offer exclusivity:

- preferred probability target: `>= 0.72`;
- hard fallback probability floor: `>= 0.68`;
- data depth: `>= 0.80`;
- surface history: `>= 5/5`;
- real Match Winner odds are still required because this is a betting section;
- decimal odds have only a low-price sanity floor of `1.20`;
- edge and expected value are **not** Top Bets eligibility or ranking inputs; they remain diagnostic market metadata only;
- max 10 picks;
- ranking is lexicographic: model probability -> data depth -> minimum player surface sample -> minimum player overall sample -> odds as final tiebreaker.

This means 71% always ranks ahead of 68% regardless of a larger quoted edge/EV on the 68% row. If ten rows already exist above 72%, lower-probability fallback rows never enter the public top ten. If fewer exist, the selector naturally fills downward only as far as the 68% floor.

Elo, surface Elo, H2H and form are not separately re-added to the Top Bets ranking because they already feed the Match Winner model probability. Data depth and sample counts are used only as evidence-strength tiebreakers so those model inputs are not double-counted.

**Implementation**
- `api/tbt/services/market_selection.py`: Top Bets 72% preferred / 68% floor, 1.20 odds sanity floor, edge/EV optional and disabled by default, confidence-first quality ranking, market-selection schema 6 / `prime_top_value_v3_confidence_first_top`.
- `web/ui-config.json`: mirrors the confidence-first rule and marks edge/EV `diagnostic_only`.
- `web/index.html`, `web/app.js`: Top Bets copy, empty state and detail table now emphasize probability/data quality; Top cards foreground odds, depth and surface sample rather than edge/EV.
- tests: regression coverage for 71% outranking 68% even when the lower-probability row has much larger edge/EV, quality tiebreak order, top-10 filling down to exactly the 68% floor, and limit-aware exclusivity so an unpublished #11 Top qualifier can still become a lower-priority Value offer if it independently qualifies.

**Data/API impact**
No new provider endpoint and no wider pre-price discovery gate are required. The existing odds discovery floor (`p >= 0.55`, depth `>= 0.75`, surface `>= 3/3`) already covers all possible v6.1 Top Bets candidates, so provider request volume should not increase solely because of this selector change.

**Validation**
- `python -m compileall -q api scripts` — PASS.
- `node --check web/app.js` and `node --check web/auth.js` — PASS.
- `web/ui-config.json` JSON parse — PASS.
- focused market/publication/admin suite — 28 PASS.
- full collection — 190 tests. Local runtime does not have `pyarrow`; excluding the same 8 parquet/history tests that require it, the remaining 182 tests PASS.

**Production result**
PENDING. Requires a real refresh/deploy/publication confirmation after v6.1 is pushed.

**Follow-up**
- inspect the first several live v6.1 boards before changing the 68% floor;
- compare hit rate by probability band: 72%+, 70-71.99%, 68-69.99%;
- optionally expose those bands as transparent UI labels without changing ranking;
- keep Value as the separate market-disagreement/EV experiment;
- keep exclusivity limit-aware: only an actually published higher-priority offer reserves a selection identity.

---

## 23. Entry template for future work

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

### 2026-09-07 — Ace statistics enrichment: non-fatal unsupported statistics payloads (v5.8)

**Why**
The first targeted `ace-statistics` run used `max_requests=3000`, `target_samples=18` and `lookback_days=550`. After roughly 33 minutes it aborted inside `parse_statistics()` with `ProviderError: Statistics contain no supported rate/count fields; no imputation performed`. TennisApi can legitimately return HTTP 200 event-statistics payloads that contain statistics, but none of the conservative Aces/DF/serve fields currently consumed by BlinQ. One such event must not abort the whole targeted enrichment job.

**Decision**
Keep the statistics parser strict and fail-closed for malformed envelopes, ambiguous/missing `ALL` periods, conflicting values and identity mismatches. Introduce a dedicated `NoSupportedStatisticsError` only for the valid-envelope/no-consumable-fields case. `StatisticsEnricher` catches only that narrow condition, records the event as `unavailable`, and continues. This prevents silent schema corruption while treating provider coverage gaps as normal missing data.

**Implementation**
- `api/tbt/providers/statistics.py`: added `NoSupportedStatisticsError`, a `ProviderError` subclass; the no-supported-fields condition now raises that subclass.
- `api/tbt/services/statistics_enrichment.py`: catches only `NoSupportedStatisticsError`; writes `_tbt_statistics.status=unavailable`, `reason=no_supported_fields`, and a bounded `unsupported_keys` summary for later adapter analysis; normal monthly retry policy remains in force.
- `tests/test_statistics.py`: added regression coverage that a valid `ALL` payload containing only unsupported statistics is marked unavailable, does not populate `match.stats`, and is cached instead of re-requested immediately.

**Data/API impact**
No new API endpoint. No imputation and no fabricated statistics. Unsupported event-statistics rows become explicit missing coverage instead of fatal run errors. The marker is persisted in canonical history and is eligible for the existing monthly retry behavior.

**Validation**
- Python `compileall` for the changed statistics/enrichment/Ace script: PASS.
- Focused Ace/statistics suite excluding the two tests that require local `pyarrow`: 11 PASS.
- Full `tests/test_statistics.py` was also attempted: the two parquet round-trip tests could not run locally because `pyarrow` is not installed; this is an environment limitation, not a code assertion failure.

**Production result**
Pending. Re-run `ace-statistics` with the same `3000 / 18 / 550` parameters after deploying v5.8. The failed run's `finally` checkpoint path should have persisted previously changed year partitions before process exit, so the rerun is expected to reuse already-persisted markers/data and continue rather than necessarily starting from zero. Confirm this from the next real run log/report.

**Follow-up**
- Inspect `unsupported_keys` frequency after the rerun; add aliases only when provider field semantics are verified.
- Continue the separate backlog experiment comparing event-by-event statistics with `getTeamYearStatistics(player_id, year)` for Ace/DF request efficiency and predictive value.
