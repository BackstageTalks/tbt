from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.schemas import MatchRecord
from tbt.services.projection_odds import extract_match_total_odds, enrich_projection_odds
from tbt.services.score_enrichment import ScoreEnricher

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
SG_SCRIPT = (ROOT / "scripts/enrich_sg_history.py").read_text(encoding="utf-8")


def test_total_games_line_accepts_provider_choice_group():
    payload = {
        "markets": [
            {"marketName": "Total games won", "choiceName": "Over", "choiceGroup": "20.5", "decimalOdds": 1.91},
            {"marketName": "Total games won", "choiceName": "Under", "choiceGroup": "20.5", "decimalOdds": 1.88},
        ]
    }
    assert extract_match_total_odds(payload, "games") == [
        {"line": 20.5, "market_name": "Total games won", "over": 1.91, "under": 1.88}
    ]


def test_projection_odds_attach_real_total_games_price_and_report_reason():
    class Provider:
        def event_odds(self, event_id, provider_id=1):
            assert event_id == "123"
            return {
                "markets": [
                    {"marketName": "Total games won", "choiceName": "Over", "choiceGroup": "20.5", "decimalOdds": 1.91},
                    {"marketName": "Total games won", "choiceName": "Under", "choiceGroup": "20.5", "decimalOdds": 1.88},
                ]
            }

    sg = [{
        "event_id": "123", "market": "games", "projection": 23.3,
        "reference_projection": 20.6, "projection_direction": "high",
        "selection_id": "games:high", "selection": "Over 20.6 Games",
    }]
    ace, updated, report = enrich_projection_odds(Provider(), [], sg, max_events=10, provider_id=1)
    assert ace == []
    assert updated[0]["odds"] == 1.91
    assert updated[0]["selection"] == "Over 20.5 Games"
    assert updated[0]["price_status"] == "priced_projection"
    assert report["priced_cards"]["games"] == 1
    assert report["unpriced_reasons"]["games"]["priced"] == 1
    assert report["observed_market_names_top40"]["Total games won"] == 2


def test_missing_projection_odds_render_as_dash_not_zero():
    assert "projectionOdds=publication?.odds==null?NaN:Number(publication?.odds)" in APP
    assert "Number.isFinite(projectionOdds)&&projectionOdds>1?projectionOdds.toFixed(2):'—'" in APP


def test_score_enricher_persists_identity_mismatch_and_does_not_repeat_provider_call(tmp_path):
    class Provider:
        def __init__(self):
            self.calls = 0
        def _get(self, path, enrichment=True):
            self.calls += 1
            return {"event": {
                "id": 999, "status": {"type": "finished"},
                "homeTeam": {"id": 77, "name": "Wrong A"},
                "awayTeam": {"id": 88, "name": "Wrong B"},
            }}

    now = datetime.now(timezone.utc)
    match = MatchRecord(
        match_id="mismatch", tour="atp", scheduled_at=now - timedelta(days=2),
        player1_id="1", player1_name="A", player2_id="2", player2_name="B",
        winner_id="1", status="finished", best_of=3,
        provider_payload={"_tbt_provider_event_id": "999"},
    )
    provider = Provider()
    enricher = ScoreEnricher(provider, tmp_path / "cache.sqlite")
    try:
        assert enricher.enrich(match) == "identity_mismatch"
        assert match.provider_payload["_tbt_score"]["status"] == "identity_mismatch"
        assert match.provider_payload["_tbt_event_identity"]["expected_player_ids"] == ["1", "2"]
        assert provider.calls == 1
        assert enricher.enrich(match) == "cached_identity_mismatch"
        assert provider.calls == 1
    finally:
        enricher.close()


def test_sg_batch_distinguishes_identity_mismatch_from_provider_transport_errors():
    assert '"identity_mismatch",' in SG_SCRIPT
    assert 'report["provider_error_429"]' in SG_SCRIPT
    assert 'report["provider_error_http_4xx"]' in SG_SCRIPT
    assert 'report["provider_error_transport_or_5xx"]' in SG_SCRIPT
