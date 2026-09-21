# BlinQ 7.3.6 / 736-r48 — Core hardening report

## Scope

r48 deliberately avoids visual redesign. It closes the main code-audit lifecycle risks and adds validation instrumentation for the two still-data-dependent models.

### FREE / ROOKIE inactivity lifecycle

- Public tier remains `FREE`; internal authorization id remains `rookie`.
- Normal inactivity expiry is anchored to **last verified activity + 30 days**.
- The warning window opens 7 days before the fixed expiry, but the e-mail states the **exact expiry date** instead of an approximate “in N days”.
- If SMTP was unavailable until very late, automatic expiry is delayed only enough to preserve a **minimum 3-day successful-warning lead**. In normal operation the original fixed expiry date is unchanged.
- Warning delivery uses durable `pending -> sent` state. A leftover `pending` claim is not blindly resent because SMTP may already have accepted the message.
- Firebase identity is still never auto-deleted or disabled; only BlinQ access becomes `expired`.
- FREE self-reactivation remains limited to already-expired non-admin/non-suspended users and cannot downgrade active paid access.

### Paid membership expiry notices

- PRO / ELITE / Legend / GOAT reminders remain independent of FREE inactivity housekeeping.
- Windows remain 7 days and 3 days before the exact paid expiry timestamp.
- Each notice is tied to that exact expiry value, so extending membership creates a new reminder cycle.
- Per-user delivery now persists `pending -> sent`; a post-SMTP storage uncertainty does not trigger a blind duplicate on the next worker run.

### Account verification / password reset

- New-account verification and password reset remain BlinQ-owned branded SK/EN SMTP messages.
- Firebase Admin generates the one-time action code; the public link is rewritten to `/auth/action` on the BlinQ domain.
- Verification is authenticated and rate-limited; reset remains account-enumeration-safe and rate-limited.

### LIVE / 2nd set lifecycle

- Deterministic automated insight IDs are now **refreshable**, not create-once forever.
- Repeated radar scans update body and expiry metadata without sending duplicate push notifications.
- WATCH and Set-2 items receive a 20-minute TTL; confirmed Comeback items receive a 30-minute TTL.
- When a stage stops being observed it naturally disappears after the short TTL instead of remaining indefinitely active.
- Set-2 publishing still requires real provider Set-2 Winner odds plus the existing sample/quality/edge/EV gate.

### Doubles validation

- The doubles collector and normal refresh now emit a strict **walk-forward, point-in-time** model validation report.
- Every evaluated match is scored before that match updates the Elo state, preventing target leakage.
- Report includes sample count, accuracy, mean confidence, Brier score, log loss, calibration gap, rejection reasons, and confidence-band breakdown.
- `validation_ready` means only that there is a sufficiently large sample to inspect.
- `betting_edge_proven` remains explicitly `false` until historical bookmaker prices are available for an odds-aware profitability backtest. Data readiness is not presented as proof of edge.

## Verification

- `scripts/audit_repo_contract.py`: PASS
- Python focused lifecycle/LIVE/Doubles suite: 29 PASS
- Broad Python suite available in the local environment: **711 PASS, 1 skipped, 8 deselected**
- The 8 deselected tests are parquet tests requiring local `pyarrow`; GitHub CI installs the training requirements.
- `test_v700_api_smoke_contract.py` cannot collect locally because the container does not have `azure.functions`; GitHub CI provides it.
- `node --check web/app.js`: PASS
- `node --check web/auth.js`: PASS
- All frontend Node contract tests: PASS, including Firebase verification/reset flow and UI runtime contract for `736-r48`.

## Remaining data-dependent validation

The code path is now ready for the final mega-data output. Once that run completes, inspect:

1. Doubles walk-forward validation metrics and real selected-pick sample size.
2. LIVE Set-2 priced/eligible counts and subsequent result history.
3. No profitability/edge claim should be made from `ready=true` alone.
