# BlinQ v6.6.0 — approved public UI rebuild

## Locked public composition

The public overview now follows one deliberate hierarchy:

1. Top navigation
2. Three managed promo / CTA blocks
3. One managed rotating hero
4. Adaptive main pick grid

There is no homepage search, Quick Overview side panel, Results side panel, or legacy advertising row interrupting this composition. Search remains part of the dedicated Overview route.

## Adaptive main grid

The main grid continues to use the six managed sections:

- Prime
- Top
- Aces
- Value
- Doubles
- Sets / Games

Admin can independently hide sections. Remaining sections reflow into the available geometry. Desktop uses a three-card rhythm, tablet uses two columns, and mobile uses one column. Results, Overview, and BTTS are dedicated routes and do not consume one of the six dashboard slots.

## Visual system

A new final cascade layer (`web/final-ui.css`) owns the public UI without rewriting authentication, feed, account, Admin, permissions, or publication logic.

The approved visual language uses:

- a soft blue-white light theme;
- a deep navy dark theme with the same geometry;
- restrained borders and shadows;
- consistent rounded surfaces;
- clearer type hierarchy;
- one nested match card per dashboard section;
- one highlighted prediction strip;
- three KPI cells and a detail action;
- clean empty and locked states.

The three promo blocks and hero remain managed from Admin. The hero includes non-promissory product principles: model predictions, real statistics, transparent results.

## Aces / double-fault markets

The current feed is still projection-only unless a verified market line is present. The UI no longer assumes one generic number is sufficient.

When the API provides an O/U line using one of the supported fields (`line`, `market_line`, `over_under_line`, `total_line`, `threshold`), the card can display the player selection against that line and show projection, opponent projection, and confidence.

When no line exists, the card remains explicitly projection-only and does not invent odds or a betting market.

## Search

There is no global header search. Filtering/search belongs to Overview, where it has sufficient context (date, player, tournament, surface, category, sort).

## Responsive validation

The layout was rendered at desktop, tablet and mobile widths with no page-level horizontal overflow. Promo blocks become a horizontal snap carousel on smaller screens; the dashboard becomes 2 columns on tablet and 1 on mobile.

## Compatibility

Existing logic preserved:

- Supabase/auth session flow
- Admin role bypass and Admin Preview
- plan/access matrix
- dynamic section visibility
- hero and CTA management
- Overview route and filters
- Results route
- content tracking
- player photos/fallback asset hooks
- light/dark preference persistence

No schema migration is required. `ui-config.json` remains on the existing revision because the visual rebuild does not change the stored configuration schema.
