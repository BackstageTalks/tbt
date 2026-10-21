"""Seasonal abbreviated names are only research evidence, never CDB identities."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import csv
import hashlib
import json

import pytest

from scripts.cdb_vendor_season_candidate_audit import _alias, _stats, audit


def match(mid="private-id", **kwargs):
    base=dict(match_id=mid,tour="wta",
              scheduled_at=datetime(2024,1,4,tzinfo=timezone.utc),
              player1_name="Madison Keys", player2_name="Marie Bouzkova",
              player1_id="canonical-one",player2_id="canonical-two",
              winner_id="canonical-one",surface="hard",tournament="United Cup",
              stats={})
    base.update(kwargs)
    return SimpleNamespace(**base)


def csv_source(path: Path, **overrides):
    row=dict(match_id="vendor-987",date_timestamp=str(int(datetime(2024,1,4,tzinfo=timezone.utc).timestamp())),
             tour_type="2", tour_type_human="WTA Tour", home_name="Keys M.",away_name="Bouzkova M.",
             home_id="vendor-keys",away_id="vendor-bouzkova",winner_code="1",
             surface="hard",tournament="United Cup WTA",
             home_aces="4",away_aces="2",home_double_faults="1",away_double_faults="3",
             home_service_points_won_perc="70",away_service_points_won_perc="62",
             home_return_points_won_perc="38",away_return_points_won_perc="30")
    row.update(overrides)
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_alias_is_not_canonical_verified_identity():
    assert _alias("Davidovich Fokina A.",source=True)==("davidovich fokina","a")
    assert _alias("Alejandro Davidovich Fokina",source=False)==("davidovich fokina","a")
    assert _alias("Keys Madison",source=True) is None


def test_only_research_candidates_reported_without_ids(tmp_path):
    src=tmp_path/"season.csv"
    digest=csv_source(src)
    result=audit([match()],[(src,"wta",digest)])
    assert result["counts"]["research_candidates_same_day_pair_winner_surface_tournament"]==1
    assert result["counts"]["candidate_missing_cells_UNVERIFIED"]==8
    assert result["canonical_matches_confirmed"]==0
    assert result["import_ready"] is False
    serialized=json.dumps(result)
    for forbidden in ("vendor-987","private-id","canonical-one","Madison Keys"):
        assert forbidden not in serialized


def test_ambiguous_and_wrong_winner_or_tournament_are_blocked(tmp_path):
    source=tmp_path/"input.csv"
    digest=csv_source(source)
    result=audit([match("one"),match("two")],[(source,"wta",digest)])
    assert result["counts"]["ambiguous_canonical_alias_date"]==1
    assert result["counts"].get("candidate_missing_cells_UNVERIFIED",0)==0
    result=audit([match(winner_id="canonical-two")],[(source,"wta",digest)])
    assert result["counts"]["canonical_winner_conflict"]==1
    result=audit([match(tournament="Another Open")],[(source,"wta",digest)])
    assert result["counts"]["event_not_exact"]==1


def test_bad_sha_fails_no_output(tmp_path):
    src=tmp_path/"input.csv"
    csv_source(src)
    with pytest.raises(ValueError,match="SHA-256"):
        audit([match()],[(src,"wta","0"*64)])


def test_zero_zero_complement_missing_rate_sentinel_never_counted(tmp_path):
    src = tmp_path / "zero-sentinel.csv"
    digest = csv_source(src, home_service_points_won_perc="0",
                        away_return_points_won_perc="0")
    result = audit([match()], [(src, "wta", digest)])
    assert result["counts"]["no_valid_match_stats"] == 1
    assert result["counts"].get("candidate_missing_cells_UNVERIFIED", 0) == 0
    assert result["canonical_matches_confirmed"] == 0


def test_complementary_serving_returning_rates_rounding_and_fail_closed():
    base = dict(home_service_points_won_perc="71",
                away_return_points_won_perc="29",
                away_service_points_won_perc="53",
                home_return_points_won_perc="47")
    assert _stats(base) is not None
    assert _stats({**base, "away_return_points_won_perc": "30"}) is not None
    assert _stats({**base, "away_return_points_won_perc": "28"}) is not None
    assert _stats({**base, "away_return_points_won_perc": "0"}) is None
    assert _stats({**base, "home_return_points_won_perc": "0"}) is None
    assert _stats({**base, "home_service_points_won_perc": "0",
                   "away_return_points_won_perc": "100"}) is not None


def test_challenger_tour_code_pair_checked_not_guessed(tmp_path):
    from scripts.cdb_vendor_season_candidate_audit import TOUR_CODE_LABELS
    assert TOUR_CODE_LABELS[("3", "atp chall")] == "atp"
    assert TOUR_CODE_LABELS[("4", "wta chall")] == "wta"
    assert ("5", "atp exhib") not in TOUR_CODE_LABELS
    src=tmp_path/"season.csv"
    digest=csv_source(src,tour_type="4",tour_type_human="WTA Chall")
    result=audit([match()],[(src,"wta",digest)])
    assert result["counts"]["research_candidates_same_day_pair_winner_surface_tournament"]==1
    digest=csv_source(src,tour_type="5",tour_type_human="ATP Exhib")
    result=audit([match()],[(src,"wta",digest)])
    assert result["counts"]["tour_type_unverified"]==1
