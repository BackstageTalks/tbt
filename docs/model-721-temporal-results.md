# BlinQ 7.2.1 — temporal study evaluation

State: VERIFIED report provenance and aggregate consistency; research only, no deployment.

Run: https://github.com/BackstageTalks/tbt/actions/runs/39991649667
Source: e50b6579b6bdd3eb80fae71117e6b2c7d96fb23c
Report SHA256: 0d8c5abfd6be2cc8b8bf659472124128df2d22189918b703f76bddbcf645b5f2

The report matches its frozen-backup certificate (run, source and input-manifest SHA); leakage audit passed. All seven fold-weighted accuracy, log-loss and Brier aggregates independently reconcile, as do diagnostic segment counts. Raw predictions are not exported, so this is not independent row-level recomputation.

## Paired winner accuracy

| Population | n | Shared baseline | Partial pooling | Extra correct |
|---|---:|---:|---:|---:|
| all | 180419 | 70.4682% | 70.7692% | 543 |
| atp | 107668 | 70.7991% | 71.0778% | 300 |
| wta | 72751 | 69.9784% | 70.3124% | 243 |

Partial pooling improves aggregate accuracy in all seven test quarters (2025 Q1–2026 Q3). Overall log loss improves 0.557389 → 0.552980; Brier 0.189597 → 0.187993. Reported daily-block 95% interval for accuracy gain: +0.205 to +0.387 percentage points. This interval does not remove model-selection, player/tournament dependence or reused historical-period limitations.

## Segments and limitations

| Segment | n | Baseline | Partial pooling |
|---|---:|---:|---:|
| surface: carpet | 44 | 56.818% | 56.818% |
| surface: clay | 67812 | 70.735% | 71.101% |
| surface: grass | 3713 | 65.365% | 65.203% |
| surface: hard | 88820 | 70.484% | 70.804% |
| surface: indoor_hard | 17212 | 70.172% | 70.248% |
| surface: unknown | 2818 | 72.285% | 72.427% |
| competition: ATP | 7274 | 64.050% | 64.050% |
| competition: Challenger | 19916 | 65.550% | 65.816% |
| competition: Exhibition | 48 | 68.750% | 68.750% |
| competition: ITF Men | 49169 | 75.757% | 76.312% |
| competition: ITF Women | 44079 | 70.428% | 70.762% |
| competition: International | 19 | 63.158% | 63.158% |
| competition: Italy | 340 | 56.176% | 56.176% |
| competition: UTR Men | 21027 | 68.712% | 68.403% |
| competition: UTR Women | 17017 | 71.352% | 71.487% |
| competition: WTA | 7288 | 66.068% | 66.959% |
| competition: WTA 125 | 4048 | 66.527% | 66.848% |
| competition: Wheelchairs | 120 | 77.500% | 75.833% |
| competition: Wheelchairs Juniors | 28 | 50.000% | 46.429% |
| competition: atp 250 | 594 | 64.983% | 64.815% |
| competition: atp 500 | 342 | 62.573% | 65.497% |
| competition: atp tour | 55 | 54.545% | 54.545% |
| competition: grand slam | 794 | 66.121% | 68.514% |
| competition: itf futures | 7774 | 67.301% | 67.224% |
| competition: masters 1000 | 487 | 62.218% | 65.298% |

ATP/WTA tour groups include lower-level events. They are NOT synonymous with main-tour ATP/WTA competitions. Most absolute gain comes from ITF; main ATP category is unchanged, UTR Men regresses in accuracy AND proper scores, grass loses six correct predictions. Competition labels are inconsistent (e.g. ATP versus atp 250, and Italy); normalize from verified identities before any competition-specific model selection. Small segments are descriptive only.

## Predictions with confidence at least 80%

| Population / arm | Selected n | Coverage | Accuracy |
|---|---:|---:|---:|
| all / baseline | 54894 | 30.426% | 87.572% |
| all / partial_pool | 53304 | 29.545% | 88.357% |
| atp / baseline | 35646 | 33.107% | 87.331% |
| atp / partial_pool | 33261 | 30.892% | 88.488% |
| wta / baseline | 19248 | 26.457% | 88.020% |
| wta / partial_pool | 20043 | 27.550% | 88.140% |

These arms choose different subsets: this table is not a paired accuracy comparison. Overall high-confidence coverage decreases; ATP coverage decreases while WTA coverage increases. No evidence of more 80% selections every day.

## Decision

Recommend implementing a single versioned package combining pooled and ATP/WTA specialists, with mixture weights selected only on a preceding selection window and sparse-data fallback. Do not choose pure WTA specialization post hoc from these test outcomes. Do not switch production or active shadow from this historical result alone.

Evidence-depth inputs alone do not improve aggregate accuracy (12 fewer correct). Separate global calibration produced identical predictions in this experiment; it does not establish that calibration is generally useless. The comparator is a retrained shared baseline, not the currently serving champion.

Next required work: export/load/runtime tests for the combined package, protected candidate fit with unchanged backup/leakage gates, then new prospective shadow evidence; investigate UTR regression without tuning against this same test. Admin cards are prepared in PR #969, not deployed. Court/environment ablation has not run: historical source availability and venue/forecast alignment remain unverified; the current Tennis Abstract snapshot cannot be backfilled. No predictive gain is claimed for those inputs.
