"""Contract tests for private Drive inbox source normalization and safe link filtering."""
import csv
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.cdb_inbox_adapter import run as normalize, normalize as normalize_row, read_rows, pieces
from scripts.cdb_inbox_stage import run as stage


def sample(**kw):
    row = {
        "tour": "ATP", "match_date": "2026-10-17",
        "tournament": "Vienna", "winner": "Alpha One", "loser": "Beta Two",
        "round": "QF", "surface": "Hard",
        "w_svpt": "70", "w_1stIn": "40", "w_1stWon": "30", "w_2ndWon": "14",
        "l_svpt": "60", "l_1stIn": "35", "l_1stWon": "25", "l_2ndWon": "11",
    }
    row.update(kw)
    return row


def test_normalize_csv_uses_approved_source_columns(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    with (src / "tennis.csv").open("w", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=sample())
        writer.writeheader()
        writer.writerow(sample())
        writer.writerow(sample(tour="unknown"))
    result = normalize(src, out)
    assert result["production_mutated"] is False
    assert result["counts"]["normalized_rows"] == 1
    assert result["counts"]["rejected_rows"] == 1
    output = Path(result["normalized"][0]["path"])
    rows = list(csv.DictReader(output.open()))
    assert rows[0]["tourney_date"] == "20261017"
    assert rows[0]["tourney_name"] == "Vienna"
    assert rows[0]["w_svpt"] == "70"


def test_json_zip_and_identical_duplicate_bytes(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    raw = json.dumps({"matches": [sample(tour="WTA")]}).encode()
    (src / "one.json").write_bytes(raw)
    (src / "two.json").write_bytes(raw)
    with zipfile.ZipFile(src / "bundle.zip", "w") as archive:
        archive.writestr("wta_match.jsonl", json.dumps(sample(tour="WTA")))
    report = normalize(src, out)
    assert report["counts"]["duplicate_source_files"] == 1
    assert report["counts"]["normalized_rows"] == 2
    assert all(x["tour"] == "wta" for x in report["normalized"])


def test_bad_file_refuses_false_import_ready(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (src / "bad.jsonl").write_text(json.dumps({"tour": "ATP", "winner": "A"}) + "\n")
    result = normalize(src, out)
    assert result["normalized"] == []
    assert result["counts"]["rejected_rows"] == 1


def test_zip_oversize_rejected_without_unbounded_extraction(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    with zipfile.ZipFile(src / "too-large.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("records.csv", b"x" * (33 * 1024 * 1024))
    result = normalize(src, out)
    assert not result["normalized"]
    assert result["counts"].get("invalid_archives", 0) == 1


def test_stage_requires_exact_day_tournament_winner_and_extra_evidence(tmp_path, monkeypatch):
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    sample_file = normalized / "atp_0123456789abcdef_0.csv"
    sample_file.write_text("league\natp\n")
    manifest = tmp_path / "report.json"
    manifest.write_text(json.dumps({"normalized": [{"path": str(sample_file)}]}))

    def fake_link(command, **kw):
        link_dir = Path(command[command.index("--out-dir") + 1])
        link_dir.mkdir(parents=True)
        (link_dir / "report.json").write_text(json.dumps({"production_mutated": False,
            "api_requests": 0, "counts": {"identity_linked": 3}, "source_rows": 3}))
        def row(mid, proof):
            return {"schema": 1, "import_ready": True, "match_id": mid,
                    "canonical": {"tour": "atp", "scheduled_date_utc": "2026-10-17"},
                    "incoming_stats": {"p1_aces": 7},
                    "sources": [{"source": "sackmann:" + sample_file.name, "evidence": proof}]}
        rows = [
            row("good", ["date_exact", "winner", "tournament_exact", "round"]),
            row("weak", ["date_tournament_window", "winner", "tournament_exact", "round"]),
            row("conflict", ["date_exact", "winner", "tournament_exact", "surface"]),
        ]
        (link_dir / "auto_linked.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
        (link_dir / "quarantine.jsonl").write_text(json.dumps({"match_id": "conflict"}) + "\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.cdb_inbox_stage.subprocess.run", fake_link)
    result = stage(manifest, tmp_path / "history", tmp_path / "stage")
    assert result["eligible_matches"] == 1
    assert result["eligible_new_values"] == 1
    assert result["filtered_matches"] == 2
    assert result["conflict_matches"] == 1
    assert json.loads((tmp_path / "stage/eligible.jsonl").read_text())["match_id"] == "good"
