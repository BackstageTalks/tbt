# BlinQ v7.3.6 — approved upgrade/loading visual pass

v7.3.6 builds directly on v7.3.5 and applies the approved BlinQ visual direction without removing the access-control, storage or deployment-integrity work already present.

## Applied

- Full-bleed loading scene; the previous heavy outer loading square is removed.
- New `blinq_loading_scene_v736.webp` asset with a compact ~89 KB production payload.
- Header Upgrade opens a complete membership chooser, not a single-plan prompt.
- Locked content uses the same chooser while marking the plan required by the locked section.
- Upgrade chooser always exposes PRO, ELITE, LEGEND and GOAT, with plan-specific CTAs.
- Legacy purple UI blocks in membership/account controls are overridden by the current dark teal/green BlinQ system; plan artwork may retain tier-specific colors.
- Account/profile membership controls are visually aligned with the new upgrade chooser.
- Existing v7.3.5 Rookie random-pick/access rules, Support/INFO storage fallbacks and v7.3.4 deployment rollback protection are preserved.

## Release markers

- HTML: `data-web-release="7.3.6"`
- Footer: `UI 7.3.6`
- CSS: `final-polish-736.css?v=7360`
- Release marker: `blinq-web-736`
