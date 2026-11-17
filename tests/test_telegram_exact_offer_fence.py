"""BlinQ Telegram one-day exact-offer fence: native-writer and serving contract."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_offer_publisher as tg
from test_r55_daily_offer_snapshot import winner_row, publication_for
from tbt.services.publication import build_confirmed_daily_offer_snapshot, build_daily_offer_snapshot

ROOT = Path(__file__).resolve().parents[1]
RESERVED = datetime(2026, 11, 18, 5, 21, tzinfo=timezone.utc)
READBACK = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
DAY = "2026-11-18"
C = {"sections": {"top": True, "value": True, "aces": True},
     "free_top_pick": False, "include_started": False, "max_per_section": 0}


def top(event, at="2026-11-18T14:00:00+00:00", *, odds=1.70):
    row = winner_row(event, at, selection="Alpha", odds=odds, day=DAY)
    row["probability"] = 0.70
    row["blinq_probability"] = 0.70
    return row


def published(rows):
    return [{"event_id": r["event_id"],
             "market_publications": [publication_for(r, "top_daily")]}
            for r in rows]


def state_for(snapshot, *, when=RESERVED, status="sent"):
    expected = tg.select_groups(
        {**snapshot, "generated_at": when.isoformat()}, C, when
    )
    receipts = [tg.result_reference(r, section)
                for section in tg.SECTIONS
                for r in expected.get(section, [])]
    return {"schema": 1, "attempts": {
        f"{DAY}:daily:0620": {
            "status": status,
            "reserved_at": when.isoformat(),
            "sent_at": (when.isoformat() if status == "sent" else None),
            "message_ids": [1] if status == "sent" else [],
            "rows": receipts,
        }
    }}


def case(rows):
    feed = {"generated_at": RESERVED.isoformat(),
            "top_daily_picks": rows,
            "value_picks": [], "ace_picks": [],
            "sg_picks": [], "prime_picks": [], "doubles_picks": [],
            "market_selection": {
                "top_daily_rule": {"policy": "sports_tiered_top5_60_v24"}
            }}
    ledger = published(rows)
    snapshot = build_confirmed_daily_offer_snapshot(feed, ledger, now=RESERVED)
    return feed, ledger, snapshot


def test_same_exact_reservation_and_sent_offer_readback():
    feed, ledger, snapshot = case([top("a"), top("b"), top("c")])
    frozen = state_for(snapshot)
    before = deepcopy((feed, ledger, snapshot, frozen))
    result = tg.verify_frozen_daily_offer(snapshot, frozen, READBACK)
    assert result == {"status": "verified", "betting_day": DAY,
                      "locked": True, "counts": {"top": 3, "value": 0, "aces": 0}}
    assert (feed, ledger, snapshot, frozen) == before


def test_late_two_issued_top_picks_fail_closed_in_native_writer_and_serving():
    first = [top("a"), top("b"), top("c")]
    _, _, morning = case(first)
    frozen = state_for(morning)
    five = first + [top("late-1"), top("late-2")]
    feed, ledger, confirmed = case(five)
    assert len(confirmed["top_daily_picks"]) == 5
    with pytest.raises(RuntimeError, match="top website/confirmed=5 reserved/sent=3"):
        tg.verify_frozen_daily_offer(confirmed, frozen, READBACK)
    # The native prediction release writer must reject even pending extras,
    # instead of assuming that only currently issued ledger entries matter.
    candidate = build_daily_offer_snapshot(feed, now=READBACK)
    with pytest.raises(RuntimeError, match="top website/confirmed=5 reserved/sent=3"):
        tg.verify_frozen_daily_offer(candidate, frozen, READBACK)


def test_same_count_changed_selection_or_price_is_not_equivalent():
    first = [top("a"), top("b"), top("c")]
    _, _, morning = case(first)
    frozen = state_for(morning)
    updated = [top("a"), top("b"), top("c", odds=1.75)]
    _, _, changed = case(updated)
    with pytest.raises(RuntimeError, match="freeze violation"):
        tg.verify_frozen_daily_offer(changed, frozen, READBACK)


def test_started_before_reservation_is_not_a_late_telegram_pick():
    # The website can preserve a legitimately issued early match after start.
    early = top("early", at="2026-11-18T05:00:00+00:00")
    a, b, c = top("a"), top("b"), top("c")
    _, _, snapshot = case([early, a, b, c])
    frozen = state_for(snapshot)
    assert [r["event_id"] for r in frozen["attempts"][f"{DAY}:daily:0620"]["rows"]] == ["a", "b", "c"]
    assert tg.verify_frozen_daily_offer(snapshot, frozen, READBACK)["counts"]["top"] == 3


def test_reserved_state_already_freezes_before_telegram_api_send():
    _, _, snapshot = case([top("a")])
    state = state_for(snapshot, status="reserved")
    assert tg.verify_frozen_daily_offer(snapshot, state, READBACK)["locked"]
    _, _, changed = case([top("a"), top("late")])
    with pytest.raises(RuntimeError, match="freeze violation"):
        tg.verify_frozen_daily_offer(changed, state, READBACK)


def test_lack_of_telegram_ledger_is_never_interpreted_as_no_send():
    _, _, snapshot = case([top("a")])
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        tg.verify_frozen_daily_offer(snapshot, None, READBACK)
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        tg.verify_frozen_daily_offer(snapshot, {"schema": 1}, READBACK)
    empty = {"schema": 1, "attempts": {}}
    assert tg.verify_frozen_daily_offer(snapshot, empty, READBACK)["status"] == "not_reserved"


def test_legacy_offer_is_not_reinterpreted_by_forward_only_change():
    _, _, snapshot = case([top("a")])
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    assert tg.verify_frozen_daily_offer(snapshot, None, now)["status"] == "legacy_day"


def test_duplicate_reservations_refused_without_writing_anything():
    _, _, snapshot = case([top("a")])
    state = state_for(snapshot)
    state["attempts"][f"{DAY}:manual:other"] = deepcopy(
        state["attempts"][f"{DAY}:daily:0620"])
    with pytest.raises(RuntimeError, match="multiple"):
        tg.verify_frozen_daily_offer(snapshot, state, READBACK)


def test_real_publication_paths_apply_fence_before_irreversible_upload():
    pipeline = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    serving = (ROOT / "scripts" / "prepare_feed.py").read_text(encoding="utf-8")
    confirm = (ROOT / "scripts" / "confirm_prediction_publication.py").read_text(encoding="utf-8")
    assert "before_upload=_telegram_offer_before_upload" in pipeline
    assert "verify_frozen_daily_offer(" in pipeline
    assert "verify_frozen_daily_offer(" in serving
    assert "verify_frozen_daily_offer(" in confirm
    assert confirm.index('verify_frozen_daily_offer(') < confirm.index('write_json(directory / "ledger.json", confirmed)')
