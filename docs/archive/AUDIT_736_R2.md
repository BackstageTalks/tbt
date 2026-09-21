# BlinQ 7.3.6-r2 — audit / repair pass

This patch intentionally keeps the public release contract at 7.3.6 / asset revision 7360. Changed assets use an extra `p=2` cache-bust query so production receives the repaired JS/CSS without breaking the existing CI release checks.

## Root causes fixed

### 1. Loader was accidentally made static
`final-polish-736.css` replaced the animated SVG with a full-screen static WebP and clipped the real loader card to 1x1 px. The patch restores `/assets/blinq_loading_animated_v6.svg`, which already contains the rallying tennis ball animation, while keeping a clean dark BlinQ background and no outer box.

### 2. Image fallbacks were incompatible with the CSP
Tournament logos, flags and some player photos relied on inline `onerror=` handlers. The deployed CSP has `script-src 'self'` and does not allow inline event handlers, so the browser could show broken-image icons instead of the local fallbacks. Fallback handling is now installed centrally through a normal JavaScript error listener and works for:
- player photos -> `missing_foto_m.webp` / `missing_foto_w.webp`
- tournament logos -> local tournament family fallback SVG
- country flags -> text fallback

### 3. Tournament identity was mixed into the match cell
Results now have a dedicated `Turnaj` column. Tournament logo/name are grouped together and location is rendered as a separate secondary line only when explicit location data exists. Historical labels such as `Tournament, Country` are split conservatively; draw labels such as `Group D` are not treated as locations.

Backend prediction rows now expose explicit provider tournament/venue city/country fields when available. No geocoding or name guessing is added.

### 4. Upgrade cards had duplicated / overlapping copy
Repeated plan description text is removed, the required-tier pill is moved into normal document flow, avatar pairs and text sizes are normalized, and the cards keep a stable responsive grid.

### 5. Footer LIVE wording was too aggressive
The visible footer now reports data freshness (`Dáta synchronizované`, `Posledná aktualizácia`, `Čaká sa na aktualizáciu dát`) rather than advertising `LIVE radar aktívny · práve teraz`. The LIVE freshness signal remains available internally for diagnostics.

### 6. Previous 7.3.7 attempt broke the release contract
The repair does not bump the release to 7.3.7. The repository remains internally consistent at UI `7.3.6`, frontend marker `blinq-web-736`, asset revision `7360`; changed `app.js` and `final-polish-736.css` get `&p=2` for cache busting.

## Verification performed
- `node --check web/app.js` PASS
- `node --check web/auth.js` PASS
- `node --check web/responsive.js` PASS
- `python -m compileall -q api scripts` PASS
- focused regression/UI/engine suite: **102 passed**
