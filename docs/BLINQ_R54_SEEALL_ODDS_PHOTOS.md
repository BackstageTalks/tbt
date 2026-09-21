# BlinQ 7.3.6 / 736-r54 — SEE ALL consistency, projection odds and player photos

**Baseline:** clean `736-r52` (the discarded r53 bookmaker experiment is not included).

## 1. SEE ALL table consistency

The old SEE ALL header used the normal 8-column Match Winner layout, while ACES / Double Faults / Games / Sets rows rendered 9 cells. That shifted projection/confidence values under the wrong headings.

r54 keeps SEE ALL on one 8-column contract:

`# · TIME · TOURNAMENT · MATCH · PREDICTION · ODDS · MODEL · ACTION`

- Match Winner / Short Odds / Value / Doubles rows use the MODEL cell for BlinQ probability.
- ACES / Double Faults / Games / Sets use the same MODEL cell for projection + projection confidence/data depth.
- Individual market tabs keep their dedicated Projection and Confidence columns.

## 2. Projection odds

Two different issues were fixed.

### False 0.00

JavaScript `Number(null)` equals `0`, so an explicitly missing projection price rendered as `0.00`. Projection rows now use nullable parsing and display `—` unless a real decimal price greater than 1 is present.

### Odds enrichment coverage

The backend still stays fail-closed: no synthetic odds are generated. r54 expands the real provider pass instead:

- the projection odds pass now uses the configured `market_odds_max_events` budget instead of silently truncating at the first 40 events;
- match-total aliases now recognize common provider names such as `Total number of sets`, `Number of sets`, `Total number of games`, etc.;
- nested provider envelopes whose market container is named simply `name`/`label` are handled without confusing priced outcome names with market names;
- ACES / Double Faults superiority markets accept additional exact winner-style wording such as `Who will serve more aces?` and `Player to make more double faults`;
- player-total Over/Under markets are still rejected for ACES/DF because the current BlinQ ACES/DF model predicts which player records more, not a bookmaker player-total line.

Where the provider exposes the exact compatible market, `odds`, provider metadata and publication snapshot are frozen normally and later appear in Results. Where it does not, the UI shows `—`.

Historical projection publications that were issued without a real captured price are intentionally not repriced after the match.

## 3. Player photos — Predictions + Results

Both Predictions and Results continue to use the same central `playerPhotoSource` / `playerAvatarHtml` renderer.

r54 adds:

- extra compatible photo/image field aliases;
- cache-busting for local `/assets/players/*` and `missing_foto_*` assets using the current web patch;
- the same versioned local fallback path after a failed player image;
- deterministic ATP/WTA fallback artwork instead of stale cached 404 -> initials behavior.

This targets the grey initial circles visible for players such as Lorenzo Beraldo / Leandra Nizetic in the supplied screenshots.

## Validation

- repository contract audit: PASS
- `node --check web/app.js`: PASS
- frontend runtime contract: PASS
- auth cross-tab race: PASS
- Firebase web auth contract: PASS
- Firebase verification contract: PASS
- UI regression contract: PASS
- focused r51/r52/r54 projection + photo + responsive tests: PASS
- broad Python suite in this environment: **741 passed, 1 skipped, 8 deselected**
- the 8 deselected tests require optional `pyarrow`, unavailable in this sandbox
- Azure smoke collection also cannot run here because `azure.functions` is not installed and outbound package installation is blocked
- Playwright browser runtime is installed, but navigation to the internal `blinq.test` host is blocked by this execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`)
