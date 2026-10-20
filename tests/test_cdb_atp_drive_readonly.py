"""Fail-closed tests for partial ATP Drive sources and tournament-window linking."""
import json

import pytest

from scripts.cdb_atp_drive_pinned import PINNED, fetch_sources
from scripts.cdb_atp_drive_strict_stage import filter_atp


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_pinned_drive_sources_have_distinct_ids_and_digests():
    assert {x[0] for x in PINNED} == {2016, 2017}
    assert len({x[1] for x in PINNED}) == len(PINNED)
    assert all(len(x[2]) == 64 and x[3] > 0 for x in PINNED)
    assert PINNED[1][3] < PINNED[0][3]  # 2017 workbook is partial


def test_empty_output_required(tmp_path):
    output = tmp_path / "source"
    output.mkdir()
    (output / "preexisting.txt").write_text("protect")
    with pytest.raises(ValueError, match="must be empty"):
        fetch_sources(output)
    assert (output / "preexisting.txt").read_text() == "protect"


def test_tournament_window_requires_winner_surface_round_and_exact_tournament(tmp_path):
    link = tmp_path / "link"
    link.mkdir()
    stage = tmp_path / "stage"
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "normalized": [{"tour": "atp", "path": "work/source/normalized/atp_sample_0.csv"}],
    }))
    (link / "report.json").write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "matching_strategy": "verified_ids", "source_rows": 5, "counts": {},
    }))
    def row(mid, evidence, year="2016", src="sackmann:atp_sample_0.csv"):
        return {"schema": 1, "match_id": mid, "import_ready": True,
                "canonical": {"tour": "atp", "scheduled_date_utc": year+"-01-06"},
                "incoming_stats": {"p1_aces": 4.0},
                "sources": [{"source": src, "evidence": evidence}]}
    evidence = ["winner", "surface", "round", "tournament_exact", "date_tournament_window"]
    _write_jsonl(link / "auto_linked.jsonl", [
        row("valid", evidence),
        row("conflicted", evidence),
        row("weak", ["winner", "surface", "tournament_exact", "date_tournament_window"]),
        row("foreign", evidence, src="sackmann:unexpected.csv"),
        row("year", evidence, year="2018"),
    ])
    _write_jsonl(link / "quarantine.jsonl", [{"match_id": "conflicted"}])
    report = filter_atp(link, source, stage)
    assert report["eligible_matches"] == 1
    assert report["eligible_new_stat_fields"] == 1
    assert report["reasons"] == {
        "canonical_conflict": 1, "weak_or_conflicting_identity_evidence": 2,
        "wrong_year": 1}
    assert [json.loads(line)["match_id"] for line in
            (stage / "eligible.jsonl").read_text().splitlines()] == ["valid"]
    assert report["production_mutated"] is False
    assert report["api_requests"] == 0
    with pytest.raises(ValueError, match="Refusing overwrite"):
        filter_atp(link, source, stage)


def test_untrusted_linker_result_rejected(tmp_path):
    link = tmp_path / "link"
    link.mkdir()
    src = tmp_path / "report.json"
    src.write_text(json.dumps({"production_mutated": False, "api_requests": 0,
                               "normalized": [{"tour": "atp", "path": "foo.csv"}]}))
    (link / "report.json").write_text(json.dumps({
        "production_mutated": True, "api_requests": 0, "matching_strategy": "verified_ids",
    }))
    with pytest.raises(ValueError, match="read-only|contract"):
        filter_atp(link, src, tmp_path / "out")
