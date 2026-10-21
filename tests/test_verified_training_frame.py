"""Offline-only verified feature-cache contracts. No GitHub or CDB access."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from verified_training_frame import persist, load


CERT = dict(run_id="123456", attempt="1", application_sha="a"*40,
            remote_manifest_sha256="b"*64)


def _frame():
    return pd.DataFrame({
        "match_id": ["1", "2"],
        "scheduled_at": pd.to_datetime(["2026-10-01T12:00:00Z", "2026-10-02T12:00:00Z"]),
        "tour_atp": [1., 0.], "target": [1, 0],
        "elo_probability": [0.7, 0.4], "stats_known_both": [0., 1.]
    })


def _matches():
    return [SimpleNamespace(match_id=x) for x in ("1", "2")]


def test_run_bound_cache_roundtrip_and_sha_readback(tmp_path):
    path = tmp_path / "audited.parquet"
    with patch("verified_training_frame.validate_certificate", return_value=CERT):
        proof = persist(_frame(), path, "top-7.2.1")
        assert proof["rows"] == 2
        assert len(load(path, "top-7.2.1", _matches())) == 2
        with pytest.raises(RuntimeError, match="profile"):
            load(path, "standard", _matches())
        with pytest.raises(RuntimeError, match="identity"):
            load(path, "top-7.2.1", [SimpleNamespace(match_id="1"),
                                       SimpleNamespace(match_id="3")])
        with pytest.raises(RuntimeError, match="overwrite"):
            persist(_frame(), path, "top-7.2.1")
        path.write_bytes(path.read_bytes() + b"tamper")
        with pytest.raises(RuntimeError, match="SHA"):
            load(path, "top-7.2.1", _matches())


def test_cache_must_match_immutable_backup_certificate(tmp_path):
    path = tmp_path / "audited.parquet"
    with patch("verified_training_frame.validate_certificate", return_value=CERT):
        persist(_frame(), path, "top-7.2.1")
    with patch("verified_training_frame.validate_certificate",
               return_value={**CERT, "remote_manifest_sha256": "c"*64}):
        with pytest.raises(RuntimeError, match="immutable"):
            load(path, "top-7.2.1", _matches())


def test_invalid_cache_cannot_be_sealed(tmp_path):
    with patch("verified_training_frame.validate_certificate", return_value=CERT):
        frame = _frame()
        frame.loc[1, "match_id"] = "1"
        with pytest.raises(RuntimeError, match="identity"):
            persist(frame, tmp_path / "duplicates.parquet", "top-7.2.1")
        frame = _frame()
        frame.loc[0, "scheduled_at"] = datetime(2026, 11, 1, tzinfo=timezone.utc)
        with pytest.raises(RuntimeError, match="chronology"):
            persist(frame, tmp_path / "future.parquet", "top-7.2.1")
