from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from tbt.schemas import MatchRecord
from tbt.services.engine import _betting_metrics, _match_void_reason, _settle_match_winner_publications

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
RELEASE = json.loads((ROOT / "web" / "release.json").read_text(encoding="utf-8"))
UI = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_r50_release_and_header_upgrade_cleanup():
    assert RELEASE["patch"] == UI["ui_patch"] == "736-r52"
    assert 'content="736-r52"' in INDEX
    assert 'id="topUpgradeLabel">Upgrade</span></button>' in INDEX
    assert 'label.textContent=lcopy(\'Upgrade\',\'Upgrade\',\'Upgrade\')' in APP
    assert "BlinQ runtime patch 7.3.6-r52" in CSS
    assert "border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important" in CSS


def test_upgrade_modal_removes_generic_duplicate_badges_and_copy():
    # The requirement pill remains only for a genuinely locked section.
    assert "lockedContext?`<span class=\"upgrade-requires-pill is-required-context\"" in APP
    assert "upgrade-account-role" not in APP
    assert "More predictions, more data and premium functions in one BlinQ workspace." not in APP
    assert "Every higher level adds more data, functions and access." not in APP
    assert "const summaryLabel=isAdmin?'ADMIN':(currentLabel||'FREE');" in APP


def test_results_match_winner_highlights_selected_player_not_row_order():
    assert "function resultPickIdentity(publication,row)" in APP
    assert "const p1Selected=selectable&&pickIdentity.side==='p1';" in APP
    assert "const p2Selected=selectable&&pickIdentity.side==='p2';" in APP
    assert "results-match-player${p1Class}${integrityClass}" in APP
    assert "results-opponent${p2Class}${integrityClass}" in APP
    assert "results-pick-mark" in APP
    assert ".results-match-player.is-pick strong" in CSS
    assert ".results-opponent.is-pick b" in CSS


def _retired_match():
    now = datetime.now(timezone.utc)
    return MatchRecord(
        match_id="m-ret",
        tour="atp",
        scheduled_at=now - timedelta(hours=2),
        player1_id="10",
        player1_name="Player A",
        player2_id="20",
        player2_name="Player B",
        winner_id="20",
        status="finished",
        provider_payload={
            "id": 123456,
            "status": {"type": "finished", "description": "Retired"},
            "winnerCode": 2,
        },
    )


def test_finished_provider_row_with_retired_description_is_void_not_loss():
    match = _retired_match()
    assert _match_void_reason(match) == "retired"
    issued = (match.scheduled_at - timedelta(hours=1)).isoformat()
    row = {
        "market_publications": [
            {
                "market": "match_winner",
                "section": "top_daily",
                "selection_id": "10",
                "selection": "Player A",
                "odds": 1.67,
                "issued_at": issued,
            }
        ]
    }
    _settle_match_winner_publications(row, match, datetime.now(timezone.utc))
    result = row["market_publications"][0]["result"]
    assert result["status"] == "void"
    assert result["reason"] == "retired"
    assert result["correct"] is None
    assert result["profit_units"] == 0.0


def test_void_match_winner_does_not_enter_betting_hit_rate_denominator():
    void_pub = {
        "market": "match_winner",
        "section": "top_daily",
        "odds": 1.67,
        "result": {"status": "void", "reason": "retired", "correct": None, "profit_units": 0.0, "staked_units": 0.0},
    }
    win_pub = {
        "market": "match_winner",
        "section": "top_daily",
        "odds": 1.50,
        "result": {"correct": True, "profit_units": 0.5, "staked_units": 1.0},
    }
    metrics = _betting_metrics([void_pub, win_pub])
    assert metrics["n"] == 1
    assert metrics["wins"] == 1
    assert metrics["losses"] == 0
    assert metrics["voids"] == 1
    assert metrics["hit_rate"] == 1.0
