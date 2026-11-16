"""Exact, time-aware private market quote pairing: never fuzzy name matching."""
from copy import deepcopy
from hashlib import sha256

from scripts.prepare_paired_top_quotes import strict_first_morning_quotes
from scripts.evaluate_paired_top_selection import evaluate


PIN = "a"*64


def paired():
    return {
        "schema": 1,
        "historical_prices_included": False,
        "evaluation": "previously_inspected_chronological_holdout_not_prospective",
        "holdout_fingerprint": "same-fixture",
        "candidate_version": "v2",
        "champion_version": "v1",
        "rows": [{
            "match_id": "canonical-100",
            "provider_event_id": "provider-100",
            "scheduled_at": "2026-11-10T11:00:00Z",
            "player1_id": "b", "player2_id": "a", "winner_id": "a",
            "target_player1_win": 0,
            "tour": "atp", "competition": "ATP", "surface": "hard",
            "pre_match_feature_evidence": {
                "data_depth": .95, "surface_history_count": 18,
            },
            "production_player1_probability": .30,
            "candidate_player1_probability": .25,
        }],
    }


def selector(*, event="provider-100", one="a", two="b",
             captured="2026-11-10T08:00:00Z", p1=1.55, p2=2.10,
             start="2026-11-10T11:00:00Z"):
    return {
        "event_id": event, "tour": "ATP", "scheduled_at": start,
        "player1": {"id": one}, "player2": {"id": two},
        "two_way_market": {
            "player1_odds": p1, "player2_odds": p2,
            "captured_at": captured, "provider_id": "verified-provider",
        }
    }


def archives(*rows, at="2026-11-10T09:00:00Z"):
    return [{"source_sha256": PIN, "archive": {"schema": 1, "snapshots": [{
        "generated_at": at, "rows": list(rows),
    }]}}]


def test_exact_provider_event_and_swapped_pair_reorders_prices():
    scored = paired()
    quotes, report = strict_first_morning_quotes(scored, archives(selector()))
    assert len(quotes) == 1
    assert report["exact_time_verified_quotes"] == 1
    assert quotes[0]["match_id"] == "canonical-100"
    assert quotes[0]["player1_id"] == "b"
    assert quotes[0]["odds_player1"] == 2.10
    assert quotes[0]["odds_player2"] == 1.55
    result = evaluate(scored, quotes)
    assert result["comparison"]["production"]["qualified"] == 1
    assert result["comparison"]["candidate"]["qualified"] == 1
    assert result["comparison"]["candidate"]["all_qualified"]["wins"] == 1


def test_wrong_event_identity_never_fuzzy_matched():
    quotes, report = strict_first_morning_quotes(paired(), archives(selector(event="different")))
    assert not quotes
    assert report["rejections"]["no_exact_identity"] == 1


def test_too_late_or_future_quote_is_rejected():
    q, report = strict_first_morning_quotes(
        paired(), archives(selector(captured="2026-11-10T10:00:01Z")))
    assert not q
    assert report["rejections"]["unverified_prestart_quote_time"] == 1
    # Snapshot itself cannot occur after this match.
    q, report = strict_first_morning_quotes(
        paired(), archives(selector(), at="2026-11-10T12:00:00Z"))
    assert not q
    assert report["rejections"]["snapshot_after_start"] == 1


def test_fixture_start_drift_and_unpriced_rows_fail_closed():
    q, report = strict_first_morning_quotes(
        paired(), archives(selector(start="2026-11-10T09:00:00Z")))
    assert not q
    assert report["rejections"]["start_drift_over_45m"] == 1
    broken = selector()
    broken.pop("two_way_market")
    q, report = strict_first_morning_quotes(paired(), archives(broken))
    assert not q
    assert report["rejections"]["missing_two_way_market"] == 1


def test_ambiguous_scored_provider_crosswalk_is_quarantined():
    score = paired()
    duplicate = deepcopy(score["rows"][0])
    duplicate["match_id"] = "another-canonical"
    score["rows"].append(duplicate)
    q, report = strict_first_morning_quotes(score, archives(selector()))
    assert not q
    assert report["ambiguous_scored_event_keys"] == 1


def test_first_morning_snapshot_fixed_before_outcomes():
    data = archives(selector(p1=1.55, p2=2.1))
    data[0]["archive"]["snapshots"].append({
        "generated_at": "2026-11-10T10:30:00Z",
        "rows": [selector(p1=2.2, p2=3.1)],
    })
    q, report = strict_first_morning_quotes(paired(), data)
    assert q[0]["odds_player1"] == 2.1
    assert report["days_with_first_morning_snapshot"] == 1


def test_untrusted_archive_pin_is_rejected():
    data = archives(selector())
    data[0]["source_sha256"] = "unknown"
    import pytest
    with pytest.raises(ValueError, match="Unverified"):
        strict_first_morning_quotes(paired(), data)
