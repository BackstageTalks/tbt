# BlinQ v7.1.3 — Mega Data Run

## New workflow mode
`Tennis data and predictions` now includes `mega-data`.

One `max_requests` value is a global cap across the whole run. Phases execute sequentially under the existing `tbt-history-data-writer` concurrency lock.

Order:
1. provider capability probe (small/read-only, doubles + market discovery)
2. history repair + catch-up
3. targeted Aces / Double Fault statistics
4. targeted Sets / Games score enrichment
5. generic statistics sweep with all remaining request budget

Unused request headroom from an earlier phase rolls forward. The last generic statistics phase can use everything left, so the operator does not need to launch separate jobs merely to consume the quota.

## Doubles
Doubles are intentionally `probe_only` in this run. The current singles collector/model filters doubles, and there is no validated pair/team training dataset yet. The probe report captures real provider pair/member identity and market coverage; a separate doubles collector/model should be added only after this evidence is confirmed.

## Recommended manual run
For a remaining quota around 10,000 requests:
- mode: `mega-data`
- max_requests: `9500` if you want a ~500-request safety margin
- start/end: blank
- lookback_days: 1095
- ace_target_samples: 18
- ace_lookback_days: 550
- sg_target_samples: 24
- sg_lookback_days: 730
- promote: false

The artifact `blinq-mega-data-<run id>` contains the combined request-usage report and provider capability probe.
