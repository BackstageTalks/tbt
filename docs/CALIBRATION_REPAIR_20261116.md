# Protected calibration validation repair

The protected fit 43761397712 produced candidate
`v7.2.1-v201-20261115T222407973866Z`. On its 7,087 held-out
fixtures, accuracy was 69.38% versus champion 69.51%, Brier
0.195830 versus 0.195656, and log loss 0.573814 versus 0.573626.
It did not qualify for promotion. No improvement is established.

That report also shows calibration ending 2026-06-10 while the eligible
holdout begins 2026-10-27. The initial 70/15/15 calendar split was followed
by an eligibility filter only on the test set; the intervening pre-holdout
history was never returned to learning. For the smooth candidate, retain
the exact eligible holdout and split ALL earlier history in the same 70:15
train/calibration ratio. Boundaries use dates and existing provenance only,
not outcomes. Use the frozen audit timestamp for current-day exclusion.
Unknown eligibility does not expand training, and other profiles retain
their existing splits. Tests prove unchanged holdout membership, absence of
day overlap, inclusion of recent earlier data, and outcome-independent splits.

The 65% confidence guard applied only to the global mapping. Subsequent
tour and evidence overrides could improve their overall scores while
regressing the high-confidence slice. This patch applies that same
fixed-raw-fixture guard to each override in the smooth 7.2.1 profile.
Fewer than 100 high-confidence selection rows rejects an override.
The existing overall score and minimum-improvement requirements remain.
Deterministic regression fixtures reproduce acceptance before the fix and
rejection after it. The prior real candidate selected no subgroup overrides,
so this bypass is NOT claimed as the cause of its measured regression.

The smooth profile also retains the exact fitted calibration parameters
scored on later selection days. Previously, fitting again on all calibration
rows silently changed those parameters after their checks. Earlier fitting,
later selection and final holdout remain separated. Legacy serialized
champion inference and other training profiles are unchanged.

These source fixes do not prove improved production calibration. A new
candidate must pass the existing immutable backup/restore, leakage and
same-fixture evaluation gates. The previously inspected October 27–November
14 holdout is now a regression set, not a fresh independent confirmation.
Fresh prospective pre-match shadow evidence is required before activation,
including the actually issued TOP population. The 51 published outcomes
are not used to fit or select calibration. No odds enter the fitted maps.

No production model promotion or prediction percentage override accompanies
this patch. PROMO, TOP selection thresholds and outbound messaging are out
of scope.
