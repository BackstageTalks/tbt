# Model 7.2.1 checkpoint — 2026-10-23

## Objective
Improve winner accuracy without odds/EV. Establish temporal ATP/WTA comparisons before changing the active model. User authorized autonomous implementation and asked for durable checkpoints.

## Confirmed baseline
Active shadow: v7.2.1-v201-20261022T134742452543Z. Refresh 39934982800 succeeded; independently read shadow report with 176 captured / 0 settled at 2026-10-23 10:08 UTC. This is a historical observation, recheck current counts. Champion unchanged at last verification.

## Code
Branch feat/721-evidence-depth; PR https://github.com/BackstageTalks/tbt/pull/969.
0785626: six recent evidence support inputs, candidate-only; prior turn 44 targeted tests passed.
New temporal study: seven non-overlapping calendar quarters, 2025 Q1 through 2026 Q3. Training starts 2024; each fold has 60 calibration days, 30 model-selection days, then the test quarter. Compares baseline, same-model global calibration, evidence inputs, separate ATP/WTA fits and partial pooling. Specialist mixture uses selection-period accuracy with LL/Brier safeguards, never test labels. Sparse tour data fall back to pooled model. No deployable model is exported.

Workflow temporal_study=true skips candidate fit/publication/Admin update/activation and runs the study only after immutable backup verification and leakage audit. Report is saved after each fold and uploaded with always() even on failure. Future reruns currently refit; partial reports are evidence/checkpoints, not automatic trusted resume input.

## Verification
20 targeted tests passed (temporal leakage, evidence features, backup requirements, Model Factory, verified feature cache) using PYTHONUTF8=1 and workspace --basetemp on Windows. One additional workflow isolation test added subsequently; run before push. Tests use fake estimators for orchestration, not ungated real training.

## Running work / next actions
Evidence candidate training 39986158547 advanced from CDB wait to frozen-candidate during this turn. Do not cancel now: actual backup/training preparation may be underway. Check result and artifact before any activation.
Commit/push temporal study changes; dispatch protected-frozen-cdb-candidate.yml on this branch with training_profile=top-7.2.1, temporal_study=true, auto_shadow=false. Record returned run ID below. Shared workflow concurrency serializes it behind existing training.
Then inspect study artifact: exact input SHA, eligible folds, ATP/WTA paired accuracy and uncertainty, calibration choices, weaker segments. Existing historical test is development evidence, not fresh promotion proof. If study fails, fix cause rather than loosen gates.

## Outstanding scope
Opponent-adjusted serve/return ratings and validated DIL-to-CDB feature integration are not implemented by this change. Admin recalibration controls also remain future work. Do not claim measured predictive improvement or finished production deployment from engineering tests.

## Commands
PYTHONPATH=api;scripts, PYTHONUTF8=1; Python ../test-venv/Scripts/python.exe.
Use gh run view and gh run download for exact runs. Read AGENTS.md first when resuming. No local real fitting without enforced frozen-input/backup gate. No production activation.

## Dispatch checkpoint
Temporal study commit: 6863306. Run https://github.com/BackstageTalks/tbt/actions/runs/39988784731 dispatched with temporal_study=true and auto_shadow=false. Prior candidate run: https://github.com/BackstageTalks/tbt/actions/runs/39986158547. Four temporal tests passed after adding workflow publication-isolation check (21 targeted tests cumulatively). PR description updated to final combined scope. Dispatch is not successful completion; inspect current state before proceeding.

## Continuation checkpoint — segment diagnostics
Code e50b657 adds surface/competition/data-support diagnostic metrics, per-tour 80% confidence accuracy WITH coverage, and atomic report replacement. Aggregate fold checkpoints include prediction fingerprints; no raw rows are uploaded. Eight temporal/evidence tests passed after the change.
Old temporal run 39988784731 was still pending with zero jobs and was cancelled before any fit to replace its older code. Replacement research run: https://github.com/BackstageTalks/tbt/actions/runs/39991649667 (temporal_study=true, auto_shadow=false). This is now the run to inspect for the study. Do not rerun the cancelled old study.
Candidate run 39986158547 remains untouched; last observation was freezing/verifying input backup and champion restore, not a completed model fit. Read fresh workflow state before making completion claims. Opponent-adjusted feature work and Admin recalibration remain outstanding as above.

## User steering and heartbeat checkpoint (2026-10-23 18:33 UTC)
User approved one externally versioned BlinQ model with internal ATP/WTA specialization if supported by tests, and requested a user-friendly Admin update: one model, separate ATP/WTA results, existing three stages, clear states/blockers, expandable technical details. Recalibration UI must connect to a real governed backend, not a placeholder. This is authorized follow-on implementation, not yet delivered. Automation prompt updated to retain this scope and finish it before stopping.
Fresh workflow check: 39986158547 passed leakage audit and entered candidate fitting; 39991649667 remains pending. No prediction results yet, no new dispatch or model activation.

## Verified candidate result — 2026-10-23 19:03 UTC heartbeat
Run 39986158547 SUCCESS. Downloaded artifact and independently downloaded immutable release blinq-candidate-frozen-39986158547-1 training_report.json; bytes identical and SHA matches release bundle manifest: b15bb0f93021d39cc0e7d2ef55352cece6911a592c0a90646f52e9ca4b2072dd. Source commit 0785626a06cbfa3a17dbac4ebde2845a8cb56d48. Local reports: ../model-721-run39986158547/.
Same 9,559 holdout matches: candidate 70.0910% vs champion 69.4633% (60 extra correct, +0.6277 pp). LL .558815 vs .574373; Brier .189984 vs .195877. ATP n5336: 70.1649% vs 69.5465%. WTA n4223: 69.9976% vs 69.3583%. Both proper scores improve in both tours. Candidate 80% subset n2898, accuracy87.4051%, coverage30.3170%; descriptive subset, not all-match accuracy.
Do NOT attribute gain specifically to evidence-depth changes: this compares against production champion, not the prior active 7.2.1 on the exact same cohort. Prior holdout had 9251 rows, so aggregate comparisons between runs are not paired. Temporal study 39991649667 now in_progress and will isolate variant effects. No activation performed. Active shadow and production remain outside this research publication flow. Next: obtain temporal-study report, complete authorized Admin implementation, then summarize recommendation.

## Court/environment checkpoint — 2026-10-23 19:23 UTC
User authorized preparing best possible court-speed/environment experiment. See docs/model-721-court-environment.md. Fixed CourtSpeedHistory same-day leakage and cross-tour surface/player contamination; eight targeted tests passed. Raw Tennis Abstract page captured and independently SHA-read back at ../court-speed-snapshots/20261023T192305162367Z (68fc278677154bc2a6cde7c43a9cf2442166af14891f2a3e4b2352d6ac660fb4). Availability starts at capture; not historical training eligible. New snapshot capture script does not fit or change models. Venue mapping, forecast provenance audit and guarded paired ablation remain outstanding. No new experiment dispatch; existing temporal study unaffected. Automation scope updated accordingly.

## Admin implementation entry points — 2026-10-23 19:33 UTC
Temporal run 39991649667 still auditing frozen inputs; no new result/failure. Admin inspection: web/app.js render around 5128-5167 builds offlinePanel, currently contains stale fallback label Model 7.1.1 and claims untouched historical holdout. api/tbt/services/model_calibration_status.py::_offline_candidate normalizes only aggregate metrics, dropping tour metrics. To expose real ATP/WTA rows, extend verified offline evidence publisher (scripts/publish_frozen_candidate_evidence.py), snapshot normalizer and frontend together with paired tour count validation. Do not fabricate subgroup metrics from aggregate totals. Prior model711 identity pin is intentional; preserve exact legacy mapping. Add honest unavailable states and development-vs-prospective copy. No Admin code changed or deployed yet.

## Admin code checkpoint
Implemented paired offline ATP/WTA metrics end to end: frozen evidence publisher now includes champion tour blocks, snapshot normalizer validates paired n/required finite metrics and total bounds, UI renders separate ATP/WTA metric tables under one BlinQ model. Legacy missing champion subgroups explicitly show unavailable. Updated historical-test wording, removed stale 7.1.1 fallback label while retaining exact verified legacy alias pin. 14 snapshot/publisher tests passed; node --check web/app.js passed. Not yet merged/deployed or browser-render verified. Existing persisted evidence lacks champion tour blocks until verified republishing/new candidate publication; do not claim live ATP/WTA cards populated. No activation or fitting triggered.
