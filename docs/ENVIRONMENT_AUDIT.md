# Environment coverage audit

`.github/workflows/environment-audit.yml` is a read-only audit of the private `tbt-data-v1` history release.
It does **not** call TennisApi, Open-Meteo or Supabase and does not modify history.

The audit can run while environment enrichment is still active. Release downloads are checksum-verified; if the audit lands in the short interval between a parquet upload and the replacement bundle-manifest commit, it retries and reads the latest fully committed checkpoint.

The report includes:

- canonical completed match count after provider-event dedupe,
- environment object coverage,
- resolved venue coverage,
- weather object coverage,
- usable weather coverage (temperature + humidity + wind),
- indoor resolved matches where weather is intentionally absent,
- unresolved/missing counts,
- ATP/WTA and yearly breakdowns,
- top unresolved tournaments.

A JSON report and log are uploaded as a GitHub Actions artifact and key numbers are written into the workflow summary.
