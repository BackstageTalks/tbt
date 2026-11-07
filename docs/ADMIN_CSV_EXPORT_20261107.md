# Admin CSV export — acceptance and release record

## Scope
- Admin → Export CSV provides two separate read-only downloads: Results and Predictions.
- Results: complete available settled published ledger **before** UI pagination, deduplicated by publication identity, with all belonging categories; original fields in `src_zápas.*` and `src_publikácia.*`.
- Predictions: current published market tables for TOP, ACCA, Value, Esá, Dvojchyby, Štvorhra, Sety and Gamy, with source fields in `src_predikcia.*`.
- Results CSV distinguishes the native quoted price from display/indicative/illustrative odds and includes outcome, projected/actual values, profit units.
- CSV uses UTF-8 BOM, semicolon delimiter, correct escaping, and spreadsheet formula protection.
- Export fails closed when the durable results archive or centrally enforced exclusion policy is unavailable.

## Boundaries
- No new tennis provider API calls, CDB/model/data mutation, or new public endpoint.
- The browser exports only data authorized to the current verified admin session; do not export admin feed outside admin role.
- Never claim the full canonical CDB is included: this is the full **available published table**.

## Proof
- Feature merged via PR #1449: https://github.com/BackstageTalks/tbt/pull/1449
- PR CI: https://github.com/BackstageTalks/tbt/actions/runs/42417925134
- Node CSV contract: PASS, including 121-result no-page-limit sample, merged categories, market-specific odds, source fields, CSV escaping/injection.
- Real Chromium test: PASS, downloaded 121 Results rows + header and Predictions; fail-closed archive guard.
- Production rollout and live readback require a separate successful deploy job at current main SHA. Do not infer that from this record.

## Acceptance
- The new asset and admin buttons must be present in the exact serving release.
- Both download actions yield CSV files with expected headers, categories, and totals; no missing pages.
- Existing auth, model, published selections, match Results, and provider budgets remain unchanged.
