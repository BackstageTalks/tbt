# BlinQ r49 – Visual / Sets & Games cleanup

Release identity: `7.3.6 / 736-r49` (asset revision `7360`, cache patch `p=49`).

## Functional changes

- Sets projections now represent the expected **total number of sets in the match**, not the probability/direction score of one side.
  - New SG model contract: `sets-games-projection-v4`.
  - Public Sets rows carry `projection_unit = sets`, a reference line (typically 2.5 for BO3), a total-set projection and a separate direction confidence.
  - A consistency guard prevents a displayed total-set projection from contradicting the published Over/Under side.
  - Legacy v3 BO3 rows are converted for presentation so existing stored rows no longer render misleading values such as `0.9 Sets`.
- Games keep the existing total-games projection and are presented in the same result layout as Sets.
- The combined `Sets & Games` result filter was removed from the visible Results UI; `Sets` and `Games` remain separate.
- Doubles EV remains calculated/stored for analysis but no longer blocks publication. Data/history/probability/odds filters remain unchanged, including `data_depth >= 0.35`.

## UI cleanup

- Player-photo lookup in Results now uses the full source/fallback helper before falling back to local gender fallback/initials.
- Anti-share branding is reduced to one subtle bottom-right BlinQ watermark; duplicate/footer/extra-page marks are disabled and Admin remains watermark-free.
- Admin → Accounts → Telegram nickname now places the Telegram icon in the field label instead of over the editable text.

## Verification

- Repository contract audit: PASS.
- Focused SG/Doubles/r46/r47/r30 tests: 27 PASS.
- r49 contract tests: 6 PASS.
- Frontend Node contract/runtime tests: PASS.
- Broad Python suite available in the local environment: 717 PASS, 1 skipped, 8 deselected (the 8 require local `pyarrow`; the local environment also does not provide `azure.functions`).
- `node --check web/app.js`: PASS.
- `node --check web/auth.js`: PASS.
