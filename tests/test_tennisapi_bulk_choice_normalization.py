"""Offline regression contract for parsing every entry of a paid bulk odds map."""
from datetime import datetime, timezone
import json

import pytest

from tbt.errors import ProviderError
from tbt.providers.tennisapi_bulk_choices import extract_bulk_match_winner_choices
from scripts.probe_tennisapi_extended_contract import summarize


STAMP = datetime(2026, 11, 9, 6, 35, tzinfo=timezone.utc)


def _pair(*, home="3/2", away="2/3", source=None):
    choices = [
        {"name": "1", "fractionalValue": home},
        {"name": "2", "fractionalValue": away},
    ]
    if source is not None:
        for row in choices:
            row["sourceId"] = source
    return {"choices": choices}


@pytest.mark.parametrize("count", [700, 900, 1100])
def test_processes_every_event_in_one_response_without_artificial_match_limit(count):
    payload = {"odds": {str(i): _pair(source=1) for i in range(1, count + 1)}}
    result = extract_bulk_match_winner_choices(payload, processed_at=STAMP)
    assert result["raw_entry_count"] == count
    assert result["valid_native_event_key_count"] == count
    assert result["decoded_research_pair_count"] == count
    assert result["rejected_by_reason"] == {}
    assert len(result["pairs"]) == count
    assert result["pairs"][0]["home_decimal_odds"] == 2.5
    assert result["pairs"][-1]["away_decimal_odds"] == pytest.approx(1 + 2 / 3)
    assert all(not row["cdb_import_authorized"] for row in result["pairs"])
    assert all(not row["pre_match_asof_verified"] for row in result["pairs"])
    assert all(not row["canonical_identity_verified"] for row in result["pairs"])


def test_rejects_ambiguous_or_unavailable_individual_events_without_losing_peers():
    broken = {
        "01": _pair(),                              # alternate ID representation
        "2": {"choices": [_pair()["choices"][0]]},   # incomplete
        "3": {"choices": [{"name": "1", "fractionalValue": "3/2"},
                          {"name": "1", "fractionalValue": "2/3"}]},
        "4": {"choices": [{"name": "1", "fractionalValue": "3/2"},
                          {"name": "2", "fractionalValue": "0/1"}]},
        "5": {"choices": [{"name": "1", "fractionalValue": "3/2",
                          "sourceId": 1},
                          {"name": "2", "fractionalValue": "2/3",
                           "sourceId": 2}]},
        "6": {"suspended": True, **_pair()},
        "7": _pair(source=1),
        "8": {"choices": [{"name": "Home", "decimalValue": 2.0},
                          {"name": "Away", "decimalValue": 1.8}]},
        "9": {"choices": [{"name": "1", "fractionalValue": "3/2",
                          "decimalValue": 3.5},
                          {"name": "2", "fractionalValue": "2/3"}]},
    }
    parsed = extract_bulk_match_winner_choices({"odds": broken}, processed_at=STAMP)
    assert parsed["raw_entry_count"] == 9
    assert [row["native_event_id"] for row in parsed["pairs"]] == ["7", "8"]
    assert parsed["rejected_by_reason"] == {
        "ambiguous_choice_side": 1,
        "contradictory_price_fields": 1,
        "invalid_latest_price": 1,
        "invalid_native_event_key": 1,
        "missing_or_nonbinary_choices": 1,
        "unavailable_event": 1,
        "unmatched_quote_source": 1,
    }


def test_no_historical_quote_or_source_provenance_is_inferred():
    p = extract_bulk_match_winner_choices({"odds": {"123": _pair()}}, processed_at=STAMP)
    row = p["pairs"][0]
    assert row["source_id"] is None
    assert row["processed_at_utc"] == "2026-11-09T06:35:00+00:00"
    assert row["provider_quote_timestamp_known"] is False
    assert p["provider_quote_timestamp_verified"] is False
    assert p["cdb_import_authorized"] is False


def test_bulk_probe_emits_only_counters_not_raw_900_event_ids_or_prices():
    # The endpoint is called once upstream. The offline summarizer cannot
    # incur any requests; no per-event price or event ID may leave the report.
    payload = {"odds": {
        str(i): _pair(home="513/7", away="31/13") for i in range(1, 901)
    }}
    report = summarize("daily_match_winner_odds", payload, event_id=1000)
    decoded = report["daily_odds_value_profile"]["full_batch_research_decode"]
    assert decoded["raw_entry_count"] == 900
    assert decoded["valid_native_event_key_count"] == 900
    assert decoded["decoded_research_pair_count"] == 900
    assert decoded["rejected_by_reason"] == {}
    assert not decoded["cdb_import_authorized"]
    published = json.dumps(report, sort_keys=True)
    assert "513/7" not in published
    assert "31/13" not in published
    assert '"native_event_id"' not in published
    assert '"pairs"' not in published


def test_invalid_batch_and_naive_clock_fail_closed():
    with pytest.raises(ProviderError):
        extract_bulk_match_winner_choices({"odds": []}, processed_at=STAMP)
    with pytest.raises(ValueError):
        extract_bulk_match_winner_choices(
            {"odds": {"1": _pair()}}, processed_at=datetime(2026, 11, 9))
