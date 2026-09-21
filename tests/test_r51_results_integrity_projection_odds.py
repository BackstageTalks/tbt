from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from tbt.data.provider_context import minimize_provider_payload
from tbt.schemas import MatchRecord
from tbt.services.engine import _match_void_reason, _settle_sg_projection_publications
from tbt.services.projection_odds import extract_match_total_odds, extract_player_superiority_odds

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
RELEASE = json.loads((ROOT / "web/release.json").read_text())
UI = json.loads((ROOT / "web/ui-config.json").read_text())


def test_r51_release_and_result_identity_are_id_authoritative():
    assert RELEASE["patch"] == UI["ui_patch"] == "736-r53"
    assert "function resultPickIdentity(publication,row)" in APP
    assert "const p1Selected=selectable&&pickIdentity.side==='p1';" in APP
    assert "const p2Selected=selectable&&pickIdentity.side==='p2';" in APP
    assert ">TIP</i>" in APP
    assert "✓</i>" not in APP[APP.index("function renderResults()") : APP.index("function wireResultsFilters()")]
    assert "opacity:.34!important" in CSS


def test_results_use_separate_model_odds_actual_columns_and_projection_odds():
    assert "<th>Model / BlinQ %</th><th>Kurz</th><th>Skutočne</th>" in APP
    assert "projectionOdds=publication?.odds==null?NaN:Number(publication?.odds)" in APP
    assert "Number.isFinite(projectionOdds)&&projectionOdds>1?projectionOdds.toFixed(2):'—'" in APP
    assert "if(tab==='games'||tab==='sets')return ['#',time,tournament,match,prediction,odds,projection,confidence]" in APP
    assert "if(tab==='ace'||tab==='double_faults')return ['#',time,tournament,match,prediction,odds,projection,confidence]" in APP


def test_exact_match_total_parser_requires_two_sided_real_market():
    payload = {
        "markets": [
            {"marketName": "Total games won", "choiceName": "Over 20.5", "decimalOdds": 1.91},
            {"marketName": "Total games won", "choiceName": "Under 20.5", "decimalOdds": 1.88},
            {"marketName": "Player 1 total games", "choiceName": "Over 10.5", "decimalOdds": 1.70},
        ]
    }
    rows = extract_match_total_odds(payload, "games")
    assert rows == [{"line": 20.5, "market_name": "Total games won", "over": 1.91, "under": 1.88}]
    assert extract_match_total_odds(payload, "sets") == []


def test_aces_price_parser_rejects_player_over_under_but_accepts_most_aces():
    bad = {
        "rows": [
            {"marketName": "Player A Total Aces", "choiceName": "Over 4.5", "decimalOdds": 1.80},
            {"marketName": "Player A Total Aces", "choiceName": "Under 4.5", "decimalOdds": 1.95},
        ]
    }
    assert extract_player_superiority_odds(bad, "aces", "Player A", "Player B") is None
    good = {
        "rows": [
            {"marketName": "Most Aces", "choiceName": "Player A", "decimalOdds": 1.72},
            {"marketName": "Most Aces", "choiceName": "Player B", "decimalOdds": 2.05},
        ]
    }
    parsed = extract_player_superiority_odds(good, "aces", "Player A", "Player B")
    assert parsed and parsed["player1_odds"] == 1.72 and parsed["player2_odds"] == 2.05


def test_compact_provider_payload_preserves_retirement_reason():
    compact = minimize_provider_payload({
        "id": 123,
        "status": {"type": "finished", "description": "Retired"},
        "homeTeam": {"id": 1, "name": "A"},
        "awayTeam": {"id": 2, "name": "B"},
    })
    assert compact["_tbt_termination"]["reason"] == "retired"


def test_legacy_incomplete_final_score_is_void_without_provider_description():
    now = datetime.now(timezone.utc)
    match = MatchRecord(
        match_id="legacy-ret", tour="atp", scheduled_at=now - timedelta(hours=2),
        player1_id="1", player1_name="A", player2_id="2", player2_name="B",
        winner_id="2", status="finished", best_of=None,
        stats={"p1_sets_won": 0, "p2_sets_won": 1, "total_sets": 1, "total_games": 14},
        provider_payload={"status": "finished"},
    )
    assert _match_void_reason(match) == "retired_or_incomplete"


def test_priced_projection_settlement_carries_real_units():
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=2)
    match = MatchRecord(
        match_id="sg-price", tour="atp", scheduled_at=start,
        player1_id="1", player1_name="A", player2_id="2", player2_name="B",
        winner_id="1", status="finished", best_of=3,
        stats={"p1_sets_won": 2, "p2_sets_won": 0, "total_sets": 2, "total_games": 18},
    )
    row = {"market_publications": [{
        "market": "sets", "section": "sets", "selection_id": "sets:under:2.5",
        "selection": "Under 2.5 Sets", "projection": 2.18, "reference_projection": 2.5,
        "odds": 1.80, "price_status": "priced_projection",
        "issued_at": (start - timedelta(hours=1)).isoformat(),
    }]}
    _settle_sg_projection_publications(row, match, now)
    result = row["market_publications"][0]["result"]
    assert result["status"] == "hit"
    assert result["staked_units"] == 1.0
    assert result["return_units"] == 1.8
    assert round(result["profit_units"], 6) == 0.8
