from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import audit_figshare_wimbledon_2023 as mod


def test_auditor_detects_point_table(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    pd.DataFrame([
        {
            "match_id": "m1",
            "player1": "A",
            "player2": "B",
            "set_no": 1,
            "game_no": 1,
            "point_no": 1,
            "server": "A",
            "point_winner": "A",
            "serve_speed": 185,
            "rally_count": 3,
            "break_point": 0,
        },
        {
            "match_id": "m1",
            "player1": "A",
            "player2": "B",
            "set_no": 1,
            "game_no": 1,
            "point_no": 2,
            "server": "A",
            "point_winner": "B",
            "serve_speed": 178,
            "rally_count": 5,
            "break_point": 1,
        },
    ]).to_csv(src / "points.csv", index=False)

    result = mod.inspect_file(src / "points.csv", src)
    table = result["tables"][0]
    assert table["rows"] == 2
    assert table["point_schema_score"] >= 3
    assert table["identity_schema_score"] >= 2
    assert "match_id" in table["columns"]


def test_manifest_is_stable_and_research_only(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "note.txt").write_text("CC BY 4.0", encoding="utf-8")
    frame = pd.DataFrame({"server": ["A"], "point_winner": ["A"], "score": ["15-0"]})
    frame.to_csv(src / "data.csv", index=False)

    inspected = [mod.inspect_file(path, src) for path in sorted(src.iterdir())]
    assert all(item["sha256"] for item in inspected)
    assert any(item.get("tables") for item in inspected)
