"""Regression tests for immutable private OddsTrader canonical parquet enrichment.

Never opens a remote release or uses credentials. Verifies that an importer may
add only approved market provenance while retaining all older canonical facts.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def safe_importer(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "api"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setenv("GITHUB_RUN_ID", "unit-test")
    filename = ROOT / "scripts" / "research" / "import_oddstrader_private_safe.py"
    spec = importlib.util.spec_from_file_location("oddstrader_guard_under_test", filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    original = tmp_path / "original"
    shadow = tmp_path / "shadow"
    original.mkdir()
    shadow.mkdir()
    monkeypatch.setattr(module, "BEFORE", original)
    monkeypatch.setattr(module, "SHADOW", shadow)
    (original / "history_manifest.json").write_text(json.dumps({
        "years": {"2016": {"rows": 2}},
    }))
    return module, original, shadow


def _write(directory, contexts, *, column="provider_context_json", ranks=(1, 2)):
    table = pa.table({
        "match_id": ["m1", "m2"],
        "player1_rank": list(ranks),
        column: [json.dumps(item, sort_keys=True) for item in contexts],
    })
    pq.write_table(table, directory / "history-2016.parquet", compression="zstd")


def _new_marker():
    return {
        "source": "oddstrader_atp_2015_2026",
        "price_kind": "historical_two_way_unspecified_timestamp",
        "player1_odds": 1.75,
        "player2_odds": 2.10,
    }


def test_preserves_original_context_and_unmodified_parquet_columns(safe_importer):
    module, original, shadow = safe_importer
    legacy = {
        "historical_verified_source": {"x": 1, "z": ["a", "b"]},
        "_tbt_environment": {"altitude_m": 330},
    }
    _write(original, [legacy, {"old": "exactly-preserved"}])
    # Generic writer omits old evidence and normalizes the document. Our
    # restoration must copy it back and graft only the proven market marker.
    _write(shadow, [{"_tbt_match_winner_odds": _new_marker()}, {"old": "exactly-preserved"}])
    report = module.preserve_original_context([2016])
    checked = pq.read_table(shadow / "history-2016.parquet").to_pydict()
    restored = json.loads(checked["provider_context_json"][0])
    assert restored["historical_verified_source"] == legacy["historical_verified_source"]
    assert restored["_tbt_environment"] == legacy["_tbt_environment"]
    assert restored["_tbt_match_winner_odds"] == _new_marker()
    assert checked["player1_rank"] == [1, 2]
    assert report["inserted_markers"] == {"_tbt_match_winner_odds": 1}
    gate = module.immutable_market_gate([2016])
    assert gate["verified_changed_matches"] == 1
    assert gate["new_matches"] == 0
    assert gate["stats_unchanged"] is True


def test_rejects_changed_non_context_field(safe_importer):
    module, original, shadow = safe_importer
    _write(original, [{}, {}])
    _write(shadow, [{"_tbt_match_winner_odds": _new_marker()}, {}], ranks=(999, 2))
    with pytest.raises(RuntimeError, match="Immutable canonical column changed"):
        module.preserve_original_context([2016])


def test_rejects_modified_existing_market_marker(safe_importer):
    module, original, shadow = safe_importer
    marker = _new_marker()
    _write(original, [{"_tbt_match_winner_odds": marker}, {}])
    _write(shadow, [{"_tbt_match_winner_odds": {**marker, "player1_odds": 9.9}}, {}])
    with pytest.raises(RuntimeError, match="Existing market evidence changed"):
        module.preserve_original_context([2016])


def test_rejects_mismatched_provider_column_name(safe_importer):
    module, original, shadow = safe_importer
    _write(original, [{}, {}], column="provider_payload_json")
    _write(shadow, [{}, {}], column="provider_payload_json")
    with pytest.raises(RuntimeError, match="Unverifiable original/updated match identity"):
        module.preserve_original_context([2016])
