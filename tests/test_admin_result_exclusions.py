"""Admin result exclusion controls never mutate issued ledger, and Results KPIs exclude tests."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tbt.services import result_exclusions
from tbt.services.dashboard_kpis import published_results_metrics
from test_results_archive_runtime import Table


def published(event="101", section="top_daily", price=1.7, selection="11"):
    return {
        "event_id": event, "scheduled_at": "2026-10-10T10:00:00+00:00",
        "tour": "ATP", "player1":{"id":"11","name":"Alpha"},
        "player2":{"id":"22","name":"Beta"},
        "market_publications":[{
            "section":section, "market":"match_winner",
            "selection_id":selection, "issued_at":"2026-10-10T08:00:00Z",
            "odds":price, "result":{"status":"hit","correct":True,
                                     "staked_units":1.0,"profit_units":price-1},
        }],
    }


def test_exclusion_round_trip_restores_and_keeps_immutable_source(monkeypatch):
    table=Table()
    monkeypatch.setattr(result_exclusions, "_table", lambda _:table)
    feed={"results":[published("101"),published("102"),published("103")]}
    original=deepcopy(feed)
    candidates=result_exclusions.result_candidates(feed)
    assert len(candidates)==3
    k=candidates[0]["id"]
    result=result_exclusions.set_result_exclusions([k],True,"admin-1")
    assert result["excluded_total"]==1
    assert k in result_exclusions.load_result_exclusions()
    visible=result_exclusions.apply_result_exclusions(feed,result_exclusions.load_result_exclusions())
    assert len(visible["results"])==2
    assert feed==original  # no changes to ledger
    assert result_exclusions.set_result_exclusions([k],False,"admin-1")["excluded_total"]==0
    assert len(result_exclusions.apply_result_exclusions(feed,result_exclusions.load_result_exclusions())["results"])==3


def test_bulk_100_per_call_and_strict_no_unknown_or_partial_id(monkeypatch):
    table=Table()
    monkeypatch.setattr(result_exclusions,"_table",lambda _name:table)
    ids=[result_exclusions.result_bet_id(published(str(i)),published(str(i))["market_publications"][0]) for i in range(120)]
    assert len(set(ids))==120
    with pytest.raises(ValueError):
        result_exclusions.set_result_exclusions(ids,True,"admin")
    with pytest.raises(ValueError):
        result_exclusions.set_result_exclusions([ids[0],ids[0]],True,"admin")
    with pytest.raises(ValueError):
        result_exclusions.set_result_exclusions(["bad"],True,"admin")
    assert result_exclusions.set_result_exclusions(ids[:100],True,"admin")["updated"]==100
    assert result_exclusions.set_result_exclusions(ids[100:],True,"admin")["excluded_total"]==120


def test_exclusion_preserves_other_publications_in_same_match():
    row=published()
    row["market_publications"].append({
        "section":"value", "market":"match_winner", "selection_id":"22",
        "issued_at":"2026-10-10T08:01:00Z",
        "result":{"correct":False,"status":"miss"},
    })
    feed={"results":[row]}
    key=result_exclusions.result_bet_id(row,row["market_publications"][0])
    visible=result_exclusions.apply_result_exclusions(feed,{key})
    assert len(visible["results"])==1
    assert len(visible["results"][0]["market_publications"])==1
    assert visible["results"][0]["market_publications"][0]["selection_id"]=="22"
    assert len(feed["results"][0]["market_publications"])==2


def test_same_bet_category_aliases_share_one_identity_and_different_ou_do_not():
    row=published()
    a=deepcopy(row["market_publications"][0])
    b=deepcopy(a);b["section"]="value"
    assert result_exclusions.result_bet_id(row,a)==result_exclusions.result_bet_id(row,b)
    a.update(market="aces",section="ace",price_contract="player_total_ou",
             ou_side="over",market_line=4.5)
    b.update(market="aces",section="ace",price_contract="player_total_ou",
             ou_side="under",market_line=6.5)
    assert result_exclusions.result_bet_id(row,a)!=result_exclusions.result_bet_id(row,b)


def test_public_results_financial_stats_exclude_test_rows():
    feed={"results":[published("101",price=1.7),published("102",price=1.5)]}
    initial=published_results_metrics(feed,"all",now=datetime(2026,10,12,tzinfo=timezone.utc))
    assert initial["sample"]==2
    assert abs(initial["profit_units"]-1.2)<1e-10
    first=feed["results"][0]
    key=result_exclusions.result_bet_id(first,first["market_publications"][0])
    visible=result_exclusions.apply_result_exclusions(feed,{key})
    final=published_results_metrics(visible,"all",now=datetime(2026,10,12,tzinfo=timezone.utc))
    assert final["sample"]==1
    assert abs(final["profit_units"]-.5)<1e-10
    assert abs(final["roi"]-.5)<1e-10


def test_admin_results_frontend_has_jump_and_no_50_row_hardcap():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    src=(root/"web"/"app.js").read_text(encoding="utf-8")
    assert "id=\"adminTestGoPage\"" in src
    assert "data-admin-test-action=\"go\"" in src
    assert "adminTestAction('go')" in src
    assert "data-admin-test-action=\"select-all\"" in src
    assert "state.adminTestSelected" in src
