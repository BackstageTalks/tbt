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


def test_filtered_cohort_reuses_sealed_audit_time_and_still_checks_identities(tmp_path):
    def match(identity, day):
        return SimpleNamespace(match_id=identity, scheduled_at=datetime(2026, 10, day, tzinfo=timezone.utc),
                               provider_payload={}, is_completed=True, player1_id="a", player2_id="b",
                               stats={}, tour="atp", surface="hard")
    source = [match("1", 1), match("2", 2), match("future", 4)]
    cutoff = datetime(2026, 10, 3, tzinfo=timezone.utc)
    path = tmp_path / "filtered.parquet"
    with patch("verified_training_frame.validate_certificate", return_value=CERT):
        persist(_frame(), path, "top-7.2.1", audit_at=cutoff)
        # Even if loaded weeks later, future-at-audit remains excluded.
        frame = load(path, "top-7.2.1", source)
        assert frame.match_id.tolist() == ["1", "2"]
        assert frame.attrs["history_audit_at"] == cutoff.isoformat()
        with pytest.raises(RuntimeError, match="count"):
            load(path, "top-7.2.1", source + [match("extra", 2)])
        with pytest.raises(RuntimeError, match="identity"):
            load(path, "top-7.2.1", [source[0], match("wrong", 2), source[2]])
        from tbt.services import training
        from tbt.services.data_quality import audit_history
        # Stop before feature augmentation/fitting; verify the downstream
        # trainer uses exactly the same frozen cutoff and accepted cohort.
        with patch.object(training, "audit_history", wraps=audit_history) as audit_mock:
            with patch.object(training, "_enforce_rank_provenance", side_effect=RuntimeError("stop before fit")) as rank:
                with pytest.raises(RuntimeError, match="stop before fit"):
                    training.train_from_matches(source, verified_frame=frame)
            assert audit_mock.call_args.kwargs["now"] == cutoff
            assert [m.match_id for m in rank.call_args.args[0]] == ["1", "2"]
