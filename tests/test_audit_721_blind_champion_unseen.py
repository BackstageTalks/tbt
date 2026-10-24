"""Identity/time tests for true blind champion vs 7.2.1 fresh-only evidence."""
from datetime import datetime, timezone
from types import SimpleNamespace
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import pytest
from audit_721_blind_champion_unseen import build_result


def instance(mid,day,captured,prod=.3,candidate=.7):
    return {"match_id":mid,"event_id":mid,"tour":"ATP","surface":"hard",
            "scheduled_at":f"2026-10-{day:02d}T13:00:00+00:00",
            "captured_at":captured,"status":"settled",
            "target_player1_win":1,
            "production_player1_probability":prod,
            "challenger_player1_probability":candidate}
def cases():
    overlap={"champion_cutoff_utc_day":"2026-09-25",
             "candidate_consumed_cutoff_utc_day":"2026-10-22",
             "champion_unseen_reported":4,
             "strictly_after_all_frozen_721_consumption":{"rows":3},
             "candidate_sha256":"testsha",
             "candidate":{"frozen_candidate_version":"v7.2.1",
                          "production_version":"v201"}}
    segment={"candidate_version":"v7.2.1","production_version":"v201",
             "candidate_model_sha256":"testsha","eligible_settled":2,
             "overall":{"candidate_minus_champion":{"accuracy":0.1}}}
    rows=[
        instance("old",22,"2026-10-22T12:00:00+00:00"),
        instance("fresh",23,"2026-10-23T12:00:00+00:00"),
        instance("too-late",23,"2026-10-23T12:55:00+00:00")]
    source={"source":{"production_version":"v201"},"rows":rows}
    records=[SimpleNamespace(match_id=r["match_id"],scheduled_at=
        datetime.fromisoformat(r["scheduled_at"])) for r in rows]
    records.append(SimpleNamespace(match_id="uncaptured",
        scheduled_at=datetime.fromisoformat("2026-10-23T16:00:00+00:00")))
    return overlap,segment,source,records


def run(o,s,shadow,records):
    with patch("audit_721_blind_champion_unseen.audit_history",return_value=(records,{})), \
         patch("audit_721_blind_champion_unseen.validate_frozen_evidence",side_effect=
               lambda source,production_version:(source["rows"],{"settled":3})), \
         patch("audit_721_blind_champion_unseen.exclude_repeated_events",side_effect=lambda rows:rows):
        return build_result(o,s,shadow,records,datetime(2026,10,24,10,tzinfo=timezone.utc))


def test_only_original_prematch_fresh_matches_score():
    o,s,shadow,rec=cases()
    report=run(o,s,shadow,rec)
    assert report["cohort"]["champion_unseen_original"] == 4
    assert report["cohort"]["fresh_after_frozen_721_consumption"] == 3
    assert report["cohort"]["overlap_old_issued_and_settled_not_blind"] == 1
    assert report["cohort"]["quarantined_near_start"] == 1
    assert report["cohort"]["fresh_and_actually_issued_and_settled"] == 1
    assert report["cohort"]["missing_fresh_original_pair"] == 2
    assert report["fresh_paired"]["n"] == 1
    assert report["fresh_paired"]["candidate_721"]["accuracy"] == 1
    assert report["fresh_paired"]["champion"]["accuracy"] == 0
    assert report["fresh_utc_days"] == 1
    assert report["no_model_promotion"] is True and report["provider_requests"] == 0


def test_reject_mismatched_candidate_sha():
    o,s,shadow,rec=cases()
    s["candidate_model_sha256"]="wrong"
    with pytest.raises(ValueError,match="sha"):
        run(o,s,shadow,rec)


def test_reject_mutable_readiness_count():
    o,s,shadow,rec=cases()
    o["champion_unseen_reported"]=5
    with pytest.raises(ValueError,match="read_back_cohort_disagrees"):
        run(o,s,shadow,rec)


def test_reject_uncertain_fresh_cohort_size():
    o,s,shadow,rec=cases()
    o["strictly_after_all_frozen_721_consumption"]["rows"]=999
    with pytest.raises(ValueError,match="fresh_cohort_disagrees"):
        run(o,s,shadow,rec)


def test_reject_duplicate_provider_event():
    o,s,shadow,rec=cases()
    extra=dict(shadow["rows"][1])
    extra["match_id"]="uncaptured"
    shadow["rows"].append(extra)
    rec[-1]=SimpleNamespace(match_id="uncaptured",scheduled_at=datetime.fromisoformat(extra["scheduled_at"]))
    with patch("audit_721_blind_champion_unseen.audit_history",return_value=(rec,{})), \
         patch("audit_721_blind_champion_unseen.validate_frozen_evidence",side_effect=
               lambda source,production_version:(source["rows"],{"settled":3})), \
         patch("audit_721_blind_champion_unseen.exclude_repeated_events",side_effect=lambda rows:rows):
        with pytest.raises(ValueError,match="duplicated_issued_event"):
            build_result(o,s,shadow,rec,datetime(2026,10,24,10,tzinfo=timezone.utc))
