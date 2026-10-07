import csv
from pathlib import Path

from scripts.link_kaggle_wta_2016_2017_odds import (
    SOURCE_LABEL,
    build_sidecar,
    deduplicate_source,
)


FIELDS = [
    "date", "name_1", "name_2", "age_1", "age_2",
    "rating_1", "rating_2", "k1", "k2", "result", "player1_is_win?",
]


def _write(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def _pair():
    first = {
        "date": "01.01.2016",
        "name_1": "Samantha Crawford",
        "name_2": "Tsvetana Pironkova",
        "age_1": "20",
        "age_2": "28",
        "rating_1": "142",
        "rating_2": "59",
        "k1": "4.05",
        "k2": "1.27",
        "result": "7-6(1) 6-4",
        "player1_is_win?": "1",
    }
    second = {
        "date": "01.01.2016",
        "name_1": "Tsvetana Pironkova",
        "name_2": "Samantha Crawford",
        "age_1": "28",
        "age_2": "20",
        "rating_1": "59",
        "rating_2": "142",
        "k1": "1.27",
        "k2": "4.05",
        "result": "7-6(1) 6-4",
        "player1_is_win?": "0",
    }
    return first, second


def test_exact_mirror_deduplicates_to_one_match(tmp_path):
    path = tmp_path / "2016-2017_orig.csv"
    _write(path, _pair())
    matches, counts = deduplicate_source(path)
    assert counts["source_rows"] == 2
    assert counts["source_match_groups"] == 1
    assert counts["usable_deduplicated_matches"] == 1
    assert len(matches) == 1
    match = matches[0]
    assert match.player_a == "Samantha Crawford"
    assert match.player_b == "Tsvetana Pironkova"
    assert match.winner == "Samantha Crawford"
    assert match.odds_a == 4.05
    assert match.odds_b == 1.27


def test_inconsistent_mirror_fails_closed(tmp_path):
    path = tmp_path / "2016-2017_orig.csv"
    first, second = _pair()
    second["k1"] = "1.31"
    _write(path, [first, second])
    matches, counts = deduplicate_source(path)
    assert matches == []
    assert counts["mirror_inconsistent"] == 1


def test_invalid_odds_are_not_imported(tmp_path):
    path = tmp_path / "2016-2017_orig.csv"
    first, second = _pair()
    first["k1"] = "-1"
    second["k2"] = "-1"
    _write(path, [first, second])
    matches, counts = deduplicate_source(path)
    assert matches == []
    assert counts["invalid_or_unpriced_match_groups"] == 1


def test_sidecar_is_neutral_and_benchmark_only(tmp_path):
    path = tmp_path / "2016-2017_orig.csv"
    _write(path, _pair())
    match = deduplicate_source(path)[0][0]
    sidecar = build_sidecar(
        match,
        orientation="swapped",
        source_file_sha256="a" * 64,
        evidence=["date_exact", "winner_exact"],
    )
    assert sidecar["source"] == SOURCE_LABEL
    assert sidecar["player1_odds"] == 1.27
    assert sidecar["player2_odds"] == 4.05
    assert sidecar["bookmaker"] is None
    assert sidecar["price_kind"] == "historical_two_way_unspecified_timestamp"
    assert sidecar["model_feature_policy"] == "benchmark_only_no_same_match_training_feature"
