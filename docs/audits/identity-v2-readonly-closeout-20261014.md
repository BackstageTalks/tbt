# BlinQ Identity V2 — read-only engineering closeout (2026-10-14)

## Scope and immutable decisions

- **Canonical remains authoritative.** No direct write, release promotion, model training, website deployment or mutation of obsolete `tbt-pro` is part of Identity V2 research.
- A new candidate is a **search result**, never an independently verified source-to-CDB link. A strong event/tournament-context label is likewise **not identity proof**.
- Feature approval requires a separate **official original event identifier, both provider-native player identifiers, independent lineage and event/date/round/winner validation**. Source-native *row coordinates* are NOT provider-issued event IDs.
- All source rights, attributed origin, as-of/point-in-time rules, current complete canonical partition SHA, CURRENT NULL-field delta and a governed single-writer lock + rollback/readback remain distinct, mandatory production gates. Reusing existing validators is preferred to inventing duplicate weaker gates.
- **Sackmann source terms:** CC BY-NC-SA 4.0 (attribution, noncommercial conditions, share-alike); mirrors add no extra rights. A free site alone is not a completed case-specific compliance review. Other providers may have different terms. Never infer rights from public availability.

## Five requested capabilities — exactly what is implemented

| Requested capability | Audit-only implementation | Production activation |
|---|---|---|
| 1. One resolver for heterogeneous import sources | `identity_v2_gateway.py` and `identity_v2_adapters.py` with explicit scoped native IDs, dates and no-write research gateway; bounded input preflight | **BLOCKED**: legacy governed importers intentionally not rewired while source-native IDs and independent witness remain unproven |
| 2. Broad initial/alias/transliteration/formats discovery | `identity_v2.py` with source-specific names/aliases, Unicode and cautious fuzzy research keys | Research-only; no name-key identity authorization |
| 3. Independent source/event/player verification | `identity_v2_witness_preflight.py` and external existing `verify_tml_event_witnesses.py`, `build_cdb_verified_player_crosswalk.py`; collide/duplicate/winner/date safety tests | **BLOCKED**: preflight checks *claims/shape*, not independent byte-authenticated official provider originals for each disputed match |
| 4. Tournament editions, dates, rounds, scores | `identity_v2_editions.py` and `identity_v2.py`; source edition/date-kind, draw/season/tour/level, explicit score/retirement and side-orientation hard negatives | Doubles/mixed 4-player team identity not yet supported; never misrepresent 2 names as doubles teams |
| 5. Historical shadow old/new | `shadow_sackmann2025_vs_cdb.py`, SHA-pinned workflow, `identity_v2_triage.py`, `identity_v2_loss_diagnosis.py` | Verified candidate diagnostics are **not** an exhaustive comparison with all legacy importers and all CDB years |

## Reproducible prior snapshot (not current CDB)

Original 2025 Sackmann ATP/WTA 5-source inputs: **56,889 matches**. Immutable historical CDB 2025 parquet: **90,571 matches**, SHA-256 `3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58`. Test workflow checks every source file hash and this specific CDB hash before any comparison.

Research baseline (strict normalized name/date/round proxy) found 44,057 source rows with candidates. V2 found 45,613. New-only: **1,600** source cases, including **10** with a single strong edition-context candidate. Old-only: **44** cases. Old unique became ambiguous: **777** cases, including **763 ATP Futures**. Candidate sets differ in **936** source cases where both sides found candidates.

A second-pass diagnostic found **197 rejected original candidate edges across 193 source rows**: **177 winner-orientation conflicts**, **20 ambiguous side orientation**. It must not be confused with the 44 source rows losing every old candidate. None of these numbers are verified CDB enrichments.

Every currently reviewed cross-source new identity remains **unverified** and every canonical field write remains **unauthorized** by this project.

## Audit review priorities

1. **ATP Futures**: 763 old-unique-now-ambiguous cases, distinguish native edition/year/level/draw + independently issued match/event IDs; never rely on one-city/same-names assumptions.
2. **Regressions**: review 44 source rows losing all prior links and 197 rejected candidate edges against original independent provider results; never override winner conflict just to increase recall.
3. **Broader recovery**: 1,600 new-only research cases (esp. WTA ITF/qualifying), of which 10 have strong event context but 0 independently authenticated canonical event and both-player links.
4. **Independent golden set**: source-original verified ID pairs and provider lineage in private review; `identity_v2_private_review.py` exports only with explicit private local permissions and is **forbidden in CI**. Official evidence validation must be performed separately.
5. **Additional sources**: explicit provider-native adapters for odds, Match Charting and PBP; quarantine whenever source lacks actual native event **and both player** IDs. Doubles require four-player/team identity model and separate tests.

## What would genuinely qualify as *production complete*

A **new** separate review/PR, after positive and negative golden tests, must prove:

1. Original, independently validated provider event and both provider-player identities and nonconflicting one-to-one graph; at minimum a golden sample stratified across ATP Tour/Futures/Challenger and WTA Tour/ITF plus negative controls.
2. Source-by-source valid reuse/attribution/right-to-process decision; no one umbrella license assumption.
3. Frozen full current canonical release, partition/manifest SHA independent readback, complete input source hashes and versioned provenance.
4. Bounded field-level validated strictly-NULL CDB delta, identity/event/date/winner/score check, PIT restrictions, isolated preview with zero writes, and independent post-run readback.
5. Existing single-writer authorization, verified backup/restore and explicit user authorization for **any** governed production data migration.
6. Repeated full regression/precision/false-positive/ambiguity evaluation, no regression in API quota or live-model serving, and intentional deploy decision.

If any gate is absent, the correct status is **BLOCKED for production import**. Green CI of this read-only feature does not change that status.

## Source credit and licensing references

- Jeff Sackmann / Tennis Abstract, original GitHub tennis_atp and tennis_wta datasets, CC BY-NC-SA 4.0.
- Aneeshers/tennis-sackmann-archive mirror README and LICENSE (redistribution does not create rights).
- Existing canonical BackstageTalks/tbt-data identity and writer evidence/audit contracts.

No original tennis source CSV, sensitive CDB row, private case-level review list, credential or model artifact is checked into this PR.


## Final real-world acceptance evidence, 14 October 2026

**Audit-only implementation status: COMPLETE and merged. Third-party source → production CDB identity/writer status: BLOCKED pending independent evidence.** These are not contradictory outcomes. No date, label or name-based resolver may remove the writer gate.

### Runs and immutable original sources

- PR [#727](https://github.com/BackstageTalks/tbt/pull/727) merged the shared discovery and no-write identity research code; PR [#729](https://github.com/BackstageTalks/tbt/pull/729) merged a genuine test using existing original native ID sources. It also fixed an unrelated, time-expired account test **fixture only**, not account authorization business logic.
- Read-only genuine provider controls [#38548126831](https://github.com/BackstageTalks/tbt/actions/runs/38548126831) passed on PR head `1fca892798071446a22be2d33a44356d2681e893`. 50 stored historical first-party REcodeX TennisApi1 event ID + both participant ID judgments were replayed against the exact frozen 2025 CDB bytes (25 ATP, 25 WTA). Existing provider winner/start results were **not freshly queried**; a new provider API witness must be counted separately if it ever happens.
- The negative comparator replayed **20,732** source-native TennisData.App event IDs against **90,571** frozen CDB records, observed **13** same-numeric-event-string overlaps with **13 different native participant ID pairs**, and authorized **0** cross-provider canonical matches. Equal digits across source ID namespaces do not prove a shared event. Original source ledger SHA-256 `90915bcb5174be1cad2a55ee87ed3dbc998b68b1b6934b4eba849f5aa4a17a00`.
- Historical CDB `history-2025.parquet` SHA-256 `3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58`. Prior private provider first-party detail SHA-256 `f8cf817321ea9a411df7bc21acd5f15a897e6ad100ef195c90f285d0de60df70`, with the original private release SHA256SUMS also passing.
- Dedicated negative controls: **10 new** and **12 reused** offline tests passed. Cross-repository writer lock [#38548126619](https://github.com/BackstageTalks/tbt/actions/runs/38548126619) passed. Full PR CI [#38548126557](https://github.com/BackstageTalks/tbt/actions/runs/38548126557) and complete post-merge main CI [#38548722194](https://github.com/BackstageTalks/tbt/actions/runs/38548722194) passed.
- Squash commit on `main`: `d4212f81f19949326ed0b3d86b94dc14b6dbf3b3`. GitHub UI-deploy and hourly-status push jobs **skipped** because the squash title was `[audit-only]`. Neither the live application nor canonical write paths were modified by PR #729.
- This pilot consumed **0 additional RapidAPI calls**, performed **0 Identity V2 CDB writes**, and did not attest a single independently verified external-source → CDB event+both-players crosswalk.

### Independent pre-existing private source audits checked

- `tbt-data/audit/import-preparation/TML_L2_STAGE_INDEPENDENT_QA_20261014.json`: 25,926 original user-upload derived TML L2 stage rows with stage-integrity PASS, 36,065 quarantined; **0** independently verified primary provider-to-CDB event+two-player links and **0** production import permissions. Read-only staging integrity is not source-ID identity proof.
- `tbt-data/audit/import-preparation/L2_UNIFIED_IDENTITY_RECONCILIATION_20261013.json`: 2,699 source-to-source research event correspondences, 195 repeated-support candidate player links; **0** independently verified canonical event or player links. TML and Tennis Abstract may share upstream lineage.
- `tbt-data/audit/import-preparation/TML_CDB_PROTECTED_DRYRUN_20261014.json`: 377 source-to-CDB candidates for review across the archival ATP study, but **0** independently verified native original event ID ↔ canonical provider event ID, **0** approved new NULL-field writes.
- `tbt-data/audit/import-preparation/CDB2025_PROVIDER_ID_NULL_DISCOVERY_20261013.json`: 163,322 strictly NULL candidates among four target ace/double-fault fields in immutable CDB2025, with **0** independently source-approved replacement observations for them. This is **missing-field inventory**, not 163,322 importable observations.
- `tbt-data/audit/import-preparation/CDB_API50_FIRSTPARTY_IDS_AND_PBP_CANDIDATE_GATES_20261013.json`: original first-party 50/50 provider ID validation; does **not** confer rights or event IDs to unrelated providers.

### Production activation decision

**NO-GO: THIRD-PARTY CDB IMPORT VIA IDENTITY V2.** The missing input is an **independently original and source-authorized per-match event plus BOTH player ID crosswalk**, tied by verified upstream provenance to canonical REcodeX-native event and player IDs, along with source-specific reuse rights. Neither the 763 Futures ambiguities, 1,600 new candidates, 10 strong-context names, TML source-only agreements, 50 same-provider positive controls nor 13 numeric-ID negative controls supply that cross-provider evidence.

A provider-licensed mapping must contain source namespace, native match ID (not CSV row index), both native player IDs, independent official event ID and both official player IDs, canonical provider match ID and both canonical provider player IDs with per-edge original evidence, tournament edition/draw/round/day/winner/score corroboration, immutable original document hash and rights reference. Verify independent origin and one-to-one uniqueness before acceptance. Quarantine any missing or conflicting evidence.

**Until all those inputs are supplied, all affected Futures and other cross-provider records stay review-only in L2.** The existing first-party REcodeX API-backed gapfill, subject to its own daily quota, license, strict CURRENT NULL-only writer gates and snapshot guards, remains a separate potentially permitted workflow. This audit does not run it or authorize a quota-consuming action.

### External publisher terms and source credits

- TML's maintained README: https://github.com/Tennismylife/TML-Database/blob/master/README.md — ATP player IDs are from ATP source, and redistribution/reuse has publisher and ATP restrictions.
- TennisData.App terms dated 16 April 2026: https://tennisdata.app/terms/ — derivative reuse and systematic extraction restricted unless permission is established; a public CSV download by itself is not blanket CDB republication approval.
- Jeff Sackmann archival sources: maintain existing permission/CC BY-NC-SA 4.0 attribution and scope review independently; do not extend it to TML, TennisData.App or another provider.

**Acceptance endpoint for this release:** research toolkit and real native-ID negative/positive tests are complete; unsafe source-to-CDB promotion is intentionally disabled; independently evidenced third-party canonical imports are **not yet possible**. This is the honest final boundary.
