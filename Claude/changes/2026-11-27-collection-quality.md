# Hourly autofill: collection quality metrics (Codex patch 41)
After each hourly statistics run: calls per endpoint, HTTP outcome (200 data / 200 empty / 404 / error), new matches, filled fields, conflicts, yield per 1,000 calls -> run artifact + 14-day overview in Admin → Systém. No new API calls; limits unchanged. Cache hits not counted separately yet.
Revert: revert this PR.
