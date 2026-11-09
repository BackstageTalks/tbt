from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from audit_cdb_sackmann_native_bp_lineage import reject_reasons


def test_native_eight_digit_date_is_not_reported_as_malformed():
    path = Path("atp_matches_2020.csv")
    row = {"tourney_date": "20200106", "winner_id": "1", "loser_id": "2",
           "winner_name": "Alpha", "loser_name": "Beta"}
    match = SimpleNamespace(tour="atp", is_completed=True, status="completed",
        scheduled_at=datetime(2020, 1, 6, tzinfo=timezone.utc), match_id="hist-js:fixture",
        player1_id="hist-js:atp:1", player2_id="hist-js:atp:2", winner_id="hist-js:atp:1",
        player1_name="Alpha", player2_name="Beta", provider_payload={
            "_tbt_statistics": {"source": "jeff_sackmann_match_snapshot:" + path.name},
            "_tbt_provider_event_id": "hist-js:fixture", "_tbt_source_category_name": "historical_main"})
    assert reject_reasons(match, row, "atp", "main", path) == []
    assert reject_reasons(match, {**row, "tourney_date": "20200107"}, "atp", "main", path) == ["date_differs"]
    assert reject_reasons(match, {**row, "tourney_date": "2020-01-06"}, "atp", "main", path) == ["source_date_invalid"]
