"""Synthetic exact-first-capture tests; zero provider calls or release mutations."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_only_a0_private_capture import (
    ASSET, first_capture_update, staged_full_slate,
    capture_using_existing_shadow_store,
)
from tbt.services.market_only_shadow_research import load_shadow_params

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_shadow_params(
    ROOT / "research/market_only_shadow/params_2026-11-20.json"
)
NOW = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 21, 14, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)


def prediction(n, *, fair=.78, model=.81):
    market = (
        {
            "source": "tennisapi_provider_1", "provider_id": 1,
            "source_id_known": True, "source_id": "bookmaker-source-1",
            "player1_implied_probability": fair,
            "player2_implied_probability": 1 - fair,
        } if fair is not None else None
    )
    return {
        "id": f"canonical-{n}", "event_id": f"event-{n}",
        "prediction_family": "singles", "model_version": "champion-test-v1",
        "tour": "ATP" if n % 2 else "WTA",
        "competition": "ATP 250", "surface": "hard",
        "scheduled_at": START.isoformat(),
        "created_at": "2026-11-21T08:00:00+00:00",
        "player1": {"id": f"a-{n}", "probability": model},
        "player2": {"id": f"b-{n}", "probability": 1 - model},
        "match_winner_market": market,
    }


def completed(n, *, winner_first=True):
    return SimpleNamespace(
        match_id=f"canonical-{n}", is_completed=True,
        winner_id=f"a-{n}" if winner_first else f"b-{n}",
        scheduled_at=START,
    )


def stage(rows):
    return staged_full_slate(rows, observed_at=NOW, params=PARAMS)


def test_collect_full_slate_including_unpriced_not_just_published_top():
    rows, counts = stage([prediction(i, fair=.78 if i < 4 else None)
                          for i in range(9)])
    assert len(rows) == 9
    assert counts["priced_primary_complete_two_way"] == 4
    assert counts["missing_fair_t3"] == 5
    assert rows[0]["fair_player1"] == pytest.approx(.78)
    assert rows[4]["fair_player1"] is None
    assert rows[4]["shadow_player1_probability"] == pytest.approx(.81)
    assert rows[0]["match_id"] == "canonical-0"


def test_first_capture_five_t2_fallbacks_and_exact_second_pass_immutable():
    rows, _ = stage([prediction(i, fair=.40) for i in range(8)])
    first, report = first_capture_update(None, rows, [], now=NOW, params=PARAMS)
    assert report["new_captured"] == 8
    assert report["new_issued"] == 5
    assert all(r["selection_tier"] == "T2" for r in first["issued_shadow"])
    second, report = first_capture_update(first, rows, [], now=NOW, params=PARAMS)
    assert report == {
        "new_captured": 0, "new_issued": 0, "new_settled": 0,
        "total_captured": 8, "total_issued": 5, "total_settled": 0,
    }
    assert second == first


def test_all_missing_fair_still_captures_five_model_fallbacks():
    rows, _ = stage([prediction(i, fair=None) for i in range(7)])
    first, report = first_capture_update(None, rows, [], now=NOW, params=PARAMS)
    assert report["new_issued"] == 5
    assert all(r["selection_tier"] == "T3" and
               r["selection_basis"] == "fallback_model"
               for r in first["issued_shadow"])


def test_fewer_than_five_available_issues_all_but_does_not_invent():
    rows, _ = stage([prediction(i, fair=None) for i in range(3)])
    result, report = first_capture_update(None, rows, [], now=NOW, params=PARAMS)
    assert report["new_issued"] == 3
    assert len(result["snapshots"]) == len(result["issued_shadow"]) == 3


def test_settlement_exact_cdb_id_after_start_only_and_never_changes_snapshot():
    rows, _ = stage([prediction(0)])
    first, _ = first_capture_update(None, rows, [], now=NOW, params=PARAMS)
    old_snapshot = json.dumps(first["snapshots"], sort_keys=True)
    result, report = first_capture_update(
        first, [], [completed(0)], now=LATER, params=PARAMS)
    assert report["new_settled"] == 1
    assert result["settlements"][0]["status"] == "settled"
    assert result["settlements"][0]["winner_id"] == "a-0"
    assert json.dumps(result["snapshots"], sort_keys=True) == old_snapshot
    repeated, same = first_capture_update(
        result, [], [completed(0)], now=LATER, params=PARAMS)
    assert same["new_settled"] == 0
    assert repeated == result


def test_duplicate_cdb_and_changed_canonical_identity_fail_closed():
    rows, _ = stage([prediction(0)])
    first, _ = first_capture_update(None, rows, [], now=NOW, params=PARAMS)
    with pytest.raises(ValueError, match="Duplicate completed"):
        first_capture_update(
            first, [], [completed(0), completed(0)],
            now=LATER, params=PARAMS)
    other = dict(rows[0], player2_id="different")
    with pytest.raises(ValueError, match="Canonical A0"):
        first_capture_update(first, [other], [], now=NOW, params=PARAMS)


def test_model_version_drift_blocks_append_instead_of_recalibrating():
    rows, _ = stage([prediction(0)])
    first, _ = first_capture_update(None, rows, [], now=NOW, params=PARAMS)
    more, _ = stage([prediction(1)])
    more[0]["model_version"] = "new-unauthorized-version"
    with pytest.raises(ValueError, match="Champion model changed"):
        first_capture_update(first, more, [], now=NOW, params=PARAMS)


def test_market_quote_requires_exact_two_way_provider_book_and_real_clock():
    src = prediction(1)
    src["match_winner_market"]["source_id_known"] = False
    rows, counts = stage([src])
    assert counts["missing_fair_t3"] == 1 and rows[0]["fair_player1"] is None
    src2 = prediction(2)
    src2["scheduled_at"] = "2026-11-21T09:02:00Z"
    rows, counts = stage([src2])
    assert len(rows) == 0 and counts["late_or_invalid"] == 1


class FakeStore:
    def __init__(self, remote, folder):
        self.repository = "BackstageTalks/tbt-data"
        self.tag = "tbt-model-shadow-v1"
        self.directory = folder
        self.remote = remote
        self.directory.mkdir(parents=True, exist_ok=True)
    def _asset_names(self):
        return set(self.remote)
    def download(self, *, extra_names, required_names, require_bundle_manifest):
        assert require_bundle_manifest is True
        for name in required_names:
            if name not in self.remote:
                raise FileNotFoundError(name)
            (self.directory / name).write_bytes(self.remote[name])
    def upload_bundle(self, paths):
        for path in paths:
            self.remote[Path(path).name] = Path(path).read_bytes()


def test_existing_single_writer_fake_store_roundtrip_readback(tmp_path, monkeypatch):
    # Fake store is an in-memory unit fixture, never a real GitHub Actions writer.
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    remote = {}
    store = FakeStore(remote, tmp_path / "writer")
    def factory(repo, tag, folder):
        assert repo == store.repository and tag == store.tag
        return FakeStore(remote, folder)
    result = capture_using_existing_shadow_store(
        store, [prediction(0), prediction(1)], [], observed_at=NOW,
        readback_factory=factory, model_sha256="a"*64)
    assert result["status"] == "PRIVATE_READBACK_VERIFIED"
    assert result["provider_requests"] == 0
    assert result["production_modified"] is False
    ledger = json.loads(remote[ASSET])
    assert len(ledger["snapshots"]) == 2
    assert len(ledger["issued_shadow"]) == 2
    before = remote[ASSET]
    again = capture_using_existing_shadow_store(
        store, [prediction(0), prediction(1)], [], observed_at=NOW,
        readback_factory=factory, model_sha256="a"*64)
    assert again["status"] == "NO_CHANGE"
    with pytest.raises(ValueError, match="champion artifact digest"):
        capture_using_existing_shadow_store(
            store, [prediction(0)], [], observed_at=NOW,
            readback_factory=factory, model_sha256="b"*64)
    assert remote[ASSET] == before


def test_later_same_day_fixture_is_captured_but_cannot_rewrite_first_issue():
    initial, _ = stage([prediction(i, fair=.40) for i in range(6)])
    first, r1 = first_capture_update(None, initial, [], now=NOW, params=PARAMS)
    assert r1["new_issued"] == 5
    first_receipts = json.dumps(first["issued_shadow"], sort_keys=True)
    later, _ = stage([prediction(99, fair=.99)])
    result, r2 = first_capture_update(
        first, later, [], now=NOW, params=PARAMS)
    assert r2["new_captured"] == 1
    assert r2["new_issued"] == 0
    assert result["snapshots"][-1]["a0_first_daily_slate"] is False
    assert json.dumps(result["issued_shadow"], sort_keys=True) == first_receipts


def test_market_a0_refresh_workflow_requires_separate_owner_opt_in():
    workflow = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
    lines = [line for line in workflow.splitlines()
             if line.strip().startswith("BLINQ_MARKET_A0_SHADOW_ENABLED:")]
    assert len(lines) == 1
    assert "vars.BLINQ_MARKET_A0_OWNER_APPROVED == 'true'" in lines[0]
    assert "inputs.mode == 'refresh'" in lines[0]
    assert "inputs.mode == 'current-refresh'" in lines[0]
