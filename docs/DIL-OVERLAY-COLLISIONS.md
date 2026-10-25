# DIL — full secondary overlay collision audit (25 Oct 2026)

Source: previously restored and SHA-confirmed immutable DIL SQLite (998,732 canonical matches; 50,805 rows in `dil_enrichment_compact`).

Run in read-only mode using `python scripts/audit_dil_overlay_collisions_20261025.py --dil /private/base.sqlite --report /private/new-report.json`. The audit rejects existing output reports. It never writes to CDB, DIL, API, or production.

Result for restored source: 50,805/50,805 overlay rows reference a real canonical match ID; **0 key-name overlaps** between overlay and existing canonical stats, hence **0 conflicting existing canonical metrics**. The JSON report is aggregate-only: `/mnt/data/DIL_REAL_OVERLAY_COLLISIONS_20261025.json`. Five regression tests passed.

**Do not equate this audit with current CDB-DIL parity.** Latest 78-part CDB was separately read-only verified via GitHub Actions run 40208558064 attempt 2, but the full physical match/stat comparison remains pending. Only a verified, private full current-source `refresh_dil_secondary.py` run may promote a *secondary-only* pointer; never switch primary DB.