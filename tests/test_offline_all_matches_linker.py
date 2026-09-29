from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tbt.data.history_snapshot import write_year_partition
from tbt.schemas import MatchRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "link_offline_all_matches.py"


FIELDS = [
    "start_date","end_date","location","court_surface","prize_money","currency","year",
    "player_id","player_name","opponent_id","opponent_name","tournament","round",
    "num_sets","sets_won","games_won","games_against","tiebreaks_won","tiebreaks_total",
    "serve_rating","aces","double_faults","first_serve_made","first_serve_attempted",
    "first_serve_points_made","first_serve_points_attempted","second_serve_points_made",
    "second_serve_points_attempted","break_points_saved","break_points_against",
    "service_games_won","return_rating","first_serve_return_points_made",
    "first_serve_return_points_attempted","second_serve_return_points_made",
    "second_serve_return_points_attempted","break_points_made","break_points_attempted",
    "return_games_played","service_points_won","service_points_attempted",
    "return_points_won","return_points_attempted","total_points_won","total_points",
    "duration","player_victory","retirement","seed","won_first_set","doubles",
    "masters","round_num","nation",
]


def canonical(*, match_id="m1", tournament="Kosice Challenger", round_name="Quarter-Finals",
              winner_id="p1", stats=None):
    return MatchRecord(
        match_id=match_id,
        tour="atp",
        scheduled_at=datetime(2012, 6, 15, 12, tzinfo=timezone.utc),
        player1_id="p1",
        player1_name="Aljaz Bedene",
        player2_id="p2",
        player2_name="Arnau Brugues-Davi",
        surface="clay",
        tournament=tournament,
        tournament_id="t1",
        tournament_level="C",
        round_name=round_name,
        winner_id=winner_id,
        status="completed",
        best_of=3,
        stats=stats or {},
        provider_payload={"_tbt_provider_event_id": "1001"},
    )


def source_rows(**overrides):
    a = {
        "start_date":"2012-06-11","end_date":"2012-06-17","location":"Slovakia",
        "court_surface":"Clay","year":"2012","player_id":"aljaz-bedene","player_name":"A. Bedene",
        "opponent_id":"arnau-brugues-davi","opponent_name":"A. Brugues-Davi",
        "tournament":"kosice_challenger","round":"Quarter-Finals","num_sets":"3","sets_won":"2",
        "games_won":"17","games_against":"13","aces":"13","double_faults":"4",
        "first_serve_points_made":"35","first_serve_points_attempted":"43",
        "second_serve_points_made":"22","second_serve_points_attempted":"48",
        "service_points_won":"57","service_points_attempted":"91",
        "return_points_won":"41","return_points_attempted":"94","player_victory":"t",
        "retirement":"f","doubles":"f","masters":"100","round_num":"5",
    }
    b = {
        "start_date":"2012-06-11","end_date":"2012-06-17","location":"Slovakia",
        "court_surface":"Clay","year":"2012","player_id":"arnau-brugues-davi","player_name":"A. Brugues-Davi",
        "opponent_id":"aljaz-bedene","opponent_name":"A. Bedene",
        "tournament":"kosice_challenger","round":"Quarter-Finals","num_sets":"3","sets_won":"1",
        "games_won":"13","games_against":"17","aces":"3","double_faults":"4",
        "first_serve_points_made":"39","first_serve_points_attempted":"62",
        "second_serve_points_made":"14","second_serve_points_attempted":"32",
        "service_points_won":"53","service_points_attempted":"94",
        "return_points_won":"34","return_points_attempted":"91","player_victory":"f",
        "retirement":"f","doubles":"f","masters":"100","round_num":"5",
    }
    for key, value in overrides.items():
        target, field = key.split("__", 1)
        (a if target == "a" else b)[field] = str(value)
    return a, b


def write_source(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_linker(tmp_path: Path, matches, rows):
    history = tmp_path / "history"
    history.mkdir()
    write_year_partition(matches, history, 2012)
    source = tmp_path / "all_matches.csv"
    write_source(source, rows)
    out = tmp_path / "out"
    subprocess.run([
        sys.executable, str(SCRIPT),
        "--history-dir", str(history),
        "--all-matches-csv", str(source),
        "--out-dir", str(out),
    ], cwd=ROOT, check=True)
    report = json.loads((out / "report.json").read_text())
    staged = [json.loads(x) for x in (out / "auto_linked.jsonl").read_text().splitlines() if x.strip()]
    review = [json.loads(x) for x in (out / "review.jsonl").read_text().splitlines() if x.strip()]
    quarantine = [json.loads(x) for x in (out / "quarantine.jsonl").read_text().splitlines() if x.strip()]
    return report, staged, review, quarantine


def test_reciprocal_source_links_inside_tournament_window(tmp_path):
    rows = source_rows()
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], rows)
    assert report["api_requests"] == 0
    assert report["counts"]["paired_source_matches"] == 1
    assert report["counts"]["identity_linked"] == 1
    assert report["counts"]["staged_matches"] == 1
    assert not review
    assert not quarantine
    stats = staged[0]["incoming_stats"]
    assert stats["p1_aces"] == 13
    assert stats["p2_aces"] == 3
    assert stats["p1_service_points_won"] == 57 / 91
    assert stats["p1_return_points_won"] == 41 / 94
    assert stats["p2_service_points_won"] == 53 / 94
    assert stats["p2_return_points_won"] == 34 / 91


def test_single_perspective_is_quarantined(tmp_path):
    a, _ = source_rows()
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], [a])
    assert not staged
    assert not review
    assert report["counts"]["non_reciprocal_groups"] == 1
    assert quarantine[0]["reason"] == "non_reciprocal_group"


def test_winner_conflict_fails_closed(tmp_path):
    rows = source_rows()
    report, staged, review, quarantine = run_linker(
        tmp_path, [canonical(winner_id="p2")], rows
    )
    assert not staged
    assert not quarantine
    assert report["counts"]["weak_evidence"] == 1
    assert "winner_conflict" in review[0]["evidence"]


def test_round_conflict_fails_closed(tmp_path):
    rows = source_rows()
    report, staged, review, _ = run_linker(
        tmp_path, [canonical(round_name="Semi-Finals")], rows
    )
    assert not staged
    assert report["counts"]["weak_evidence"] == 1
    assert "round_conflict" in review[0]["evidence"]


def test_canonical_stat_conflict_is_quarantined(tmp_path):
    rows = source_rows()
    report, staged, _, quarantine = run_linker(
        tmp_path, [canonical(stats={"p1_aces": 99.0})], rows
    )
    assert not staged
    assert report["counts"]["stat_conflict_matches"] == 1
    assert quarantine[-1]["reason"] == "stat_conflict"


def test_doubles_are_excluded_before_pairing(tmp_path):
    a, b = source_rows(a__doubles="t", b__doubles="t")
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], [a, b])
    assert not staged
    assert not review
    assert not quarantine
    assert report["counts"]["doubles_rows"] == 2
