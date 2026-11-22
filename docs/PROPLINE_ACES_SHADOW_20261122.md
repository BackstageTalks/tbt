# PropLine ESÁ N+ — shadow-only pilot (22 Nov 2026)

**Authorization:** owner requested testing of the 23 November 2026 bookmaker offer. This experiment is **NOT** part of official BlinQ ESÁ, Results, KPI, levels, ACCA or the serving champion.

## What runs

- Existing external 23:00 Bratislava PropLine archive (no new scheduler). The collector first obtains the free bulk board, then—only under verified provider quota—requests exact per-event player-aces markets. The existing private `tbt-data` JSON archive remains the source of truth and retains native bookmaker evidence.
- The already-authorized **morning** `data.yml` refresh (`morning_refresh=true`) opt-ins to `BLINQ_PROPLINE_ACES_SHADOW_ENABLED` automatically. It reads the preceding evening's latest immutable `research/propline-evening-odds/YYYY-MM-DD/` snapshot without new provider requests; no separate GH Actions scheduler.
- A shadow-only scorer matches original bookmaker event players + match start to **exactly one** canonical BlinQ prediction (maximum 30-minute schedule difference). Ambiguous or missing names/IDs are fail-closed. The research pilot accepts Challenger and WTA 125 for observation **without** relaxing the production ATP/WTA 250+ ESÁ gate.
- All sportsbook N+ Aces selections (including prices **below 1.50**) are visible in the private research record. This is **not** a sportsbook two-way O/U publication.
- The existing historical ace count v4 projection computes a per-player pre-match count mean and uses the repository's **provisional, uncalibrated** normal-tail probability function for the offered integer threshold. No bookmaker-implied probability substitution, no training and no serving-model change.
- `model_probability >= 0.60` and `EV = model_probability * decimal_odds - 1 >= 0` qualify candidates; choose at most **one** best EV option per canonical match for shadow-only testing. Other offers retain their price, model P, EV and rejection reason.
- If no history or reliable canonical match exists, show actual quotes with **null** probability/EV, not invented predictions. If no priced future event is available for the 23rd, persist an honest zero-pick research day.
- First pre-match daily snapshots stay immutable in `tbt-model-shadow-v1:propline_aces_shadow.json`. The existing serialized ReleaseStore writer commits the checksum manifest; an independent second ReleaseStore downloads the file and byte-compares it. No separate writer, no official offer/result or CDB writes.
- Later authorized morning refreshes may append read-only count-based research settlements from exact completed canonical CDB matches; retired/walkover/ambiguous stats stay pending. Research ROI never enters official KPI.

## Evidence and rollout

- PR code/tests are **PREPARED** until exact-head CI and merge.
- Merge makes the feature available for already authorized morning `workflow_dispatch` runs. It does not start an additional paid/API refresh.
- Runtime acceptance is **not met** until a real 23:00 archive, successful morning scorer execution, private release asset/readback and nonzero source/matched quote metrics are independently checked. No candidate count or accuracy is assumed.
- The PropLine Google Drive archival writer has previously failed with HTTP 404. Private GitHub immutable archiving and readback provide independent source evidence; do not mistake Drive failure for a working Google Drive copy.
- To check results open the private `tbt-model-shadow-v1` Release asset `propline_aces_shadow.json`, inspect `captures[-1].counts` and `quotes`; check `settlements` separately. Each selected row includes model P/EV, exact price/market/bookmaker, event/time and raw SHA.

### Stop / rollback

Set repository variable `BLINQ_PROPLINE_ACES_SHADOW_DISABLED=true` to stop this research-only pilot on future morning refreshes, or revert the scoped workflow/pipeline hook. Do not delete immutable private research evidence or change the canonical CDB.
