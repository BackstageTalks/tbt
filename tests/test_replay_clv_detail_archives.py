import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/replay_clv_detail_archives.py"
spec = importlib.util.spec_from_file_location("replay_clv_detail_archives", PATH)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def _event(market="h2h"):
    return {
        "event_id": "8888", "home_team": "A", "away_team": "B",
        "captured_at": "2026-11-01T10:00:00+00:00",
        "commence_time": "2026-11-01T13:00:00+00:00",
        "bookmakers": [{"key": "X", "markets": [
            {"key": market, "outcomes": [
                {"name": "A", "price": 2.2},
                {"name": "B", "price": 1.8},
            ]}
        ]}],
    }


def test_replay_removes_player_props_without_touching_original():
    obj = {"schema": 1, "events": [_event(), _event("player_aces")]}
    clean = replay.h2h_events(obj)
    assert len(clean) == 1
    assert clean[0]["bookmakers"][0]["markets"][0]["key"] == "h2h"
    assert obj["events"][1]["bookmakers"][0]["markets"][0]["key"] == "player_aces"


def test_replay_rejects_unrecognized_schema():
    assert replay.h2h_events({"schema": 3, "events": [_event()]}) == []


def test_replay_accepts_only_verified_runtime_counts(monkeypatch):
    monkeypatch.setattr(replay, "BASE", "https://blinq.test")
    monkeypatch.setattr(replay, "WORKER", "worker")
    class FakeResponse:
        def __init__(self, obj):
            self.obj = obj
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self):
            import json
            return json.dumps(self.obj).encode()
    def good(req, timeout):
        return FakeResponse({"ok": True, "accepted": 1, "verified": 1,
                             "written": 1})
    monkeypatch.setattr(replay.urllib.request, "urlopen", good)
    assert replay.send([_event()])["verified"] == 1
    def bad(req, timeout):
        return FakeResponse({"ok": True, "accepted": 2, "verified": 1})
    monkeypatch.setattr(replay.urllib.request, "urlopen", bad)
    import pytest
    with pytest.raises(RuntimeError, match="read-back"):
        replay.send([_event()])
