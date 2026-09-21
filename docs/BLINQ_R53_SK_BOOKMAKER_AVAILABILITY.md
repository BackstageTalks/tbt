# BlinQ 7.3.6-r53 — SK bookmaker availability

r53 adds a presentation-only verification layer that can mark a BlinQ pick with the Slovak bookmakers where the **same event + market + selection + line** was confirmed by an external odds snapshot.

## Supported Slovak bookmakers

The normalized registry currently supports:

- Tipsport
- Niké
- Fortuna
- DOXXbet
- SYNOT TIP
- TIPOS
- Chance

Aliases such as `tipsport.sk`, `nike.sk`, `ifortuna.sk`, `doxxbet.sk`, `synottip.sk`, `etipos.sk` and `chance.sk` are normalized to the same seven bookmaker IDs.

## Safety contract

This integration is deliberately **fail-closed**:

- no source configured -> no bookmaker badge;
- stale, suspended or inactive offer -> no badge;
- unknown bookmaker -> no badge;
- event mismatch -> no badge;
- market mismatch -> no badge;
- total/prop line mismatch -> no badge;
- Aces / Double Faults require the same player subject as well as the same side and line;
- a source failure never blocks BlinQ publication and never fabricates availability.

The layer is attached after the normal market-selection process. It does not modify BlinQ probability, chosen pick, model odds, edge or EV.

## Data source

r53 intentionally does not infer bookmaker identity from the existing TennisAPI `provider_id`. The existing provider contract has no bookmaker-name mapping and therefore cannot safely be used for branded badges.

A normalized snapshot can be supplied in either form:

- `BLINQ_BOOKMAKER_OFFERS_FILE=/path/to/offers.json`
- `BLINQ_BOOKMAKER_FEED_URL=https://.../offers.json`

Optional HTTPS settings:

- `BLINQ_BOOKMAKER_FEED_TOKEN`
- `BLINQ_BOOKMAKER_FEED_TIMEOUT_SECONDS` (default `8`)
- `BLINQ_BOOKMAKER_MAX_AGE_MINUTES` (default `45`)
- `BLINQ_BOOKMAKER_EVENT_TOLERANCE_SECONDS` (default `10800`)

See `api/config/bookmaker-offers.example.json` for the normalized schema. This adapter boundary lets a licensed/commercial multi-book feed be connected later without changing the web UI or BlinQ model.

## Web presentation

Matched rows receive `bookmaker_availability[]`. The dashboard renders compact BlinQ-styled monogram badges below the odds. The tooltip contains the bookmaker name and, when supplied, the verified line and current decimal odds.

The first r53 UI deliberately uses compact text monograms rather than copied bookmaker logos. This avoids packaging third-party brand artwork while still giving the user an immediate availability indicator.
