# Opt-in 7.2.1 probability candidate

Dispatch `protected-frozen-cdb-candidate.yml` with `training_profile=top-7.2.1`.
The existing immutable input backup, private CDB lock, isolated champion restore,
identity/leakage audit and independent candidate readback remain mandatory.

The profile selects ensemble blend parameters by calibration log-loss rather than
overall winner accuracy. Calibrator selection remains chronological log-loss.
The final holdout is not used for optimization. Candidate versions start with
`v7.2.1-`; the standard profile retains its existing behavior.

Before fitting, each ATP/WTA training and calibration partition must have varying
rank, serve and return inputs and finite enabled feature values. Historical rank
priors can satisfy the rank requirement when legacy rank fields are absent. The
report records finite/nonzero counts, unique values and variance. This is a minimum
availability check, not proof of sufficient coverage or predictive value.

TOP still requires separate point-in-time market evaluation at odds >=1.50 with
at most ten daily picks and no mandatory fill. The report explicitly marks this
NOT_EVALUATED and the pipeline blocks promotion for this profile. A probability
candidate's general holdout gain must not be presented as proven TOP performance.

No selector policy, canonical data or serving model is changed by choosing
this profile. The profile uses artifact-persisted independent serve/return
availability. A separate opt-in `independent_direct_rates` flag also preserves
the original point-weighted service or return observation when the complementary
field is missing (instead of silently falling back to an unrelated rate).
Old champions and already fitted 7.2.1 candidate artifacts default this new flag
to false, preserving their exact original inference/replay semantics.

The additional feature availability is a code-level correction, not evidence of
better real-market TOP results. Retrain and compare on untouched chronological
data and forward-frozen pre-match odds before any promotion. Never reuse an old
7.2.1 fitted model with newly changed feature semantics.
