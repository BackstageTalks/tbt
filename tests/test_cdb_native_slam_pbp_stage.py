"""Grand Slam point tapes remain source-only and cannot masquerade as CDB stats."""
import csv
import json
from pathlib import Path

from scripts.cdb_native_slam_pbp_stage import prepare


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_observed_points_are_not_canonical_match_statistics(tmp_path):
    directory = tmp_path / "src"
    mid = "2023-ausopen-1101"
    _write(directory / "2023-ausopen-matches.csv", [{
        "match_id": mid, "player1": "Alpha One", "player2": "Beta Two",
        "player1id": "pbp-alpha", "player2id": "pbp-beta"
    }])
    _write(directory / "2023-ausopen-points.csv", [
        {"match_id": mid, "SetNo": "1", "GameNo": "1",
         "PointNumber": str(i), "PointServer": server, "PointWinner": winner}
        for i, server, winner in ((1, "1", "1"), (2, "1", "2"), (3, "2", "1"),
                                   (4, "2", "2"))
    ])
    report = prepare(directory, tmp_path / "stage", 2023, 2023)
    assert report["canonical_write_authorized"] is False
    assert report["crosswalk_promotion_authorized"] is False
    assert report["full_match_coverage_verified"] is False
    assert report["counts"]["research_match_observations"] == 1
    row = json.loads((tmp_path / "stage/point_observations.jsonl").read_text())
    assert row["source_id_namespace"] == "sackmann-slam-pbp"
    assert (row["source_player1_id"], row["source_player2_id"]) == (
        "pbp-alpha", "pbp-beta"
    )
    assert row["p1_observed_service_win_rate"] == 0.5
    assert row["p2_observed_return_win_rate"] == 0.5
    assert row["state"] == "RESEARCH_ONLY"
    assert row["import_ready"] is False
    assert row["full_match_coverage_verified"] is False
    assert "incoming_stats" not in row


def test_conflicting_duplicate_point_observations_fail_closed(tmp_path):
    directory = tmp_path / "src"
    mid = "2020-usopen-1101"
    _write(directory / "2020-usopen-matches.csv", [{
        "match_id": mid, "player1": "Alpha", "player2": "Beta"
    }])
    _write(directory / "2020-usopen-points.csv", [
        {"match_id": mid, "SetNo": "1", "GameNo": "1",
         "PointNumber": "1", "PointServer": "1", "PointWinner": "1"},
        {"match_id": mid, "SetNo": "1", "GameNo": "1",
         "PointNumber": "1", "PointServer": "2", "PointWinner": "2"},
    ])
    result = prepare(directory, tmp_path / "out", 2020, 2020)
    assert result["counts"]["duplicate_point_keys"] == 1
    assert result["counts"]["quarantined_match_observations"] == 1
    row = json.loads((tmp_path / "out/point_observations.jsonl").read_text())
    assert row["state"] == "QUARANTINE"
    assert row["import_ready"] is False


def test_missing_metadata_does_not_promote_unknown_players(tmp_path):
    directory = tmp_path / "src"
    mid = "2022-wimbledon-1101"
    _write(directory / "2022-wimbledon-matches.csv", [{
        "match_id": "other", "player1": "A", "player2": "B"
    }])
    _write(directory / "2022-wimbledon-points.csv", [{
        "match_id": mid, "SetNo": "1", "GameNo": "1",
        "PointNumber": "1", "PointServer": "1", "PointWinner": "1",
    }])
    result = prepare(directory, tmp_path / "out", 2022, 2022)
    assert result["counts"]["quarantined_match_observations"] == 1
