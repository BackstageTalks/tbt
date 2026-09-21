# BlinQ v7.3.2 — asset revision consistency fix

Built on v7.3.1 UI polish. No prediction/data-model logic changed.

- Unified every frontend asset reference under one `asset_revision` (`7320`).
- Bumped UI/API release metadata to `7.3.2`.
- Removed stale tests that pinned historical cache-bust numbers; they now follow `ui-config.json`.
- Prevents CI failures where JS used a newer query revision than CSS/config.
