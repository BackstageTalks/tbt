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

## Extended conflict diagnosis — 14 Oct 2026 (read-only)

Run [#38537392573](https://github.com/BackstageTalks/tbt/actions/runs/38537392573) passed against the same SHA-pinned 2025 original source files and historical CDB snapshot. The expanded regression diagnosis distinguishes **source rows losing every old proxy candidate** from **individual old candidate edges rejected despite other candidates surviving**.

- Exactly **44 source rows** lost all their old strict-name matches; these are included in the broader **193 source rows** where at least one legacy candidate edge was rejected.
- **197 old candidate edges** rejected by the v2 checks: **177 winner-side conflicts** and **20 ambiguous player-side orientations**. Breakdown by file: ATP Tour 1 winner + 1 ambiguous, ATP Futures 74 winner + 11 ambiguous, ATP qualifying/Challenger 30 winner, WTA Tour 8 winner + 2 ambiguous, WTA qualifying/ITF 64 winner + 6 ambiguous.
- The diagnostic explains **why the v2 research matcher rejected** an old proxy edge; this does NOT establish which independent source is factually correct. Neither the 44 old-only source rows nor the 197 rejected old edges may be automatically rescued into CDB.
- Full-year candidate and conflict metrics remain as above; the new diagnostic adds classification, not additional source or CDB facts.

## Official event/both-player witness intake (shape-only)

`scripts/research/identity_v2_witness_preflight.py` and `tests/test_identity_v2_witness_preflight.py` introduce a **source-scoped, SHA-pinned, two-player provider witness preflight**. It checks source row coordinates vs native provider event IDs, original lineage claims vs source lineage, exact source/canonical pair orientation and winner, candidate official played date, independent source/CDB digest consistency, duplicate witness submissions and collisions between provider/native/canonical event and player mappings.

**Critical limitation:** the preflight validates the structure and internal consistency of the provided evidence *claims*. It does **not** retrieve or cryptographically validate the official provider originals or prove the caller's claimed lineage is truly independent. All apparently consistent rows remain `witness_shape_consistent_for_PRIVATE_review`, not `identity_verified`. Zero matches are independently attested by this new code alone.

The existing `scripts/verify_tml_event_witnesses.py`, `scripts/build_cdb_verified_player_crosswalk.py` and `tbt-data/scripts/research/reconcile_l2_identity_bridges.py` remain the authoritative *separate* evidence/audit contracts to reuse. Do not replace their stricter checks with a new surname/score heuristic; all writers remain untouched.

The next valid evidence step is a pinned original official event and both provider player IDs, with independently verified upstream provenance and permitted data use, and a current canonical snapshot and NULL-only comparison. This remains review-only until explicitly authorized and the existing writer gate is independently satisfied. This PR is still DRAFT and shall not be merged/deployed as an importer.

## Read-only research gateway closeout — 14 October 2026

**Purpose:** Close the code/research phase of the five-step Identity V2 plan while explicitly isolating *unproven canonical identity* from *proposed match candidates*. The canonical CDB remains unchanged and is not replaced by a proposed new database.

### Shared staged entrypoint

- `scripts/research/identity_v2_gateway.py` exposes a bounded common read-only discovery API, `stage_sackmann`, `stage_season`, `stage_native` and `stage_canonical_context`. Gateway states: `no_research_match`, `research_unique_weak_context`, `research_unique_strong_context`, `research_ambiguous_quarantined`, `source_context_overflow_quarantined`. **Every state always has `identity_verified=False`, `cdb_write_authorized=False`.**
- `identity_v2_stage.py` accepts SHA-pinned CSV or JSONL for `sackmann`, `season`, `canonical` and the new `native` source kind, with optional explicit field mapping for source-native IDs. Source rows with missing provider event ID or any participant ID go to *source-only quarantine*; a filename, surname, score, fixture position or row line number cannot replace provider-issued identities.
- `shadow_sackmann2025_vs_cdb.py` now uses the same shared gateway as the native source adapters. Real historical replay must preserve all previously verified counts, with zero canonical writes.
- `identity_v2_editions.py` treats season/tour/draw/discipline/competition level and SHA-backed aliases as research context only; it is NOT an official tournament edition registry. `identity_v2_triage.py`, `identity_v2_loss_diagnosis.py` and `identity_v2_witness_preflight.py` provide risk-based review categories, negative evidence and independently claimed official provider ID preflight. None verifies a source merely because a JSON object says “official”.
- `identity_v2_private_review.py` optionally prepares an exclusive local-only private review pack with `0700` parent and `0600` file permissions and refuses GitHub CI. Do NOT upload, commit or expose this package.
- `BackstageTalks/tbt-pro` is *obsolete*; it remains a read-only historical data and alias archive, **never an active implementation/runtime dependency**.

Example, using a private SHA-pinned source **without** CDB writes:

```bash
PYTHONPATH=. python scripts/research/identity_v2_stage.py \
  --source /secure/native-originals.csv \
  --source-sha256 '<actual 64-hex SHA256>' \
  --format csv --kind native --tour atp \
  --collection 2025 --source-name example-official-feed \
  --date-kind played --max-rows 100000
```

For different column names use `--field-map-json` with explicit source-field mappings. Match rows missing native IDs remain quarantined. CSV/JSONL are the supported direct on-disk formats in this pilot. XLS/XLSX, ZIP, Parquet and other formats require their own *provenance-preserving conversion/adapters*, not silent acceptance based on a filename.

### Measured research results and meaning

Same five **byte-SHA-pinned 2025 Sackmann sources**: **56,889 input source matches** versus immutable `history-2025.parquet` (**90,571 canonical matches**, SHA-256 `3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58`). Old strict normalized-name proxy found any candidate for **44,057** source matches; v2 found candidates for **45,613**. There are **1,600 v2-only** source matches, **777** old-unique-now-ambiguous, **44** old-only, **936** changed candidate sets where both find something. These are discovery counts, **not ground-truth precision** or CDB NULL coverage.

Of **197 individual old candidate edges rejected**, **177** conflicted on winner orientation and **20** had ambiguous player-side orientation; these affected **193** source matches, of which **44** lost all old candidates. Old-only count and rejected-edge count are different denominators. Strong tournament-label/round/winner context is *not* independently verified provider event identity.

### Go/no-go: explicitly NOT satisfied for production imports

A future governed canonical import requires **all** of:

1. Independently retrieved/checksummed original *provider-issued event ID and both provider-issued player IDs* including documented upstream lineage, unambiguous source-to-provider row/ID bridge, and no many-to-one/one-to-many collisions. Witness format checks alone do not prove external provenance.
2. Authoritative year/tour/level/draw-specific tournament edition identity with verifiable aliases, consistent exact result/winner/round/date semantics, resolution of ambiguous Futures events and all disputed old-only cases.
3. Per-source reuse/licence review, observed-at timestamp and prediction-time / post-match leakage separation (especially odds versus later match statistics).
4. Fresh exact **CURRENT canonical partition manifest and SHA verification**, actual NULL-only field delta, nonconflicting observation semantics and global writer exclusive lock, CAS, verified durable backup/restorability and post-write readback.
5. A human/authoritative independent **positive-and-negative golden set**, including the 763 high-risk Futures newly ambiguous matches. Demonstrate recall **and false positives** versus source originals; do not infer correctness from candidate count. Full cross-year/ATP/WTA and source-family shadow A/B after official evidence is available.
6. **Separate explicit production authorization** after all checks and a dry run. This read-only PR must not activate or bypass `tbt`/`tbt-data` governance or start a model training/deployment.

**Current decision:** research code and reproducible 2025 pilot may be archived/merged with an explicit `[audit-only]` no-deploy merge title after green checks, but enabling ANY production importer is **BLOCKED by independent official identity evidence/rights/current-CDB NULL gate**. All claimed verified new CDB identities in the pilot: **0**. New CDB writes: **0**.

