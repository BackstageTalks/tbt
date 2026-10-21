"""Native ATP/WTA Sackmann ingestion preserves IDs and fails closed on ambiguity."""
from __future__ import annotations

import csv
from pathlib import Path

from scripts.cdb_native_sackmann_stage import prepare, _quality
from scripts.link_offline_serve_return import _sackmann_rows


def _match(**kw):
    result = {
        "tourney_id": "2025-9900", "tourney_name": "United Cup",
        "tourney_date": "20241227", "match_num": "300",
        "winner_id": "126203", "loser_id": "128034",
        "winner_name": "Alpha One", "loser_name": "Beta Two",
        "surface": "Hard", "round": "F", "score": "6-4 6-4",
        "best_of": "3", "w_svpt": "54", "w_1stIn": "35",
        "w_1stWon": "25", "w_2ndWon": "11", "w_ace": "5",
        "w_df": "1", "w_bpSaved": "2", "w_bpFaced": "3",
        "l_svpt": "63", "l_1stIn": "37", "l_1stWon": "20",
        "l_2ndWon": "11", "l_ace": "2", "l_df": "3",
        "l_bpSaved": "4", "l_bpFaced": "7",
    }
    result.update(kw)
    return result


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_native_original_source_ids_and_tournament_date_are_retained(tmp_path):
    root = tmp_path / "raw"
    _write(root / "atp_matches_2025.csv", [_match()])
    result = prepare(root, tmp_path / "stage", 2025, 2025)
    assert result["canonical_write_authorized"] is False
    assert result["production_mutated"] is False
    assert result["counts"]["linker_ready_source_rows"] == 1
    file = Path(result["files"][0]["linker_csv"])
    row = list(csv.DictReader(file.open()))[0]
    assert row["winner_id"] == "126203"
    assert row["loser_id"] == "128034"
    assert row["tourney_date"] == "20241227"
    assert row["league"] == "atp"
    assert row["source_record_id"].startswith("sackmann:atp:main:2025:")
    parsed = list(_sackmann_rows([str(file)]))[0]
    assert parsed.source_id_namespace == "sackmann"
    assert (parsed.source_player_a_id, parsed.source_player_b_id) == ("126203", "128034")
    assert parsed.source_match_id == row["source_record_id"]
    assert parsed.event_date.isoformat() == "2024-12-27"


def test_duplicate_native_match_tuple_is_not_sent_to_canonical_linker(tmp_path):
    root = tmp_path / "src"
    _write(root / "wta_matches_qual_itf_2025.csv", [
        _match(match_num="200", winner_id="w1", loser_id="w2"),
        _match(match_num="200", winner_id="w3", loser_id="w4"),
        _match(match_num="201", winner_id="w5", loser_id="w6"),
    ])
    result = prepare(root, tmp_path / "stage", 2025, 2025)
    assert result["counts"]["quarantined_ambiguous_native_match_key"] == 2
    assert result["counts"]["linker_ready_source_rows"] == 1
    rows = list(csv.DictReader(Path(result["files"][0]["linker_csv"]).open()))
    assert len(rows) == 1
    assert rows[0]["winner_id"] == "w5"
    assert rows[0]["league"] == "wta"


def test_invalid_service_counts_and_missing_ids_are_not_linked(tmp_path):
    root = tmp_path / "source"
    _write(root / "atp_matches_futures_2026.csv", [
        _match(match_num="1", w_1stWon="80"),
        _match(match_num="2", winner_id=""),
        _match(match_num="3", w_svpt="", l_svpt=""),
        _match(match_num="4"),
    ])
    assert _quality(_match(w_1stWon="80")) == "INCOMPLETE_OR_INVALID"
    result = prepare(root, tmp_path / "out", 2026, 2026)
    assert result["counts"]["quarantined_identity_or_tournament_start"] == 1
    assert result["counts"]["linker_ready_source_rows"] == 1
    assert result["counts"]["COMPLETE_BASIC_SERVE_RETURN"] == 1
    assert result["canonical_stat_fields_written"] == 0
    assert result["api_requests"] == 0
