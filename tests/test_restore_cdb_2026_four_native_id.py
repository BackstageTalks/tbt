"""Offline fail-closed tests for single-real-match 2026 native-source repair."""
from datetime import datetime, timezone
import json

import pyarrow as pa
import pytest

import restore_cdb_2026_four_native_id as repair


WHEN = datetime(2026, 10, 23, 18, 55, tzinfo=timezone.utc)


def t(rows):
    return pa.Table.from_pylist([{
        "match_id": mid, "tour": "wta", "scheduled_at": WHEN,
        "tournament_id": "bakersfield", "tournament": "ITF W35 Bakersfield, CA Women",
        "round_name": "Quarterfinals", "player1_id": p1, "player2_id": p2,
        "player1_name": "Jo-Yee Chan", "player2_name": "Hanna Chang",
        "winner_id": p2 if valid_winner else "wrong",
        "status": "finished", "stats_json": json.dumps({"p1_aces": 0, "p2_aces": 4}),
        "provider_context_json": json.dumps({"_tbt_event_identity": {
            "event_id": ev, "home": {"id": p1}, "away": {"id": p2}},
            "_tbt_statistics": {"event_id": ev, "source": "tennisapi1",
                                "status": "available"}}),
    } for mid, p1, p2, ev, valid_winner in rows])


def test_winner_uses_canonical_side_not_unmatched_source_native_id():
    a = t([("one", "a", "b", "event-1", True)])
    assert repair.winning_player(a, 0) == "hannachang"
    b = t([("one", "a", "b", "event-1", False)])
    assert repair.winning_player(b, 0) is None


def test_additive_candidate_preserves_original_canonical_prefix(monkeypatch):
    pre = t([("prewrite", "a", "b", "event-1", True)])
    live = t([("current", "x", "y", "event-2", True)])
    monkeypatch.setattr(repair, "validate_four", lambda o, p, l: (
        0, {"verified_existing_atp_aliases": 2}))
    candidate, proof = repair.build_candidate(pre, pre, live)
    assert candidate.num_rows == 2
    assert candidate.slice(0, 1).equals(live)
    assert candidate["match_id"].to_pylist() == ["current", "prewrite"]
    assert proof["verified_net_new_real_matches"] == 1


def test_rejects_duplicate_prewrite_identity_even_if_a_match_is_requested(monkeypatch):
    pre = t([("current", "a", "b", "event-1", True)])
    live = t([("current", "a", "b", "event-1", True)])
    monkeypatch.setattr(repair, "validate_four", lambda o, p, l: (0, {}))
    with pytest.raises(ValueError, match="exactly one absent"):
        repair.build_candidate(pre, pre, live)


def test_rejects_extra_duplicate_candidates(monkeypatch):
    pre = t([("extra-a", "a", "b", "ev-1", True),
             ("extra-b", "a", "b", "ev-2", True)])
    live = t([("current", "x", "y", "event-0", True)])
    monkeypatch.setattr(repair, "validate_four", lambda o, p, l: (0, {}))
    with pytest.raises(ValueError, match="exactly one absent"):
        repair.build_candidate(pre, pre, live)



def test_schema_alignment_only_widens_exact_small_bestof_and_null_ranks():
    pre = pa.table({
        "match_id": pa.array(["old"]),
        "best_of": pa.array([3], type=pa.int64()),
        "player1_rank": pa.nulls(1),
        "player2_rank": pa.nulls(1),
        "stats_json": pa.array(['{"p1_aces":0}']),
    })
    live = pa.table({
        "match_id": pa.array(["live"]),
        "best_of": pa.array([5.0], type=pa.float64()),
        "player1_rank": pa.array([10.0], type=pa.float64()),
        "player2_rank": pa.array([20.0], type=pa.float64()),
        "stats_json": pa.array(['{"p1_aces":1}']),
    })
    aligned, same = repair.align_prewrite_exact_observed_types(pre, live)
    assert aligned.schema.equals(live.schema)
    assert aligned["best_of"].to_pylist() == [3.0]
    assert aligned["player1_rank"].to_pylist() == [None]
    assert aligned["player2_rank"].to_pylist() == [None]
    assert aligned["stats_json"].equals(pre["stats_json"])
    assert same.equals(live)


def test_schema_alignment_fails_on_invalid_bestof_and_other_type_change():
    base = pa.table({
        "best_of": pa.array([9], type=pa.int64()),
        "player1_rank": pa.nulls(1),
        "player2_rank": pa.nulls(1),
        "name": pa.array(["a"]),
    })
    target = pa.table({
        "best_of": pa.array([3.0], type=pa.float64()),
        "player1_rank": pa.array([10.0], type=pa.float64()),
        "player2_rank": pa.array([10.0], type=pa.float64()),
        "name": pa.array(["a"]),
    })
    with pytest.raises(ValueError, match="Nonstandard source best_of"):
        repair.align_prewrite_exact_observed_types(base, target)
    shifted = base.set_column(base.schema.get_field_index("name"), "name",
                              pa.array([1], type=pa.int64()))
    with pytest.raises(ValueError, match="Unapproved prewrite"):
        repair.align_prewrite_exact_observed_types(shifted, target)


def test_unchanged_external_writer_and_no_freeform_provider_calls():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]
              / "scripts/restore_cdb_2026_four_native_id.py").read_text()
    assert "ReleaseStore(REPO, TAG, history)" in source
    assert "store.upload_bundle(" in source
    assert 'verify(REPO, Path(".cdb-global-writer-lock.json"))' in source
    assert "stamp(release(TAG)) != baseline" in source
    assert 'backup_current(args.out, history)' in source
    assert '"REMOTE_PERSISTED_READBACK_VERIFIED"' in source
    assert "verify_cross_year(history, proposed_ids)" in source
    assert "RAPIDAPI_KEY" not in source
    assert "httpx" not in source
