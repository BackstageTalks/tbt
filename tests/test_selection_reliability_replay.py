"""Synthetic, provider-free controls for frozen BlinQ selection replay."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

import pytest

from replay_selection_reliability import (
    analyze, anchors, canonical_index, dt, eligible, load_snapshots,
    metrics, prepare, verify_pins,
)


def candidate(event, *, raw=.8, depth=1.0, selected="top_daily",
              model="v7.2.1-frozen", quote="2026-11-02T06:58:00+00:00"):
    return {
        "event_id": event, "scheduled_at": "2026-11-02T12:00:00+00:00",
        "tour": "ATP", "surface": "hard", "model_version": model,
        "winner_id": "player-a",
        "player1": {"id": "player-a", "rank": 10, "probability": raw},
        "player2": {"id": "player-b", "rank": 12, "probability": 1-raw},
        "raw_model_probability": raw,
        "blinq_probability": .5 + (raw-.5)*depth, "data_depth": depth,
        "samples": {"player1_matches": 20, "player2_matches": 24,
                    "player1_surface_matches": 12, "player2_surface_matches": 9},
        "priced": True,
        "betting": {"selection_id": "player-a", "odds": 1.65,
                    "captured_at": quote, "expected_value": -99},
        "two_way_market": {"player1_odds": 1.65, "player2_odds": 2.35,
                           "captured_at": quote},
        "selected_section": selected,
    }


def settled(event, *, winner="player-a", status="finished"):
    return {"match_id": event, "player1_id": "player-a", "player2_id": "player-b",
            "winner_id": winner, "status": status, "tournament_level": "ATP250",
            "scheduled_at": "2026-11-02T12:00:00+00:00"}


def snapshot(rows, when="2026-11-02T07:00:00+00:00"):
    return {"schema": 1, "generated_at": when,
            "scope": {"post_match_fields_excluded": True}, "rows": rows}


def test_load_rejects_post_match_fields(tmp_path):
    path = tmp_path / "selection_candidates_2026-11.json.gz"
    item = candidate("event1")
    item["result"] = {"correct": True}
    with gzip.open(path, "wt") as handle:
        json.dump({"schema": 1, "month": "2026-11",
                   "snapshots": [snapshot([item])]}, handle)
    with pytest.raises(ValueError, match="post-match"):
        load_snapshots([path])


def test_earliest_daily_anchor_and_prestart_guard():
    first, later = snapshot([candidate("a")]), snapshot([candidate("b")],
                                                 when="2026-11-02T08:00:00+00:00")
    assert anchors([first, later])["2026-11-02"] is first
    diagnostics = {}
    # Use Counter-like dictionary only for accepted event.
    assert prepare(candidate("a"), dt(first["generated_at"]), "2026-11-02",
                   canonical_index([settled("a")]), {})["correct"] is True
    from collections import Counter
    c = Counter()
    assert prepare(candidate("a"), dt("2026-11-02T12:00:00+00:00"),
                   "2026-11-02", canonical_index([settled("a")]), c) is None
    assert c["late_or_outside_betting_day"] == 1


def test_exact_pairing_only_and_correctness_from_cdb():
    result = analyze([snapshot([candidate("e1"), candidate("e2", selected=None)])],
                     [settled("e1"), settled("e2", winner="player-b")])
    model = result["model_quality_A"]["v7.2.1-frozen"]
    assert model["all_candidates_raw"]["settled"] == 2
    assert model["all_candidates_raw"]["hit_rate"] == .5
    assert model["by_segment"]["tour"]["ATP"]["settled"] == 2
    replay = result["selector_comparison_B"]["v7.2.1-frozen|top_daily"]
    assert replay["baseline_assignment"]["settled"] == 1
    assert replay["confidence_first"]["selected"] == 1
    assert replay["quality_first"]["selected"] == 1
    assert replay["baseline_assignment"]["hit_rate"] == 1.0
    assert result["provider_requests"] == 0
    assert result["production_mutated"] is False


def test_canonical_identity_collision_excluded_from_scoring():
    bad = settled("e1")
    bad["player2_id"] = "another-player"
    report = analyze([snapshot([candidate("e1")])], [bad])
    assert report["model_quality_A"]["v7.2.1-frozen"]["all_candidates_raw"]["settled"] == 0
    assert report["diagnostics"]["canonical_player_collision"] == 1


def test_duplicates_and_quote_late_fail_closed():
    with pytest.raises(ValueError, match="duplicate canonical"):
        canonical_index([settled("a"), settled("a")])
    from collections import Counter
    c = Counter()
    r = prepare(candidate("a", quote="2026-11-02T11:59:00+00:00"),
                dt("2026-11-02T07:00:00+00:00"), "2026-11-02",
                canonical_index([settled("a")]), c)
    assert r["correct"] is True
    assert not r["quote_ok"]
    assert not eligible(r, "top_daily")


def test_model_versions_never_pooled():
    r = analyze([snapshot([candidate("x", model="v7.2.1"),
                           candidate("y", model="legacy", selected=None)])],
                [settled("x"), settled("y")])
    assert set(r["model_quality_A"]) == {"v7.2.1", "legacy"}
    assert r["model_quality_A"]["v7.2.1"]["all_candidates_raw"]["settled"] == 1
    assert r["model_quality_A"]["legacy"]["all_candidates_raw"]["settled"] == 1


def test_zero_impact_of_ev_and_no_automatic_promotion():
    r = analyze([snapshot([candidate("e1")])], [settled("e1")])
    assert r["status"] == "READ_ONLY_REPLAY_NO_DEPLOY"
    assert r["recommended_production_action"].startswith("NONE")
    assert r["selector_comparison_B"]["v7.2.1-frozen|top_daily"]["baseline_assignment"]["selected"] == 1


def test_readback_detects_mutated_asset_and_missing_bundle_checksum(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir()
    (directory / "history-2026.parquet").write_bytes(b"canonical")
    (directory / "history_manifest.json").write_bytes(b"{}")
    import hashlib
    digest = lambda x: hashlib.sha256(x).hexdigest()
    manifest = {"files": {
        "history-2026.parquet": {"sha256": digest(b"canonical")},
        "history_manifest.json": {"sha256": digest(b"{}")},
    }}
    (directory / "_tbt_bundle_manifest.json").write_text(json.dumps(manifest))
    files = ["history-2026.parquet", "history_manifest.json", "_tbt_bundle_manifest.json"]
    releases = {"assets": [{"name": n, "id": i+1, "size": (directory/n).stat().st_size,
                            "updated_at": "2026-11-03T00:00:00Z"}
                           for i, n in enumerate(files)]}
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps(releases))
    after.write_text(json.dumps(releases))
    proof = verify_pins(before, after, files, directory, require_manifest=True)
    assert proof["history-2026.parquet"]["bundle_manifest_verified"]
    releases["assets"][0]["id"] = 500
    after.write_text(json.dumps(releases))
    with pytest.raises(ValueError, match="changed during"):
        verify_pins(before, after, files, directory, require_manifest=True)
