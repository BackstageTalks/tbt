from datetime import datetime, timezone
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts.link_pointbypoint_serve_return import (
    _parse_pbp,
    _pbpx_score_validated,
    _source_files,
    _source_tour,
    _winner_side,
    _historical_alias_indexes,
    _resolve_historical_alias,
)


def test_tennisvisuals_zero_based_winner_mapping():
    assert _winner_side("0", zero_based=True) == 1
    assert _winner_side("1", zero_based=True) == 2
    assert _winner_side("2", zero_based=True) is None
    assert _winner_side("1") == 1
    assert _winner_side("2") == 2


def test_tennisvisuals_tour_mapping_for_lower_tours():
    assert _source_tour({"tour": "ATP"}, Path("ATP_Singles_pbp.csv")) == "atp"
    assert _source_tour({"tour": "CHALLENGER"}, Path("CHALLENGER_Singles_pbp.csv")) == "atp"
    assert _source_tour({"tour": "ITF Men"}, Path("ITF-Men_Singles_pbpx.csv")) == "atp"
    assert _source_tour({"tour": "WTA"}, Path("WTA_Singles_pbpx.csv")) == "wta"
    assert _source_tour({"tour": "WTA 125K"}, Path("WTA-125K_Singles_pbpx.csv")) == "wta"
    assert _source_tour({"tour": "ITF Women"}, Path("ITF-Women_Singles_pbpx.csv")) == "wta"


def test_source_files_accepts_validated_singles_and_rejects_doubles(tmp_path):
    names = [
        "pbp_matches_atp_main_archive.csv",
        "ATP_Singles_pbp.csv",
        "ATP_Singles_pbpx.csv",
        "ITF-Men_Singles_pbpx.csv",
        "WTA_Doubles_pbpx.csv",
    ]
    for name in names:
        (tmp_path / name).write_text("date,server1,server2,pbp\n", encoding="utf-8")
    selected = {p.name for p in _source_files(tmp_path)}
    assert "pbp_matches_atp_main_archive.csv" in selected
    assert "ATP_Singles_pbp.csv" in selected
    assert "ATP_Singles_pbpx.csv" in selected
    assert "ITF-Men_Singles_pbpx.csv" in selected
    assert "WTA_Doubles_pbpx.csv" not in selected


def test_validated_rich_pbp_parser_handles_lowercase_aces_and_double_faults():
    parsed = _parse_pbp("sAsrS;SDsSrS;SsRSRRsDSrSRSS")
    assert parsed is not None
    assert parsed["point_count"] > 0
    assert 0.0 <= parsed[1]["service_points_won"] <= 1.0
    assert 0.0 <= parsed[2]["return_points_won"] <= 1.0


def _match(mid, name1, name2, pid1="player-1", pid2="player-2", day="2016-05-05"):
    return SimpleNamespace(
        match_id=mid, tour="atp", scheduled_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
        player1_id=pid1, player2_id=pid2, player1_name=name1, player2_name=name2,
        tournament="Madrid", round_name="R16", surface="Clay", winner_id=pid1,
    )


def test_unique_canonical_historical_alias_requires_same_canonical_id():
    history = [
        _match("prior", "JoaoSousa", "Jack Sock", day="2015-05-05"),
        _match("target", "Joao Sousa", "Jack Sock"),
    ]
    result = _resolve_historical_alias(
        _historical_alias_indexes(history),
        "atp", "2016-05-05", "JoaoSousa", "Jack Sock",
        "Madrid", "Clay", "R16",
    )
    assert result is not None
    assert result[0].match_id == "target"
    assert result[1] == ((1, "p1"), (2, "p2"))
    assert result[2] == "canonical_historical_alias"


def test_compact_name_requires_unique_global_id_and_event_corroboration():
    indexes = _historical_alias_indexes([_match("target", "Joao Sousa", "Jack Sock")])
    matched = _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Madrid", "Clay", "R16",
    )
    assert matched is not None
    assert matched[2] == "canonical_unique_compact_alias"
    assert _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Other", "Clay", "R16",
    ) is None
    assert _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Madrid", "Hard", "R16",
    ) is None
    assert _resolve_historical_alias(
        indexes, "atp", "2016-05-06", "JoaoSousa", "Jack Sock", "Madrid", "Clay", "R16",
    ) is None


def test_homonym_canonical_ids_never_become_alias_matches():
    matches = [
        _match("target", "Joao Sousa", "Jack Sock"),
        _match("homonym", "JoaoSousa", "Different Person", pid1="other-id", pid2="different-id", day="2017-05-05"),
    ]
    assert _resolve_historical_alias(
        _historical_alias_indexes(matches),
        "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Madrid", "Clay", "R16",
    ) is None


def test_source_orientation_can_be_swapped_without_guessing_identity():
    indexes = _historical_alias_indexes([_match("target", "Joao Sousa", "Jack Sock")])
    matched = _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "Jack Sock", "JoaoSousa", "Madrid", "Clay", "R16",
    )
    assert matched is not None
    assert matched[1] == ((1, "p2"), (2, "p1"))


def _synthetic_6_0_6_0_pbpx():
    # Six games per set: server 1 wins all games, including receiving games.
    # Deliberately record an ace for player 1 and a double fault for player 2.
    games = ["ASSS", "DRRR", "SSSS", "RRRR", "SSSS", "RRRR"]
    return ";".join(games) + "." + ";".join(games)


def test_pbpx_tape_not_raw_winner_is_server_relative():
    parsed = _parse_pbp(_synthetic_6_0_6_0_pbpx())
    assert parsed is not None
    assert parsed["winner_side"] == 1
    assert parsed["set_games"] == [(6, 0), (6, 0)]
    assert parsed[1]["aces"] == 2
    assert parsed[2]["double_faults"] == 2
    # A score from the opposite draw orientation is valid, even when
    # source winner=1 is not server2. This was the lost-data root cause.
    assert _pbpx_score_validated(parsed, "0-6 0-6")
    assert _pbpx_score_validated(parsed, "6-0 6-0")
    assert not _pbpx_score_validated(parsed, "6-1 6-0")
    assert not _pbpx_score_validated(parsed, "6-0 0-6")


def test_pbpx_linker_uses_point_tape_winner_and_stages_missing_counts(tmp_path, monkeypatch):
    import scripts.link_pointbypoint_serve_return as linker
    match = _match("safe", "Andy Murray", "Gilles Simon")
    match.stats = {}
    match.provider_payload = {}
    match.tournament = "Madrid"
    match.round_name = "R16"
    match.surface = "Clay"
    monkeypatch.setattr(linker, "load_partitions", lambda *args: [match])
    monkeypatch.setattr(
        linker, "sanitize_history_identities",
        lambda rows: (list(rows), {"quarantined_rows": 0}),
    )
    sourcedir = tmp_path / "source"
    sourcedir.mkdir()
    with (sourcedir / "ATP_Singles_pbpx.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "date", "tournament", "type", "tour", "draw",
            "server1", "server2", "winner", "pbp", "score",
            "adf_flag", "round", "surface",
        ])
        writer.writeheader()
        writer.writerow({
            "date": "2016-05-05", "tournament": "Madrid",
            "type": "Singles", "tour": "ATP", "draw": "64",
            "server1": "Andy Murray", "server2": "Gilles Simon",
            "winner": "1", "pbp": _synthetic_6_0_6_0_pbpx(),
            "score": "0-6 0-6", "adf_flag": "1",
            "round": "R16", "surface": "Clay",
        })
    out = tmp_path / "link"
    monkeypatch.setattr(
        sys, "argv",
        ["pbpx-linker", "--history-dir", str(tmp_path),
         "--source-dir", str(sourcedir), "--out-dir", str(out)],
    )
    linker.main()
    report = json.loads((out / "report.json").read_text())
    stage = json.loads((out / "auto_linked.jsonl").read_text().strip())
    assert report["counts"]["staged_matches"] == 1
    assert report["quality_ready_projected_added"] == 1
    assert report["counts"]["pbpx_raw_winner_not_server_oriented"] == 1
    assert stage["incoming_stats"]["p1_aces"] == 2.0
    assert stage["incoming_stats"]["p2_double_faults"] == 2.0
    assert "winner_derived_from_point_tape" in stage["provenance"][0]["evidence"]
    assert stage["provenance"][0]["score_validated"] is True

    # An already quality-ready match can still receive missing A/DF counts,
    # without falsely reporting a quality-ready coverage increase.
    decoded = _parse_pbp(_synthetic_6_0_6_0_pbpx())
    match.stats = {
        f"p{side}_{field}": decoded[side][field]
        for side in (1, 2)
        for field in ("service_points_won", "return_points_won")
    }
    out2 = tmp_path / "link2"
    monkeypatch.setattr(
        sys, "argv",
        ["pbpx-linker", "--history-dir", str(tmp_path),
         "--source-dir", str(sourcedir), "--out-dir", str(out2)],
    )
    linker.main()
    report2 = json.loads((out2 / "report.json").read_text())
    stage2 = json.loads((out2 / "auto_linked.jsonl").read_text().strip())
    assert report2["quality_ready_projected_added"] == 0
    assert report2["counts"]["staged_matches"] == 1
    assert set(stage2["incoming_stats"]) == {
        "p1_aces", "p1_double_faults", "p2_aces", "p2_double_faults",
    }

    # A hist-js canonical timestamp denotes tournament start, NOT the point
    # tape's match date; a day-3 result must not leak into day-0 features.
    match.match_id = "hist-js:atp:test"
    match.scheduled_at = datetime(2016, 5, 2, tzinfo=timezone.utc)
    # Production workflow sets SOURCE_REF globally; test the fail-closed
    # behavior when the immutable source pin is deliberately unavailable.
    monkeypatch.delenv("SOURCE_REF", raising=False)
    out3 = tmp_path / "link3"
    monkeypatch.setattr(
        sys, "argv",
        ["pbpx-linker", "--history-dir", str(tmp_path),
         "--source-dir", str(sourcedir), "--out-dir", str(out3)],
    )
    linker.main()
    report3 = json.loads((out3 / "report.json").read_text())
    assert report3["counts"]["window_pit_blocked"] == 1
    assert report3["quality_ready_projected_added"] == 0
    assert (out3 / "auto_linked.jsonl").read_text() == ""

    # Source timestamp evidence now permits PRIVATE, nonconsumable canonical
    # archival metadata without smuggling late stats into early-date features.
    monkeypatch.setenv("SOURCE_REF", "a" * 40)
    out4 = tmp_path / "link4"
    monkeypatch.setattr(
        sys, "argv",
        ["pbpx-linker", "--history-dir", str(tmp_path),
         "--source-dir", str(sourcedir), "--out-dir", str(out4)],
    )
    linker.main()
    report4 = json.loads((out4 / "report.json").read_text())
    saved = json.loads((out4 / "auto_linked.jsonl").read_text().strip())
    assert report4["counts"]["pit_evidence_only_staged"] == 1
    assert report4["quality_ready_projected_added"] == 0
    assert saved["incoming_stats"] == {}
    assert saved["baseline_stats"] == match.stats
    assert saved["delayed_observation"]["source_date"] == "2016-05-05"
    assert saved["delayed_observation"]["status"] == "pit_quarantined_unconsumed"
    assert saved["delayed_observation"]["stats"]["p1_aces"] == 2.0
    assert saved["delayed_observation"]["source_ref"] == "a" * 40


def test_pbpx_canonical_payload_retains_provenance():
    from tbt.data.provider_context import minimize_provider_payload
    marker = {
        "schema": 1, "source": "tennisvisuals_validated_pointbypoint",
        "source_file": "ATP_Singles_pbpx.csv", "source_row": 42,
        "source_ref": "pinned-sha", "source_date": "2016-05-05",
        "score_validated": True, "stat_keys": ["p1_aces"],
    }
    reduced = minimize_provider_payload({"_tbt_pbpx_enrichment": marker})
    assert reduced["_tbt_pbpx_enrichment"] == marker

    delayed = {
        "schema": 1, "source": "tennisvisuals_validated_pointbypoint",
        "source_file": "ATP_Singles_pbpx.csv", "source_row": 42,
        "source_ref": "a" * 40, "source_date": "2016-05-05",
        "status": "pit_quarantined_unconsumed",
        "score_validated": True,
        "stats": {
            f"{p}_{field}": 0.5 if field.endswith("_won") else 3.0
            for p in ("p1", "p2")
            for field in ("service_points_won", "return_points_won", "aces", "double_faults")
        },
    }
    assert minimize_provider_payload({
        "_tbt_pbpx_delayed_observation": delayed,
    })["_tbt_pbpx_delayed_observation"] == delayed
