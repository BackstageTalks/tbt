# BlinQ repository audit — v7.2.4 final UI polish

## Scope

This release keeps the v7.2.3 data/LIVE/media/push backend intact and performs a final production UI pass on the member dashboard and footer configuration.

## Header / top navigation

- Unified control height and spacing for navigation, Upgrade, LIVE, INFO and profile controls.
- Refined dark-glass header treatment with restrained green accents and clearer active navigation.
- Improved logo scale, alignment and visual hierarchy without changing authentication/session behavior.

## Prediction board

- Tournament cells now use the existing `tournamentVisual(row)` pipeline, preferring provider tournament logos and falling back to the local tournament family assets.
- Country flags remain real local flag assets and are presented at a consistent size.
- Player presentation changed from cramped horizontal text to a two-line match stack with flags, optional rankings and a clear picked-player accent.
- Column headers and widths are market-aware (TOP/VALUE vs ESA/GAMES/SETS).
- Prediction, odds/projection and confidence are visually separated into label/value groups.
- Confidence receives a compact progress meter for fast scanning.
- Rows, dividers, action buttons and tab states were rebalanced for a denser professional analytics-board look.

## Footer / benefit rail

The former four marketing boxes are now a lightweight configurable link rail. Each of the four entries has only:

- title,
- description,
- URL/link.

An empty URL leaves the item informational/non-clickable. External links receive an external-link affordance; internal links remain same-site navigation.

The Admin editor for this rail no longer exposes irrelevant banner image/audience controls.

## Responsive behavior

The final CSS layer includes desktop, medium-width and mobile rules so the new table/header treatment does not make a later mobile adaptation harder. Dense board columns remain horizontally scrollable instead of collapsing into unreadable cards.

## Validation

- `node --check web/app.js` — PASS
- `node --check web/auth.js` — PASS
- `python -m compileall -q api scripts` — PASS
- Final UI + launch/media/content contract suite — PASS (32 tests before release metadata bump; rerun in packaging step)

Browser screenshot automation was not available in the sandbox because local `http://127.0.0.1` / `file://` navigation is blocked by the execution environment. The changes were therefore validated through source inspection, syntax checks and automated UI contracts rather than a headless-browser screenshot.
