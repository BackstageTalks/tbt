"""Backfill-free cross-channel integrity tests for frozen historical wagers."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_telegram_web_parity import reconcile_day, audit
from tbt.services.telegram_site_parity import site_day_projection
from tbt.services.result_exclusions import result_bet_id

DAY = "2026-11-05"
SCHEDULED = "2026-11-05T12:00:00+00:00"
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def sent(*, channel="aces", event="e1", odds=1.69):
    return {
        "event_id": event, "section": "ace" if channel == "aces" else "top_daily",
        "channel": channel, "market": "aces" if channel == "aces" else "match_winner",
        "selection_id": "p1", "publication_key": "local-aces-ou-v1:e1:p1:over:4.5"
            if channel == "aces" else "",
        "market_line": 4.5 if channel == "aces" else None,
        "projection_direction": "over" if channel == "aces" else "",
        "scheduled_at": SCHEDULED, "odds": odds,
        "price_basis": "local_aces_statistical_v1" if channel == "aces" else None,
    }


def settled(ref, *, status=True, actual=7, odds=None):
    return {**{k: ref[k] for k in (
        "event_id", "section", "market", "selection_id", "publication_key",
        "market_line", "projection_direction", "scheduled_at")},
        "odds": ref["odds"] if odds is None else odds,
        "price_status": "priced_projection",
        "result": {"correct": status, "void": False,
                   "actual_count": actual,
                   "runtime_source": "match_status_snapshot"}}


def site(items):
    return {
        "schema": 1, "betting_day": DAY,
        "source": "website_results_pre_entitlement_v1",
        "member_render_verified": False, "rows": items,
        "published_sections": {"ace": len(items)}, "excluded_sections": {},
    }


def test_same_original_sent_ace_contract_and_free_mirror_match_both_channels():
    ace = sent()
    top = sent(channel="top", event="e2", odds=1.60)
    free = {**top, "channel": "free"}
    ar = [settled(ace), settled(top, status=False, actual=None)]
    result = reconcile_day(
        DAY, [ace, top, free], ar, site(ar),
        {"status": "sent", "counts": {"won": 1, "lost": 1, "void": 0, "pending": 0}},
        now=NOW,
    )
    assert result["parity"] == "verified_same_contract"
    assert result["premium_references"] == 2
    assert result["free_mirror_references"] == 1
    assert result["archive"]["won"] == 1
    assert result["archive"]["lost"] == 2  # FREE mirrors TOP in verification
    assert result["member_account_render_verified"] is False


def test_previous_sent_telegram_report_no_longer_matches_persisted_archive():
    ace = sent()
    report = reconcile_day(
        DAY, [ace], [], site([]),
        {"status": "sent", "counts": {"won": 1, "lost": 0, "void": 0, "pending": 0}},
        now=NOW,
    )
    assert report["parity"] == "mismatch"
    assert report["mismatch_reasons"]["overdue_exact_archive_missing"] == 1
    assert report["mismatch_reasons"]["delivered_summary_vs_verified_archive_mismatch"] == 1


def test_website_missing_or_changed_outcome_is_detected_not_graded_by_event():
    ace = sent()
    exact = settled(ace)
    wrong_line = {**exact, "market_line": 3.5,
                  "publication_key": "local-aces-ou-v1:e1:p1:over:3.5"}
    missing = reconcile_day(DAY, [ace], [exact], site([wrong_line]), None, now=NOW)
    assert missing["mismatch_reasons"] == {"site_missing_exact_archive_result": 1}
    disagree = reconcile_day(
        DAY, [ace], [exact], site([settled(ace, status=False)]), None, now=NOW,
    )
    assert disagree["mismatch_reasons"]["site_terminal_outcome_conflict"] == 1


def test_website_quote_and_actual_player_statistic_conflicts_are_not_silent():
    ace = sent()
    exact = settled(ace)
    altered = settled(ace, actual=8, odds=1.70)
    report = reconcile_day(DAY, [ace], [exact], site([altered]), None, now=NOW)
    assert report["mismatch_reasons"]["website_price_changed"] == 1
    assert report["mismatch_reasons"]["site_player_statistic_conflict"] == 1


def test_site_projection_is_bounded_to_betting_day_and_preserves_original_ou():
    ref = sent()
    record = {
        "event_id": "e1", "scheduled_at": SCHEDULED,
        "player1": {"id": "p1", "name": "A"}, "player2": {"id": "p2", "name": "B"},
        "market_publications": [{
            "section": "ace", "market": "aces", "selection_id": "p1",
            "publication_key": ref["publication_key"],
            "market_line": 4.5, "ou_side": "over", "odds": 1.69,
            "price_contract": "player_total_ou",
            "price_status": "priced_projection",
            "issued_at": "2026-11-05T07:00:00+00:00",
            "result": {"correct": True, "void": False, "actual_count": 7,
                       "runtime_source": "match_status_snapshot"},
        }],
    }
    before = deepcopy(record)
    page = site_day_projection({"results": [record]}, DAY)
    assert record == before
    assert page["rows"][0]["publication_key"] == ref["publication_key"]
    assert page["rows"][0]["result"]["actual_count"] == 7
    assert page["member_render_verified"] is False
    assert page["provider_requests"] == 0
    assert site_day_projection({"results": [record]}, "2026-11-04")["rows"] == []
    omitted = site_day_projection(
        {"results": [record]}, DAY,
        {result_bet_id(record, record["market_publications"][0])},
    )
    assert omitted["rows"] == []
    assert omitted["excluded_sections"] == {"ace": 1}


def test_audit_does_not_silently_claim_member_render_or_resolve_other_market():
    first = sent()
    row = settled(first)
    state = {"attempts": {"2026-11-05:daily:0620": {
        "status": "sent", "rows": [first], "message_ids": [11],
        "sent_at": "2026-11-05T07:30:00+00:00",
    }}}
    def read_archive(url, day):
        assert day == DAY
        return [row]
    def read_site(url, day):
        assert day == DAY
        return site([row])
    doc = audit(state, "https://example.com", [DAY], now=NOW,
                site_reader=read_site, archive_reader=read_archive)
    assert doc["status"] == "pass"
    assert doc["complete_member_render_verification"] is False
    assert doc["paid_provider_requests"] == 0
    assert doc["archive_writes"] == 0


def test_site_gap_breakdown_distinguishes_contract_from_source_without_ids():
    ace = sent()
    exact = settled(ace)
    missing = reconcile_day(DAY, [ace], [exact], site([]), None, now=NOW)
    assert missing["site_gap_breakdown"] == {"aces:no_exact_contract": 1}
    legacy = deepcopy(exact)
    legacy["result"].pop("runtime_source")
    present_but_unverified = reconcile_day(DAY, [ace], [exact], site([legacy]), None, now=NOW)
    assert present_but_unverified["site_gap_breakdown"] == {"aces:no_verified_final": 1}
    assert not any("e1" in item for item in present_but_unverified["site_gap_breakdown"])


def test_site_absence_diagnostics_do_not_expose_issued_bet_identity():
    ace=sent()
    exact=settled(ace)
    absent=reconcile_day(DAY,[ace],[exact],site([]),None,now=NOW)
    assert absent["site_absence_breakdown"]=={"aces:event_absent":1}
    other_contract={**exact,"publication_key":"ace:wrong","market_line":3.5}
    another=reconcile_day(DAY,[ace],[exact],site([other_contract]),None,now=NOW)
    assert another["site_absence_breakdown"]=={"aces:selection_present_other_contract":1}
    other_selection={**exact,"selection_id":"other"}
    different=reconcile_day(DAY,[ace],[exact],site([other_selection]),None,now=NOW)
    assert different["site_absence_breakdown"]=={"aces:event_present_other_selection":1}
    assert all("e1" not in category and "p1" not in category for category in (
        *absent["site_absence_breakdown"],
        *another["site_absence_breakdown"],
        *different["site_absence_breakdown"],
    ))


def test_archive_merge_diagnostics_are_aggregate_only():
    reference = sent(channel="top", event="missing")
    page = site([])
    page["archive_merge_diagnostics"] = {
        "archive_contract_not_merged": 1,
        "archive_contract_shifted_betting_day": 2,
        "shifted_winner_multiple_publications": 1,
        "shifted_other_market": 4,
        "shifted_winner_schedule_disagrees": "bad-secret",
        "raw_identity": "never-log-event-or-player",
        "unknown_failure": -1,
    }
    report = reconcile_day(DAY, [reference], [settled(reference)], page, None, now=NOW)
    assert report["archive_merge_diagnostics"] == {
        "archive_contract_not_merged": 1,
        "archive_contract_shifted_betting_day": 2,
        "shifted_winner_multiple_publications": 1,
        "shifted_other_market": 4,
    }
    assert "never-log-event-or-player" not in str(report)
    assert "bad-secret" not in str(report)
