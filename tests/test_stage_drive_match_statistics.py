from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stage_drive_match_statistics import (
    _read_headers,
    make_payload,
    run,
    stage_row,
)
from tbt.providers.statistics import parse_statistics


def complete_source():
    # Real observed counts for the 2016 Brisbane Raonic–Federer final, with
    # synthetic source IDs here so unit tests never assert canonical linkage.
    return {
        "winner_name": "Milos Raonic",
        "loser_name": "Roger Federer",
        "winner_player_id": "source-r975",
        "loser_player_id": "source-f324",
        "tourney_name": "Brisbane",
        "tourney_dates": "2016.01.04",
        "tourney_round_name": "Finals",
        "match_score": "64 64",
        "winner_aces": "6", "loser_aces": "7",
        "winner_double_faults": "6", "loser_double_faults": "3",
        "winner_service_points_won": "42", "winner_service_points_total": "60",
        "loser_service_points_won": "39", "loser_service_points_total": "61",
        "winner_return_points_won": "22", "winner_return_points_total": "61",
        "loser_return_points_won": "18", "loser_return_points_total": "60",
        "winner_first_serve_points_won": "28", "winner_first_serve_points_total": "34",
        "winner_second_serve_points_won": "14", "winner_second_serve_points_total": "26",
        "loser_first_serve_points_won": "25", "loser_first_serve_points_total": "34",
        "loser_second_serve_points_won": "14", "loser_second_serve_points_total": "27",
        "winner_first_serve_return_won": "9", "winner_first_serve_return_total": "34",
        "winner_second_serve_return_won": "13", "winner_second_serve_return_total": "27",
        "loser_first_serve_return_won": "6", "loser_first_serve_return_total": "34",
        "loser_second_serve_return_won": "12", "loser_second_serve_return_total": "26",
    }


def test_offline_payload_uses_exact_production_rapidapi_statistics_parser():
    source = complete_source()
    payload, fields = make_payload(source)
    assert payload["statistics"][0]["period"] == "ALL"
    assert parse_statistics(payload, home_is_player1=True) == fields
    assert fields["p1_service_points_won"] == pytest.approx(42 / 60)
    assert fields["p2_service_points_won"] == pytest.approx(39 / 61)
    assert fields["p1_return_points_won"] == pytest.approx(22 / 61)
    assert fields["p2_return_points_won"] == pytest.approx(18 / 60)
    assert fields["p1_aces"] == 6
    assert fields["p2_aces"] == 7
    assert fields["p1_double_faults"] == 6
    assert fields["p2_double_faults"] == 3


def test_source_origin_is_not_spoofed_as_real_provider_event_or_cdb_match():
    item = stage_row(complete_source(), file_sha256="a"*64,
                     source_file_id="TESTDRIVEID", line_number=1)
    assert item["import_ready"] is False
    assert item["provider_event_id"] is None
    assert item["canonical_match_id"] is None
    assert item["orientation"].startswith("synthetic_home")
    assert item["source"]["source_player_ids"] == {
        "winner": "source-r975", "loser": "source-f324"}
    assert item["match_hints"]["tournament_date_hint"] == "2016.01.04"
    assert item["normalized_candidate_stats"]["p2_return_points_won"] == pytest.approx(.3)


def test_unindexed_csv_is_stage_only_without_source_player_identifiers():
    row = complete_source()
    for field in ("winner_player_id", "loser_player_id", "winner_name", "loser_name"):
        row.pop(field)
    row["match_id"] = "2017-339-r975-n409"
    item = stage_row(row, file_sha256="b"*64,
                     source_file_id="DRIVE2017", line_number=8)
    assert item["source"]["source_match_id"] == "2017-339-r975-n409"
    assert item["source"]["source_player_ids"] == {"winner": None, "loser": None}
    assert item["import_ready"] is False


@pytest.mark.parametrize("change", [
    {"winner_aces": "-1"},
    {"winner_aces": "3.5"},
    {"winner_service_points_total": "12"},
    {"winner_service_points_total": ""},
    {"loser_return_points_won": "19"},
    {"winner_player_id": "same", "loser_player_id": "same"},
])
def test_inconsistent_observations_fail_closed(change):
    row = complete_source()
    row.update(change)
    with pytest.raises(ValueError):
        stage_row(row, file_sha256="c"*64,
                  source_file_id="DRIVE2016", line_number=5)


def test_no_empty_value_turns_into_fabricated_zero():
    row = complete_source()
    row.pop("winner_aces")
    row.pop("loser_aces")
    row["winner_double_faults"] = "0"
    _, values = make_payload(row)
    assert "p1_aces" not in values and "p2_aces" not in values
    assert values["p1_double_faults"] == 0


def test_headerless_drive_csv_is_read_only_and_quarantines_bad_rows(tmp_path):
    row = complete_source()
    columns = list(row)
    header = tmp_path / "titles.txt"
    header.write_text("\n".join(columns), encoding="utf-8")
    assert _read_headers(header) == columns
    source = tmp_path / "match_scores_stats_2016.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([row[k] for k in columns])
        invalid = dict(row, loser_return_points_won="999")
        writer.writerow([invalid[k] for k in columns])
    target = tmp_path / "output"
    report = run(source, header, target, "TEST_DRIVE_ID")
    assert report["counts"] == {
        "rows_seen": 2, "staged_not_import_ready": 1, "quarantined": 1}
    assert report["api_requests"] == report["cdb_writes"] == 0
    staged = [json.loads(line) for line in
              (target / "stage.jsonl").read_text().splitlines()]
    quarantine = [json.loads(line) for line in
                  (target / "quarantine.jsonl").read_text().splitlines()]
    assert len(staged) == len(quarantine) == 1
    assert staged[0]["source"]["sha256"] == report["source_sha256"]
    assert staged[0]["source"]["csv_line"] == 1
    assert quarantine[0]["csv_line"] == 2
    assert not staged[0]["import_ready"]


def test_sackmann_2024_wta_schema_49_columns_from_drive_can_stage(tmp_path):
    from stage_drive_match_statistics import normalize_sackmann_row
    example = {
        "tourney_id": "2024-example", "match_num": "101", "tourney_name": "Example",
        "tourney_date": "20240902", "round": "R16", "score": "6-4 6-3",
        "winner_id": "source-wta-p1", "loser_id": "source-wta-p2",
        "winner_name": "Player A", "loser_name": "Player B",
        "w_ace": "5", "l_ace": "2", "w_df": "2", "l_df": "4",
        "w_svpt": "60", "w_1stIn": "34", "w_1stWon": "28", "w_2ndWon": "14",
        "l_svpt": "61", "l_1stIn": "34", "l_1stWon": "25", "l_2ndWon": "14",
    }
    normalized_source = normalize_sackmann_row(example)
    payload, values = make_payload(normalized_source)
    assert parse_statistics(payload, home_is_player1=True) == values
    assert values["p1_service_points_won"] == pytest.approx(.7)
    assert values["p2_return_points_won"] == pytest.approx(.3)
    assert values["p2_service_points_won"] == pytest.approx(39/61)
    assert values["p1_return_points_won"] == pytest.approx(22/61)
    assert values["p1_aces"] == 5
    assert values["p1_double_faults"] == 2
    assert values["p2_aces"] == 2
    staged = stage_row(normalized_source, file_sha256="d"*64,
                       source_file_id="WTA_DRIVE_FILE", line_number=2)
    assert staged["source"]["source_tourney_id"] == "2024-example"
    assert staged["source"]["source_match_num"] == "101"
    assert staged["import_ready"] is False

    source_path = tmp_path / "wta_matches_2024.csv"
    with source_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(example))
        writer.writeheader()
        writer.writerow(example)
    summary = run(source_path, None, tmp_path/"out", "WTA_DRIVE_FILE",
                  source_format="sackmann")
    assert summary["counts"]["staged_not_import_ready"] == 1
    assert summary["counts"].get("quarantined", 0) == 0
    assert summary["api_requests"] == summary["cdb_writes"] == 0


def test_sackmann_cannot_invent_missing_service_points():
    from stage_drive_match_statistics import normalize_sackmann_row
    source = {
        "winner_name": "X", "loser_name": "Y",
        "w_ace": "2", "l_ace": "3", "w_df": "0", "l_df": "1",
        "w_svpt": "60", "w_1stIn": "35", "w_1stWon": "",
        "w_2ndWon": "", "l_svpt": "", "l_1stIn": "",
        "l_1stWon": "", "l_2ndWon": "",
    }
    row = normalize_sackmann_row(source)
    _, result = make_payload(row)
    assert "p1_service_points_won" not in result
    assert "p2_return_points_won" not in result
    assert result["p1_aces"] == 2 and result["p1_double_faults"] == 0
