"""Synthetic, provider-free controls for frozen BlinQ selection replay."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

import pytest

from replay_selection_reliability import (
    analyze, anchors, canonical_index, dt, eligible, load_snapshots,
    historical_cdb_coverage, metrics, paired_complete_day_comparison, prepare, verify_pins,
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



def test_provider_native_event_id_recovered_only_with_exact_player_pair():
    canonical = settled("canon-1")
    canonical["provider_context_json"] = '{"_tbt_provider_event_id":"rapid-99"}'
    index = canonical_index([canonical])
    assert index["rapid-99"]["match_id"] == "canon-1"
    outcome = analyze([snapshot([candidate("rapid-99")])], [canonical])
    assert outcome["model_quality_A"]["v7.2.1-frozen"]["all_candidates_raw"]["settled"] == 1


def test_same_provider_id_on_two_cdb_rows_is_quarantined():
    left, right = settled("canon-1"), settled("canon-2")
    left["provider_context_json"] = '{"_tbt_provider_event_id":"duplicate"}'
    right["provider_context_json"] = '{"_tbt_provider_event_id":"duplicate"}'
    with pytest.raises(ValueError, match="duplicate canonical/provider"):
        canonical_index([left, right])


def test_provider_match_requires_same_tour_date_and_normal_finish():
    original = settled("canonical-id")
    original.update(tour="wta", provider_context_json='{"_tbt_provider_event_id":"native-id"}')
    out = analyze([snapshot([candidate("native-id")])], [original])
    assert out["diagnostics"]["canonical_tour_disagreement"] == 1
    original["tour"] = "atp"
    original["scheduled_at"] = "2026-11-05T12:00:00+00:00"
    out = analyze([snapshot([candidate("native-id")])], [original])
    assert out["diagnostics"]["canonical_schedule_disagreement"] == 1
    original["scheduled_at"] = "2026-11-02T12:00:00+00:00"
    original["provider_context_json"] = '{"_tbt_provider_event_id":"native-id","_tbt_termination":{"reason":"retired"}}'
    out = analyze([snapshot([candidate("native-id")])], [original])
    assert out["model_quality_A"]["v7.2.1-frozen"]["all_candidates_raw"]["settled"] == 0
    assert out["diagnostics"]["unsettled_or_void"] == 1



def test_current_cdb_serve_return_report_not_misused_as_pit_inference():
    record = settled("m1")
    record.update(scheduled_at="2026-10-14T12:00:00+00:00", tour="atp",
                  player1_rank=22, player2_rank=31,
                  stats_json=json.dumps({
                      "p1_service_points_won": .67, "p2_service_points_won": .62,
                      "p1_return_points_won": .36, "p2_return_points_won": .32,
                      "p1_break_point_return_win": .4, "p2_break_point_return_win": .5,
                  }))
    q=historical_cdb_coverage([record])
    assert q["scope"] == "CURRENT_CDB_POST_MATCH_FIELD_AVAILABILITY_NOT_PIT_INFERENCE"
    assert q["groups"]["all"]["both_service_return_rates"] == 1
    assert q["groups"]["all"]["both_break_point_rates"] == 1
    assert q["groups"]["2026-10|tour:ATP"]["both_rank_values"] == 1


def test_full_day_paired_comparison_excludes_unresolved_days():
    orig = [{"correct": True}, {"correct": False}]
    alt = [{"correct": True}, {"correct": True}]
    result = paired_complete_day_comparison(
        [("2026-10-01", orig), ("2026-10-02", [{"correct": None}])],
        [("2026-10-01", alt), ("2026-10-02", [{"correct": True}])],
    )
    assert result["complete_days"] == 1
    assert result["paired_capacity"] == 2
    assert result["difference_percentage_points"] == 50
    assert result["status"].startswith("DESCRIPTIVE")


def test_paired_comparison_rejects_capacity_mismatch():
    with pytest.raises(ValueError, match="capacity"):
        paired_complete_day_comparison(
            [("2026-10-01", [{"correct": True}])],
            [("2026-10-01", [{"correct": True}, {"correct": False}])],
        )



def test_raw_confidence_below_65_is_not_labeled_65_to_70():
    record = candidate("weak", raw=.61, depth=1, selected=None)
    out = analyze([snapshot([record])], [settled("weak")])
    buckets = out["model_quality_A"]["v7.2.1-frozen"]["by_segment"]["confidence"]
    assert buckets["below_65"]["settled"] == 1
    assert "65_70" not in buckets


def test_provisional_canonical_winner_is_not_a_finished_result():
    original = settled("not-done", status="scheduled")
    r = analyze([snapshot([candidate("not-done")])], [original])
    m = r["model_quality_A"]["v7.2.1-frozen"]["all_candidates_raw"]
    assert m["selected"] == 1 and m["settled"] == 0
    assert r["diagnostics"]["unsettled_or_void"] == 1


def test_count_fields_never_masquerade_as_break_point_rates():
    original = settled("mcount")
    original.update(scheduled_at="2026-10-14T12:00:00+00:00", tour="atp",
                    stats_json=json.dumps({
                       "p1_break_points_won": 1, "p2_break_points_won": 1,
                       "p1_return_points_won": .4, "p2_return_points_won": .3,
                    }))
    coverage = historical_cdb_coverage([original])["groups"]["all"]
    assert coverage["both_return_rates"] == 1
    assert coverage["both_break_point_rates"] == 0


def test_paired_comparison_rejects_misaligned_dates():
    with pytest.raises(ValueError, match="keys differ"):
        paired_complete_day_comparison(
            [("2026-10-01", [{"correct": True}])],
            [("2026-10-02", [{"correct": True}])],
        )
