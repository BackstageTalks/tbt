# Longer cache for finished matches (2026-11-26)
Finished match data never changes, so repeat paid calls are wasted quota.
- tennis_response_cache: finished_statistics 30 -> 180 days, finished_detail 1 -> 30 days.
- private_tennis_cache max-age cap 30 -> 180 days; statistics_enrichment reads with 180 days.
Empty statistics and unfinished details are still never cached (unchanged), so missing data is retried as before.
Revert: revert this PR (original values: 30*86400, 86400, cap 30*86400, max_age=30*86400).
