# BlinQ repository audit — v7.2.5 UI carousel + ambient polish

## Scope

Built on v7.2.4. This release keeps the existing LIVE/INFO/data functionality intact and changes the banner management and visual shell only.

## Hero carousel

- Admin exposes exactly five fixed hero tabs: Banner 1–5.
- Admin controls the number of active banners from 1 to 5.
- The active range is deterministic: Banner 1 through Banner N.
- Automatic rotation is enabled when N > 1.
- Rotation delay is constrained to 3–10 seconds; default 6 seconds.
- Hover pauses rotation; reduced-motion still disables automatic animation.
- Public hero dots are restyled as a small premium progress control.
- Every banner keeps separate desktop/mobile image, editable copy and link.
- The existing binary image uploader now also supports the global site background field.
- Published UI values take precedence over static presentation defaults, so carousel count/delay persist across reloads.

## Background polish

- Homepage gets restrained teal/green ambient glows and subtle court/data geometry over the configurable background image.
- Admin gets its own calm dark teal ambient background and a very subtle grid/data layer.
- The admin route no longer has nested outer framing.
- The right admin work area is now one coherent bordered surface; its header and content panel no longer each create separate boxes.

## Validation

- New/current UI contracts: 14/14 PASS.
- Broad available suite: 425 PASS, 1 skipped.
- Remaining 8 failures are parquet-only tests requiring local `pyarrow`; no UI/carousel regressions were observed.
- Azure import smoke is not runnable in this sandbox because `azure-functions` is not installed; GitHub CI installs runtime requirements.
- `node --check web/app.js`: PASS.
- `python -m compileall -q api scripts`: PASS.

## Final UX addendum — same v7.2.5 build

- Footer now exposes feed freshness as `Aktualizované HH:MM · LIVE dáta aktívne` with a green operational dot; stale/error states change the indicator.
- Main board confidence cells include a compact `DATA DEPTH` indicator derived from `data_depth` or usable sample counts.
- Match details open as a right-side intelligence drawer on desktop and a bottom drawer on mobile.
- Winner (TOP/VALUE) details are restricted to winner-relevant evidence: model probability, ranking, current/surface form, surface/history sample, H2H, serve/return context, market context for VALUE and model signals. Ace averages and set/game totals are not inserted into winner detail.
- ESA keeps its own ace/double-fault projection detail.
- GAMES and SETS have dedicated projection detail cards with reference, projection gap, confidence, history/surface samples and DATA DEPTH; projection-only output is explicitly labelled as such.
- Comeback LIVE and the second-set model are visually separated: comeback state is the primary live signal, while `P(win set 2)`, live Set-2 odds, edge and EV are shown as a separate supporting signal only when available.
- Sticky table headers and restrained hover/tab/hero micro-interactions are reinforced.
