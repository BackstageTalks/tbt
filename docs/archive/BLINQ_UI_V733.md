# BlinQ v7.3.3 — UI + service resilience

- Header composition polished into one navigation rail.
- Login and loading screens use the BlinQ background and subtle wordmark watermark.
- Footer logo is a watermark and language selectors use the BlinQ green palette.
- Footer freshness is derived from feed timestamp and LIVE radar scan timestamp; stale data is never labelled LIVE-active.
- Support form helper copy moved to `web/config/site-content.json`; auth/loading/status copy is in `web/ui-config.json -> ui_copy`.
- Durable admin storage can reuse `BLINQ_STORAGE_CONNECTION_STRING` or `BLINQ_MEDIA_STORAGE_CONNECTION_STRING` in addition to the dedicated admin setting / AzureWebJobsStorage.
- LIVE radar remains usable during insight-history storage outages; only alert history is marked unavailable.
