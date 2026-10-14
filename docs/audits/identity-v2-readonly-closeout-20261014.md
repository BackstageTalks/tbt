# BlinQ Identity V2 — read-only engineering closeout (2026-10-14)

## Scope and immutable decisions

- **Canonical remains authoritative.** No direct write, release promotion, model training, website deployment or mutation of obsolete \`tbt-pro\` is part of Identity V2 research.
- A new candidate is a **search result**, never an independently verified source-to-CDB link. A strong event/tournament-context label is likewise **not identity proof**.
- Feature approval requires a separate **official original event identifier, both provider-native player identifiers, independent lineage and event/date/round/winner validation**. Source-native *row coordinates* are NOT provider-issued event IDs.
- All source rights, attributed origin, as-of/point-in-time rules, current complete canonical partition SHA, CURRENT NULL-field delta and a governed single-writer lock + rollback/readback remain distinct, mandatory production gates. Reusing existing validators is preferred to inventing duplicate weaker gates.
- **Sackmann source terms:** CC BY-NC-SA 4.0 (attribution, noncommercial conditions, share-alike); mirrors add no extra rights. A free site alone is not a completed case-specific compliance review. Other providers may have different terms. Never infer rights from public availability.

## Five requested capabilities — exactly what is implemented

| Requested capability | Audit-only implementation | Production activation |
|---|---|---|
| 1. One resolver for heterogeneous import sources | \`identity_v2_gateway.py\` and \`identity_v2_adapters.py\` with explicit scoped native IDs, dates and no-write research gateway; bounded input preflight | **BLOCKED**: legacy governed importers intentionally not rewired while source-native IDs and independent witness remain unproven |
| 2. Broad initial/alias/transliteration/formats discovery | \`identity_v2.py\` with source-specific names/aliases, Unicode and cautious fuzzy research keys | Research-only; no name-key identity authorization |
| 3. Independent source/event/player verification | \`identity_v2_witness_preflight.py\` and external existing \`verify_tml_event_witnesses.py\`, \`build_cdb_verified_player_crosswalk.py\`; collide/duplicate/winner/date safety tests | **BLOCKED**: preflight checks *claims/shape*, not independent byte-authenticated official provider originals for each disputed match |
| 4. Tournament editions, dates, rounds, scores | \`identity_v2_editions.py\` and \`identity_v2.py\`; source edition/date-kind, draw/season/tour/level, explicit score/retirement and side-orientation hard negatives | Doubles/mixed 4-player team identity not yet supported; never misrepresent 2 names as doubles teams |
| 5. Historical shadow old/new | \`shadow_sackmann2025_vs_cdb.py\`, SHA-pinned workflow, \`identity_v2_triage.py\`, \`identity_v2_loss_diagnosis.py\` | Verified candidate diagnostics are **not** an exhaustive comparison with all legacy importers and all CDB years |

## Reproducible prior snapshot (not current CDB)

Original 2025 Sackmann ATP/WTA 5-source inputs: **56,889 matches**. Immutable historical CDB 2025 parquet: **90,571 matches**, SHA-256 \`3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58\`. Test workflow checks every source file hash and this specific CDB hash before any comparison.

Research baseline (strict normalized name/date/round proxy) found 44,057 source rows with candidates. V2 found 45,613. New-only: **1,600** source cases, including **10** with a single strong edition-context candidate. Old-only: **44** cases. Old unique became ambiguous: **777** cases, including **763 ATP Futures**. Candidate sets differ in **936** source cases where both sides found candidates.

A second-pass diagnostic found **197 rejected original candidate edges across 193 source rows**: **177 winner-orientation conflicts**, **20 ambiguous side orientation**. It must not be confused with the 44 source rows losing every old candidate. None of these numbers are verified CDB enrichments.

Every currently reviewed cross-source new identity remains **unverified** and every canonical field write remains **unauthorized** by this project.

## Audit review priorities

1. **ATP Futures**: 763 old-unique-now-ambiguous cases, distinguish native edition/year/level/draw + independently issued match/event IDs; never rely on one-city/same-names assumptions.
2. **Regressions**: review 44 source rows losing all prior links and 197 rejected candidate edges against original independent provider results; never override winner conflict just to increase recall.
3. **Broader recovery**: 1,600 new-only research cases (esp. WTA ITF/qualifying), of which 10 have strong event context but 0 independently authenticated canonical event and both-player links.
4. **Independent golden set**: source-original verified ID pairs and provider lineage in private review; \`identity_v2_private_review.py\` exports only with explicit private local permissions and is **forbidden in CI**. Official evidence validation must be performed separately.
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
