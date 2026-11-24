from datetime import datetime
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import morning_reliability as mr

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("top,value,sends", [(0, 0, 1), (1, 0, 0), (0, 1, 0)])
def test_alarm_uses_only_admin_destination(monkeypatch, top, value, sends):
    for k in ("WORKER_TOKEN", "TGB", "TG_ADMIN_CHAT_ID"):
        monkeypatch.setenv(k, "test")
    monkeypatch.setenv("PUBLIC_BASE", "https://example.invalid")
    calls = []
    def open_request(req, **kw):
        if req.data:
            calls.append(json.loads(req.data)["chat_id"])
            return io.BytesIO(b'{"ok":true}')
        return io.BytesIO(json.dumps({"betting_day":datetime.now(mr.ZONE).date().isoformat(),
            "stale":False, "visible_counts":{"top_daily_picks":top,"value_picks":value},
            "offer_authority_keys":{"top":["t"] if top else [], "value":["v"] if value else []}}).encode())
    monkeypatch.setattr(mr, "urlopen", open_request)
    mr.alarm()
    assert calls == ["test"] * sends


def test_bad_feature_row_preserves_other_prediction(match_factory, monkeypatch):
    from tbt.services import engine
    class Model:
        version = "fixture"
        feature_names = ["elo_diff", "elo_probability", "data_depth"]
        def predict_proba(self, frame):
            return [.66] * len(frame)
    history = [match_factory("past","A","C","A",day=1)]
    good = match_factory("good","A","B",None,day=5)
    bad = match_factory("bad","X","Y",None,day=5)
    now = good.scheduled_at.replace(day=4)
    baseline = engine.predict(Model(), history, [good], now=now)
    original = engine.FeatureBuilder.snapshot
    def snapshot(builder, match):
        if match.match_id == bad.match_id:
            raise ValueError("fixture")
        return original(builder, match)
    monkeypatch.setattr(engine.FeatureBuilder, "snapshot", snapshot)
    quarantine = []
    assert engine.predict(Model(), history, [bad, good], now=now, quarantine=quarantine) == baseline
    assert quarantine == [dict(match_id=bad.match_id, stage="features", reason="ValueError")]


def test_retry_routes_to_cache_only_and_never_redispatches_paid_refresh():
    wrapper = (ROOT / ".github/workflows/morning-refresh.yml").read_text(encoding="utf-8")
    block = wrapper.split('if [[ "$attempt" == 2 ]]; then', 1)[1].split("else",1)[0]
    assert "mode=deploy-current" in block and "mode=refresh " not in block
    assert wrapper.count("dispatch_child 2") == 1
    assert 'wait_child "$first_child"' in wrapper and '"$GITHUB_RUN_ATTEMPT" == 1' in wrapper
    workflow = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
    recovery = workflow.split('elif [[ "$MODE" == deploy-current ]]; then',1)[1].split("elif",1)[0].split("else\n",1)[0]
    assert "scripts/pipeline.py" not in recovery
    assert "No complete current-day cached offer" in workflow
