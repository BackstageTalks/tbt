"""No-network regression tests for a one-time, already-issued Telegram addendum."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import telegram_offer_supplement_20261115 as supp


NOW = datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc)


def test_supplement_excludes_previously_sent_top_and_keeps_aces_separate(monkeypatch):
    def ref(row, section):
        return {"channel": section, "event_id": row["event_id"],
                "market": row["market"], "selection_id": row["selection_id"]}
    monkeypatch.setattr(supp.tg, "result_reference", ref)
    old = ref({"event_id": "top-1", "market": "match_winner", "selection_id": "a"}, "top")
    groups = {
        "top": [{"event_id": "top-1", "market": "match_winner", "selection_id": "a"},
                {"event_id": "top-2", "market": "match_winner", "selection_id": "b"}],
        "aces": [{"event_id": "ace-1", "market": "aces", "selection_id": "a"},
                 {"event_id": "ace-2", "market": "aces", "selection_id": "b"}],
        "value": [],
    }
    selections, rows = supp.unsent_rows(
        groups,
        {"2026-11-15:daily:0620": {"status": "sent", "rows": [old]}},
        betting_day="2026-11-15",
    )
    assert [r["event_id"] for r in selections["top"]] == ["top-2"]
    assert [r["event_id"] for r in selections["aces"]] == ["ace-1", "ace-2"]
    assert [r["market"] for r in rows] == ["match_winner", "aces", "aces"]
    assert all(r["event_id"] != "top-1" for r in rows)
    duplicate = dict(groups)
    duplicate["aces"] = groups["aces"] + [dict(groups["aces"][0])]
    with pytest.raises(RuntimeError, match="Duplicate supplemental"):
        supp.unsent_rows(duplicate, {}, betting_day="2026-11-15")


def test_supplement_reserves_once_after_source_and_site_validation(monkeypatch, tmp_path):
    old = {"channel": "top", "event_id": "top-1",
           "market": "match_winner", "selection_id": "a"}
    state = {
        "schema": 1,
        "attempts": {
            "2026-11-15:daily:0620": {
                "status": "sent", "message_ids": [123], "rows": [old],
            }
        },
    }
    state_path = tmp_path / "telegram-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    offer = {
        "schema": 1,
        "confirmed_only": True,
        "betting_day": "2026-11-15",
        "generated_at": NOW.isoformat(),
        "source_feed_generated_at": NOW.isoformat(),
        "top_daily_picks": [
            {"event_id": "top-1", "market": "match_winner", "selection_id": "a"},
            {"event_id": "top-2", "market": "match_winner", "selection_id": "b"},
        ],
        "value_picks": [],
        "ace_picks": [
            {"event_id": "ace-1", "market": "aces", "selection_id": "a"},
            {"event_id": "ace-2", "market": "aces", "selection_id": "b"},
            {"event_id": "most-aces", "market": "most_aces", "selection_id": "c"},
        ],
    }
    checks = []
    monkeypatch.setattr(supp.tg, "snapshot", lambda _dest: offer)
    monkeypatch.setattr(
        supp.tg, "verify_prepared_site",
        lambda source, url, now: checks.append((source["betting_day"], url)),
    )
    monkeypatch.setattr(supp.tg, "config", lambda _url: {})
    def groups(source, config, _now):
        return {
            "top": list(source["top_daily_picks"]),
            "value": list(source["value_picks"]),
            "aces": [r for r in source["ace_picks"] if r["market"] == "aces"],
        }
    monkeypatch.setattr(supp.tg, "select_groups", groups)
    monkeypatch.setattr(
        supp.tg, "result_reference",
        lambda row, section: {
            "channel": section, "event_id": row["event_id"],
            "market": row["market"], "selection_id": row["selection_id"],
        },
    )
    def formatted(source, config, _now):
        assert config["free_top_pick"] is False
        assert "most-aces" not in [r["event_id"] for r in source["ace_picks"]]
        return [{"audience": "premium", "text": "One TOP and two player O/U picks"}]
    monkeypatch.setattr(supp.tg, "messages", formatted)
    kwargs = {
        "state_path": state_path,
        "output": tmp_path / "out",
        "config_url": "https://example.org/api/v1/ui-config",
        "now": NOW,
    }
    report = supp.prepare(**kwargs)
    assert (report["new_top"], report["new_aces"], report["new_value"]) == (1, 2, 0)
    assert len(checks) == 1
    reserved = json.loads((tmp_path / "out/state.json").read_text())
    ident = "2026-11-15:supplement:top-aces-added-v1"
    assert reserved["attempts"][ident]["status"] == "reserved"
    assert len(reserved["attempts"][ident]["rows"]) == 3
    assert reserved["attempts"]["2026-11-15:daily:0620"] == state["attempts"]["2026-11-15:daily:0620"]
    # Once reserved in the private delivery ledger, another execution must
    # neither download fresh snapshots nor send the same three tips again.
    state_path.write_text(json.dumps(reserved), encoding="utf-8")
    assert supp.prepare(**kwargs) is None
    assert len(checks) == 1


def test_supplement_refuses_wrong_betting_day_or_unconfirmed_original(tmp_path):
    state_path = tmp_path / "telegram-state.json"
    state_path.write_text(json.dumps({"schema": 1, "attempts": {}}))
    with pytest.raises(RuntimeError, match="Original morning"):
        supp.prepare(
            state_path=state_path, output=tmp_path / "out",
            config_url="https://example.org/api/v1/ui-config", now=NOW,
        )
    with pytest.raises(RuntimeError, match="expired"):
        supp.prepare(
            state_path=state_path, output=tmp_path / "out",
            config_url="https://example.org/api/v1/ui-config",
            now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc),
        )
