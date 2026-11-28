# Point model shadow: no manual SAS setup (2026-11-28)
point_shadow_blob derives short-lived (2 h) SAS URLs from the existing GitHub secret BLINQ_MEDIA_STORAGE_CONNECTION_STRING and creates the private container point-model-shadow on first write. Explicit BLINQ_POINT_BLOB_*_URL secrets still win.
Morning run: BLINQ_POINT_MODEL_SHADOW defaults to true (repo variable "false" turns it off). Remaining manual step: Azure SWA env vars BLINQ_POINT_MODEL_SHADOW=true and BLINQ_POINT_MODEL_SHADOW_FILE=data/point_model_shadow.json (admin-only endpoint).
Revert: revert this PR, or set repo variable BLINQ_POINT_MODEL_SHADOW=false.
