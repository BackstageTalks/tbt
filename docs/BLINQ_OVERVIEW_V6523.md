# BlinQ v6.5.23 — Overview

New public route `#overview` shows all published upcoming matches for a selected day using the authenticated serving feed.

Displayed data comes only from existing feed fields: scheduled time, tour/tournament/round/surface, both player probabilities and rankings, model pick and probability, verified match-winner odds/edge/EV when present, data depth / surface-history coverage, and section tags (Prime, Top, Value, Doubles, Aces, S/G).

The page includes day, tour, surface and category filters, player/tournament search, sorting by time/confidence/odds/EV, and opens the existing match detail dialog for signals and market snapshot details.

Responsive behavior: desktop uses a compact table; tablet/mobile turns each table row into a readable card without horizontal scrolling.

Access is managed in Admin → Sections & access → Other pages. Default release policy is ROOKIE/TRIAL locked and PRO/ELITE/LEGEND/GOAT open, so all-match predictions are not accidentally exposed to free access.
