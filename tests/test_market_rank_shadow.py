"""Prospective market selector shadow: immutable nonpublic comparison contract."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from test_market_selection import row
from tbt.services import market_rank_shadow as shadow

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
HASH = "a" * 64
DAY = "2026-09-07"


def src(event, p=.70, odds=1.6, opponent=2.40, **opts):
    r = row(event, p, odds, opponent, **opts)
    r["id"] = f"canonical-{event}"
    r["model_version"] = "frozen-champion-v1"
    r["match_winner_market"].update({
        "provider_id": 1, "source": "tennisapi_provider_1",
        "source_id_known": True, "source_id": "book-1",
    })
    return r


def capture(rows):
    return shadow.build_market_rank_shadow(
        rows, observed_at=NOW, public_offer_day=DAY,
        champion_sha256=HASH)


def test_same_frozen_slate_has_three_paired_variants_and_no_public_issuance(monkeypatch):
    monkeypatch.setenv("TBT_RANK_SOURCE", "market_anchored")
    monkeypatch.setenv("TBT_TOP_REQUIRE_MARKET_SIDE", "true")
    monkeypatch.setenv("TBT_TOP_EMERGENCY_FILL", "true")
    source = [src("a", .75, 1.61, 2.40),
              src("b", .72, 2.60, 1.52),
              src("c", .68, 1.55, 2.5),
              src("d", .57, 1.70, 2.10)]
    frozen = json.dumps(source, sort_keys=True)
    receipt, counts = capture(source)
    assert receipt and receipt["schema"] == 1
    assert receipt["policy_id"] == shadow.POLICY_ID
    assert set(receipt["variants"]) == set(shadow.VARIANTS)
    assert counts["future_prestart"] == 4
    assert counts["complete_prestart_fair"] == 4
    assert shadow.validate_frozen_capture(receipt) is True
    assert json.dumps(source, sort_keys=True) == frozen
    assert monkeypatch is not None
    assert shadow.os.environ["TBT_RANK_SOURCE"] == "market_anchored"
    assert shadow.os.environ["TBT_TOP_REQUIRE_MARKET_SIDE"] == "true"
    for sections in receipt["variants"].values():
        for selected in sections.values():
            for r in selected:
                assert r["research_only"] is True
                assert r["public_issued"] is False
                assert r["receipt_id"] and r["shadow_issued_at"]
                assert r["match_id"].startswith("canonical-")
                assert r["quote_observed_at"] == NOW.isoformat()


def test_missing_two_way_bookmaker_provenance_falls_back_and_does_not_leak(monkeypatch):
    monkeypatch.setenv("TBT_RANK_SOURCE", "model")
    missing = src("u", .72, 1.6, 2.4)
    missing["match_winner_market"].pop("source_id_known")
    snap, counts = capture([missing])
    assert counts["future_prestart"] == 1
    assert counts["complete_prestart_fair"] == 0
    assert counts["model_fallback"] == 1
    records = [
        row for section in snap["variants"]["market_anchored"].values()
        for row in section]
    assert records
    assert all(r["fair_probability"] is None
               and r["rank_source"] == "model_fallback"
               for r in records)
    assert shadow.os.environ["TBT_RANK_SOURCE"] == "model"


def test_actual_provider_two_sided_quote_validation_and_capture_time():
    original = src("x")
    assert shadow._quote_fair(original, NOW) == pytest.approx(
        original["betting"]["fair_implied_probability"])
    bad_book = deepcopy(original)
    bad_book["match_winner_market"]["source_id_known"] = False
    assert shadow._quote_fair(bad_book, NOW) is None
    bad_sum = deepcopy(original)
    bad_sum["match_winner_market"]["player2_implied_probability"] = .90
    assert shadow._quote_fair(bad_sum, NOW) is None
    bad_quote_clock = deepcopy(original)
    bad_quote_clock["betting"]["captured_at"] = "2026-09-07T10:00:00Z"
    assert shadow._quote_fair(bad_quote_clock, NOW) is None


def test_next_betting_day_candidates_cannot_fill_today_shadow_slots():
    today = src("today")
    tomorrow = src("tomorrow")
    tomorrow["scheduled_at"] = "2026-09-08T12:00:00+00:00"
    receipt, counts = capture([today, tomorrow])
    assert receipt["input_event_ids"] == ["today"]
    assert counts["outside_offer_day"] == 1
    assert counts["future_prestart"] == 1
    for sections in receipt["variants"].values():
        for items in sections.values():
            assert all(row["event_id"] == "today" for row in items)


def test_missing_or_late_fixture_does_not_issue_shadow():
    late = src("a")
    late["scheduled_at"] = "2026-09-07T09:05:00Z"
    missing = src("b")
    missing["id"] = None
    no_snap, counts = capture([late, missing])
    assert no_snap is None
    assert counts["near_start_or_late"] == 1
    assert counts["invalid_identity"] == 1


def test_first_day_capture_immutable_and_digest_corruption_blocks():
    receipt, _ = capture([src("a")])
    hist = {"snapshots": [{"market_rank_shadow": receipt}]}
    assert shadow.first_day_shadow(hist, public_offer_day=DAY) == receipt
    tampered = deepcopy(receipt)
    tampered["variants"]["champion"]["top"].clear()
    with pytest.raises(ValueError, match="digest"):
        shadow.validate_frozen_capture(tampered)
    with pytest.raises(ValueError, match="Multiple"):
        shadow.first_day_shadow({"snapshots": [
            {"market_rank_shadow": receipt}, {"market_rank_shadow": receipt}
        ]}, public_offer_day=DAY)


def test_duplicate_canonical_event_fails_closed():
    with pytest.raises(ValueError, match="Duplicate canonical event"):
        capture([src("same"), src("same")])


def test_shadow_settlement_exact_cdb_match_and_read_only():
    rec, _ = capture([src("a", .75, 1.61, 2.40)])
    hist = {"snapshots": [{"market_rank_shadow": rec}]}
    frozen = json.dumps(hist, sort_keys=True)
    match = SimpleNamespace(
        is_completed=True, match_id="canonical-a",
        player1_id="p1", player2_id="p2",
        scheduled_at=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
        winner_id="p1",
    )
    now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    result = shadow.settled_comparison(hist, [match], asof=now)
    assert result["frozen_days"] == 1
    assert result["variants"]["champion"]["top"]["settled"] == 1
    assert result["variants"]["champion"]["top"]["correct"] == 1
    assert json.dumps(hist, sort_keys=True) == frozen
    mismatch = SimpleNamespace(**{**vars(match), "player1_id": "different"})
    bad = shadow.settled_comparison(hist, [mismatch], asof=now)
    assert bad["variants"]["champion"]["top"]["settled"] == 0
    with pytest.raises(ValueError, match="Duplicate completed"):
        shadow.settled_comparison(hist, [match, match], asof=now)


def test_rank_shadow_workflow_uses_existing_authorized_refresh_only():
    workflow = Path(".github/workflows/data.yml").read_text("utf-8")
    rows = [line for line in workflow.splitlines()
            if line.strip().startswith("TBT_MARKET_RANK_SHADOW_ENABLED:")]
    assert len(rows) == 1
    assert "vars.TBT_MARKET_RANK_SHADOW_DISABLED != 'true'" in rows[0]
    assert "inputs.mode == 'refresh'" in rows[0]
    assert "inputs.mode == 'current-refresh'" in rows[0]
    assert "|| 'false'" in rows[0]
    # Public ranking and TOP product changes retain *separate* owner approval.
    assert "vars.TBT_MARKET_ANCHORED_OWNER_APPROVED == 'true'" in workflow
    assert "vars.TBT_TOP_REQUIRE_MARKET_SIDE_OWNER_APPROVED == 'true'" in workflow
    assert "vars.TBT_TOP_EMERGENCY_FILL_OWNER_APPROVED == 'true'" in workflow


def test_no_new_writer_or_provider_client_in_shadow_module():
    import inspect
    source = inspect.getsource(shadow)
    assert "RapidTennisClient(" not in source
    assert "ReleaseStore(" not in source
    assert "upload_bundle(" not in source
    assert "save_model(" not in source
    assert "write_json(" not in source
