# BlinQ v7.1.6 — missing history manifest recovery

Adds an explicit `history-manifest-repair` maintenance mode for the fail-closed state:
`Required history manifest is missing: history_manifest.json`.

The recovery downloads current `history-YYYY.parquet` release assets, validates rows and cross-partition identities, reconstructs the manifest without rewriting parquet data, rebuilds checksum coverage, then verifies a normal ReleaseStore download.

It uses zero Tennis RapidAPI requests.
