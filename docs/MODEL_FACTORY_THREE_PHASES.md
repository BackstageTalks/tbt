# BlinQ Model Factory — three-stage operator interface (2026-10-22)

**Implementation status:** staged on `training/model-factory`, not yet deployed.
Canonical input remains the existing CDB in private `BackstageTalks/tbt-data`.
The training branch is for **versioned code development**, not an additional
database or another mutable copy of historical match records.

## 1. Pripraviť dáta — read-only source-quality preflight

A single Admin command uses the existing durable `model-lab-queue` and its
at-most-once worker to dispatch `model-factory-preflight.yml` on **main**.
It waits for the global writer to be idle, checks the existing private
canonical release and bundle manifest, audits match/player identities, and
records ATP/WTA eligible history, per-tour dates, rank, serve, return, and
break-point observation counts. The non-sensitive run report is retained as a
GitHub Actions artifact and checked from the trusted worker before the stage
can become `WORKFLOW_VERIFIED`.

This is **not** the final frozen training input. The next stage must again
freeze and independently verify the complete inputs, ranks/priors, backup,
champion restore and leakage in the existing protected training workflow.
No paid provider requests, imports, CDB writes or production changes occur.

## 2. Natrénovať a aktivovať kandidáta — gated automatic shadow

The Admin training queue requires a fresh confirmed preflight in the visual
flow. The existing protected workflow is dispatched on **main** with
`training_profile=top-7.2.1` and `auto_shadow=true`. Its complete
immutability, identity, leakage, independent holdout, evidence publishing,
and signed Admin comparison checks run unchanged.

Only after success does `auto_shadow_candidate.py` recheck the run-bound
certificate, untouched holdout, champion comparison, per-tour safety gates,
and a positive accuracy margin. It then invokes the **existing**
`activate_shadow_candidate.py`, which independently checks release digest,
writer lock, shadow readback, and unchanged serving champion, with rollback
of modified candidate/shadow bundles on failure.

If the quality gate rejects the candidate, the immutable model remains
research-only and **shadow is not activated**. No auto-promotion to production.
The manually dispatched protected training workflow defaults to
`auto_shadow=false` for backwards compatibility.

## 3. Nasadiť do produkcie — not yet implemented

The visual third button is disabled until a separate production promotion
controller is implemented and independently tested. To enable it safely:
- Bind approval to an exact immutable candidate tag, model digest, and
  serving champion digest (compare-and-swap).
- Require independently issued/settled forward shadow evidence, ATP/WTA
  subgroup metrics, real point-in-time odds and TOP/VALUE performance.
- Rehearse rollback of champion plus its dependencies outside production.
- Get an explicit operator confirmation for the **specific** model switch,
  then perform atomic publish, independent production prediction readback,
  health checks, and monitored rollback policy.

**Never** infer deployability from a green CI badge, successful training or
saved candidate release. Existing TOP/VALUE policy and CDB remain unchanged.

## Operating constraints

- Existing protected production deployment rules remain authoritative.
- One global canonical writer; fail closed on inaccessible private state.
- Keep older releases/rollback material; no secondary GitHub dataset copy.
- No second model fit while the existing protected workflow is running.
- Implemented stages are auditable through immutable run IDs and SHA.
- Preflight completion means data-audit report ready, not binary freeze.
- Launch/publish requires the usual GitHub CI and independent live health
  verification; this branch/PR alone is not a deployed Admin interface.
