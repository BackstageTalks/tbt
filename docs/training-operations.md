# Protected training in one command

Run `python scripts/training_status.py` from the repository with an authenticated GitHub CLI account that can read both repositories. It finds the newest protected training run, reads its current attempt and independently checks the annotated writer lock. Use `--run 39144726241` to pin a run, or `--json` for machine-readable output.

The command only reads GitHub. It does not restart training, change a lock, consume provider requests or activate a model. An inaccessible or missing private lock is reported as UNVERIFIED, never as permission to start another writer.

If EXECUTING, let the existing workflow continue. If BLOCKED, inspect the failed step before retrying; never delete an unverified lock. WORKFLOW_SUCCEEDED means the workflow finished, not that the model is ready to deploy.

Before release, independently read back the candidate and compare it with the pinned champion and 7.1.1. Require ATP/WTA metrics, calibration and stability, and TOP evidence at real pre-match odds >= 1.50 (sample size, hit rate, ROI and uncertainty). Production activation still requires explicit owner permission.
