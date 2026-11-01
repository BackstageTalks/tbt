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
