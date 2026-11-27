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
    monkeypatch.setattr(pipeline, "parse_statistics", lambda payload, home_is_player1, **kw: {"p1_aces": 5, "p2_aces": 3})
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


def test_conflict_outside_aces_does_not_block_settlement():
    from tbt.providers.statistics import parse_statistics, ConflictingStatisticsError
    item = lambda key, h, a: {"key": key, "homeValue": h, "awayValue": a, "home": str(h), "away": str(a)}
    payload = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        item("aces", 7, 3), item("doubleFaults", 2, 4),
        item("aces", 7, 3)]}]}]}
    out = parse_statistics(payload, home_is_player1=True, only_fields={"p1_aces", "p2_aces"})
    assert out.get("p1_aces") == 7 and out.get("p2_aces") == 3
    bad = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        item("aces", 7, 3), item("aces", 8, 3)]}]}]}
    import pytest
    with pytest.raises(ConflictingStatisticsError):
        parse_statistics(bad, home_is_player1=True, only_fields={"p1_aces", "p2_aces"})
    bad_df = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        item("aces", 7, 3), item("doubleFaults", 2, 4), item("doubleFaults", 5, 4)]}]}]}
    assert parse_statistics(bad_df, home_is_player1=True, only_fields={"p1_aces", "p2_aces"})["p1_aces"] == 7


def test_missing_match_voided_after_seven_days(monkeypatch):
    from datetime import timedelta
    ledger = _ledger("15000009")
    ledger[0]["scheduled_at"] = "2026-11-10T12:00:00+00:00"
    now = datetime(2026, 11, 27, 5, tzinfo=timezone.utc)
    report, prov = _run_now(ledger, [], monkeypatch, now)
    pub = ledger[0]["market_publications"][0]
    assert pub["result"]["status"] == "void" and pub["result"]["reason"] == "match_not_found_7d"
    assert report.get("voided_not_found") == 1 and report["missing_match"] == 0 and prov.calls == []


def test_recent_missing_match_stays_pending(monkeypatch):
    ledger = _ledger("15000010")
    ledger[0]["scheduled_at"] = "2026-11-25T12:00:00+00:00"
    now = datetime(2026, 11, 27, 5, tzinfo=timezone.utc)
    report, _ = _run_now(ledger, [], monkeypatch, now)
    assert "result" not in ledger[0]["market_publications"][0] and report["missing_match"] == 1


def test_backfill_reads_only_missing_days(monkeypatch):
    ledger = _ledger("15000011")
    ledger[0]["scheduled_at"] = "2026-11-20T12:00:00+00:00"
    seen = []

    class P:
        def matches_for_day(self, tour, day, historical=True):
            seen.append((tour, day.isoformat()))
            return [_match("canon-9", "15000011")]
    monkeypatch.setattr(pipeline, "_merge_refresh_batch_safely",
                        lambda matches, incoming, day, tour: (matches + incoming, incoming))
    now = datetime(2026, 11, 27, 5, tzinfo=timezone.utc)
    matches, report = pipeline._backfill_pending_ace_df_days(P(), ledger, [], now)
    assert seen == [("atp", "2026-11-20"), ("wta", "2026-11-20")] and report["added"] == 2


def _run_now(ledger, matches, monkeypatch, now):
    monkeypatch.setattr(pipeline, "_provider_event_id", lambda m: m.provider_payload["_tbt_provider_event_id"])
    monkeypatch.setattr(pipeline, "parse_statistics", lambda payload, home_is_player1, **kw: {"p1_aces": 5, "p2_aces": 3})
    prov = Provider()
    return pipeline._enrich_pending_ace_df_settlement_stats(prov, ledger, matches, now=now), prov


def test_terminal_exclusions_are_not_pending():
    ledger = _ledger("15000020")
    ledger[0]["market_publications"][0]["excluded_reason"] = "unknown_price_contract"
    assert pipeline._pending_ace_df_settlement_requirements(ledger) == {}
    ledger[0]["market_publications"][0]["excluded_reason"] = "projection_result_unavailable"
    assert pipeline._pending_ace_df_settlement_requirements(ledger) == {"15000020": {"aces"}}
