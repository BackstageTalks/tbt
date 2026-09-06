# Player card enrichment — verified provider endpoints (deferred)

This is intentionally deferred from the membership/content UI work. The endpoint paths below were confirmed from the provider screenshots supplied on 2026-09-06; use the currently configured RapidAPI host/key rather than hard-coding a second product host.

## Endpoints

- Player image: `GET /api/tennis/player/{player_id}/image`
- Player ranking history/current record: `GET /api/tennis/player/{player_id}/rankings`
- ATP ranking snapshot: `GET /api/tennis/rankings/atp/`
- WTA ranking snapshot: `GET /api/tennis/rankings/wta/`

The ranking snapshot payload includes player/team identity plus country metadata such as `country.alpha2`, which can be used for flags.

## Planned BlinQ serving fields

For upcoming/live prediction cards, enrich the serving contract with current presentation metadata only:

```json
{
  "player1": {
    "id": "...",
    "name": "...",
    "rank": 0,
    "country_code": "SK",
    "photo_url": "..."
  },
  "player2": {
    "id": "...",
    "name": "...",
    "rank": 0,
    "country_code": "CZ",
    "photo_url": "..."
  }
}
```

Keep current player rank/photo/country enrichment out of historical training rows unless true point-in-time provenance is available. The existing historical ranking-leakage guard remains in force.

## Request-budget rule

Do not request one photo/ranking endpoint per card on every refresh. Cache enrichment by stable player ID and prefer the ATP/WTA ranking snapshots for rank + country. Photo/profile lookups should be cached and refreshed independently at a much lower frequency.
