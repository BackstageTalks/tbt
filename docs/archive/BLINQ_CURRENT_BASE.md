# BlinQ current base — v7.3.6-r10

v7.3.6 remains the production release line; `r10` is the cleanup/stabilization patch. The data/model contracts from v7.3.0+ remain intact while obsolete UI layers and retired runtime components have been removed.

## Current product surface
- Desktop-first BlinQ dashboard with TOP, VALUE, ESA, DOUBLES, GAMES, SETS and SEE ALL.
- ROOKIE uses server-enforced plan/row access; Admin can configure SHOW / BLUR / HIDE and stable-random daily visibility.
- Locked values are withheld server-side rather than merely obscured with CSS.
- Results are publication-ledger based and start from the clean Results epoch introduced in r6.
- Doubles uses the separate doubles pipeline/model branch introduced in r7; singles probabilities are never reused.
- Comeback LIVE has an autonomous worker from r8 and remains visible to Admin for operational monitoring.

## r10 runtime cleanup
- One production stylesheet: `web/blinq-app.css`.
- Removed runtime VIP rail / four legacy benefit cards, sidebar promo rail, BTTS beta shell, old footer status widget, hidden legacy navigation drawer, and retired footer-link JSON.
- Footer is intentionally minimal: BlinQ watermark, UI version, language selector.
- Loader is a transparent vector scene with an animated ball; the old embedded/static square loader artwork is gone.
- Admin/config validation inventory matches the actual UI surface instead of preserving retired slot IDs.
- Historical patch/audit notes are stored under `docs/archive/` instead of the repository root.

## Deployment identity
- release: `7.3.6`
- asset revision: `7360`
- patch: `736-r10`
- frontend marker: `blinq-web-736`
- runtime CSS: `/blinq-app.css?v=7360&p=10`
- runtime app JS: `/app.js?v=7360&p=10`
