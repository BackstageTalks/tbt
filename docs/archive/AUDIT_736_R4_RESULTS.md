# BlinQ 7.3.6-r4 — Results integrity repair

## Findings

1. The Results UI deduplicated by `selection_key` / `publication_key`. Historical ledger schemas can contain two bookkeeping keys for the same immutable event/market/selection, so the same match could render twice.
2. `filteredResults()` silently removed rows whose surface was exactly `unknown` even when the user selected **All surfaces**. A valid settled/public result must not disappear just because surface metadata is missing.
3. Backend betting metrics used the same schema-dependent publication keys, so legacy duplicates could also inflate record / hit-rate / ROI sample counts.
4. Serving results relied on incidental ledger ordering before applying the 1000-row cap. The ledger is normally sorted, but the public window should sort explicitly by `scheduled_at` to make this invariant robust.
5. Publication confirmation happens after Azure deployment. A transient release-store/network failure can leave an actually deployed feed unconfirmed until a later retry. All deploy workflows now retry confirmation three times while the match-start timing is still fresh.

## Repairs

- Added semantic result identity: event + market/projection + selection.
- One semantic bet now renders once even if legacy publication keys differ.
- Backend betting metrics apply the same semantic dedupe.
- Unknown/missing surface is included under **All surfaces**; it is only excluded when a concrete surface filter is selected.
- Public result rows are explicitly sorted newest-first before the 1000-row limit.
- `ci.yml`, `data.yml`, and `player-enrichment.yml` retry post-deploy publication confirmation up to 3 times.
- Release remains `7.3.6 / 7360`; patch/cache marker is `736-r4 / p=4`.

## Important historical limitation

The patch never invents or backdates a publication. If a past match has no auditable issued market publication at all, it remains absent until the private ledger/deploy evidence is reconciled. This is deliberate point-in-time safety. Rows that were merely hidden by the old `surface == unknown` filter will reappear automatically after this patch.
