"""Exact source-only player-name recovery regression tests."""
from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from scripts.tennisdata_source_aliases import compact_matches_full, expand_pair, expand_verified_event, load_map
from scripts.cdb_inbox_adapter import run


def sample():
    return {
        "match_id": "unit-1",
        "tour_type_human": "ATP Tour",
        "date_timestamp": str(int(datetime(2026, 10, 17, tzinfo=timezone.utc).timestamp())),
        "date_human": "17 Oct 2026",
        "tournament": "Vienna ATP",
        "round": "QF",
        "surface": "hard",
        "status": "FINISHED",
        "status_extra": "FINISHED",
        "home_name": "One A.",
        "away_name": "Two B.",
        "home_id": "101",
        "away_id": "102",
        "winner_code": "2",
        "home_set_score": "0",
        "away_set_score": "2",
        "home_aces": "3",
        "away_aces": "7",
        "home_service_points_won_perc": "61",
        "away_return_points_won_perc": "39",
        "away_service_points_won_perc": "65",
        "home_return_points_won_perc": "35",
    }


def map_file(tmp_path, current_source_sha):
    filenames = [
        f"{year}-{tour}-season(1).csv"
        for year in range(2021, 2027)
        for tour in ("atp", "wta")
    ]
    shas = {
        name: (current_source_sha if name == "2026-atp-season(1).csv"
               else hashlib.sha256(name.encode()).hexdigest())
        for name in filenames
    }
    payload = {
        "schema": 1,
        "mode": "SOURCE_ONLY_NO_CANONICAL_ID_ASSERTION",
        "raw_season_sha256": shas,
        "profiles": [
            {"tour": "atp", "local_id": "101", "full_name": "Alpha One"},
            {"tour": "atp", "local_id": "102", "full_name": "Beta Two"},
        ],
    }
    p = tmp_path / "map.json"
    p.write_text(json.dumps(payload) + "\n")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return p, digest


def test_compact_name_requires_proven_surname_and_given_initial():
    assert compact_matches_full("Fritz T.", "Taylor Fritz")
    assert compact_matches_full("Ruse G.", "Elena Gabriela Ruse")
    assert compact_matches_full("Smith T. N.", "Tina Nadine Smith")
    assert not compact_matches_full("Smith T.", "Thomas Smythe")
    assert not compact_matches_full("One Z.", "Alpha One")
    assert not compact_matches_full("One", "Alpha One")


def test_sha_pinned_source_alias_round_trip(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    path = source / "2026-atp-season(1).csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sample())
        w.writeheader()
        w.writerow(sample())
    p, digest = map_file(tmp_path, hashlib.sha256(path.read_bytes()).hexdigest())
    report = run(source, tmp_path / "output", source_alias_map_path=p,
                 expected_source_alias_sha256=digest)
    assert report["production_mutated"] is False
    assert report["api_requests"] == 0
    assert report["counts"]["tennisdata_alias_two_source_names_verified"] == 1
    assert report["source_alias_map_sha256"] == digest
    out = next(csv.DictReader(open(report["normalized"][0]["path"])))
    assert out["winner_name"] == "Beta Two"
    assert out["loser_name"] == "Alpha One"
    assert out["w_ace"] == "7"
    assert out["l_ace"] == "3"
    assert out["source_winner_id"] == "102"
    assert out["source_loser_id"] == "101"
    # The original bytes and abbreviated names were never changed.
    assert next(csv.DictReader(path.open()))["home_name"] == "One A."


def test_bad_sha_or_untrusted_source_never_expands(tmp_path):
    src = tmp_path / "a.csv"
    src.write_text("x\n1\n")
    good_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    p, digest = map_file(tmp_path, good_sha)
    with pytest.raises(ValueError, match="SHA mismatch"):
        load_map(p, "0" * 64)
    m = load_map(p, digest)
    row = sample()
    assert expand_pair(row, "1" * 64, m) == (row, "source_sha_not_in_pinned_batch")
    altered = dict(row, home_name="One Z.")
    assert expand_pair(altered, good_sha, m) == (altered, "compact_full_name_disagreement")
    assert expand_pair(row, good_sha, m)[1] == "two_source_names_verified"


def test_cross_tour_id_and_partial_alias_are_not_inferred(tmp_path):
    p, digest = map_file(tmp_path, "a" * 64)
    m = load_map(p, digest)
    raw = dict(sample(), tour_type_human="WTA Tour")
    assert expand_pair(raw, "a" * 64, m)[1] == "not_both_uniquely_named"
    raw = dict(sample(), away_id="999")
    assert expand_pair(raw, "a" * 64, m)[1] == "not_both_uniquely_named"
    raw = dict(sample(), home_id="102", away_id="102")
    assert expand_pair(raw, "a" * 64, m)[1] == "missing_or_equal_player_ids"


def test_event_translation_is_explicit_opt_in_and_preserves_raw_stats(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    row = dict(sample(), tournament="French Open ATP", round="1/8-finals")
    path = source / "2026-atp-season(1).csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    p, digest = map_file(tmp_path, original_sha)
    first = run(source, tmp_path / "regular", source_alias_map_path=p,
                expected_source_alias_sha256=digest)
    extra = run(source, tmp_path / "translated", source_alias_map_path=p,
                expected_source_alias_sha256=digest,
                tennisdata_verified_event_aliases=True)
    a = next(csv.DictReader(open(first["normalized"][0]["path"])))
    b = next(csv.DictReader(open(extra["normalized"][0]["path"])))
    assert a["tourney_name"] == "French Open"
    assert b["tourney_name"] == "Roland Garros"
    assert extra["counts"]["tennisdata_event_alias_exact_whitelist_hit"] == 1
    assert {k: v for k, v in a.items() if k != "tourney_name"} == {
        k: v for k, v in b.items() if k != "tourney_name"}
    assert original_sha == hashlib.sha256(path.read_bytes()).hexdigest()
    assert extra["production_mutated"] is False
    assert extra["api_requests"] == 0


def test_event_translation_rejects_untrusted_source_and_challenger_or_unknown_event(tmp_path):
    p, digest = map_file(tmp_path, "a" * 64)
    alias_map = load_map(p, digest)
    row = dict(sample(), tournament="French Open ATP")
    assert expand_verified_event(row, "1" * 64, alias_map) == (
        row, "source_sha_not_in_pinned_batch")
    challenger = dict(row, tour_type_human="ATP Chall")
    assert expand_verified_event(challenger, "a" * 64, alias_map) == (
        challenger, "not_main_tour")
    unsupported = dict(row, tournament="Milan ATP")
    assert expand_verified_event(unsupported, "a" * 64, alias_map) == (
        unsupported, "not_whitelisted")
    expanded, status = expand_verified_event(row, "a" * 64, alias_map)
    assert status == "exact_whitelist_hit"
    assert expanded["tournament"] == "Roland Garros"
    assert row["tournament"] == "French Open ATP"


def test_event_translation_needs_exact_private_mapping(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    with pytest.raises(ValueError, match="require SHA-pinned"):
        run(source, tmp_path / "output", tennisdata_verified_event_aliases=True)
