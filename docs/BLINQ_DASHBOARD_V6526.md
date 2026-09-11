# BlinQ v6.5.26 — adaptive six-panel dashboard

- Dashboard pick area is now a dedicated six-position responsive grid.
- Included dashboard modules: Prime, Top, Ace, Value, Doubles, Sets/Games.
- Results and BTTS stay dedicated routes and do not consume dashboard positions.
- Disabled/hidden modules no longer leave empty holes. Remaining modules expand by active count:
  - 6: 3 × 2
  - 5: 3 + 2 wider
  - 4: 2 × 2
  - 3: 3 across
  - 2: 2 across
  - 1: full width
- Tablet: 2 columns, odd final card spans full row.
- Mobile: 1 column, no artificial spanning or horizontal overflow.
- Empty and locked panels use the premium light/dark visual system instead of large grey dead zones.
- Intentional section OFF state is respected; empty enabled sections remain visible as clean empty states.
