# BlinQ player card enrichment

Current player photo/rank/country data is **presentation metadata**, not a historical model feature.
The enrichment is intentionally separated from the immutable prediction ledger and from training history.

## Verified provider sources

Provider endpoints confirmed from the TennisApi/RapidAPI screenshots supplied on 2026-09-06:

- player image: `GET /api/tennis/player/{player_id}/image`
- player ranking/current-history record: `GET /api/tennis/player/{player_id}/rankings`
- ATP current ranking snapshot: `GET /api/tennis/rankings/atp/`
- WTA current ranking snapshot: `GET /api/tennis/rankings/wta/`

Ranking rows include the player/team object and country metadata such as `country.alpha2` / `country.alpha3`.
The UI derives the country marker from `alpha2`, so no per-card country request is needed.

## Cache and request policy

Run `.github/workflows/player-enrichment.yml` manually when current card metadata should be refreshed.
It:

1. reads unique player IDs from the private `tbt-predictions-v1/feed.json`,
2. fetches the two global ATP/WTA ranking snapshots first,
3. uses a capped per-player ranking fallback only for players still missing rank/country,
4. downloads/caches player images by stable player ID,
5. publishes the cache to the private `tbt-player-assets-v1` release.

Assets:

- `player_profiles.json`
- `player_photos.zip`
- `player_enrichment_report.json`

Photo calls are not repeated for already cached images. A provider `204/404` is cached as unavailable for 30 days.
Repeated workflow runs therefore continue filling missing current players rather than spending the same quota again.

## Deployment

`scripts/prepare_feed.py` validates the private prediction feed/ledger first, then optionally attaches current player metadata and extracts only photos needed by the current serving feed into `web/assets/players/`.
The browser never receives the RapidAPI key and never calls TennisApi directly.

Serving player objects may therefore contain:

```json
{
  "id": "69208",
  "name": "Jasmine Paolini",
  "probability": 0.72,
  "rank": 21,
  "country_code": "IT",
  "country_code3": "ITA",
  "country_name": "Italy",
  "photo_url": "/assets/players/69208.png"
}
```

The dashboard also displays the already-existing model coverage fields as e.g.
`History 34 / 57 · Surface 12 / 21`.

## Leakage rule

Never backfill a historical match with today's ranking/photo/country and then treat it as point-in-time model data.
Current enrichment remains `presentation_only=true` and `historical_training_eligible=false`.
