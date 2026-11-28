# Point model: daily shadow + evaluation (Codex patch 53)
Morning run freezes pre-start point-model cards for ATP/WTA/Challenger/WTA 125 (ITF skipped); model errors are warnings only. Snapshot stored in a private Azure blob (not CDB) and packed with the API. Match-status evaluates finished matches (no retirements/walkovers/incomplete). Admin → Shadow testing shows 90-day ECE/Brier per level; first checkpoint 300 matches.
Enable: GH secrets BLINQ_POINT_BLOB_WRITE_URL / BLINQ_POINT_BLOB_READ_URL (SAS of one private blob), GH variable BLINQ_POINT_MODEL_SHADOW=true, Azure app settings BLINQ_POINT_MODEL_SHADOW=true, BLINQ_POINT_MODEL_SHADOW_FILE=data/point_model_shadow.json.
Revert: set variables to false or revert this PR.
