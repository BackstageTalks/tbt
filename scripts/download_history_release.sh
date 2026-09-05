#!/usr/bin/env bash
set -euo pipefail

: "${TBT_DATA_REPOSITORY:?Missing TBT_DATA_REPOSITORY}"
: "${TBT_HISTORY_RELEASE_TAG:=tbt-data-v1}"

ROOT_DIR="${1:-.cache/tbt}"
HISTORY_DIR="${ROOT_DIR}/history"
mkdir -p "$HISTORY_DIR"

assets="$(gh release view "$TBT_HISTORY_RELEASE_TAG" --repo "$TBT_DATA_REPOSITORY" --json assets -q '.assets[].name')"

if grep -qx 'history_manifest.json' <<<"$assets"; then
  gh release download "$TBT_HISTORY_RELEASE_TAG" \
    --repo "$TBT_DATA_REPOSITORY" \
    --pattern 'history-*.parquet' \
    --pattern 'history_manifest.json' \
    --dir "$HISTORY_DIR" \
    --clobber
else
  echo "V20.5: partition manifest not found; migrating legacy snapshot locally without Supabase."
  grep -qx 'training_snapshot.parquet' <<<"$assets" || {
    echo "No partitioned history and no legacy training_snapshot.parquet in release."
    exit 1
  }
  gh release download "$TBT_HISTORY_RELEASE_TAG" \
    --repo "$TBT_DATA_REPOSITORY" \
    --pattern 'training_snapshot.parquet' \
    --pattern 'training_snapshot.meta.json' \
    --dir "$ROOT_DIR" \
    --clobber
  python - <<PY
from pathlib import Path
from tbt.data.history_snapshot import ensure_partitions
root = Path(${ROOT_DIR@Q})
manifest = ensure_partitions(root / 'history', legacy_snapshot=root / 'training_snapshot.parquet')
print('Migrated partition years:', ', '.join(sorted((manifest.get('years') or {}).keys())))
PY
fi

python - <<PY
from pathlib import Path
from tbt.data.history_snapshot import list_partition_years, load_manifest
path = Path(${HISTORY_DIR@Q})
years = list_partition_years(path)
if not years:
    raise SystemExit('No history partitions downloaded')
manifest = load_manifest(path)
print('History partitions:', years)
print('Manifest cursor:', manifest.get('source_updated_at_max'))
PY
