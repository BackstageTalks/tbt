from pathlib import Path
import json

from tbt.services.projection_odds import (
    extract_match_total_odds,
    extract_player_superiority_odds,
    enrich_projection_odds,
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
PIPELINE = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")
RELEASE = json.loads((ROOT / "web/release.json").read_text(encoding="utf-8"))
UI = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))


def test_r54_identity_and_projection_odds_budget():
    assert RELEASE["patch"] == UI["ui_patch"] == "736-r55"
    assert "projection_odds_cap = max(0, int(args.market_odds_max_events or 0))" in PIPELINE
    assert "min(40" not in PIPELINE[PIPELINE.index("projection_odds_report = {}") : PIPELINE.index("if projection_odds_cap")]


def test_projection_odds_null_is_never_rendered_as_zero():
    assert "const odds=firstFinite(row?.odds,row?.betting?.odds);" in APP
    assert "Number.isFinite(odds)&&odds>1?odds.toFixed(2):'—'" in APP
    projection_slice = APP[APP.index("function dailyHubRow") : APP.index("function dailyHubLockedRow")]
    assert "const odds=Number(row?.odds);" not in projection_slice


def test_see_all_projection_rows_share_one_eight_column_contract():
    assert "if(tab==='see_all')return ['#',time,tournament,match,prediction,odds,lcopy('MODEL','MODEL','MODEL'),''];" in APP
    assert "function hubSeeAllProjectionHtml" in APP
    projection_slice = APP[APP.index("function dailyHubRow") : APP.index("function dailyHubLockedRow")]
    assert "hub-seeall-model-cell" in projection_slice
    assert "hub-seeall-model" in CSS


def test_player_photos_use_layered_local_fallback_in_predictions_and_results():
    assert "const versionedPlayerAsset =" in APP
    assert "meta[name=\"blinq-web-patch\"]" in APP
    assert "function playerAvatarParts" in APP
    assert "data-player-fallback" in APP
    assert "class=\"player-avatar-photo\" data-player-photo" in APP
    assert "function applyPlayerAvatarHost" in APP
    assert "const p1Photo=playerPhotoSource(r,p1,'player1');" in APP
    assert "const p1Photo=playerPhotoSource(row,p1,'player1')" in APP
    assert ".layered-player-avatar .player-avatar-fallback" in CSS
    assert ".layered-player-avatar .player-avatar-initials" in CSS


def test_total_sets_alias_and_nested_market_name_are_supported():
    payload = {
        "markets": [{
            "name": "Total number of sets",
            "choices": [
                {"choiceName": "Over", "choiceGroup": "2.5", "decimalOdds": 2.18},
                {"choiceName": "Under", "choiceGroup": "2.5", "decimalOdds": 1.67},
            ],
        }]
    }
    assert extract_match_total_odds(payload, "sets") == [
        {"line": 2.5, "market_name": "Total number of sets", "over": 2.18, "under": 1.67}
    ]


def test_aces_and_double_faults_superiority_aliases_attach_real_prices():
    aces = {
        "markets": [{"marketName": "Who will serve more aces?", "choices": [
            {"choiceName": "Alpha One", "decimalOdds": 1.72},
            {"choiceName": "Beta Two", "decimalOdds": 2.05},
        ]}]
    }
    dfs = {
        "markets": [{"marketName": "Player to make more double faults", "choices": [
            {"choiceName": "Alpha One", "decimalOdds": 1.88},
            {"choiceName": "Beta Two", "decimalOdds": 1.84},
        ]}]
    }
    assert extract_player_superiority_odds(aces, "aces", "Alpha One", "Beta Two")["player1_odds"] == 1.72
    assert extract_player_superiority_odds(dfs, "double_faults", "Alpha One", "Beta Two")["player2_odds"] == 1.84


def test_enricher_can_price_all_four_projection_categories_when_provider_exposes_them():
    payloads = {
        "a": {"markets": [{"marketName": "Who will serve more aces?", "choices": [
            {"choiceName": "Alpha One", "decimalOdds": 1.72}, {"choiceName": "Beta Two", "decimalOdds": 2.05},
        ]}]},
        "d": {"markets": [{"marketName": "Most Double Faults", "choices": [
            {"choiceName": "Gamma Three", "decimalOdds": 1.80}, {"choiceName": "Delta Four", "decimalOdds": 2.00},
        ]}]},
        "g": {"markets": [{"marketName": "Total games won", "choices": [
            {"choiceName": "Over", "choiceGroup": "20.5", "decimalOdds": 1.91}, {"choiceName": "Under", "choiceGroup": "20.5", "decimalOdds": 1.88},
        ]}]},
        "s": {"markets": [{"name": "Total number of sets", "choices": [
            {"choiceName": "Over", "choiceGroup": "2.5", "decimalOdds": 2.18}, {"choiceName": "Under", "choiceGroup": "2.5", "decimalOdds": 1.67},
        ]}]},
    }

    class Provider:
        def event_odds(self, event_id, provider_id=1):
            return payloads[event_id]

    ace = [
        {"event_id": "a", "market": "aces", "player1": {"id": "1", "name": "Alpha One"}, "player2": {"id": "2", "name": "Beta Two"}, "selection_id": "1"},
        {"event_id": "d", "market": "double_faults", "player1": {"id": "3", "name": "Gamma Three"}, "player2": {"id": "4", "name": "Delta Four"}, "selection_id": "4"},
    ]
    sg = [
        {"event_id": "g", "market": "games", "projection": 23.3, "reference_projection": 20.6, "projection_direction": "high", "selection_id": "games:high"},
        {"event_id": "s", "market": "sets", "projection": 2.18, "reference_projection": 2.5, "projection_direction": "low", "selection_id": "sets:under:2.5"},
    ]
    ace_out, sg_out, report = enrich_projection_odds(Provider(), ace, sg, max_events=10, provider_id=1)
    assert ace_out[0]["odds"] == 1.72
    assert ace_out[1]["odds"] == 2.00
    assert sg_out[0]["odds"] == 1.91
    assert sg_out[1]["odds"] == 1.67
    assert report["priced_cards"] == {"aces": 1, "double_faults": 1, "sets": 1, "games": 1}
