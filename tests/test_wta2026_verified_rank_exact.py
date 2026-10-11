"""No-external-data guarded WTA 2026 exact-ID and old-to-new rank replay."""
from datetime import date
import pandas as pd
import pytest
from import_wta2026_verified_rank_exact import (
    ensure_wta_rebase_identical, patch, load_candidates, missing, ORIGINAL_SHA
)

def frame(tour="wta",rank1=None,rank2=None):
    return pd.DataFrame([{
        "match_id":"m1","tour":tour,
        "scheduled_at":pd.Timestamp("2026-04-20T12:00:00+00:00"),
        "player1_id":"p1","player2_id":"p2",
        "player1_name":"A","player2_name":"B",
        "player1_rank":rank1,"player2_rank":rank2,
        "winner_id":"p1","provider_context_json":"{}","stats_json":"{}",
    }])

def row():
    return {
        "canonical_match_id":"m1","scheduled_at":"2026-04-20T12:00:00+00:00",
        "player1_id":"p1","player2_id":"p2",
        "source_player1_id":"sid1","source_player2_id":"sid2",
        "source_week_p1":"2026-04-13","source_week_p2":"2026-04-13",
        "add_only_null_fields":{"player1_rank":19,"player2_rank":38},
    }

def test_exact_wta_rows_preserved_from_prior_source_baseline():
    old=frame()
    now=frame()
    n=ensure_wta_rebase_identical(old,now)
    assert n==1
    now.at[0,"winner_id"]="p2"
    with pytest.raises(AssertionError):
        ensure_wta_rebase_identical(old,now)

def test_atp_changes_do_not_block_unmodified_wta():
    old=pd.concat([frame(),frame("atp").assign(match_id="m2")],ignore_index=True)
    now=old.copy()
    now.at[1,"player1_rank"]=3
    assert ensure_wta_rebase_identical(old,now)==1

def test_null_to_integer_rank_and_provenance_in_current_year():
    before=frame()
    new,counts=patch(before,[row()],expected_matches=1,expected_values=2)
    assert new.at[0,"player1_rank"]==19
    assert new.at[0,"player2_rank"]==38
    assert counts["changed_matches"]==1
    assert before.at[0,"player1_rank"] is None
    assert new.at[0,"winner_id"]=="p1"

def test_existing_top_level_rank_not_overwritten():
    before=frame(rank1=100)
    with pytest.raises(ValueError,match="Null-only"):
        patch(before,[row()],expected_matches=1,expected_values=2)

def test_identity_drift_rejected():
    before=frame()
    candidate=row()
    candidate["player1_id"]="OTHER"
    with pytest.raises(ValueError,match="identity drift"):
        patch(before,[candidate],expected_matches=1,expected_values=2)

def test_na_is_null_and_old_full_year_is_pinned():
    assert missing(float("nan"))
    assert missing(None)
    assert not missing(18)
    assert len(ORIGINAL_SHA)==64
