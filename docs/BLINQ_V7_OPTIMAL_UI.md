# BlinQ v7.0 — Optimal public UI rebuild

This release intentionally rebuilds the public presentation layer without changing the core BlinQ product model.

## Product structure

- top product navigation with theme, plans and profile
- three compact admin-configurable promo/CTA slots
- one rotating hero area
- adaptive public dashboard grid
- dedicated Results and Overview routes rather than dashboard side-panels
- Overview remains the place for match/player search and filters

## Dashboard behaviour

The dashboard uses the enabled prediction sections only. Prime, Top, Value, Ace, Doubles and Sets/Games remain independent admin-controlled sections. Disabled sections leave no visual hole; the remaining cards reflow through the existing dashboard composition engine.

Each dashboard section is a single surface. It no longer looks like a small card embedded in a second oversized panel. The dashboard preview intentionally focuses on one primary item per section; the route-level page remains the full list.

Locked access is rendered as an in-card premium gate. The former permanent `Unlock with PRO` footer bar is not used as a large visual strip.

## Aces / double-faults

The UI does not invent bookmaker prices. When the feed exposes an actual market line via one of the supported line fields (`line`, `market_line`, `threshold`, `over_under_line`, `bookmaker_line`, `total_line`), the compact card can show an O/U interpretation and the line/gap/data metrics. Without a verified line, the existing projection-only presentation is retained.

## Light / dark

Light and dark are separate tuned palettes sharing one geometry. Light uses white/powder-blue surfaces and dark navy typography. Dark uses layered navy surfaces rather than a simple color inversion. The existing persisted theme switch remains unchanged.

## Responsive rules

- desktop: 3-column adaptive dashboard
- tablet: 2 columns
- phone: 1 column
- promo slots become a horizontal snap rail on small screens
- navigation remains horizontally scrollable when necessary
- match/player information remains readable and does not rely on desktop-only hover

## Brand assets

`assets/blinq_logo_light.png` is a light-theme variant derived from the existing BlinQ logo asset so the brand remains readable on pale surfaces. The original SVG stays in use for dark mode.

## Kept intact

- authentication/session logic
- role vs plan semantics and admin bypass
- plan/access manager
- dashboard section on/off logic
- hero/header content manager
- Overview access rules
- Results route
- banner analytics/tracking
- account/admin routes

## Validation performed

- `node --check web/app.js` — PASS
- static light desktop visual render — inspected
- static dark desktop visual render — inspected
- static light mobile visual render — inspected
- selected legacy UI/access tests: 31 PASS; 3 legacy assertions fail because they hard-code older UI revisions/navigation ordering and are not runtime failures.
