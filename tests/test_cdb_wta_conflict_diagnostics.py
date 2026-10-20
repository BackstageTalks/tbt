"""WTA diagnostics must aggregate only, never publish identities or stats."""
import json

import pytest

from scripts.cdb_wta_conflict_diagnostics import summarize


def test_conflict_aggregation_redacts_source_identities(tmp_path):
    path=tmp_path/"quarantine.jsonl"
    rows=[
        {"match_id":"private-match-987",
         "sources":[{"source":"kaggle-hwaitt:source.csv",
                     "evidence":["date_exact","tournament_exact","winner","surface"]}],
         "conflicts":[
            {"reason":"canonical_conflict","key":"p1_aces",
             "existing":4.0,"incoming":5.0,
             "source_match_id":"private-source-123"},
            {"reason":"canonical_conflict","key":"p2_service_points_won",
             "existing":0.61,"incoming":0.62},
         ]},
        {"match_id":"private-match-999",
         "sources":[{"source":"kaggle-hwaitt:source.csv",
                     "evidence":["date_plusminus_1","winner"]}],
         "conflicts":[{"reason":"canonical_conflict","key":"p1_aces",
                       "existing":1.0,"incoming":3.0}]},
    ]
    path.write_text("".join(json.dumps(x)+"\n" for x in rows))
    output=summarize(path)
    assert output["quarantined_matches"]==2
    assert output["strong_identity_but_conflicting_stats_matches"]==1
    assert output["stat_field_conflicts"]=={"aces":2,"service_points_won":1}
    assert output["absolute_difference_buckets"]["over_0_25"]==2
    assert output["production_mutated"] is False
    serialized=json.dumps(output)
    for text in ("private-match-987","private-match-999",
                 "private-source-123","kaggle-hwaitt:source.csv"):
        assert text not in serialized


def test_invalid_private_quarantine_fails_closed(tmp_path):
    path=tmp_path/"data.jsonl"
    path.write_text(json.dumps({"match_id":"","conflicts":[]})+"\n")
    with pytest.raises(ValueError,match="Invalid private quarantine"):
        summarize(path)
