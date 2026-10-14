# BlinQ Identity V2 — real 2025 shadow comparison

**Status:** READ-ONLY RESEARCH VERIFIED for the specified pinned inputs; **NOT a canonical CDB importer**.  
**UTC date:** 2026-10-14  
**Branch:** `feat/identity-v2-readonly-shadow-20261014` (PR #727, draft)
**Authoritative run:** [GitHub Actions #38530994975](https://github.com/BackstageTalks/tbt/actions/runs/38530994975) (read-only SHA pinned source/CDB shadow, success).

## Sources and reproducibility

- Five original Sackmann ATP/WTA 2025 source files at public mirror SHA `83733587353df8a41f2fd4f516147d5aa83f5a8d`; individual per-file SHA-256 checked by workflow and Python input reader.
- **56,889 original source rows, all included** (`--sample-mod 1`), spanning ATP Tour, ATP Futures, ATP qualifying/Challenger, WTA Tour, WTA ITF/qualifying.
- Canonical `tbt-data-v1/history-2025.parquet`, pinned SHA-256 `3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58`, **90,571 rows**. The run verified its byte SHA and row count. This is a pinned historical snapshot, not proof that CDB did not subsequently change.
- Research comparator compares normalized name/initial candidates and date semantics across exactly those inputs. It does **not** execute every historical production importer.

## Complete source-year measurements

| Metric | Old normalized-name proxy | New research resolver |
|---|---:|---:|
| Source rows with ≥1 candidate | 44,057 | 45,613 |
| Source rows with exactly 1 candidate | 41,687 | 42,597 |
| Source rows with >1 candidate | 2,370 | 3,016 |
| Newly found where old found none | — | **1,600** |
| Previously found where new found none | — | **44** |
| Previously unique, now ambiguous | — | **777** |
| Candidate sets differ, both nonempty | — | **936** |
| Exactly same one-event match in both | — | **40,866** |

New-only by family: ATP Tour **60**, ATP Futures **1**, ATP qualifying/Challenger **232**, WTA Tour **107**, WTA qualifying/ITF **1,200**. Of 1,600 new-only cases, 1,588 have one candidate, 12 have more than one. These are *candidate counts*, not independent confirmed identities.

## Edition-context evaluation

A new `context_tier` conservatively marks a candidate `edition_context_strong` only when explicit tournament labels, round and winner-side orientation agree. Other candidates remain `unresolved_event_edition`; **both** have `identity_verified=false` and `cdb_write_authorized=false`.

- Strong edition-context candidates found for **6,548** source events.
- **6,526** events have exactly one such strong-context candidate.
- **22** events have multiple strong-context candidates.
- **39,065** newly discovered source matches have only weaker/unresolved edition context.
- Of the **1,600 newly discovered** cases, only **10** currently have one strong edition-context candidate; the remaining cases need stronger tournament/edition identity validation.

This is expected to be conservative: equivalent ATP/WTA event names may differ radically across providers. Do **not** treat a missing exact tournament label as a disproof; do **not** treat a similar event label as independent evidence either.

## Principal risks and constraints

1. Futures dates/names may reuse the same player pair and round across different editions. **777** old unique candidates become ambiguous with broader discovery, predominantly Futures (**763** of the 777); no automatic winner/venue promotion permitted.
2. `tourney_date` is an event-start date, whereas CDB `scheduled_at` is a match timestamp. The research comparator allows bounded forward search and records source date semantics.
3. A normalized surname/initial pair is not a stable provider ID crosswalk; a matching numeric ID in two providers is also not a crosswalk.
4. Missing verified tournament aliases across sources prevents confident edition matching. A source-specific **curated, provenance-backed tournament edition registry** is recommended next.
5. For doubles/mixed, the v2 adapter explicitly refuses unverified two-person representation of four-player teams, pending explicit verified team/roster identity design.
6. Historical odds/CLV require a provider-observed prestart quote timestamp; post-match boxscore features must not leak into the same match prediction.
7. Individual cross-provider canonical event and both-player witnesses, source rights, PIT and current NULL-delta gates remain unproven. **0 verified new CDB cell write candidates** and **0 CDB writes**.
8. `tbt-pro` is an obsolete archive: data/aliases may be researched without integrating old runtime or altering the archived repository.

## Next implementation gates

- **P0:** Manual or authoritative provider-backed positive/negative golden set, especially 936 candidate-set differences; do not optimize match count at the expense of precision.
- **P0:** Tournament edition registry with scoped tournament IDs/year/draw/tour and dated sponsor aliases. Prove associations using native source identifiers and independent trusted evidence, not co-occurrence of names alone.
- **P1:** Add source adapters for current LiveTennisAPI and Match Charting plus explicit doubles teams; run shadow replay against each real source family.
- **P1:** Promote independently validated player crosswalks to a shared immutable read-only registry. Reuse existing `build_cdb_verified_player_crosswalk.py` evidence gates and existing `tbt-data` independent witness validation; never infer source ID equivalence from strings.
- **P2:** Only after separate approval and 78-partition SHA proof, governed writer validation with single lock, compare-and-swap, NULL-only field writes, rights, backup/rollback and independent post-write readback.

No code from obsolete `tbt-pro` has been imported. No production import, model operation, web deployment, or Drive change is part of this PR.
