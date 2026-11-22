# Owner-gated TOP five supply — DRAFT, no activation

**State:** PREPARED / BLOCKED ON ATTACHMENT. **Target:** strive for five *eligible* TOP bets/day, never manufacture weak or invalid bets. No merged or production changes are authorized.

## Required input and traceability

Owner referenced an attachment named `top5_supply_fallback.patch`, but it was not present among conversation attachments, persistent file library, local working data, or the current main repo on 2026-11-22. The only available current conversation files were two unrelated JPEGs. **No `git apply --check`, `git apply`, or patch rebase can truthfully be reported until the original patch is supplied.** Do not reconstruct a replacement patch silently. Pin the patch SHA-256 and apply against the then-current `main` with `git apply --check` and `git apply` before review; rebase the supplied patch rather than replacing it.

Baseline main pinned at `7e8c753b847d8b6bda0bf1e7de96fd3e2680db76`.

## Main state verified in source

- `api/tbt/services/market_selection.py`: `TOP_MIN_COUNT=3`, `TOP_LIMIT=5`, normal TOP floor 0.65, minimum odds 1.50. Pool currently only contains rows whose **only** failure is `probability_below_fixed_floor`.
- `api/tbt/services/market_anchored_rank.py`: `emergency_fill` is default-OFF via `TBT_TOP_EMERGENCY_FILL`; market favorite check and `selection_tier=emergency_fill` already exist.
- `.github/workflows/data.yml`: emergency flag already requires both `TBT_TOP_EMERGENCY_FILL_OWNER_APPROVED` and `TBT_TOP_EMERGENCY_FILL`. There is presently no approved `TBT_TOP_MIN_PICKS` wiring.
- `tests/test_top_min_picks.py` **does not exist on baseline main**; it should be furnished by the original patch.
- `top_daily_shortfall`, `daily_minimum_target`, `daily_preferred_target`, `minimum_shortfall.top_daily`, `main_candidate_rule.fallback_only_if_section_below` and `top_daily_rule.daily_minimum_target` currently reference the constant 3. After patch all quantities describing the *actual* minimum must reflect the owner-gated effective value.
- TOP scope is already extended to Challenger/WTA125/Davis/BJK singles. ITF/UTR/exhibition/juniors/doubles remain excluded from new TOP.

## Acceptance criteria before approval

1. Owner minimum `TBT_TOP_MIN_PICKS` accepts integer 3–10 and falls back to 3 for unset, invalid and out-of-range input; never changes default behavior or model probability.
2. Effective minimum **only with explicit dual owner approvals**. Suggested four repository variables: `TBT_TOP_MIN_PICKS_OWNER_APPROVED=true`, `TBT_TOP_MIN_PICKS=5`, `TBT_TOP_EMERGENCY_FILL_OWNER_APPROVED=true`, `TBT_TOP_EMERGENCY_FILL=true`. **Do not set them now.**
3. Pool only if original rejection reasons are a nonempty subset of `{probability_below_fixed_floor, insufficient_surface_history}`, minimum 3 surface matches **per player**, and all other gates pass. The minimum depth stays 0.50.
4. Never relax real odds >=1.50, exact selection/player identity, match winner and singles-only, approved competition, price-integrity holds, or strictly pre-start model creation and odds capture. No post-start repricing or backdated pick.
5. Market must support the favorite: pre-start fair >=0.5 and model p>=0.5, or when no valid pre-start fair model p>=0.55; `rank_value` can order, but never replace public `probability`.
6. Unique selections, no overlap with Value/ACCA, max TOP=5 by original product limit unless owner separately approves other capacity. `emergency_fill` rows should be visibly distinguishable; must never throw TOP floor invariant on legitimate emergency rows.
7. A day with 0 core and >=5 eligible supplemental cards emits up to five in opt-in test. A day with 1–4 emits only 1–4; no crash, fake picks or forced quota.
8. All relevant market/top/emergency tests, independent browser check, default-OFF byte-parity test, and 14-day read-only historical calculation of daily `<5` counts must be attached as actual CI and report evidence.
9. Re-check UI and issued authority: raw candidate rows are NOT automatically member-visible or issued after a lock. No override of immutable daily snapshot or Telegram fencing.

## Quality interpretation

Five is a **best-effort capacity target**, not a profitability, accuracy or issuance guarantee. Owner supplied historical ordinal hit rates 59.4%, 60.8%, 57.4%, 58.4%, 55.9%, aggregate top5 58.5% vs top3 59.2%, and 26% days below five. These are **not independently verified** on this PR's exact data and are not approval to weaken model safety or claim reliable five-per-day performance. An emergency row below TOP 65% is lower-confidence regardless of its market-derived ordering; surface 3 is less evidence than surface 5. Require explicit visible provenance and prospectively measure hit rate/ROI separately from core TOP.

## C) Concrete UI and member-serving blocker found (implementation pending patch)

**Confirmed source-level defect for the future emergency tier:** `api/tbt/services/entitlements.py::_daily_rows` handles `sports_tiered_top5_65_v25` using `_row_probability(row) >= .65` with `[:5]`. An owner-approved `selection_tier=emergency_fill` candidate below .65 would therefore be **filtered out of the authorized member board**, even if the model selector emitted it. This is independent of the Telegram/issued-authority gate and must be fixed before activation.

Proposed minimal correction in **this PR after the supplied patch is applied**: for v25 only, retain the original core TOP condition, plus properly tagged `selection_tier=emergency_fill` with `emergency_fill is True`, and independently validate the exact retained odds, single match identity, original timestamped pre-start model/price evidence, original hard rejection reason allowlist, surface count >=3/player, depth >=.50 and market favorite eligibility. Preserve the original TOP order and five-card cap; do not change member plan access, issued-only authority, historical v23/v24, or enable owner variables.

**UI labelling:** `web/app.js::marketPreviewCard` (the renderer for dashboard and full TOP detail pages) presently never reads `selection_tier` or `emergency_fill`. It displays ordinary TOP confidence labels for emergency rows. Add a small translated label such as **„Doplnkový TOP“ / “Supplemental TOP”** for correctly tagged rows while preserving the exact public model probability, real odds and original rank. There is no need to add a new product or change Results schema. Test real mobile and desktop rendering; row order and public counters must agree with issued-only serving.

**No change has been made to these files:** a real emergency row does not yet exist without the missing patch. These are specific patches required before promotion of this draft.

## Read-only 14-day historical supply estimate (existing archived candidates)

**Evidence:** [GitHub Actions research run #45030467648](https://github.com/BackstageTalks/tbt/actions/runs/45030467648), one `selection_candidates_2026-11.json.gz` archive downloaded from the existing private prediction release; Python research script `scripts/audit_surface_depth_snapshot_readonly.py` on the separate research-only branch, commit `3e1d905442c28152983bc9a4a6d28d85d5260ee6`. Run exited successfully. **0 provider API calls, 0 CDB/publication writes, 0 training, 0 deployment.**

Method: first stored 06:00-or-later Bratislava snapshot per date 2026-11-09 through 2026-11-22; original stored single-match/price/identity/competition/prestart guard failures retained; 50% historical depth and odds >=1.50 retained. Owner supplemental pool requires at least three observed surface matches per player, only the two soft failures specified, pre-start market-favorite check, no Value-claimed row and no duplicate. Normal cap TOP five, target owner five. It is an **approximate hypothetical supply-only replay**, not the native patch executing in production. Snapshot classification and Value assignment can differ between historic policies.

| 14 dates | Normal TOP | Proposed best-effort owner supplement |
|---|---:|---:|
| Days with fewer than 5 candidate TOP | **14 / 14** | **4 / 14** |
| Total candidate TOP over 14 dates | **24** | **59** |
| Days with at least five | **0 / 14** | **10 / 14** |

| Date | Normal TOP | Owner-supplemented TOP (hypothetical) |
|---|---:|---:|
| 2026-11-09 | 1 | 5 |
| 2026-11-10 | 2 | 5 |
| 2026-11-11 | 3 | 5 |
| 2026-11-12 | 4 | 5 |
| 2026-11-13 | 2 | 5 |
| 2026-11-14 | 1 | 5 |
| 2026-11-15 | 1 | 5 |
| 2026-11-16 | 1 | 5 |
| 2026-11-17 | 3 | 5 |
| 2026-11-18 | 2 | 4 |
| 2026-11-19 | 3 | 3 |
| 2026-11-20 | 1 | 5 |
| 2026-11-21 | 0 | 2 |
| 2026-11-22 | 0 | 0 |

Critical limitation: the first 06:01 snapshot on 2026-11-22 contained only one priced fixture *before* the approved Challenger/WTA125/trophy discovery was applied; a later same-day run had 65 priced fixtures and 2 strict TOP+Value candidates. This is a real operational weakness that no selection rule fixes. The preceding 13 days had different scopes and policies. **These figures do NOT establish an everyday five-pick guarantee nor that emergency picks are comparably accurate.** Prospective hit-rate/CLV/ROI and low-sample data quality still require validation.

## No-production-change proof

This draft only documents the proposal and, when added, read-only tests/audit. No application code, model, CDB, provider calls, cron, deployment, repository variables or immutable pick ledgers are changed in this branch.

## Remaining gate

Obtain original `top5_supply_fallback.patch` bytes, apply/check/rebase on current main, add and run described tests, validate 14-day replay against actual patch, verify actual byte-parity with flags off, then seek **explicit owner approval recorded in PR** before any merge/activation.


## Independent source/audit re-check (2026-11-22)

**VERIFIED (source-only, not patched runtime):** at main `78f3b974fb4706cade764328933732aa3af30516`, `market_selection.py:1281-1283` explicitly exempts `selection_tier=emergency_fill` from the normal TOP core-floor `ValueError`; the patched end-to-end path still needs a test for 0 core + 5 supplements and 1–4 eligible supplements. Main's original 3-card minimum is unchanged and `tests/test_top_min_picks.py` is absent. Therefore none of the expected 368 patched tests has been executed or verified in this check.

**VERIFIED (audit log):** inspected actual job `137232715587` of [workflow run `45030467648`](https://github.com/BackstageTalks/tbt/actions/runs/45030467648), checked-out source `3e1d905442c28152983bc9a4a6d28d85d5260ee6`. The JSON log includes `historical_top_supply.requested_days=14`, `observed_days=14`, `days_below_5_normal=14`, `days_below_5_owner_supply=4`, `normal_top_total=24`, `supply_top_total=59`. This verifies the reported **read-only hypothetical candidate counts** were emitted by the run; it does *not* prove native-patch behavior, member-serving, 5 issued bets/day, price performance or accuracy. The same run independently reports just one priced fixture in the first 2026-11-22 morning snapshot and 65 in its last snapshot.

**Open design mismatch — ordering mode:** `market_anchored_rank.py::rank_value` returns `rank_probability` **only when** `TBT_RANK_SOURCE=market_anchored`; otherwise it returns public model `probability`. `market_selection.py::_market_card` only annotates the market score under that same separately owner-gated mode, and `data.yml` gates it with `TBT_MARKET_ANCHORED_OWNER_APPROVED`. Thus the four proposed TOP 5 activation variables **alone do not establish market-anchored ordering**, despite use of `rank_value`. The original patch and tests must settle how to retain the user's market-first supplemental ordering without silently enabling a separate experiment, changing public probability or expanding the four-variable activation procedure. No market-rank flag has been modified.

**Open range/cap mismatch:** `TBT_TOP_MIN_PICKS` is specified to parse values 3–10, but `TOP_LIMIT=5` and the serving `v25` board caps at five. Parsing 6–10 is acceptable for contract compatibility but **cannot imply a guarantee of six to ten issued cards**; owner-approved target for this task is exactly **5**, and this PR must not silently widen capacity. Regression tests should assert correct effective-target diagnostics for 5 even when 1–4 candidates exist.

**Confirmed serving issue:** `entitlements.py::_daily_rows` `sports_tiered_top5_65_v25` branch removes emergency cards with public probability below .65, despite the selector's tier exemption. The minimal correction must be limited to verified `emergency_fill` rows and preserve all validated hard guards, stable order, five-card cap and issued/member boundaries. `web/app.js::marketPreviewCard` currently labels such rows as ordinary TOP confidence; add a translated tier indicator but do not change probability, bookmaker price or styling of core rows. Do not mark UI or feed as verified until new end-to-end tests and browser evidence.

**Workstation limitation:** checkout/clone of public GitHub in this execution container failed at DNS resolution (`git ls-remote https://github.com/BackstageTalks/tbt.git`: `Could not resolve host: github.com`); connector source readbacks above are valid, but no local `git apply --check`, `git apply` or `pytest` run is claimed. The referenced source patch was also absent from the current conversation, searchable Library and repo; implement the original patch only after it becomes accessible.
