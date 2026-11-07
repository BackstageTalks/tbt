"""Offline contracts for provider sample research; zero network and CDB writes."""
from datetime import datetime, timezone
import json

import pytest

from scripts.audit_tennisapi_prediction_signals import (
    audit, load_samples, pre_match_signals, reconcile, source_event,
)


def event(*, eid=101, when="2023-01-18T10:00:00+00:00",
          home=11, away=22, tour="atp", duration=9000, seed="3"):
    stamp = int(datetime.fromisoformat(when).timestamp())
    row = {
        "id": eid, "startTimestamp": stamp, "winnerCode": 1,
        "tournament": {
            "category": {"slug": tour},
            "uniqueTournament": {"id": 2363},
        },
        "season": {"id": 48186},
        "homeTeam": {"id": home, "type": 1},
        "awayTeam": {"id": away, "type": 1},
        "homeScore": {"current": 2}, "awayScore": {"current": 0},
        "status": {"type": "finished"},
        "roundInfo": {"name": "Round of 64"},
        "homeTeamSeed": seed,
    }
    if duration is not None:
        row["time"] = {"period1": duration // 2,
                       "period2": duration - duration // 2,
                       "currentPeriodStartTimestamp": stamp + duration}
    return row


def test_seed_and_duration_are_only_research_rows():
    raw = event()
    row, state = source_event(raw)
    assert state == "eligible_source_row"
    assert row["home_seed"] == 3
    assert row["away_seed"] is None
    assert row["duration_seconds"] == 9000
    assert row["source_prematch_seed_temporal_attestation"] is False
    signals = pre_match_signals([row])
    assert signals[0]["duration_7d_known_both"] is False
    assert signals[0]["recorded_duration_7d_home_seconds"] is None
    assert signals[0]["eligible_for_model_training"] is False


def test_utc_same_day_results_never_feed_other_same_day_match():
    a, _ = source_event(event(eid=1, when="2023-01-18T09:00:00+00:00",
                              home=11, away=22, duration=3000))
    b, _ = source_event(event(eid=2, when="2023-01-18T17:00:00+00:00",
                              home=11, away=33, duration=4000))
    c, _ = source_event(event(eid=3, when="2023-01-19T11:00:00+00:00",
                              home=11, away=22, duration=6000))
    result = {x["event_id"]: x for x in pre_match_signals([a, b, c])}
    assert result[1]["recorded_duration_7d_home_seconds"] is None
    assert result[2]["recorded_duration_7d_home_seconds"] is None
    assert result[3]["recorded_duration_7d_home_seconds"] == 7000
    assert result[3]["recorded_duration_7d_away_seconds"] == 3000
    assert result[3]["duration_7d_advantage_home_seconds"] == -4000
    assert result[3]["historical_duration_window_complete"] is False


def test_finished_winner_mismatch_rejected():
    x = event()
    x["winnerCode"] = 2
    assert source_event(x)[1] == "winner_score_conflict"


@pytest.mark.parametrize("field, replacement", [
    ("status", {"type": "canceled"}),
    ("homeTeam", {"id": 11, "type": 2}),
    ("awayTeam", {"id": 11, "type": 1}),
    ("winnerCode", True),
    ("id", True),
])
def test_invalid_or_doubles_never_become_signals(field, replacement):
    x = event()
    x[field] = replacement
    assert source_event(x)[0] is None


def test_non_atp_wta_out_of_scope():
    assert source_event(event(tour="itf-men"))[1] == "out_of_scope_tour"


def test_monthly_seed_is_not_asof_evidence_and_duration_missing():
    x = event(duration=None)
    x["homeTeamSeed"] = "Q"
    x["awayTeamSeed"] = "15"
    row, status = source_event(x)
    assert status == "eligible_source_row"
    assert row["home_seed"] is None
    assert row["away_seed"] == 15
    assert row["duration_seconds"] is None


def test_identical_event_duplicates_are_deduped_and_conflicts_quarantined(tmp_path):
    a = tmp_path / "one.json"
    b = tmp_path / "two.json"
    a.write_text(json.dumps({"events": [event(eid=1), event(eid=2)]}))
    b.write_text(json.dumps({"events": [event(eid=1),
                                        event(eid=2, home=123)]}))
    rows, report = load_samples([a, b])
    assert [r["event_id"] for r in rows] == [1]
    assert report["counts"]["raw"] == 4
    assert report["counts"]["duplicate_identical_source_event"] == 1
    assert report["counts"]["quarantine_conflicting_native_id"] == 1
    assert report["counts"]["eligible_unique"] == 1


def test_readonly_cdb_overlap_fails_closed_on_identity_mismatch(tmp_path):
    from tbt.schemas import MatchRecord
    x = event(eid=9)
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({"events": [x]}))
    rows, summary = audit([path])
    assert summary["source"]["counts"]["raw"] == 1
    assert summary["reconciliation"]["linked"] is None
    assert summary["model_training_eligible_rows"] == 0
    assert rows[0]["canonical_link_status"] == "not_checked"
    dt = datetime.fromtimestamp(x["startTimestamp"], timezone.utc)
    match = MatchRecord(
        match_id="canonical-1", tour="atp", scheduled_at=dt,
        player1_id="11", player1_name="A",
        player2_id="22", player2_name="B",
        provider_payload={"id": 9},
    )
    linked_rows, report = audit([path], history=[match])
    assert report["reconciliation"]["linked"] == 1
    assert report["reconciliation"]["potential_unlinked"] == 0
    assert linked_rows[0]["canonical_match_id"] == "canonical-1"
    assert linked_rows[0]["eligible_for_model_training"] is False
    opposite = MatchRecord(
        match_id="canonical-2", tour="atp", scheduled_at=dt,
        player1_id="11", player1_name="A",
        player2_id="44", player2_name="B",
        provider_payload={"id": 9},
    )
    _, bad = audit([path], history=[opposite])
    assert bad["reconciliation"]["conflicts"] == 1
    _, ambiguous = audit([path], history=[match, opposite])
    assert ambiguous["reconciliation"]["conflicts"] == 1


def test_bad_files_are_rejected_without_model_or_cdb_mutations(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({"garbage": []}))
    with pytest.raises(ValueError):
        audit([path])
    path.write_text(json.dumps({"events": [event(eid=4)]}))
    alias = tmp_path / "symlink.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError):
        audit([alias])



def test_monthly_index_is_readonly_and_never_marks_any_day_complete(tmp_path):
    from scripts.audit_tennisapi_prediction_signals import check_monthly_tournaments
    row, _ = source_event(event(eid=12, when="2023-01-18T10:00:00+00:00"))
    calendar = tmp_path / "index.json"
    calendar.write_text(json.dumps({"dailyUniqueTournaments": [
        {"date": "2023-01-18", "uniqueTournamentIds": [2363, 999]},
        {"date": "2023-01-19", "uniqueTournamentIds": [2363]},
    ]}))
    summary = check_monthly_tournaments([row], calendar)
    assert summary["matched_source_events"] == 1
    assert summary["unique_tournament_ids"] == 2
    assert summary["verified_complete_days"] == 0
    assert summary["skip_daily_category_import"] is False
    calendar.write_text(json.dumps({"dailyUniqueTournaments": [
        {"date": "2023-01-18", "uniqueTournamentIds": [999]},
    ]}))
    summary = check_monthly_tournaments([row], calendar)
    assert summary["missing_tournament_in_index"] == 1
    assert summary["verified_complete_days"] == 0


def test_monthly_index_duplicate_day_and_id_quarantined(tmp_path):
    from scripts.audit_tennisapi_prediction_signals import check_monthly_tournaments
    calendar = tmp_path / "index.json"
    for days in (
        [{"date": "2026-07-01", "uniqueTournamentIds": [3, 3]}],
        [{"date": "2026-07-01", "uniqueTournamentIds": [3]},
         {"date": "2026-07-01", "uniqueTournamentIds": [4]}],
        [{"date": "2026-07-01", "uniqueTournamentIds": [3]},
         {"date": "2026-08-01", "uniqueTournamentIds": [3]}],
    ):
        calendar.write_text(json.dumps({"dailyUniqueTournaments": days}))
        with pytest.raises(ValueError):
            check_monthly_tournaments([], calendar)
