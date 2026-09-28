import json
import zipfile

import pytest

from normalize_private_serve_return import (
    build_stage,
    extract_home_away_stats,
    normalize_raw_row,
)


def provider_fixture():
    return {
        "statistics": [{
            "period": "ALL",
            "groups": [
                {"groupName": "Service", "statisticsItems": [
                    {"key": "aces", "homeValue": 5, "awayValue": 2},
                    {"key": "doubleFaults", "homeValue": 1, "awayValue": 3},
                    {"key": "firstServePointsAccuracy",
                     "homeValue": 30, "homeTotal": 40,
                     "awayValue": 20, "awayTotal": 35},
                    {"key": "secondServePointsAccuracy",
                     "homeValue": 5, "homeTotal": 10,
                     "awayValue": 8, "awayTotal": 15},
                ]},
                {"groupName": "Points", "statisticsItems": [
                    {"key": "servicePointsScored", "homeValue": 35, "awayValue": 25},
                    {"key": "receiverPointsScored", "homeValue": 15, "awayValue": 10},
                ]},
            ],
        }],
    }


def test_extracts_supported_counts_and_rates_from_all_period():
    stats = extract_home_away_stats(provider_fixture())
    assert stats["home_aces"] == 5
    assert stats["away_double_faults"] == 3
    assert stats["home_first_serve_win"] == pytest.approx(.75)
    assert stats["away_second_serve_win"] == pytest.approx(8 / 15)
    assert stats["home_service_points_won"] == pytest.approx(35 / 45)
    assert stats["away_service_points_won"] == pytest.approx(25 / 40)
    assert stats["home_return_points_won"] == pytest.approx(15 / 40)
    assert stats["away_return_points_won"] == pytest.approx(10 / 45)


def test_normalizer_never_claims_canonical_orientation():
    row = normalize_raw_row({
        "match_id": "m-1",
        "event_id": "123",
        "fetched_at": "2026-09-27T20:00:00+00:00",
        "provider_response": provider_fixture(),
    })
    assert row["provider_event_id"] == "123"
    assert row["orientation"] == "UNVERIFIED"
    assert row["import_ready"] is False
    assert row["home_away_stats"]["home_service_points_won"] == pytest.approx(35 / 45)


def test_build_stage_emits_schema_two_and_rejects_duplicate_identity(tmp_path):
    raw = tmp_path / "provider_responses.jsonl"
    source = {
        "match_id": "m-1", "event_id": "123",
        "provider_response": provider_fixture(),
    }
    raw.write_text(json.dumps(source) + "\n", encoding="utf-8")
    stage = tmp_path / "stage.zip"
    manifest = build_stage(raw, stage)
    assert manifest["schema_version"] == 2
    assert manifest["stage_rows"] == 1
    assert manifest["rows_with_both_players_quality"] == 1
    with zipfile.ZipFile(stage) as archive:
        saved = json.loads(archive.read("manifest.json"))
        staged = json.loads(archive.read("staged_serve_return.jsonl").decode().strip())
    assert saved["orientation"] == "UNVERIFIED"
    assert staged["import_ready"] is False

    raw.write_text(json.dumps(source) + "\n" + json.dumps(source) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate raw staging match ID"):
        build_stage(raw, tmp_path / "duplicate.zip")


def test_invalid_or_zero_denominators_are_omitted_not_invented():
    payload = provider_fixture()
    service = payload["statistics"][0]["groups"][0]["statisticsItems"]
    service[2]["homeTotal"] = 0
    service[3]["awayTotal"] = None
    stats = extract_home_away_stats(payload)
    assert "home_first_serve_win" not in stats
    assert "away_second_serve_win" not in stats
    assert stats["home_aces"] == 5
