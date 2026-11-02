"""Regression for the Hurkacz 9 vs 5 ace count: superiority is not an O/U win."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest

from tbt.services.match_status import runtime_settled_results
from tbt.services.results_archive import _safe_new_ace_results, merge_settled_results


def _row(publication):
    return {
        "event_id": "hurkacz-2026-11-02",
        "scheduled_at": "2026-11-02T10:00:00Z",
        "player1": {"id": "musetti", "name": "Lorenzo Musetti"},
        "player2": {"id": "hurkacz", "name": "Hubert Hurkacz"},
        "market_publications": [publication],
    }


def _pub(**extra):
    return {
        "market": "aces", "section": "ace", "selection_id": "hurkacz",
        "projection_scope": "player", "projection_metric": "aces",
        "publication_status": "published",
        "issued_at": "2026-11-02T06:15:00Z",
        "projection": 10.9,
        "price_status": "projection_only",
        "odds": None,
        **extra,
    }


def _stats():
    return {"hurkacz-2026-11-02": {
        "status": "win", "provider_status": "finished ended",
        "provider_home_id": "musetti", "provider_away_id": "hurkacz",
        "projection_stats_p1_id": "musetti",
        "projection_stats_p2_id": "hurkacz",
        "projection_stats": {"p1_aces": 5, "p2_aces": 9},
        "checked_at": "2026-11-02T13:00:00Z",
    }}


def test_legacy_superiority_not_settled_as_new_aces_ou_win():
    row = _row(_pub(price_contract="player_superiority"))
    assert runtime_settled_results({"ace_picks": [row], "results": []}, _stats()) == []


def test_exact_published_ou_over_10_5_is_loss_at_nine_aces():
    row = _row(_pub(price_contract="player_total_ou", ou_side="over", market_line=10.5))
    result = runtime_settled_results({"ace_picks": [row], "results": []}, _stats())
    assert len(result) == 1
    graded = result[0]["market_publications"][0]["result"]
    assert graded["actual_count"] == 9
    assert graded["opponent_actual_count"] == 5
    assert graded["correct"] is False
    assert graded["status"] == "miss"
    assert "profit_units" not in graded  # Local statistical quote is presentation-only.


def test_priced_original_ou_over_10_5_uses_minus_one_unit():
    row = _row(_pub(price_contract="player_total_ou", ou_side="over",
                    market_line=10.5, price_status="priced_projection", odds=1.80))
    result = runtime_settled_results({"ace_picks": [row], "results": []}, _stats())
    graded = result[0]["market_publications"][0]["result"]
    assert graded["correct"] is False
    assert graded["staked_units"] == 1
    assert graded["profit_units"] == -1


def test_archive_hides_unverifiable_ace_win_but_keeps_raw_untouched():
    original = _row(_pub(price_contract="player_superiority"))
    original["market_publications"][0]["result"] = {
        "status": "hit", "correct": True, "actual_count": 9,
        "opponent_actual_count": 5, "profit_units": .80,
    }
    raw = deepcopy(original)
    safe = _safe_new_ace_results([original])
    assert safe[0]["market_publications"][0]["result"] is None
    assert original == raw
    # An existing canonical Results row must not override the read-side guard.
    merged = merge_settled_results({"results": [original]}, [])
    assert merged["results"][0]["market_publications"][0]["result"] is None


def test_archive_regrades_bad_win_when_original_ou_is_available():
    original = _row(_pub(price_contract="player_total_ou", ou_side="over",
                         market_line=10.5, price_status="priced_projection", odds=1.80))
    original["market_publications"][0]["result"] = {
        "status": "hit", "correct": True, "actual_count": 9,
        "opponent_actual_count": 5, "profit_units": .80,
    }
    safe = _safe_new_ace_results([original])
    result = safe[0]["market_publications"][0]["result"]
    assert result["correct"] is False and result["status"] == "miss"
    assert result["profit_units"] == -1
    assert original["market_publications"][0]["result"]["correct"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="Node runtime unavailable")
def test_browser_win_and_units_cannot_use_opponent_comparison():
    root = Path(__file__).resolve().parents[1]
    js = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const begin = source.indexOf('  function publicationOutcome(');
const end = source.indexOf('  function resultVoidLabel(', begin);
assert(begin >= 0 && end > begin);
const ctx = {};vm.createContext(ctx);vm.runInContext(source.slice(begin,end), ctx);
const base = {market:'aces',issued_at:'2026-11-02T06:15:00Z',
  result:{correct:true,status:'hit',actual_count:9,opponent_actual_count:5}};
assert.equal(ctx.publicationOutcome({...base,price_contract:'player_superiority'}).kind,'pending');
assert.equal(ctx.publicationOutcome({...base,price_contract:'player_total_ou',ou_side:'over',market_line:10.5}).kind,'loss');
assert.equal(ctx.publicationOutcome({...base,price_contract:'player_total_ou',ou_side:'under',market_line:10.5}).kind,'win');
assert.equal(ctx.publicationOutcome({...base,price_contract:'player_total_ou',ou_side:'over',market_line:9.0}).kind,'void');
console.log('ACES exact O/U result display: PASS');
"""
    run = subprocess.run(["node", "-e", js], cwd=root, text=True,
                         capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
