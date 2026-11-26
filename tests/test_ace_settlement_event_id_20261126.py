"""Pending ACES/DF settlement must find matches by provider event id (ledger key)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pipeline


class Provider:
    request_count = 0

    def __init__(self):
        self.calls = []

    def event_statistics(self, eid):
        self.calls.append(eid)
        self.request_count += 1
        return {"statistics": []}

    def _get(self, path, enrichment=True):
        raise AssertionError("identity already verified")


def _match(match_id, eid, p1="a", p2="b"):
    return SimpleNamespace(
        match_id=match_id, player1_id=p1, player2_id=p2, is_completed=True, stats={},
        scheduled_at=datetime(2026, 11, 24, tzinfo=timezone.utc),
        provider_payload={"_tbt_provider_event_id": eid,
                          "_tbt_event_identity": {"event_id": eid, "status": "finished", "home": p1, "away": p2}})


def _ledger(eid, p1="a", p2="b"):
    return [{"event_id": eid, "player1": {"id": p1}, "player2": {"id": p2},
             "market_publications": [{"market": "aces", "issued_at": "2026-11-24T08:00:00Z"}]}]


def _run(ledger, matches, monkeypatch):
    monkeypatch.setattr(pipeline, "_provider_event_id", lambda m: m.provider_payload["_tbt_provider_event_id"])
    monkeypatch.setattr(pipeline, "parse_statistics", lambda payload, home_is_player1: {"p1_aces": 5, "p2_aces": 3})
    prov = Provider()
    return pipeline._enrich_pending_ace_df_settlement_stats(prov, ledger, matches), prov


def test_ledger_provider_id_matches_internal_match(monkeypatch):
    report, prov = _run(_ledger("15000001"), [_match("canon-123", "15000001")], monkeypatch)
    assert report["missing_match"] == 0 and report["enriched"] == 1 and prov.calls == ["15000001"]


def test_wrong_players_never_settle(monkeypatch):
    report, prov = _run(_ledger("15000001", "x", "y"), [_match("canon-123", "15000001")], monkeypatch)
    assert report["missing_match"] == 1 and prov.calls == []


def test_duplicate_candidates_are_ambiguous(monkeypatch):
    report, prov = _run(_ledger("15000001"), [_match("c1", "15000001"), _match("c2", "15000001")], monkeypatch)
    assert report["ambiguous_match"] == 1 and prov.calls == []
