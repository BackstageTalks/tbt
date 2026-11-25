# ITF gapfill: budget stop keeps progress (2026-11-26)
Run 45656748974 crashed on RequestBudgetExceeded (provider reserve 500), skipping report.json, so the upload step failed and progress was lost.
- scripts/itf_week_gapfill_stage.py: budget exception ends the run cleanly (stopped=budget), only fully finished weeks are written, checkpoint last_complete_week kept.
- itf-gapfill-stage.yml: max_requests optional (default 5000), clear error on invalid value.
Reserves and hard caps unchanged. Revert: revert this PR.
