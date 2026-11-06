# TennisApi provider contract — confirmed 2026-08-24

This file records provider-confirmed behavior that BlinQ must preserve.

## Event coverage

The retired flat endpoint `/api/tennis/events/{day}/{month}/{year}` must not be used.

For complete daily coverage, including events without odds:

1. `GET /api/tennis/calendar/{day}/{month}/{year}/categories`
2. For every returned category: `GET /api/tennis/category/{id}/events/{day}/{month}/{year}`
3. Filter singles in BlinQ.
4. Enrich with historical/statistical features.
5. Treat odds as optional enrichment only.

Dates are not zero padded. Stable category IDs supplied by the provider: ATP 3, WTA 6, Challenger 72, ITF Men 785, ITF Women 213, WTA 125 871, Grand Slam -100. Qualifying is a round, not a separate category.

## Odds

Primary TennisApi PRO odds source is `providerId=1` via:

`GET /api/tennis/event/{id}/odds/1/all`

Provider IDs 2, 3, etc. may legitimately return 204. TennisApi does not expose an endpoint listing available provider IDs and does not provide a bookmaker-name mapping for those IDs. It is not a multi-book comparison feed.

`initialFractionalValue` is treated as the opening value in the returned snapshot, `fractionalValue` as the current value in that snapshot, and `change` only as direction relative to that opening. These are not an odds-history tape. BlinQ must persist its own snapshots for CLV/closing-price work.

First-set, totals and tie-break markets are optional and may be absent.

## Statistics

`GET /api/tennis/event/{id}/statistics` is post-match and coverage is event-dependent; 204 is valid. Keys may include aces, doubleFaults, first/second serve and break points, with ALL and set period groups.

Statistics from the event being predicted must never be used as pre-match features. Historical event statistics may be aggregated point-in-time into player features.

## Tournament presentation assets

BlinQ prefers the dark tournament artwork endpoint:

`GET /api/tennis/tournament/{id}/image/dark`

If unavailable, presentation code falls back to:

`GET /api/tennis/tournament/{id}/image`

Tournament logos are presentation-only and never model inputs.

## Not supplied as ready-made TennisApi endpoints

- Top 50/100/200 opponent split tables
- career hold %, break % or RPW split endpoints
- retirement counts over 30/90 days
- historical open/24h/12h/6h/2h/close odds snapshots
- surface Elo time series

When BlinQ exposes such concepts, they must be explicitly derived from stored point-in-time data rather than presented as raw TennisApi fields.

## Provider clarification received 2026-10-14

Confirmed provider-1 market IDs: 1 = Match Winner (1 home / 2 away),
11 = First Set Winner (1 / 2), 12 = Total Games Over/Under (line in
choiceGroup), 15 = Current Set Winner (live only). These markets are not
guaranteed on every ATP/WTA/Challenger/WTA125/ITF event. For total games,
marketPeriod may be "Extra time": key on marketId + choiceGroup, NEVER period.

Event odds routes: /api/tennis/event/{id}/odds and
/api/tennis/event/{id}/odds/1/all; by-date
/api/tennis/events/odds/{day}/{month}/{year} returns match-winner only.
initialFractionalValue is opening, fractionalValue latest stored. Historical
re-queries are NOT time-stamped price movements or guaranteed closing quotes.
A valid HTTP 204 means no coverage.

Unavailable: set correct score, handicaps, player games totals,
aces/double faults O/U, tie-break and total-sets betting markets,
multi-bookmaker odds, timestamped historical price movements and bulk export.

Post-match endpoint /api/tennis/event/{id}/statistics may return ALL and
per-set serve/return/aces/DF. /api/tennis/event/{id}/point-by-point may
return sets/games/points. Both may return 204, especially on smaller events.
Point/game score.serving (1 home, 2 away) and score.scoring refer to the
provider event orientation; do not assume canonical p1/p2 orientation.

Implementation (2026-10-15):
- RapidTennisClient.event_markets_snapshot / event_point_by_point use existing
  guarded provider-1 enrichment calls.
- tennisapi_extra.normalize_market_snapshot has strict eventId/marketId/line
  handling, flags provider_quote_timestamp_known=False and
  pre_match_asof_verified=False; it is NOT directly a model or CLV input.
- tennisapi_extra.normalize_set_statistics reuses the established, strict
  whole-match parser on explicit per-set periods only.
- tennisapi_extra.point_by_point_inventory audits structure only; it cannot
  assert a complete match or derive pre-match features.
- probe_tennis_provider.py optionally samples finished singles point-by-point
  with --pbp-samples N (default 0) and respects its existing --max-requests cap.
- The existing identity-verified post-match StatisticsEnricher now stores
  provider home/away per-set metrics as _tbt_statistics_by_set on future
  successful statistics fetches. Invalid or contradictory set data are skipped;
  existing whole-match values take precedence, with no extra API requests.
  Cached history is NOT automatically re-fetched to obtain these new fields.
- New odds and point-by-point historical backfill, independent raw-sidecar
  publication and model promotion remain disabled until identity, completeness,
  provenance, single-writer and independent persisted read-back pass.

## Additional observed market evidence — 2026-11-01

A separately supplied provider-1 `getAllOddsForEvent` response for
`eventId=14494928` included `marketId=13`, `marketName="Tie break in match"`,
`isLive=false`, `suspended=false`, and Yes/No prices 4/9 and 13/8.
This *one observed response* refines the older 2026-10-14 statement that
tie-break prices were unavailable; it does **not** establish general coverage.
The research snapshot parser can now label **only** this exact unsuspended
prematch shape as `tie_break_in_match` (not ACES). It preserves unknown
bookmaker identity and unknown quote timestamp, and is **not** a pre-match
model/CLV price. No production ACES market selection or canonical numeric
CDB field mapping was changed.

On the read-only guarded probe dated 2026-11-01, season-wide odds for
season 67287/provider 1 returned HTTP 404. Odds-provider enumeration was
not proved available because the quota-header guard halted further requests.
Neither path is approved for production coverage or bulk import on this basis.

## REcodeX follow-up: 2026-11-01 to 2026-11-02 — implementable scope

This updates earlier general statements with the **specific** event evidence
provided by the operator's support correspondence. It is not a promise of
historical coverage, bookmaker identities or new paid-plan endpoints.

| Provider fact | BlinQ implementation / restriction |
|---|---|
| `/category/3/events/5/7/2016`, `/6/events/5/7/2016`, `/72/events/5/7/2016` and `/785/events/5/7/2016` returned 200 | The existing native calendar/category downloader can enumerate historical event IDs. A 2016–2026 coverage matrix was **not** provided; do not presume statistics or odds exist for each event. |
| `/event/{id}/statistics` has ALL and sometimes per-set aces/DF, serve, return, break points and game figures | Existing `StatisticsEnricher` parses verified known keys and stores per-set markers without rewriting canonical data. The new bounded `statistics_provider_key_inventory` report counts ALL supported/unsupported and set-only key names from already-fetched responses. Do not map unknown fields automatically. |
| `/event/17449522/odds/5/all` returned **Match Winner** on a concrete event | Primary remains provider 1. Existing extras enrichment makes **one** optional provider-5 fallback only if provider 1 has zero valid quotes **and** native category evidence is ATP 3, WTA 6 or Grand Slam -100; no speculative Challenger/ITF calls. Only market 1 may be accepted. Exact event identity is required. Store `provider_id=5`, bookmaker identity **unknown**. |
| `initialFractionalValue`, `fractionalValue`, `change` | Store opening/latest decimals and the supplied -1/0/1 movement direction. Do **not** invent price timestamps, bookmaker mapping, true closing prices or point-in-time CLV. |
| `/events/odds/{day}/{month}/{year}` returns event-ID-keyed **Match Winner only** | Existing `RapidTennisClient.events_with_odds_for_status_day` serves settlement lookup; it is not a full daily event inventory or multi-market historical tape. |
| `/event/17377322/point-by-point` showed 17 games whose terminal points were omitted | Existing PBP remains structural-only. Game server and winner indicators may support **observed-game-only** counts. These are not verified complete match totals, reconstructed point outcomes or approved pre-match model inputs. |
| `hasEventPlayerStatistics` was not exposed on the checked event | Treat a missing flag as unknown, never skip known event stats solely because the flag is absent. |

The provider does not publish a separate player Aces O/U add-on, set-correct
score, handicaps, player game totals, timed historical odds, historical bulk
export or new market access on a higher subscription. Provider 5 is a
**single observed fallback**, not evidence that polling IDs 2–10 on every
event would be efficient or accurate. Continue using approved PropLine
secondary sources for markets outside the TennisApi contract.

### Operational invariants and next verification

- **CDB:** authoritative and NULL-only; native exact-event/participant
  matching, provenance, duplicate checks, global single-writer lock,
  checkpoint, CAS, immutable backup and independent remote read-back remain
  in the established importer. No separate writer and no model activation.
- **RapidAPI:** shared 15,000/day, practical 14,500 ceiling, 500 reserve,
  6 requests/s, retries charged, unknown external usage **not** zero.
- **Quality:** count actual stored new values separately from cache hits,
  candidate rows, provider-5 fallback attempts, and observed partial PBP
  games. Unsupported key discovery is not a successful canonical import.
- **Open evidence:** measure provider-5 fallback win-rate on an authorized
  bounded extras batch; review unknown per-match statistics keys before
  permitting more typed CDB fields. Broaden 2016–2021 selectively only on
  verified identity, point-in-time, yield and shared-budget evidence.
- **Change isolation:** tests for wrong event IDs, exhausted budget, bad
  market shapes, no-coverage cooldowns, timezone/CLV isolation and partial
  game records must pass before production write activity.

The next data run must report **actual** requests, linked events, newly
persisted canonical values or metadata, and independent exact-value
read-back. A passing CI check or successful dispatch is not an import.

## 2026-11-06 — Optional season coverage research (no auto-import)

New **research-only** RapidTennisClient methods (all through the existing
shared-budget `_get(..., enrichment=True)` guard):

- `team_year_statistics(team_id, year)` requests
  `/api/tennis/team/{team_id}/year-statistics/{year}`.
  Returned aggregates are **not** individual match cells and are not
  point-in-time valid for pre-match calculations in the same season.
- `tournament_season_last_matches(tournament_id, season_id, page=0)`
  requests `/api/tennis/tournament/{tournament_id}/season/{season_id}/events/last/{page}`.
  One page is not a complete season and IDs must be cross-checked independently.
- `player_singles_results(player_id, page=0)` requests
  `/api/tennis/player/{player_id}/events/singles/last/{page}`.
  Rows must have unique event IDs, source-native player identities and dates.

Existing `scripts/probe_tennisapi_extended_contract.py` now supports focused
`--phase candidates --case team_year_statistics`,
`--case tournament_last_matches` and `--case player_singles_results`.
A probe first fetches and checks the exact source event ID and derives the
provider-native team/tournament/season identifiers, then makes **at most one**
optional endpoint call within the explicit `--max-requests` cap.
The case allowlist rejects unknown routes before any API call.

The candidate report stores payload hashes and structural observations;
it does not expose raw player statistics, guarantee archive completeness,
or permit CDB/model/odds mutations. Provider-5 fallback, local odds, serving
champion, existing importers and scheduled ingestion remain unchanged.
Provider availability, identity/coverage consistency and historical
point-in-time eligibility still require live evidence, followed by explicit
quality, deduplication, single-writer, dry-run and independent read-back
before any canonical supplement.

**Verification record:** Offline contracts are in
`tests/test_tennisapi_coverage_candidates.py`. A merged commit or green CI
does not establish live API availability. A live candidate run must record
the exact GitHub Actions run/artifact, HTTP status, quota header, spent
requests, response shape and no-CDB-write flag; HTTP 204/403/404 is not
a successful source-coverage result.

**User-provided sample (2026-11-06, not a separately billed API probe):**
the `getTeamYearStatistics` payload has 5 named surface groups and 63
reported match participations. Each group passes the following arithmetical
identities: `firstServeTotal + secondServeTotal == totalServeAttempts`,
`secondServePointsTotal + doubleFaults == secondServeTotal`, and
`firstServePointsTotal + secondServePointsTotal + doubleFaults == firstServeTotal`.
All 20 scored/total break-point and serve-point inequalities are within
bounds. Those are sample integrity checks, not provenance/identity
verification and not independent evidence that any canonical CDB NULL
was enriched. The candidate probe now records surface, service-arithmetic,
bounds, positive-match and nonempty-source checks; invalid/empty responses
are not classified as usable coverage.
