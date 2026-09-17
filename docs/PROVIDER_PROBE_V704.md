# Provider capability probe — v7.0.4

This repo adds a read-only GitHub Actions mode: `provider-probe`.

It answers four concrete questions without changing production data:

1. Does raw TennisApi daily discovery expose doubles / mixed doubles before BlinQ's singles filter?
2. Do doubles rows contain stable team/pair IDs and explicit player/member IDs?
3. Which real provider-1 odds markets appear for sampled current singles and doubles events (Match Winner, Aces/DF, Sets, Games/Totals, First Set, Tie Break)?
4. Do sampled finished doubles events expose Aces / serve / break-point statistics through the already-confirmed event statistics endpoint?

## Run

GitHub → Actions → **Tennis data and predictions** → Run workflow:

- `mode`: `provider-probe`
- `max_requests`: `80`
- leave the other inputs unchanged

The mode is read-only. It does not need `TBT_DATA_GH_TOKEN` and does not upload any history/predictions. It uses only `RAPIDAPI_KEY`.

Download the artifact `blinq-provider-probe-<run_id>` and inspect:

- `provider_probe_report.md` — human summary
- `provider_probe_report.json` — sample event identities, market names/lines/prices and statistics-key inventory

Do not implement a doubles model from the samples until pair/member identity is confirmed. Doubles remains a separate model from singles.
