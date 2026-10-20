"""Recent full-name ATP/WTA source gates are strict and read-only."""
import json

import pytest

from scripts.cdb_recent_pinned_sources import SOURCES, fetch_sources
from scripts.cdb_recent_strict_stage import filter_links


def _jsonl(path, values):
    path.write_text("".join(json.dumps(x) + "\n" for x in values))


def test_all_recent_pins_distinct_and_bounded():
    assert len(SOURCES) == 6
    assert len({(row[0], row[1]) for row in SOURCES}) == 6
    assert {tour for tour, *_ in SOURCES} == {"atp", "wta"}
    assert all(len(sha) == 64 and 0 < size < 2 * 1024 * 1024
               for _tour, _year, _id, sha, size in SOURCES)


def test_never_overwrite_pinned_source_directory(tmp_path):
    target = tmp_path / "data"
    target.mkdir()
    (target / "existing").write_text("protect")
    with pytest.raises(ValueError, match="must be empty"):
        fetch_sources(target)
    assert (target / "existing").read_text() == "protect"


def test_strict_acceptance_with_source_provenance_and_conflict_quarantine(tmp_path):
    link, out = tmp_path / "link", tmp_path / "stage"
    link.mkdir()
    normalized = tmp_path / "normalized.json"
    normalized.write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "normalized": [
            {"tour": "wta", "path": "work/source/wta_normalized_0.csv"},
            {"tour": "atp", "path": "work/source/atp_normalized_0.csv"},
        ]}))
    (link / "report.json").write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "matching_strategy": "verified_ids", "source_rows": 12, "counts": {},
    }))
    all_evidence = ["winner", "tournament_exact", "surface", "round",
                    "date_tournament_window"]
    def row(mid, source, tour, ev=all_evidence, year=2024):
        return {"schema": 1, "match_id": mid, "import_ready": True,
                "canonical": {"tour": tour,
                              "scheduled_date_utc": f"{year}-04-14"},
                "incoming_stats": {"p1_service_points_won": 0.54},
                "sources": [{"source": source, "evidence": ev}]}
    _jsonl(link / "auto_linked.jsonl", [
        row("wta-ok", "sackmann:wta_normalized_0.csv", "wta"),
        row("atp-ok", "sackmann:atp_normalized_0.csv", "atp"),
        row("conflict", "sackmann:atp_normalized_0.csv", "atp"),
        row("weak", "sackmann:wta_normalized_0.csv", "wta",
            ["winner", "tournament_exact", "surface", "date_tournament_window"]),
        row("cross-tour", "sackmann:atp_normalized_0.csv", "wta"),
        row("outdated", "sackmann:wta_normalized_0.csv", "wta", year=2020),
    ])
    _jsonl(link / "quarantine.jsonl", [{"match_id": "conflict"}])
    result = filter_links(link, normalized, out)
    assert result["eligible_matches"] == 2
    assert result["eligible_new_stat_fields"] == 2
    assert result["eligible_by_year_tour"] == {"2024_atp": 1, "2024_wta": 1}
    assert result["reasons"] == {
        "canonical_stats_conflict": 1,
        "insufficient_independent_identity": 2,
        "outside_2023_2026": 1,
    }
    assert result["production_mutated"] is False
    assert result["api_requests"] == 0
    with pytest.raises(ValueError, match="Refusing overwrite"):
        filter_links(link, normalized, out)


def test_adapter_or_linker_violation_rejected(tmp_path):
    link = tmp_path / "link"
    link.mkdir()
    (link / "report.json").write_text(json.dumps({
        "production_mutated": True, "api_requests": 0,
        "matching_strategy": "verified_ids"}))
    source = tmp_path / "normalized.json"
    source.write_text(json.dumps({"production_mutated": False, "api_requests": 0,
                                   "normalized": [{"tour": "wta", "path": "wta_a.csv"}]}))
    with pytest.raises(ValueError, match="read-only/identity"):
        filter_links(link, source, tmp_path / "out")
