"""WTA 2026 rank writer never weakens source ID, PIT or no-overwrite."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from import_wta2026_verified_rank_exact_cells import (
    apply, rank_int, verify_wta_unchanged, SOURCE_OLD_YEAR_SHA,
)


def fixture():
    before=pd.DataFrame([{
        "match_id":"wta-2026-example","tour":"wta",
        "scheduled_at":pd.Timestamp("2026-08-10T12:00:00Z"),
        "player1_id":"c123","player2_id":"c456",
        "player1_rank":float("nan"),"player2_rank":float("nan"),
        "provider_context_json":json.dumps({"existing":"keep"}),
        "stats_json":'{"p1_aces":7}',"winner_id":"c123",
    }])
    row={
        "canonical_match_id":"wta-2026-example",
        "scheduled_at":"2026-08-10T12:00:00+00:00",
        "player1_id":"c123","player2_id":"c456",
        "source_player1_id":"s321","source_player2_id":"s654",
        "source_week_p1":"2026-08-03","source_week_p2":"2026-08-03",
        "add_only_null_fields":{"player1_rank":21,"player2_rank":35},
    }
    return before,row


def test_exactly_two_null_rank_cells_added_and_other_stats_preserved():
    before,row=fixture()
    after,count=apply(before,[row],expected_matches=1,expected_values=2)
    assert count=={"player1_rank_filled":1,"player2_rank_filled":1,"updated_matches":1}
    assert int(after.loc[0,"player1_rank"])==21
    assert int(after.loc[0,"player2_rank"])==35
    assert after.loc[0,"stats_json"]==before.loc[0,"stats_json"]
    assert after.loc[0,"winner_id"]==before.loc[0,"winner_id"]
    p=json.loads(after.loc[0,"provider_context_json"])
    assert p["existing"]=="keep"
    assert p["_tbt_wta_rank_provenance"]["as_of_player1"]=="2026-08-03"
    assert p["_tbt_wta_rank_provenance"]["model_use"]=="disabled_until_explicit_training"


def test_preexisting_non_null_rank_is_never_overwritten_even_if_equal():
    before,row=fixture()
    before.at[0,"player1_rank"]=21.0
    with pytest.raises(ValueError,match="overwritten"):
        apply(before,[row],expected_matches=1,expected_values=2)


def test_canonical_player_id_change_fails():
    before,row=fixture()
    row["player1_id"]="wrong"
    with pytest.raises(ValueError,match="identity/time"):
        apply(before,[row],expected_matches=1,expected_values=2)


@pytest.mark.parametrize("week",["2026-08-10","2026-08-11","2026-07-26"])
def test_same_day_future_or_old_rank_fails(week):
    before,row=fixture()
    row["source_week_p1"]=week
    with pytest.raises(ValueError,match="prior/within"):
        apply(before,[row],expected_matches=1,expected_values=2)


def test_conflicting_provenance_fails():
    before,row=fixture()
    before.at[0,"provider_context_json"]=json.dumps({
        "_tbt_wta_rank_provenance":{"source":"different"}
    })
    with pytest.raises(ValueError,match="provenance"):
        apply(before,[row],expected_matches=1,expected_values=2)


@pytest.mark.parametrize("val",[0,-1,10001,True,None,"NaN","2.2","3x"])
def test_invalid_ranking_domains(val):
    with pytest.raises(ValueError):
        rank_int(val)


def test_full_delta_must_match_exact_expected_field_counts():
    before,row=fixture()
    with pytest.raises(ValueError,match="Unexpected WTA"):
        apply(before,[row],expected_matches=2,expected_values=4)


def test_duplicate_id_candidate_refused():
    before,row=fixture()
    with pytest.raises(ValueError,match="Repeated"):
        apply(before,[row,row],expected_matches=2,expected_values=4)


def test_other_canonical_cells_stable_through_write():
    before,row=fixture()
    other=before.copy()
    other.at[0,"tour"]="atp"
    with pytest.raises(ValueError,match="identity/time"):
        apply(other,[row],expected_matches=1,expected_values=2)


def test_rank_record_requires_full_source_week():
    before,row=fixture()
    row["source_week_p2"]="bad-week"
    with pytest.raises(ValueError):
        apply(before,[row],expected_matches=1,expected_values=2)
