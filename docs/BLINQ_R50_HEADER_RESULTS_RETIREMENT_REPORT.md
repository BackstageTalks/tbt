# BlinQ 7.3.6-r50 — Header, Upgrade modal and Results settlement polish

## Scope

- Desktop header action rail no longer has a surrounding boxed background/border.
- Header membership CTA is again a green-highlighted `Upgrade` button and the external-arrow glyph is removed.
- LIVE / INFO / account controls are slightly larger on desktop.
- Generic membership modal removes duplicate helper copy/badges; locked-context requirement badge remains.
- Match-winner Results visually highlight the actually published selection instead of always emphasizing player 1.
- Provider-proven non-standard terminations (retirement, walkover, abandoned/interrupted/suspended/cancelled/postponed) settle match-winner publications as VOID, not win/loss.
- A retirement is rendered as `SKREČ` in SK/CZ Results and does not enter hit-rate / ROI denominators.

## Verification

- `python scripts/audit_repo_contract.py` — PASS
- `node --check web/app.js` — PASS
- all frontend Node contract tests — PASS
- focused r47-r50 / Results suite — 27 PASS
- broad Python suite (excluding local Azure smoke dependency): 722 PASS, 1 skipped; 8 failures are the known local `pyarrow` dependency only.
