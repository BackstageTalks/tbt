from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

from link_offline_serve_return import _charting_match_metadata  # noqa: E402


def _raw(text: str):
    return io.BytesIO(text.encode("utf-8"))


def test_charting_metadata_repairs_omitted_surface() -> None:
    rows = _charting_match_metadata(_raw(
        "match_id,Player 1,Player 2,Pl 1 hand,Pl 2 hand,Date,Tournament,Round,Time,Court,Surface,Umpire,Best of,Final TB?,Charted by\n"
        "m1,Tallon Griekspoor,Flavio Cobolli,R,R,20240915,Davis Cup World Group,RR,18:05,Unipol Arena,Eva Asderaki-Moore,3,1\n"
    ))
    assert len(rows) == 1
    row = rows[0]
    assert row["Player 1"] == "Tallon Griekspoor"
    assert row["Player 2"] == "Flavio Cobolli"
    assert row["Surface"] == ""
    assert row["Umpire"] == "Eva Asderaki-Moore"
    assert row["Best of"] == "3"
    assert row["Final TB?"] == "1"


def test_charting_metadata_merges_complementary_duplicate_rows() -> None:
    rows = _charting_match_metadata(_raw(
        "match_id,Player 1,Player 2,Pl 1 hand,Pl 2 hand,Date,Tournament,Round,Time,Court,Surface,Umpire,Best of,Final TB?,Charted by\n"
        "m2,R,R,20240915,Davis Cup World Group,RR,15:15,Unipol Arena,Hard,Arnaud Gabas,3,1,Zindaras\n"
        "m2,Botic Van De Zandschulp,Matteo Berrettini,,,20240915,Davis_Cup_World_Group,RR,,,Hard,,,,Zindaras\n"
    ))
    assert len(rows) == 1
    row = rows[0]
    assert row["Player 1"] == "Botic Van De Zandschulp"
    assert row["Player 2"] == "Matteo Berrettini"
    assert row["Date"] == "20240915"
    assert row["Surface"] == "Hard"
    assert row["Umpire"] == "Arnaud Gabas"
    assert row["Best of"] == "3"
