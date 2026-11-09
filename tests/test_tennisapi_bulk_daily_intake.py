"""Offline full-batch TennisApi processing; no provider calls or CDB I/O."""
import json

import pytest

from tbt.errors import ProviderError
from tbt.providers.tennisapi_bulk import normalize_daily_bulk_odds
from probe_tennisapi_extended_contract import summarize


def pair(home="3/2", away="2/3", **meta):
    return {
        **meta,
        "choices": [
            {"name": "1", "fractionalValue": home},
            {"name": "2", "fractionalValue": away},
        ],
    }


def test_994_events_from_one_response_all_decoded_without_any_new_calls_or_writes():
    payload = {"odds": {str(100000 + i): pair() for i in range(994)}}
    before = json.dumps(payload, sort_keys=True)
    result = normalize_daily_bulk_odds(payload)
    summary = result["summary"]
    counts = summary["counts"]
    assert counts["raw_event_entries"] == 994
    assert counts["native_event_key_entries"] == 994
    assert counts["native_events_with_parseable_pair"] == 994
    assert counts["parseable_two_sided_pairs"] == 994
    assert counts["pairs_without_source_provider_id"] == 994
    assert len(result["candidates"]) == 994
    assert len({row["source_event_id"] for row in result["candidates"]}) == 994
    assert result["candidates"][0]["selections"]["home"]["latest_decimal"] == 2.5
    assert result["candidates"][-1]["selections"]["away"]["latest_decimal"] == pytest.approx(5/3)
    assert summary["raw_events_accounted_for"] is True
    assert summary["all_candidate_records_ineligible_for_cdb"] is True
    assert summary["canonical_new_values"] == summary["cdb_writes"] == summary["provider_requests"] == 0
    assert all(row["eligible_for_cdb_import"] is False
               and row["eligible_to_replace_individual_market_fetch"] is False
               and row["pre_match_asof_verified"] is False
               and row["event_identity_verified_against_cdb"] is False
               for row in result["candidates"])
    # Read-only: original paid source response retains its original bytes.
    assert json.dumps(payload, sort_keys=True) == before
    # Per-event prices/IDs must never leak into the published aggregate report.
    report = summarize("daily_match_winner_odds", payload, event_id=100000)
    intake = report["daily_odds_value_profile"]["bulk_pair_intake"]
    assert intake["counts"]["native_events_with_parseable_pair"] == 994
    encoded = json.dumps(report, sort_keys=True)
    assert '"source_event_id"' not in encoded
    assert '"latest_decimal"' not in encoded
    assert "3/2" not in encoded
    assert "2/3" not in encoded
    assert '"100000"' not in encoded
    assert '"100993"' not in encoded
    assert '"selections"' not in encoded


def test_hundred_bad_entries_isolate_to_review_without_losing_good_pairs():
    items = {str(100000 + i): pair() for i in range(900)}
    items.update({str(200000 + i): {"choices": [{"name": "1", "fractionalValue": "3/2"}]}
                  for i in range(100)})
    items["invalid"] = pair()
    items["201001"] = {**pair(), "eventId": 200000}
    out = normalize_daily_bulk_odds({"odds": items})
    c = out["summary"]["counts"]
    assert c["raw_event_entries"] == 1002
    assert c["native_events_with_parseable_pair"] == 900
    assert c["native_events_without_parseable_pair"] == 100
    assert c["invalid_event_key"] == 1
    assert c["event_id_mismatch"] == 1
    assert c["rejected_missing_or_invalid_choices"] == 100
    assert out["summary"]["raw_events_accounted_for"] is True
    assert len(out["candidates"]) == 900


@pytest.mark.parametrize("node,reason", [
    ({"choices": "bad"}, "missing_or_invalid_choices"),
    ({"choices": [{"name": "1", "fractionalValue": "3/2"}]},
     "missing_or_invalid_choices"),
    ({"choices": [{"name": "1", "fractionalValue": "3/2"},
                  {"name": "1", "fractionalValue": "4/2"},
                  {"name": "2", "fractionalValue": "2/3"}]},
     "conflicting_duplicate_selection"),
    ({"choices": [{"name": "1", "fractionalValue": "3/2"},
                  {"name": "X", "fractionalValue": "2/3"},
                  {"name": "2", "fractionalValue": "2/3"}]},
     "unknown_selection"),
    (pair(isLive=True), "live_or_suspended"),
    (pair(suspended=True), "live_or_suspended"),
    (pair(home="0"), "unparseable_or_ambiguous_price"),
    ({"choices": [{"name": "1", "fractionalValue": "3/2", "decimalValue": 9.99},
                  {"name": "2", "fractionalValue": "2/3"}]},
     "unparseable_or_ambiguous_price"),
])
def test_bad_price_or_market_is_quarantined_not_guessed(node, reason):
    out = normalize_daily_bulk_odds({"odds": {"101": node}})
    assert out["candidates"] == []
    assert out["summary"]["counts"]["rejected_" + reason] == 1
    assert out["summary"]["raw_events_accounted_for"] is True


def test_multiple_native_provider_shapes_remain_separate_and_clock_not_verified():
    payload = {"odds": {
        "101": {"1": pair(quotedAt="2026-11-09T08:00:00Z"),
                "5": pair("4/2", "2/2")},
        "102": pair(providerId=5, timestamp=1794200000),
    }}
    out = normalize_daily_bulk_odds(payload)
    rows = out["candidates"]
    assert len(rows) == 3
    assert {(x["source_event_id"], x["source_provider_id"])
            for x in rows} == {("101", "1"), ("101", "5"), ("102", "5")}
    assert all(x["pre_match_asof_verified"] is False for x in rows)
    assert out["summary"]["counts"]["native_events_with_parseable_pair"] == 2
    assert out["summary"]["counts"]["pair_with_clock_field_only"] == 2
    assert out["summary"]["raw_events_accounted_for"] is True


def test_no_unsafe_bulk_overrides_from_unsupported_or_cross_event_envelopes():
    with pytest.raises(ProviderError):
        normalize_daily_bulk_odds({"odds": []})
    with pytest.raises(ProviderError):
        normalize_daily_bulk_odds({"odds": {"1": pair(), "2": pair()}}, max_events=1)
    with pytest.raises(ProviderError):
        normalize_daily_bulk_odds({"error": "provider expired", "odds": {"1": pair()}})
    wrong_nested = normalize_daily_bulk_odds(
        {"odds": {"101": {"1": {**pair(), "eventId": 999}}}})
    assert not wrong_nested["candidates"]
    assert wrong_nested["summary"]["counts"]["rejected_nested_event_id_mismatch"] == 1
    assert wrong_nested["summary"]["raw_events_accounted_for"] is True
