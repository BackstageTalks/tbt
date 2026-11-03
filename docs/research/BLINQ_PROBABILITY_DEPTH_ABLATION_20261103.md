# BlinQ 7.2.1 — native probability-depth ablation, 2026-11-03

## State and strict scope

**Tested (read-only), not deployed.** Evaluate the older frozen match-winner candidates with exact canonical settlements, compare raw calibrated model confidence to `blinq_probability` after depth shrink, and test which actual 2026 TOP/VALUE/PRIME candidate assignments can be recreated from saved pre-match prices using the **current native** selector. No model fit, CDB writes, extra provider calls, EV/ROI/CLV optimization, public feed change, production candidate activation or probability transform change.

### Evidence

- [Run 41731075081](https://github.com/BackstageTalks/tbt/actions/runs/41731075081), SHA `2c5d36389d766797bf86720b1f60734e083a6ed3`: **28/28 regression tests passed**. Original canonical replay rebuilt from private assets with release before/after ID+size+updated timestamp and bundle SHA-256 checks; independent source reference metrics reproduced with 1e-10 tolerance. Private aggregate artifact: `blinq-probability-depth-ablation-41731075081` (artifact ID 13277205888).
- [Prior historical quality-availability gate test 41720833518](https://github.com/BackstageTalks/tbt/actions/runs/41720833518): 7/7 tests, independent private source readback. Separate [draft #1346](https://github.com/BackstageTalks/tbt/pull/1346).

### Exact same-candidate raw vs shrunk scoring

| Metric / cohort | Raw model confidence | Depth-shrunk BlinQ confidence |
|---|---:|---:|
| 7.2.1, all 1,762 settled candidate events — Brier | **0.19705999** | 0.21221606 |
| 7.2.1, all settled — log-loss | **0.57529420** | 0.61166642 |
| 7.2.1, all settled — day-bootstrap Brier difference (shrunk minus raw) | 95% descriptive CI **[+0.005995, +0.026545]** | |
| 7.2.1, 759 candidates with depth BELOW .80 — Brier | **0.18733735** | 0.22256445 |
| 7.2.1, 1,003 candidates with depth AT LEAST .80 — Brier | 0.20441740 | **0.20438513** |
| 7.2.1, 1,003 depth >= .80 — log-loss | **0.59305860** | 0.59314988 |
| 7.2.1, 177 historical TOP/VALUE/PRIME assigned and settled — Brier | 0.13589402 | **0.13573323** |
| 7.2.1, 177 historical assigned and settled — log-loss | **0.43323945** | 0.43330138 |
| 7.2.1, 177 historical assigned and settled — hit rate | 82.49% | 82.49% |

**Critical inference:** The strong all-candidate improvement is mainly from shallow depth (< .80), which does NOT qualify for normal TOP/PRIME admission. On the historical **actually assigned** candidate subset the shrink rule is a fraction better on Brier (difference 0.000161 in its favor), raw fraction better on log-loss (0.000062), neither establishes an accuracy win. The sample is small and not independently verified public issuance; no argument for deleting the current shrink.

### Native real selector reproduction barrier

- For frozen 7.2.1 there were 8 daily model/snapshot groups, **2 exactly reproduced** by the current native-public selector from the frozen, pre-start verified price pool, **6 did not**. On exactly reproduced days, switching to raw adds **one** TOP candidate and no change in PRIME/VALUE. Only 1 day / 4 same-capacity TOP observations had all outcomes known (no gain); this is not a prospective win-rate comparison.
- For the older champion 16 groups, **0 exactly reproduced**, likely historical policy and reconstruction divergence. Do NOT infer exact counters or wins on nonreproduced days.
- Earlier data collection selected what got priced under the **adjusted** pre-price gate. Historical counterfactuals cannot invent quotes that the then-current provider flow never requested. The generated snapshot's `selected_section` is a *candidate section assignment*, NOT proof that a bet was published.

### Additional older-match model experiment

- Fixed 2023–2026 annual test score composition, 356,742 rows: quality-aware model when `stats_known_both`, without-quality model otherwise => accuracy **0.695105**, Brier **0.195757**, log-loss **0.573374**. Always-quality arm 0.694580 / 0.196173 / 0.574332. This is **a gate rule selected retrospectively on all four years**, not a trained or independently validated new 7.2.2; cannot claim improved real champion.

### Decisions and remaining work

- **NO production change.** The original finding of all-universe shrink deterioration does not transfer to published section accuracy.
- Preserve existing candidate/model, selector, CDB, odds sourcing and all automation.
- If seeking a true improvement: a separate PIT same-offer forward shadow of confidence adjustment and quality gate, or a certified immutable-backup-gated per-year conditional model fold that validates model quality on 2026 without retuning the gate to 2026 results. Need current serving model binary hash readback and real issuance/settlement evidence; historical snapshots are insufficient for causal selector improvement.
- 0 Tennis API provider requests and 0 CDB/model/feed writes in this replay. **Status: tested / readback verified for these cohorts; not a better candidate, not merged/deployed.**
