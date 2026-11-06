"""Exact 5 Nov Telegram Results replay: identity, source evidence and idempotency."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from telegram_20261105_verified_replay import (
    DAY, SOURCE_JOB, SOURCE_RUN, SOURCE_UPDATED, WITNESS,
    verified_witness, prepare,
)
from telegram_20261104_verified_replay import frozen_candidate

CASES = [
    ("17427366", "289146", "2026-11-05T16:00:00+00:00", 11.5, 1.73, 13.46, True),
    ("17427631", "107357", "2026-11-05T10:40:00+00:00", 4.5, 1.65, 5.58, False),
    ("17428222", "90798", "2026-11-05T10:00:00+00:00", 9.5, 1.62, 11.32, True),
    ("17427362", "229218", "2026-11-05T12:10:00+00:00", 6.5, 1.61, 8.26, True),
    ("17427548", "161262", "2026-11-05T22:00:00+00:00", 3.5, 1.77, 4.9, False),
    ("17427589", "289106", "2026-11-05T10:30:00+00:00", 6.5, 1.78, 8.47, True),
    ("17428229", "136042", "2026-11-05T19:30:00+00:00", 8.5, 1.75, 10.29, True),
]


def ace_row(case):
    event, player, at, line, price, projection, _ = case
    return {
        "event_id": event, "selection_id": player, "market": "aces",
        "section": "ace", "channel": "aces", "name": "Frozen original player",
        "scheduled_at": at, "projection": projection,
        "price_basis": "local_aces_statistical_v1",
        "market_line": line, "odds": price, "projection_direction": "over",
        "publication_key": f"local-aces-ou-v1:{event}:{player}:over:{line:.1f}",
    }


def issued_rows():
    rows = [ace_row(c) for c in CASES]
    # Existing telegram report requires the original 3 TOP + 2 VALUE + FREE
    # references too. Use distinct same-day identities for a hermetic test.
    for i, channel in enumerate(("top", "top", "top", "value", "value", "free")):
        rows.append({
            "event_id": f"test-{i}", "selection_id": f"player-{i}",
            "market": "match_winner",
            "section": "value" if channel == "value" else "top_daily",
            "channel": channel, "name": "Frozen Match Winner",
            "scheduled_at": "2026-11-05T20:00:00+00:00",
            "odds": 1.65, "publication_key": "",
        })
    return rows


@pytest.mark.parametrize("case", CASES)
def test_exact_frozen_5nov_player_aces_use_actual_count_not_match_winner(case):
    witness = json.loads(WITNESS.read_text(encoding="utf-8"))
    ref = ace_row(case)
    statuses = verified_witness(issued_rows(), witness)
    result = frozen_candidate(
        ref, statuses[case[0]], "2026-11-05T09:11:27.931790+00:00",
        betting_day=DAY,
    )
    assert result["result"]["correct"] is case[-1]
    assert result["result"]["runtime_source"] == "match_status_snapshot"
    assert result["publication_key"] == ref["publication_key"]
    assert result["market_line"] == ref["market_line"]
    assert result["odds"] == ref["odds"]
    assert result["price_status"] == "priced_projection"


def test_source_native_witness_requires_all_seven_unchanged_player_counts():
    witness = json.loads(WITNESS.read_text(encoding="utf-8"))
    assert witness["source_run_id"] == SOURCE_RUN
    assert witness["source_job_id"] == SOURCE_JOB
    assert witness["source_updated_at"] == SOURCE_UPDATED
    assert len(verified_witness(issued_rows(), witness)) == 7
    corrupted = deepcopy(witness)
    corrupted["statuses"]["17427548"]["projection_stats"]["p1_aces"] = None
    with pytest.raises(RuntimeError, match="Ace count"):
        verified_witness(issued_rows(), corrupted)
    wrong = deepcopy(witness)
    wrong["statuses"]["17427631"]["projection_stats_p2_id"] = "another-player"
    with pytest.raises(RuntimeError, match="identity"):
        verified_witness(issued_rows(), wrong)
    stale = deepcopy(witness)
    stale["source_job_id"] = -1
    with pytest.raises(RuntimeError, match="witness"):
        verified_witness(issued_rows(), stale)


def test_prepares_all_verified_results_once_without_mutating_receipts(tmp_path):
    sent = issued_rows()
    state = {"schema": 1, "attempts": {
        DAY + ":daily:0620": {
            "status": "sent", "message_ids": [734, 735],
            "sent_at": "2026-11-05T09:11:27.931790+00:00", "rows": sent,
        }
    }}
    original = deepcopy(state)
    archived = [{
        "event_id": ref["event_id"], "selection_id": ref["selection_id"],
        "section": ref["section"], "market": ref["market"],
        "publication_key": ref["publication_key"], "odds": ref["odds"],
        "result": {"runtime_source": "match_status_snapshot", "correct": True},
    } for ref in sent if ref["channel"] != "aces"]
    info = prepare(state, archived, json.loads(WITNESS.read_text()), {}, tmp_path)
    assert info["status"] == "reserved"
    assert info["verified_issued"] == 13
    assert len(info["replayed_exact_aces"]) == 7
    # FREE duplicates a published TOP tip; it is excluded from premium ROI.
    assert info["counts"] == {"won": 10, "lost": 2, "void": 0, "pending": 0}
    assert info["paid_provider_requests"] == 0
    assert state == original
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["attempts"]["results:" + DAY]["status"] == "reserved"
    assert saved["attempts"][DAY + ":daily:0620"] == original["attempts"][DAY + ":daily:0620"]
    assert (tmp_path / "messages.json").exists()
    assert (tmp_path / "ready").read_text() == "results:" + DAY
    assert prepare(saved, archived, json.loads(WITNESS.read_text()), {}, tmp_path) == {
        "status": "skipped", "reason": "results_already_reserved_or_sent", "day": DAY
    }


def test_never_relabel_wrong_day_or_tampered_market_contract():
    data = json.loads(WITNESS.read_text())
    ref = ace_row(CASES[0])
    forged = dict(ref, market_line=3.5)
    with pytest.raises(RuntimeError, match="Immutable Telegram Aces"):
        frozen_candidate(forged, data["statuses"][CASES[0][0]],
                         "2026-11-05T09:11:27.931790+00:00", betting_day=DAY)
    with pytest.raises(RuntimeError, match="Immutable Telegram Aces"):
        frozen_candidate(ref, data["statuses"][CASES[0][0]],
                         "2026-11-05T09:11:27.931790+00:00",
                         betting_day="2026-11-04")
