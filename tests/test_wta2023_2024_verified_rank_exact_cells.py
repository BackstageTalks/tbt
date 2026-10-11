"""Regression gates for WTA 2023/2024 year-pinned null-only rank publisher."""
import json
from datetime import date
from pathlib import Path
import sys
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import import_wta2023_2024_verified_rank_exact_cells as w


def request(year):
    return {"schema":1, "mode":"write", "year":year,
       "source_audit_run":123456, "source_tag":f"blinq-wta{year}-id-ranked-null-audit-123456",
       "source_original_year_sha256":"a"*64, "current_year_sha256":"a"*64,
       "source_stage_sha256":"b"*64, "source_report_sha256":"c"*64,
       "expected_matches":1, "expected_added_values":2, "expected_wta_rows":1,
       "require_global_lock":True, "require_immutable_backup":True,
       "require_full_year_readback":True, "require_whole_wta_unchanged":True,
       "strict_canonical_player_ids":True, "exact_null_only":True,
       "overwrite_existing_rank":False, "train_model":False,
       "promote_model":False, "create_cron":False, "provider_api_requests":0}


def sample(year):
    before=pd.DataFrame([{"match_id":"test-match", "tour":"wta",
       "scheduled_at":pd.Timestamp(f"{year}-08-10T12:00:00Z"),
       "player1_id":"canonical-1", "player2_id":"canonical-2",
       "player1_rank":float("nan"),"player2_rank":float("nan"),
       "provider_context_json":json.dumps({"existing":True}),
       "stats_json":'{"p1_aces":8}', "winner_id":"canonical-1"}])
    row={"canonical_match_id":"test-match",
         "scheduled_at":f"{year}-08-10T12:00:00+00:00",
         "player1_id":"canonical-1", "player2_id":"canonical-2",
         "source_player1_id":"id-1","source_player2_id":"id-2",
         "source_week_p1":f"{year}-08-03","source_week_p2":f"{year}-08-03",
         "add_only_null_fields":{"player1_rank":15,"player2_rank":30}}
    return before,row


@pytest.mark.parametrize("year",[2023,2024])
def test_two_nulls_with_provenance_no_other_cell_changed(year):
    w.configure(request(year))
    frame,row=sample(year)
    after,counts=w.apply(frame,[row])
    assert counts["updated_matches"]==1
    assert counts["player1_rank_filled"]==1
    assert counts["player2_rank_filled"]==1
    assert after.at[0,"stats_json"]==frame.at[0,"stats_json"]
    assert after.at[0,"winner_id"]==frame.at[0,"winner_id"]
    ctx=json.loads(after.at[0,"provider_context_json"])
    assert ctx["existing"] is True
    assert ctx["_tbt_wta_rank_provenance"]["point_in_time"] is True
    assert ctx["_tbt_wta_rank_provenance"]["source_player1_id"]=="id-1"


@pytest.mark.parametrize("year",[2023,2024])
def test_unchanged_whole_wta_cohort_and_changed_player_identity_fails(year):
    w.configure(request(year))
    before,row=sample(year)
    assert w.verify_wta_unchanged(before,before.copy())==1
    changed=before.copy()
    changed.at[0,"player1_id"]="impostor"
    with pytest.raises(AssertionError):
        w.verify_wta_unchanged(before,changed)
    with pytest.raises(ValueError,match="identity/time"):
        w.apply(changed,[row])


@pytest.mark.parametrize("year",[2023,2024])
def test_no_overwrite_unknown_week_or_conflicting_provenance(year):
    w.configure(request(year))
    before,row=sample(year)
    before.at[0,"player1_rank"]=15
    with pytest.raises(ValueError,match="overwritten"):
        w.apply(before,[row])
    before,row=sample(year)
    row["source_week_p1"]=f"{year}-08-10"
    with pytest.raises(ValueError,match="prior/within"):
        w.apply(before,[row])
    before,row=sample(year)
    before.at[0,"provider_context_json"]=json.dumps({"_tbt_wta_rank_provenance":{"x":1}})
    with pytest.raises(ValueError,match="provenance"):
        w.apply(before,[row])


@pytest.mark.parametrize("year",[2023,2024])
def test_missing_invalid_mismatched_required_pins_fail_closed(year):
    good=request(year)
    for delta in [
        {"current_year_sha256":"d"*64},
        {"source_tag":"blinq-wta2025-id-ranked-null-audit-123456"},
        {"expected_added_values":3},
        {"overwrite_existing_rank":True},
        {"require_global_lock":False},
        {"provider_api_requests":1},
        {"model_promoted":True},
        {"source_stage_sha256":"bad"},
    ]:
        bad=good|delta
        with pytest.raises(ValueError):
            w.configure(bad)


@pytest.mark.parametrize("year",[2023,2024])
def test_invalid_rank_and_duplicate_exact_match_fail(year):
    w.configure(request(year))
    frame,row=sample(year)
    with pytest.raises(ValueError,match="Repeated"):
        w.apply(frame,[row,row],expected_matches=2,expected_values=4)
    for value in (-1,0,10001,"nan",True):
        with pytest.raises(ValueError):
            w.rank_int(value)
