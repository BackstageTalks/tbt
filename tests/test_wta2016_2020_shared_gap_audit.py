"""2016-2020 read-only stage never proposes half-complete ranking overwrites."""
from copy import deepcopy
import audit_wta_2016_2020_shared_gap_audit as a


def test_two_null_stage_filter_discards_partial_existing_rank():
    good={"add_only_null_fields":{"player1_rank":7,"player2_rank":9},
          "expected_player1_rank":None,"expected_player2_rank":None}
    partial={"add_only_null_fields":{"player2_rank":9},
             "expected_player1_rank":7,"expected_player2_rank":None}
    report={"counts":{"candidate_matches":2,"candidate_rank_cells":3},
            "quarantined":{}}
    eligible=a.two_null_only(report,[deepcopy(good),deepcopy(partial)])
    assert eligible==[good]
    assert report["counts"]["candidate_matches"]==1
    assert report["counts"]["candidate_rank_cells"]==2
    assert report["counts"]["unfiltered_audit_candidate_matches"]==2
    assert report["quarantined"]["partial_null_not_stageable_by_strict_writer"]==1
    assert a.YEARS==(2016,2017,2018,2019,2020)
