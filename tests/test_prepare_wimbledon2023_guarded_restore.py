"""No production data: synthetic manifest/restore request fail-closed checks."""
import copy
import json
import sys
from pathlib import Path
import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_wimbledon2023_guarded_restore as r


def request():
    data = {
        "schema": 1, "mode": "write_exact_five_2023_only",
        "source_release": r.BACKUP,
        "source_year_sha256": r.BACKUP_SHA,
        "expected_current_year_sha256": r.CURRENT_SHA,
        "year": 2023,
        "expected_current_rows": r.EXPECTED_OLD_ROWS,
        "expected_restored_rows": r.EXPECTED_NEW_ROWS,
        "expected_new_match_ids": sorted(r.TARGET_IDS),
        "provider_api_requests": 0,
        "train_model": False, "promote_model": False,
        "create_cron": False, "overwrite_current_nonnull": False,
    }
    data.update({key: True for key in r.GATES})
    return data


def test_pinned_request_can_only_restore_exact_five():
    r.validate_request(request())
    for k, value in [
        ("source_year_sha256", "b"*64),
        ("expected_current_year_sha256", "c"*64),
        ("year", 2024),
        ("expected_restored_rows", 107764),
        ("provider_api_requests", 1),
        ("train_model", True),
        ("promote_model", True),
        ("overwrite_current_nonnull", True),
        ("require_immutable_prewrite_backup", False),
        ("require_fresh_release_CAS", False),
    ]:
        changed = copy.deepcopy(request()); changed[k] = value
        with pytest.raises(ValueError):
            r.validate_request(changed)
    changed = request(); changed["unexpected"] = True
    with pytest.raises(ValueError):
        r.validate_request(changed)


def test_prepares_manifest_but_keeps_all_other_years(tmp_path, monkeypatch):
    # Tiny synthetic 78-year metadata fixtures, no private bytes.
    years = {str(y): {"year": y, "rows": 1, "sha256": "a"*64,
                       "asset": f"history-{y}.parquet"} for y in range(1949, 2027)}
    years["2023"]["rows"] = r.EXPECTED_OLD_ROWS
    before = tmp_path / "before"
    before.mkdir()
    rows = [{"match_id": f"m{i}"} for i in range(2)]
    present = pd.DataFrame(rows)
    file = before / r.PARTITION
    present.to_parquet(file, index=False)
    sha = r.sha256(file)
    monkeypatch.setattr(r, "CURRENT_SHA", sha)
    years["2023"].update({"sha256": sha, "bytes": file.stat().st_size})
    # 78 partitions in real data are 1949..2026 = 78. Stub elsewhere 1 row.
    years["2026"]["rows"] = 994096 - r.EXPECTED_OLD_ROWS - 76
    source_manifest = {"years": years, "generated_at": "old",
                       "storage_policy": {"year_independent": True}}
    (before / r.MANIFEST).write_text(json.dumps(source_manifest))
    (before / r.BUNDLE).write_text(json.dumps({"files": {
        r.PARTITION: {"sha256": r.sha256(file)},
        r.MANIFEST: {"sha256": r.sha256(before / r.MANIFEST)}
    }}))
    proposed = tmp_path / "proposed.parquet"
    candidate = pd.DataFrame({"match_id": ["a", "b"]})
    candidate.to_parquet(proposed)
    monkeypatch.setattr(r, "EXPECTED_NEW_ROWS", 2)
    monkeypatch.setattr(r, "EXPECTED_OLD_ROWS", 2)
    monkeypatch.setattr(r, "TARGET_IDS", frozenset({"a", "b"}))
    # Stub 2023 row count adjusts the global row-count invariant as well.
    # These requirements are intentionally hard-coded production pins: synthetic
    # partial inputs cannot accidentally satisfy real writer conditions.
    with pytest.raises(ValueError):
        r.prepare_updated_manifest(before, proposed, tmp_path / "out.json", request())


def test_missing_file_or_wrong_release_checksum_fails_closed(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError, KeyError)):
        r.verify_release_inputs(tmp_path, request())
