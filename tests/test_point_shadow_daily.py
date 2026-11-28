from datetime import datetime, timedelta, timezone
from hashlib import sha256
import gzip
import json
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import build_point_model_shadow as builder
import point_shadow_blob as blob
from tbt.schemas import MatchRecord
from tbt.services import point_model_shadow, point_shadow_results as results

UTC = timezone.utc


def test_capture_freeze_replay_and_grade(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    # Local noon tomorrow works even when this test runs around midnight or DST.
    start = (now.astimezone(ZoneInfo("Europe/Bratislava")) + timedelta(days=1)).replace(hour=12)
    candidate = tmp_path/"candidate"
    candidate.write_bytes(b"fixture")
    monkeypatch.setattr(builder, "MODEL_SHA", sha256(b"fixture").hexdigest())
    matches, predictions = [], []
    for key, level, date in [("a", "ATP", start), ("b", "ITF M15", start),
                             ("c", "Challenger", start+timedelta(days=1)), ("d", "WTA 125", start),
                             ("e", "Challenger", start), ("f", "WTA", start), ("g", "ATP", now)]:
        tour = "wta" if level.startswith("WTA") else "atp"
        m = MatchRecord(key, tour, date, "1","A","2","B", tournament_level=level)
        matches.append(m)
        predictions.append({"id":key, "event_id":key, "scheduled_at":date.isoformat(),
                            "created_at":now.isoformat(), "player1":{"id":"1","probability":.67},
                            "player2":{"id":"2"}})
    saved = {}
    monkeypatch.setattr(blob, "publish", saved.update)
    monkeypatch.setattr(builder, "load_partitions", lambda *a, **kw: [])
    builder.capture_morning(matches, predictions, candidate, tmp_path)
    assert set(saved) == {"a","d","e","f"}
    card = saved["a"]
    assert datetime.fromisoformat(card["frozen_at"]) < start
    assert card["schema"] == 3 and card["model_version"] == "point-model-v2:" + builder.CANDIDATE
    assert len(card["calibration_version"]) == 64
    event = {"id":"a", "homeTeam":{"id":"2"}, "awayTeam":{"id":"1"},
             "status":{"type":"finished"}, "winnerCode":2,
             "homeScore":{"current":0,"period1":6,"period2":2},
             "awayScore":{"current":2,"period1":7,"period2":6}}
    after = start + timedelta(hours=3)
    actual = results.outcome(card, event, after)
    assert actual == {"set_score":"2:0","games":21,"margin_p1":5,"tiebreak":True}
    for status in ("retired", "walkover", "inprogress"):
        assert results.outcome(card, dict(event, status=status), after) is None
    assert results.outcome(card, dict(event, homeScore={"period1":6}), after) is None
    assert results.outcome(card, dict(event, actual_started_at=now.isoformat()), after) is None
    markets = list(results.markets(card, actual))
    observations = {name:y for name,p,y in markets}
    assert observations["over 20.5"] and not observations["over 21.5"]
    assert observations["P1 -3.5"] and not observations["P2 +3.5"]
    # Persist twice via the real settlement path, using an in-memory table.
    card["scheduled_at"] = (now-timedelta(hours=2)).isoformat()
    card["frozen_at"] = (now-timedelta(hours=3)).isoformat()
    from tbt.services import admin_storage
    records = []
    table = MagicMock()
    table.query_entities.side_effect = lambda *a, **kw: records
    table.create_entity.side_effect = records.append
    monkeypatch.setattr(admin_storage, "_table", lambda _: table)
    monkeypatch.setattr(point_model_shadow, "snapshot_cards", lambda: {"a":card})
    results.settle({"a":event})
    results.settle({"a":event})
    assert len(records) == 1
    report = results.summarize(records)
    assert report["count"] == 1 and report["checkpoint"] == 300
    p = next(p for name,p,y in markets if name == "over 20.5")
    row = next(r for r in report["rows"] if (r["market"],r["level"]) == ("over 20.5","ATP"))
    assert row["n"] == 1 and row["ece"] == pytest.approx(1-p)
    assert row["brier"] == pytest.approx((1-p)**2)


def test_blob_first_freeze_wins(tmp_path, monkeypatch):
    store = {}
    monkeypatch.setenv("BLINQ_POINT_BLOB_WRITE_URL", "https://example.invalid/private")
    monkeypatch.setattr(blob, "read_blob", lambda url: (store, '"etag"' if store else None))
    writes = []
    def put(request, **kwargs):
        writes.append(request)
        store.update(json.loads(gzip.decompress(request.data))["cards"])
        return MagicMock()
    monkeypatch.setattr(blob, "urlopen", put)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    first = {"event_id":"a","scheduled_at":tomorrow,"p":.6}
    blob.publish({"one":first})
    blob.publish({"one":dict(first,p=.9), "new-id":dict(first,p=.1)})
    assert len(writes) == 1 and store == {"one":first}


def test_model_failure_does_not_interrupt_offer(tmp_path, monkeypatch, capsys):
    import pipeline
    monkeypatch.setenv("BLINQ_POINT_MODEL_SHADOW", "true")
    model = tmp_path/"model"
    model.write_bytes(b"model")
    def broken(*args):
        raise RuntimeError("private detail")
    monkeypatch.setattr(builder, "capture_morning", broken)
    pipeline._point_shadow_after_offer([], [], [], model, model, tmp_path)
    log = capsys.readouterr().out
    assert "point_model_shadow_failed" in log and "private detail" not in log


def test_packaged_snapshot_reaches_api(tmp_path, monkeypatch):
    card = {"match_id":"a", "frozen_at":"2026-11-27T06:00:00+00:00"}
    monkeypatch.setenv("BLINQ_POINT_BLOB_READ_URL", "read")
    monkeypatch.setattr(blob, "read_blob", lambda url: ({"a":card}, "tag"))
    path = tmp_path/"point_model_shadow.json"
    blob.package(path)
    monkeypatch.setenv(point_model_shadow.SNAPSHOT, str(path))
    assert point_model_shadow.shadow_card("a") == card
    assert point_model_shadow.shadow_card("missing") is None
