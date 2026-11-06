"""Offline regression for meaningful verified adaptive evidence selection."""
import json
from datetime import datetime, timezone

import fetch_adaptive_verified_prior as mod


def test_tiny_closeout_does_not_hide_recent_substantive_verified_evidence(monkeypatch):
    now = datetime(2026, 11, 6, 17, 30, tzinfo=timezone.utc)
    runs = [
        {"databaseId": 3, "createdAt": "2026-11-06T17:00:00Z"},
        {"databaseId": 2, "createdAt": "2026-11-06T16:00:00Z"},
        {"databaseId": 1, "createdAt": "2026-11-06T15:00:00Z"},
    ]
    evidence = {
        "3": {"requests_including_retries": 1},
        "2": {"requests_including_retries": 80},
        "1": {"requests_including_retries": 100},
    }
    def gh(*args):
        if args[0:2] == ("run", "list"):
            return json.dumps(runs)
        assert args[0:2] == ("run", "download")
        run_id = args[2]
        directory = args[args.index("--dir") + 1]
        from pathlib import Path
        (Path(directory) / "adaptive_cdb_evidence.json").write_text(
            json.dumps(evidence[run_id]), encoding="utf-8")
        return ""
    monkeypatch.setattr(mod, "_gh", gh)
    monkeypatch.setattr(mod, "validated_prior", lambda data, **kwargs: {})
    assert mod.locate_prior("BackstageTalks/tbt", now=now) == evidence["2"]


def test_all_small_verified_reports_fallback_to_newest(monkeypatch):
    now = datetime(2026, 11, 6, 17, 30, tzinfo=timezone.utc)
    def gh(*args):
        if args[0:2] == ("run", "list"):
            return json.dumps([
                {"databaseId": 3, "createdAt": "2026-11-06T17:00:00Z"},
                {"databaseId": 2, "createdAt": "2026-11-06T16:00:00Z"},
            ])
        from pathlib import Path
        directory = args[args.index("--dir") + 1]
        (Path(directory) / "adaptive_cdb_evidence.json").write_text(
            json.dumps({"requests_including_retries": int(args[2])}),
            encoding="utf-8")
        return ""
    monkeypatch.setattr(mod, "_gh", gh)
    monkeypatch.setattr(mod, "validated_prior", lambda data, **kwargs: {})
    assert mod.locate_prior("BackstageTalks/tbt", now=now) == {
        "requests_including_retries": 3
    }
