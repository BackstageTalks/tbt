"""Locally calibrated Aces prices are stable across feed, site and Telegram."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ace_working_odds import PRICE_BASIS, working_ace_odds, verified_ace_odds, selected_ace_odds  # noqa: E402
import telegram_daily_results as daily  # noqa: E402


def test_aces_working_prices_are_stable_and_bounded():
    picks = [
        {"market": "aces", "event_id": "match-100", "selection_id": "player-100"},
        {"market": "aces", "event_id": "match-101", "selection_id": "player-101"},
        {"market": "aces", "event_id": "match-102", "selection_id": "player-102"},
    ]
    for pick in picks:
        first = working_ace_odds(pick)
        assert first is not None and 1.60 <= first <= 1.80
        assert round(first, 2) == first
        assert first == working_ace_odds({**pick, "odds": 2.0})
        assert first == working_ace_odds({**pick, "scheduled_at": "2026-12-01T12:00:00Z"})
    assert len({working_ace_odds({"event_id": f"match-{i}", "selection_id": f"p-{i}"})
                for i in range(100)}) >= 14


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_js_and_python_prices_match_across_unicode_picks():
    picks = [
        {"market": "aces", "event_id": "ace-100", "selection_id": "player-a"},
        {"market": "aces", "event_id": "ace-101", "selection_id": "hráč-šíp"},
        {"market": "aces", "event_id": "ace-102", "selection_id": "😃"},
    ]
    program = r"""
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const start=source.indexOf('  function stableAceDisplayOdds(');
const stop=source.indexOf('  function normalizeFeedAceOdds(',start);
if(start<0||stop<0)throw Error('Missing stable ACES calculator');
const context={};vm.createContext(context);vm.runInContext(source.slice(start,stop),context);
const picks=JSON.parse(process.argv[1]);
console.log(JSON.stringify(picks.map(r=>context.stableAceDisplayOdds(r))));
"""
    result = subprocess.run(
        ["node", "-e", program, json.dumps(picks, ensure_ascii=False)],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=20,
    )
    assert json.loads(result.stdout) == [working_ace_odds(p) for p in picks]


def test_telegram_uses_frozen_local_ace_odds_only_with_verified_settlement():
    sent = {
        "event_id": "ace-1", "selection_id": "player-1", "section": "ace",
        "channel": "aces", "market": "aces", "publication_key": "k1",
        "market_line": None, "projection_direction": "",
        "price_basis": PRICE_BASIS,
        "odds": working_ace_odds({"event_id": "ace-1", "selection_id": "player-1"}),
    }
    record = {
        "event_id": "ace-1", "selection_id": "player-1", "section": "ace",
        "market": "aces", "publication_key": "k1",
        "market_line": None, "projection_direction": "", "odds": 2.0,
        "price_status": "projection_only",
        "result": {"runtime_source": "match_status_snapshot", "correct": True},
    }
    success = daily.evaluate(sent, [record])
    assert success["status"] == "won"
    assert success["stake"] == 1
    assert abs(success["units"] - (sent["odds"] - 1)) < 1e-8
    forged = {**sent, "odds": 9.99}
    assert daily.evaluate(forged, [record])["stake"] == 0
    assert daily.evaluate(sent, [])["status"] == "pending"


def test_provider_quote_first_fallback_only_when_not_verified():
    base = {
        "market": "aces", "event_id": "fixture-11", "selection_id": "player-1",
        "price_status": "priced_projection", "odds_contract_version": "ace_df_real_api_v1",
        "provider_id": 2, "odds_source": "propline", "odds_bookmaker": "bookA",
        "captured_at": "2026-11-01T06:45:00Z", "odds": 2.125,
        "price_contract": "player_total_ou", "market_line": 7.5, "ou_side": "over",
    }
    assert verified_ace_odds(base) == 2.125
    assert selected_ace_odds(base) == (2.125, True)
    placeholder = {**base, "odds": 2.0}
    assert verified_ace_odds(placeholder) is None
    assert selected_ace_odds(placeholder) == (
        working_ace_odds(placeholder), False)
    for future in ("2026-11-02T13:00:00Z", "2027-05-02T13:00:00Z"):
        assert selected_ace_odds({**placeholder, "scheduled_at": future}) == (
            working_ace_odds(placeholder), False)
    # A concrete non-placeholder, independently matched API quote still wins.
    assert selected_ace_odds({**base, "odds": 1.93}) == (1.93, True)
    assert selected_ace_odds({**base, "provider_id": 1})[1] is False
    assert selected_ace_odds({**base, "odds_bookmaker": ""})[1] is False
    assert selected_ace_odds({**base, "market_line": float("nan")})[1] is False
    assert selected_ace_odds({**base, "odds_contract_version": ""})[1] is False
    assert selected_ace_odds({**base, "captured_at": ""})[1] is False
    assert selected_ace_odds({**base, "market": "games"})[1] is False
    fallback, is_provider = selected_ace_odds({**base, "odds_source": ""})
    assert not is_provider and 1.60 <= fallback <= 1.80
    assert selected_ace_odds({**base, "odds_source": ""}) == (fallback, False)
    assert verified_ace_odds({**base, "odds_source": "rapidapi", "provider_id": 1}) == 2.125
    assert verified_ace_odds({**base, "odds_source": "moviodds", "provider_id": 3,
                              "odds_bookmaker": "bet365"}) == 2.125


def test_telegram_prices_verified_aces_and_fallback_without_model_changes():
    import telegram_offer_publisher as tg

    base = {
        "market": "aces", "event_id": "fixture-11", "selection_id": "player-1",
        "scheduled_at": "2026-11-01T13:00:00Z",
        "player1": {"id": "player-1", "name": "Sample Player"},
        "player2": {"id": "player-2", "name": "Other Player"},
        "price_status": "priced_projection", "odds_contract_version": "ace_df_real_api_v1",
        "provider_id": 2, "odds_source": "propline", "odds_bookmaker": "bookA",
        "captured_at": "2026-11-01T06:45:00Z", "odds": 2.125,
        "price_contract": "player_total_ou", "market_line": 7.5, "ou_side": "over",
    }
    before = json.dumps(base, sort_keys=True)
    text = tg.fmt(base, "aces", {"show_odds": True})
    assert "2.12" in text or "2.13" in text
    issued = tg.result_reference(base, "aces")
    assert issued["odds"] == 2.125
    assert issued["price_basis"] is None
    assert json.dumps(base, sort_keys=True) == before
    local = {**base, "odds_source": ""}
    price = working_ace_odds(local)
    assert f"{price:.2f}" in tg.fmt(local, "aces", {"show_odds": True})
    local_reference = tg.result_reference(local, "aces")
    assert local_reference["odds"] == price
    assert local_reference["price_basis"] == PRICE_BASIS
    # Even provider-labelled 2.00 remains a placeholder on ALL future days.
    for date in ("2026-11-02T13:00:00Z", "2027-05-02T13:00:00Z"):
        placeholder = {**base, "odds": 2.0, "scheduled_at": date}
        price = working_ace_odds(placeholder)
        assert f"{price:.2f}" in tg.fmt(placeholder, "aces", {"show_odds": True})
        issued = tg.result_reference(placeholder, "aces")
        assert issued["odds"] == price
        assert issued["price_basis"] == PRICE_BASIS
        assert placeholder["odds"] == 2.0
