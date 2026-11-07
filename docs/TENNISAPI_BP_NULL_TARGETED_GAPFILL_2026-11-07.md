# BlinQ TennisApi PRO – CDB break-point gapfill completion (2026-11-07)

## Authoritative goal and evidence

Operator goal: maximize verified ATP/WTA 2016–2026 CDB serve/return/break-point enrichment while using the shared 15,000/day TennisApi PRO quota effectively. Fixed provider reset **17:09 UTC**; preserve 500-request reserve, global shared **14,500** practical ceiling, max 6/s and writer lock. Do not alter model 7.2.1, unrelated work, bookmaker-as-of semantics or local ace-odds statistics.

Validated 2026-11-07 live source/CDB audit:
- [GitHub Actions #42371965059](https://github.com/BackstageTalks/tbt/actions/runs/42371965059): 10 paid requests, 165 raw event occurrences, 109 unique valid ATP/WTA singles, 98 strict native-id/day/tour/player-pair/winner CDB links, 11 unlinked source IDs (NOT authorized net-new), 0 conflicting native source IDs. CDB 2023/2026 bundle SHA independently read back unchanged.
- Within the 98 exact linked rows **130** NULL `break_point_return_win` cells plus **66** NULL `break_point_serve_win` cells. This is a missing-cell inventory, **not** proven provider availability or an import commitment.
- 2026 daily odds index gave 993 native keys for one call, 782 with *some* CDB native claim; 0 pre-match historical quote timestamp attestations. No bookmaker or ML changes approved.

## Implemented isolated fix

Prior main targeted statistics queue `TARGET_FIELDS` contained only `service_points_won`, `return_points_won`, `aces`, `double_faults`: BP-only NULL rows were skipped. New `--break-points-focus` selects only NULL `p1/p2_break_point_serve_win` and `p1/p2_break_point_return_win`. It calls the **existing** `StatisticsEnricher` and native `/api/tennis/event/{id}/statistics` route; its validated ALL period maps `breakPointsSaved` → serve BP win rate and `breakPointsConverted` → return BP win rate. No novel writer, no inferred BP counts.

Safeguards: exact native event ID, finished home/away identity, existing conflict quarantine, retry cooldown, isolated manual mode (not normal adaptive hourlies), local cap 500 requests including retries. Strict control over manual GitHub `workflow_dispatch` and scoped `[data-request]` JSON: source tennisapi1, mode statistics, targeted true, no high-yield interference, no model promotion, explicit CDB NULL-only permission. Existing publisher uses global writer lock, backups, previous-value precedence, checkpoint and independent `verify_targeted_statistics.py` read-back.

Reproduction after merge from authenticated runner:
- CI: `python -m pytest -q tests/test_tennisapi_breakpoint_focus.py tests/test_targeted_statistics_gapfill.py`
- Manual controlled: `mode=statistics`, `break_points_focus=true`, `max_requests<=500`, `promote=false`, `start/end` limited to target historical windows. The measured API request cap is hard; unknown shared usage is not zero.
- Review `statistics_gap_plan.json` and `download_report.json` for eligible / rejected / requests / paid net-new stats, then inspect `statistics_expected.json`, `statistics_readback.json` and independent CDB snapshot hashes.

## Hard boundaries, not yet claimed

Eleven native event IDs without a CDB claim are **review candidates** only; do not invent match identity, overwrite existing IDs or count as imported rows. The 196 missing BP cells are a baseline. Real added cells and their CDB persistence must be established with the actual importer and independent read-back **after** the first production run. If provider offers no ALL-period BP values, record reasoned unavailable/cooldown, not paid success.

Release statuses must distinguish code merged, running import, completed stats publication, and independent persisted CDB readback. A green CI does not prove import.
