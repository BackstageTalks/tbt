# BlinQ — competition eligibility and end-to-end audit (2026-11-17)

## Goal and approved scope
- TOP / match winner: ATP/WTA main tour first, ATP Challenger second. Exclude WTA 125, all ITF categories (including W100), UTR, juniors, exhibitions. Keep calibrated probability floor 60%, preferred three picks, maximum five, never force fill.
- ESÁ + VIAC ES: women's events only with positive WTA 250/500/1000, WTA Finals or Grand Slam grade evidence; fail closed on WTA 125, ITF and ambiguous generic WTA. ATP/Challenger remains on existing rules and both player ranks must be verified TOP-1000.
- Frozen already-issued 2026-11-17 picks remain unchanged; WTA grade gate for new offers starts at 2026-11-18 06:00 Europe/Bratislava (2026-11-18T05:00:00Z). Do not backfill or retroactively regrade.
- No adjustments to model/calibration, prices as model inputs, CLV, CDB, raw data, historical Results or Telegram send ledger.

## Verified baseline and evidence
- Before edits: PR #1687 CI at SHA `3f803c5efabcf4088538b4dfe89670cb929380ae` passed 5,443 Python tests, plus UI/contract checks. Run: https://github.com/BackstageTalks/tbt/actions/runs/44061858998
- Source coverage from private read-only `tbt-data/audit/high-impact-latest.json` (2026-10-04): ATP 250,956 / 510,107 completed matches with any stats (49.2%), WTA 89,259 / 375,386 (23.8%); quality-capable 43.3% ATP, 17.3% WTA. **Not a WTA 125-versus-WTA250 point-in-time breakdown.** Insufficient evidence to include WTA 125 in TOP.
- 2026 source availability audit `tbt-data/audit/import-preparation/DRIVE-SOURCE-QUALITY-2026-CHALLENGER-WTA-ATP-20261011.json`: source-native serve-stat complete Challenger 4,296 / 4,311 strict source match identities, WTA 1,112 / 1,295. These are NOT actual current CDB integrated values nor verified pre-match data coverage.
- Production 2026-11-17 read-only quote/offer audit: https://github.com/BackstageTalks/tbt/actions/runs/44059750084. At 2026-11-17T09:53:56Z, 6/6 offered ESÁ were independently found on website, 30 additional VIAC ES rows, web snapshot generation matched confirmed source, zero published picks changed, zero provider calls, zero CDB writes. **This proves baseline web presence, not new policy deployment or complete Telegram send parity.**
- Baseline 2026-10-04 TOP issued report `tbt-data/audit/market-quality-latest.json`: section grouped only ATP/WTA/Challenger/ITF and small samples. Grade-specific WTA125 calibration not available.

## Implementation references
- ESÁ/VIAC ES draft: https://github.com/BackstageTalks/tbt/pull/1687 — shared selector and web/TG filter, forward-only activation boundary, WTA tier tests and future website-vs-TG identity parity test.
- TOP draft: https://github.com/BackstageTalks/tbt/pull/1688 — disallow ITF globally from TOP, WTA125 and mislabeled female Challenger excluded, reject junior/doubles/exhibition before Challenger classification; sync UI policy v24 and morning preflight.
- Independent calibration work in draft PR #1669 untouched.

## Acceptance checklist and stop conditions
- [ ] Exact final commit SHA CI green in **both** PRs. Earlier green is not transferable across subsequent edits.
- [ ] Complete test summary checked, including TOP60/limit/ranking, WTA grades, legacy and next-day boundary, provider-free no mutation, website/Telegram same frozen selection, Results preserved.
- [ ] Fresh PR diff inspected for unrelated changes and conflicts against current main / PR #1669.
- [ ] Deploy only when frozen 2026-11-17 offer will not be changed; verify next 06:00 finalization barrier.
- [ ] Independent production read-back of deployed version, final feed offers and matching Telegram receipt identities; fail closed on disagreement.
- [ ] Check historical Results/KPI readback and no duplicate publication, no accidental CDB writes.

## Status and limits
Changes IMPLEMENTED on draft branches; not yet declared DEPLOYED or independently VERIFIED in production. Historical aggregate coverage numbers cannot prove specific WTA tournament-grade calibration. Provider/API budget used for this audit: zero; CDB write count by this task: zero. If deployment/readback tooling cannot access protected live source, preserve draft/rollback boundary and report the missing evidence instead of asserting completion.
