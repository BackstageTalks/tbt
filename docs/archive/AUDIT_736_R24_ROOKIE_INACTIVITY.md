# BlinQ 7.3.6-r24 — FREE ROOKIE + membership labels + inactivity review

## Product contract

- ROOKIE is the always-on FREE base membership with no fixed duration or automatic trial expiry.
- The legacy trial object remains only as a disabled compatibility alias (`trial_hours: 0`).
- PRO / ELITE / LEGEND remain time-limited; GOAT remains lifetime.
- The small green membership eyebrow is independent from the level/card title, editable in Admin → Členstvá, and may be blank.

## Inactivity review

A separate daily worker can review Firebase `last_sign_in_at` without changing the unlimited ROOKIE contract. Default policy: 90 inactive days, warning 7 days before, admin summary enabled, user mail disabled, automatic ROOKIE expiry disabled.

Optional automatic FREE ROOKIE archival is deliberately separate and OFF by default. When enabled, a durable warning marker must exist from an earlier worker run before the account can be marked expired.

Runtime settings remain server-side: `BLINQ_ACCOUNT_WORKER_TOKEN`, SMTP settings and `BLINQ_ADMIN_EMAIL`. GitHub scheduling is gated by `TBT_ACCOUNT_INACTIVITY_ENABLED=true`.

## Regression protection

`test_v736_r24_rookie_inactivity.py`, `test_account_inactivity.py`, the frontend runtime tests and `scripts/audit_repo_contract.py` protect the r24 contract.
