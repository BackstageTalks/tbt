"""Pinned 4 Nov Telegram Aces replay never infers from model probability."""
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))
from telegram_20261104_verified_replay import (
    DAY, WITNESS, verified_witness, frozen_candidate, prepare,
)


@pytest.mark.parametrize("event,selection,line,price,projection,expected_win", [
    ("17483450", "315575", 5.5, 1.67, 7.21, True),
    ("17428228", "136042", 8.5, 1.73, 10.31, True),
    ("17428207", "90798", 11.5, 1.60, 12.95, True),
    ("17455490", "229218", 7.5, 1.78, 8.61, True),
    ("17488695", "273778", 6.5, 1.61, 7.71, False),
    ("17486949", "373228", 3.5, 1.75, 4.88, False),
])
def test_source_native_4nov_stakes_only_at_original_frozen_over_line(
    event, selection, line, price, projection, expected_win
):
    status = json.loads(WITNESS.read_text())["statuses"][event]
    ref = {
        "event_id": event, "selection_id": selection, "market": "aces",
        "section": "ace", "channel": "aces",
        "price_basis": "local_aces_statistical_v1",
        "projection": projection,
        "market_line": line, "odds": price,
        "projection_direction": "over",
        "publication_key": f"local-aces-ou-v1:{event}:{selection}:over:{line:.1f}",
        "scheduled_at": "2026-11-04T20:00:00+00:00" if event == "17488695" else (
            "2026-11-04T17:00:00+00:00" if event == "17486949" else
            "2026-11-04T13:50:00+00:00" if event == "17428228" else
            "2026-11-04T10:00:00+00:00"
        ),
        "name": "Original frozen selection",
    }
    output = frozen_candidate(ref, status, "2026-11-04T05:38:38.877232+00:00")
    assert output["result"]["correct"] is expected_win
    assert output["result"]["runtime_source"] == "match_status_snapshot"
    assert output["publication_key"] == ref["publication_key"]


def test_refuse_changed_market_line_and_missing_original_six_event_manifest():
    x = json.loads(WITNESS.read_text())
    assert len(x["statuses"]) == 6
    with pytest.raises(RuntimeError, match="incomplete exact source-native"):
        verified_witness([], x)
    status = x["statuses"]["17488695"]
    altered = {
        "event_id": "17488695", "selection_id": "273778", "section": "ace",
        "market": "aces", "channel": "aces",
        "market_line": 9.5, "odds": 1.61, "projection": 7.71,
        "projection_direction": "over", "price_basis": "local_aces_statistical_v1",
        "publication_key": "local-aces-ou-v1:17488695:273778:over:6.5",
        "scheduled_at": "2026-11-04T20:00:00+00:00",
    }
    with pytest.raises(RuntimeError, match="immutable Telegram Aces"):
        frozen_candidate(altered, status, "2026-11-04T05:38:38.877232+00:00")


def test_never_reserve_second_results_delivery_for_same_day(tmp_path):
    state = {"schema": 1, "attempts": {"results:2026-11-04": {"status": "reserved"}}}
    assert prepare(state, [], {}, {}, tmp_path)["status"] == "skipped"
    assert not (tmp_path / "ready").exists()
