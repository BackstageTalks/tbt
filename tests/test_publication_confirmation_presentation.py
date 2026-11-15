from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = spec_from_file_location(
    "confirm_prediction_publication_test_module",
    SCRIPTS / "confirm_prediction_publication.py",
)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_publication_candidate_view_ignores_nested_member_presentation_fields():
    private = {
        "doubles_picks": [
            {
                "event_id": "evt-1",
                "player1": {
                    "id": "team-a",
                    "name": "Team A",
                    "members": [
                        {"id": "p1", "name": "One"},
                        {"id": "p2", "name": "Two"},
                    ],
                },
                "player2": {
                    "id": "team-b",
                    "name": "Team B",
                    "members": [
                        {"id": "p3", "name": "Three"},
                        {"id": "p4", "name": "Four"},
                    ],
                },
                "selection": "Team A",
            }
        ]
    }
    deployed = {
        "player_assets": {"available": True},
        "doubles_picks": [
            {
                "event_id": "evt-1",
                "player1": {
                    "id": "team-a",
                    "name": "Team A",
                    "rank": 10,
                    "members": [
                        {"id": "p1", "name": "One", "photo_url": "/p1.jpg", "country_code": "SK"},
                        {"id": "p2", "name": "Two", "best_rank": 22},
                    ],
                },
                "player2": {
                    "id": "team-b",
                    "name": "Team B",
                    "members": [
                        {"id": "p3", "name": "Three", "ranking_points": 500},
                        {"id": "p4", "name": "Four", "height_cm": 188},
                    ],
                },
                "selection": "Team A",
            }
        ],
    }

    assert module._publication_candidate_view(deployed) == module._publication_candidate_view(private)


def test_publication_candidate_view_still_detects_prediction_changes():
    left = {"top_daily_picks": [{"event_id": "evt", "player1": {"id": "1", "name": "A"}, "odds": 1.8}]}
    right = {"top_daily_picks": [{"event_id": "evt", "player1": {"id": "1", "name": "A"}, "odds": 1.9}]}
    assert module._publication_candidate_view(left) != module._publication_candidate_view(right)


def test_confirmation_retry_accepts_exact_released_feed_after_ledger_restore():
    original = {
        "market_selection": {"publication_schema": 1},
        "top_daily_picks": [{"event_id": "today", "betting": {"odds": 1.8}}],
    }
    # A previous partial confirmation can add already-issued historical rows
    # when restoring market snapshots; the released bytes must still compare.
    restored = {
        **original,
        "top_daily_picks": original["top_daily_picks"] + [
            {"event_id": "previous-issued", "betting": {"odds": 2.1}}
        ],
    }
    assert module._matches_private_publication_candidate(original, original, restored)
    assert module._matches_private_publication_candidate(restored, original, restored)
    mismatched = {
        **original,
        "top_daily_picks": [{"event_id": "today", "betting": {"odds": 9.99}}],
    }
    assert not module._matches_private_publication_candidate(mismatched, original, restored)


def test_confirmed_snapshot_readback_reports_top_esa_and_viac_es_separately():
    snapshot = {
        "schema": 1, "confirmed_only": True, "betting_day": "2026-11-15",
        "top_daily_picks": [
            {"event_id": "top-1", "market": "match_winner"},
            {"event_id": "top-2", "market": "match_winner"},
        ],
        "prime_picks": [], "value_picks": [], "doubles_picks": [],
        "sg_picks": [],
        "ace_picks": [
            {"event_id": "ace-1", "market": "aces"},
            {"event_id": "ace-2", "market": "aces"},
            {"event_id": "more-1", "market": "most_aces"},
        ],
    }
    for key in (
        "top_daily_picks", "prime_picks", "value_picks", "doubles_picks",
        "sg_picks", "ace_picks",
    ):
        snapshot.setdefault("totals", {})[key] = len(snapshot[key])
    report = module.summarize_confirmed_offer_snapshot(snapshot)
    assert report["top"] == 2
    assert report["esa"] == 2
    assert report["viac_es"] == 1
    assert report["value"] == 0

    from copy import deepcopy
    import pytest
    duplicate = deepcopy(snapshot)
    duplicate["ace_picks"].append(duplicate["ace_picks"][0])
    duplicate["totals"]["ace_picks"] += 1
    with pytest.raises(ValueError, match="Duplicate issued"):
        module.summarize_confirmed_offer_snapshot(duplicate)
    pending = deepcopy(snapshot)
    pending["confirmed_only"] = False
    with pytest.raises(ValueError, match="not confirmed"):
        module.summarize_confirmed_offer_snapshot(pending)
    incorrect_total = deepcopy(snapshot)
    incorrect_total["totals"]["top_daily_picks"] = 1
    with pytest.raises(ValueError, match="category mismatch"):
        module.summarize_confirmed_offer_snapshot(incorrect_total)


def test_persisted_snapshot_readback_fails_on_remote_mismatch(monkeypatch):
    import json
    import pytest

    snapshot = {
        "schema": 1, "confirmed_only": True, "betting_day": "2026-11-15",
        "top_daily_picks": [{"event_id": "top-1", "market": "match_winner"}],
        "prime_picks": [], "value_picks": [], "doubles_picks": [],
        "sg_picks": [], "ace_picks": [{"event_id": "ace-1", "market": "aces"}],
    }
    snapshot["totals"] = {
        k: len(snapshot[k]) for k in (
            "top_daily_picks", "prime_picks", "value_picks", "doubles_picks",
            "sg_picks", "ace_picks",
        )
    }
    state = {"tamper": False}

    class ReadOnlyStore:
        def __init__(self, _repository, _tag, directory):
            self.directory = Path(directory)

        def download(self, *, extra_names=(), required_names=(), require_bundle_manifest=False):
            assert required_names == ("daily_offer_snapshot.json",)
            assert require_bundle_manifest is True
            copy = json.loads(json.dumps(snapshot))
            if state["tamper"]:
                copy["top_daily_picks"] = []
            target = self.directory / "daily_offer_snapshot.json"
            target.write_text(json.dumps(copy), encoding="utf-8")

    monkeypatch.setattr(module, "ReleaseStore", ReadOnlyStore)
    report = module.verify_uploaded_offer_snapshot("test/private", snapshot)
    assert report["status"] == "verified"
    assert (report["top"], report["esa"], report["viac_es"]) == (1, 1, 0)
    state["tamper"] = True
    with pytest.raises(RuntimeError, match="read-back mismatch"):
        module.verify_uploaded_offer_snapshot("test/private", snapshot)
