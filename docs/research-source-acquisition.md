# BlinQ research source acquisition

This workflow preserves research-only source snapshots in the private `tbt-data` release `tbt-research-sources-v1`.

It intentionally does **not** change canonical history, production predictions, or the serving model. Every bundle is pinned or hashed and the generated manifest records license/provenance plus sources that were intentionally not downloaded.

Current acquisition set:
- Sackmann ATP weekly rankings + players.
- Sackmann WTA weekly rankings + players.
- Sackmann Grand Slam point-by-point archive.
- Valuebetennis 2021-2026 raw market history when the public source is reachable.

Sources with unclear permission, source-term restrictions, or approval requirements are recorded as unavailable/deferred rather than scraped.
