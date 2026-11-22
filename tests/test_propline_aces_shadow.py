"""PropLine N+ aces private shadow: real-source invariants, no publication."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tbt.schemas import MatchRecord
from propline_evening_odds import collect
from propline_aces_shadow import (
    ASSET, EXPERIMENT, build_snapshot, capture_in_existing_store, _settle_research,
)

CAPTURE = datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc)
MORNING = datetime(2026, 11, 23, 5, 15, tzinfo=timezone.utc)
START = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
MODEL_SHA = "a" * 64


def source():
    return {"events": [{
        "id": "1234", "home_team": "Alexander Zverev",
        "away_team": "Ben Shelton", "tour": "Challenger",
        "tournament": "ATP Challenger Synthetic",
        "commence_time": START.isoformat(),
        "bookmakers": [{
            "key": "napoleon", "markets": [{
                "key": "player_aces", "last_update": CAPTURE.isoformat(),
                "outcomes": [
                    {"description": "Alexander Zverev", "name": "3+ Aces", "price": -500},
                    {"description": "Alexander Zverev", "name": "4+ Aces", "price": -196},
                    {"description": "Alexander Zverev", "name": "5+ Aces", "price": 120},
                    {"description": "Ben Shelton", "name": "Over", "point": 8.5, "price": -110},
                    {"description": "Ben Shelton", "name": "Under", "point": 8.5, "price": -110},
                ],
            }],
        }, {
            "key": "sleeper", "markets": [{
                "key": "player_aces", "outcomes": [
                    {"description": "Alexander Zverev", "name": "Over", "point": 5.5, "price": 110},
                    {"description": "Alexander Zverev", "name": "Under", "point": 5.5, "price": -110},
                ],
            }],
        }],
    }]}


def archive(data=None):
    return collect(date(2026, 11, 23), now=CAPTURE,
                   get=lambda: (data or source(), 480))


def prediction():
    return {
        "id": "canonical-event", "event_id": "provider-event",
        "model_version": "champion_aces_existing", "scheduled_at": START.isoformat(),
        "tour": "ATP", "competition": "Challenger", "surface": "hard",
        "player1": {"id": "p1", "name": "Alexander Zverev"},
        "player2": {"id": "p2", "name": "Ben Shelton"},
    }


def history():
    data = []
    for i in range(12):
        when = CAPTURE - timedelta(days=15 + i * 4)
        for who, rival, own in [("p1", "oppa-" + str(i), 9),
                                ("p2", "oppb-" + str(i), 7)]:
            data.append(MatchRecord(
                match_id=who + str(i), tour="atp", scheduled_at=when,
                player1_id=who, player2_id=rival,
                player1_name=who, player2_name=rival, winner_id=who,
                status="finished", surface="hard", tournament="Historical",
                stats={"p1_aces": own, "p2_aces": 2},
            ))
    return data


def snapshot(data=None, rows=None, past=None):
    return build_snapshot(
        history() if past is None else past,
        [prediction()] if rows is None else rows,
        archive(data), now=MORNING, model_sha256=MODEL_SHA)


def test_real_below_150_prices_stay_visible_and_model_selects_max_one():
    r = snapshot()
    assert r["odds_minimum"] is None
    assert r["model_probability_calibrated"] is False
    assert r["counts"]["incremental_provider_requests"] == 0
    assert r["counts"]["raw_quotes"] == 3
    assert len(r["quotes"]) == 3  # DFS and two-sided-only markets are not N+.
    assert any(x["odds"] == 1.2 for x in r["quotes"])
    assert r["counts"]["modelled_quotes"] == 3
    assert r["counts"]["shadow_picks"] == 1
    assert sum(x["status"] == "shadow_pick" for x in r["quotes"]) == 1
    assert all(x["research_only"] and not x["official_publication"] for x in r["quotes"])
    assert all(x["model_probability"] is not None and x["expected_value"] is not None
               for x in r["quotes"])
    assert r["cdb_writes"] == 0 and not r["official_results_modified"]


def test_no_history_still_preserves_all_real_market_quotes_without_inventing_probability():
    r = snapshot(past=[])
    assert len(r["quotes"]) == 3
    assert r["counts"]["modelled_quotes"] == 0
    assert r["counts"]["shadow_picks"] == 0
    assert all(x["model_probability"] is None and x["expected_value"] is None
               and x["status"] == "no_count_projection" for x in r["quotes"])


def test_native_ace_price_has_prestart_sha_and_cannot_be_rewritten():
    r = archive()
    r["observed_prematch_priced_events"][0]["provider_raw_event"]["id"] = "other"
    scored = build_snapshot(history(), [prediction()], r,
                            now=MORNING, model_sha256=MODEL_SHA)
    assert scored["counts"]["invalid_event_evidence"] == 1
    assert scored["quotes"] == []


def test_duplicate_canonical_fixture_blocks_unsafe_mapping():
    two = prediction()
    two["id"] = "different-canonical"
    r = snapshot(rows=[prediction(), two])
    assert r["counts"]["identity_ambiguous"] == 1
    assert r["quotes"] == []


def test_no_matched_model_uses_null_not_market_implied_probability():
    r = snapshot(rows=[])
    assert len(r["quotes"]) == 3
    assert r["counts"]["identity_missing"] == 1
    assert all(x["model_probability"] is None for x in r["quotes"])


def test_stale_or_partial_archive_is_rejected_and_never_scored():
    r = archive()
    r["coverage_truncated"] = True
    with pytest.raises(ValueError, match="archive"):
        build_snapshot(history(), [prediction()], r,
                       now=MORNING, model_sha256=MODEL_SHA)
    with pytest.raises(ValueError, match="archive"):
        build_snapshot(history(), [prediction()], archive(),
                       now=MORNING + timedelta(days=2), model_sha256=MODEL_SHA)


def test_too_close_to_start_never_becomes_shadow_pick():
    late = MORNING + timedelta(minutes=7)
    data = source()
    data["events"][0]["commence_time"] = late.isoformat()
    r = build_snapshot(history(), [prediction()], archive(data),
                       now=MORNING, model_sha256=MODEL_SHA)
    assert r["quotes"] == []


def test_existing_production_main_tour_gate_not_edited():
    from tbt.services.ace_selection import _main_tour_for_aces
    assert _main_tour_for_aces(prediction()) is False
    assert snapshot()["counts"]["modelled_quotes"] == 3


def test_exact_completed_count_is_research_only_and_immutable():
    r = snapshot()
    select = next(x for x in r["quotes"] if x["status"] == "shadow_pick")
    match = SimpleNamespace(
        match_id="canonical-event", is_completed=True,
        status="finished", scheduled_at=START,
        player1_id="p1", player2_id="p2",
        stats={"p1_aces": 9, "p2_aces": 3},
    )
    before = deepcopy(r)
    settled = _settle_research([r], [], [match], now=START + timedelta(days=1))
    assert len(settled) == 1
    assert settled[0]["status"] == "win"
    assert settled[0]["actual_aces"] == 9
    assert settled[0]["evidence"] == "canonical_cdb_completed_match_count_research_proxy"
    assert not settled[0]["official_results_modified"]
    assert r == before
    assert _settle_research([r], settled, [match], now=START + timedelta(days=2)) == settled
    wrong = SimpleNamespace(**{**vars(match), "status": "retired"})
    assert _settle_research([r], [], [wrong], now=START + timedelta(days=1)) == []


class FakeStore:
    def __init__(self, remote, directory):
        self.repository = "BackstageTalks/tbt-data"
        self.tag = "tbt-model-shadow-v1"
        self.directory = Path(directory)
        self.remote = remote
        self.directory.mkdir(parents=True, exist_ok=True)
        self.writes = 0

    def _asset_names(self):
        return set(self.remote)

    def download(self, *, extra_names, required_names, require_bundle_manifest):
        assert require_bundle_manifest
        for name in required_names:
            (self.directory / name).write_bytes(self.remote[name])

    def upload_bundle(self, paths):
        self.writes += 1
        for p in paths:
            self.remote[Path(p).name] = Path(p).read_bytes()


def test_private_shadow_capture_uses_existing_writer_with_fresh_remote_readback(
        tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    remote = {}
    store = FakeStore(remote, tmp_path / "original")
    reader = lambda repo, tag, folder: FakeStore(remote, folder)
    result = capture_in_existing_store(
        store, history(), [prediction()], archive(),
        observed_at=MORNING, model_sha256=MODEL_SHA, readback_factory=reader)
    assert result["status"] == "PRIVATE_READBACK_VERIFIED"
    assert result["current_day_picks"] == 1
    assert store.writes == 1
    persisted = json.loads(remote[ASSET])
    assert persisted["experiment"] == EXPERIMENT
    assert len(persisted["captures"]) == 1
    assert persisted["settlements"] == []
    same = capture_in_existing_store(
        store, history(), [prediction()], archive(),
        observed_at=MORNING, model_sha256=MODEL_SHA, readback_factory=reader)
    assert same["status"] == "UNCHANGED"
    assert store.writes == 1


def test_publication_integration_is_optin_existing_morning_refresh_only():
    pipeline = (ROOT / "scripts/pipeline.py").read_text()
    workflow = (ROOT / ".github/workflows/data.yml").read_text()
    assert 'if (args.morning_refresh and os.getenv(' in pipeline
    assert "BLINQ_PROPLINE_ACES_SHADOW_ENABLED" in pipeline
    assert "capture_in_existing_store" in pipeline
    assert '\"propline_aces_shadow\": propline_aces_shadow_result' in pipeline
    assert "inputs.morning_refresh == true" in workflow
    assert "BLINQ_PROPLINE_ACES_SHADOW_ENABLED:" in workflow
