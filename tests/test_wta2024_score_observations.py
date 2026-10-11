"""Focused tests for source-scoped finished WTA score counts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_wta2024_score_observations import score, parse_completed

def row(a="2",b="1",pairs=((6,4),(4,6),(7,6))):
    out={"side1_sets_won":a,"side2_sets_won":b}
    for i,(x,y) in enumerate(pairs,1):
        out[f"set{i}_side1"]=str(x)
        out[f"set{i}_side2"]=str(y)
    return out

def test_three_finished_sets_games():
    r=parse_completed(row())
    assert r["total_games"]==33
    assert r["side1_games"]==17
    assert r["side2_games"]==16
    assert r["side1_sets"]==2

def test_tiebreak_brackets_are_not_games():
    assert score("7(12)")==7
    assert score("6(8)")==6
    assert parse_completed(row("2","0",((7,6),(6,0))))["total_games"]==19

def test_partial_and_retired_are_not_importable():
    assert parse_completed(row("1","0",((6,4),))) is None
    assert parse_completed(row("2","0",((6,4),))) is None
    assert parse_completed(row("2","1",((6,4),(4,6)))) is None

def test_disallow_equal_undecided_or_super_tiebreak():
    for pairs in (((6,6),(6,4)),((10,8),(6,4)),((7,0),(6,4))):
        assert parse_completed(row("2","0",pairs)) is None

def test_score_single_values():
    assert score("") is None
    assert score("RET") is None
    assert score("7(5)")==7
    assert score("6")==6
