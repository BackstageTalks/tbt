from __future__ import annotations

import csv
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from tbt.data.history_snapshot import write_year_partition
from tbt.schemas import MatchRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "link_offline_serve_return.py"


def canonical(*, match_id="m1", tournament="Brisbane", round_name="QF", stats=None):
    return MatchRecord(
        match_id=match_id,
        tour="atp",
        scheduled_at=datetime(2024, 1, 5, 12, tzinfo=timezone.utc),
        player1_id="p1",
        player1_name="Roman Safiullin",
        player2_id="p2",
        player2_name="Matteo Arnaldi",
        surface="hard",
        tournament=tournament,
        tournament_id="t1",
        tournament_level="A",
        round_name=round_name,
        winner_id="p1",
        status="completed",
        best_of=3,
        stats=stats or {},
        provider_payload={"_tbt_provider_event_id": "1001"},
    )


def write_source(path: Path, **overrides):
    fields = [
        "tourney_id","tourney_name","surface","tourney_date","match_num",
        "winner_name","loser_name","score","best_of","round",
        "w_ace","w_df","w_svpt","w_1stIn","w_1stWon","w_2ndWon",
        "l_ace","l_df","l_svpt","l_1stIn","l_1stWon","l_2ndWon",
    ]
    row = {
        "tourney_id":"2024-0339","tourney_name":"Brisbane","surface":"Hard",
        "tourney_date":"20240105","match_num":"296",
        "winner_name":"Roman Safiullin","loser_name":"Matteo Arnaldi",
        "score":"7-6(4) 6-2","best_of":"3","round":"QF",
        "w_ace":"9","w_df":"3","w_svpt":"73","w_1stIn":"43","w_1stWon":"36","w_2ndWon":"14",
        "l_ace":"3","l_df":"2","l_svpt":"69","l_1stIn":"37","l_1stWon":"27","l_2ndWon":"16",
    }
    row.update({k:str(v) for k,v in overrides.items()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def run_linker(tmp_path: Path, matches: list[MatchRecord], source: Path | None = None, charting: Path | None = None):
    history = tmp_path / "history"
    history.mkdir()
    write_year_partition(matches, history, 2024)
    out = tmp_path / "out"
    cmd = [
        sys.executable, str(SCRIPT),
        "--history-dir", str(history),
        "--out-dir", str(out),
    ]
    if source is not None:
        cmd += ["--source-csv", str(source)]
    if charting is not None:
        cmd += ["--charting-zip", str(charting)]
    subprocess.run(cmd, cwd=ROOT, check=True)
    report = json.loads((out / "report.json").read_text())
    staged = [json.loads(x) for x in (out / "auto_linked.jsonl").read_text().splitlines() if x.strip()]
    review = [json.loads(x) for x in (out / "review.jsonl").read_text().splitlines() if x.strip()]
    quarantine = [json.loads(x) for x in (out / "quarantine.jsonl").read_text().splitlines() if x.strip()]
    return report, staged, review, quarantine


def test_exact_sackmann_row_links_and_projects_quality(tmp_path):
    source = tmp_path / "atp_matches_2024.csv"
    write_source(source)
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], source=source)
    assert report["api_requests"] == 0
    assert report["production_mutated"] is False
    assert report["counts"]["identity_linked"] == 1
    assert report["counts"]["staged_matches"] == 1
    assert report["quality_ready_projected_added"] == 1
    assert not review
    assert not quarantine
    row = staged[0]
    assert row["match_id"] == "m1"
    assert row["incoming_stats"]["p1_service_points_won"] == (36 + 14) / 73
    assert row["incoming_stats"]["p1_return_points_won"] == (69 - 27 - 16) / 69
    assert row["incoming_stats"]["p2_service_points_won"] == (27 + 16) / 69
    assert row["incoming_stats"]["p2_return_points_won"] == (73 - 36 - 14) / 73


def test_winner_conflict_is_not_auto_linked(tmp_path):
    source = tmp_path / "atp_matches_2024.csv"
    write_source(source, winner_name="Matteo Arnaldi", loser_name="Roman Safiullin")
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], source=source)
    assert not staged
    assert report["counts"]["weak_evidence"] == 1
    assert review[0]["reason"] == "weak_evidence"
    assert "winner_conflict" in review[0]["evidence"]
    assert not quarantine


def test_duplicate_canonical_candidate_fails_ambiguous(tmp_path):
    source = tmp_path / "atp_matches_2024.csv"
    write_source(source)
    second = canonical(match_id="m2")
    report, staged, review, _ = run_linker(tmp_path, [canonical(), second], source=source)
    assert not staged
    assert report["counts"]["ambiguous"] == 1
    assert review[0]["reason"] == "ambiguous"
    assert set(review[0]["candidate_match_ids"]) == {"m1", "m2"}


def test_existing_canonical_stat_conflict_is_quarantined(tmp_path):
    source = tmp_path / "atp_matches_2024.csv"
    write_source(source)
    match = canonical(stats={"p1_aces": 99.0})
    report, staged, _, quarantine = run_linker(tmp_path, [match], source=source)
    assert not staged
    assert report["counts"]["stat_conflict_matches"] == 1
    assert quarantine[0]["match_id"] == "m1"
    assert any(x["key"] == "p1_aces" for x in quarantine[0]["conflicts"])


def test_charting_requires_exact_event_metadata_and_links(tmp_path):
    zpath = tmp_path / "tennis_project_old.zip"
    matches_csv = """match_id,Player 1,Player 2,Pl 1 hand,Pl 2 hand,Date,Tournament,Round,Time,Court,Surface,Umpire,Best of,Final TB?,Charted by
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,Matteo Arnaldi,R,R,20240105,Brisbane,QF,,,Hard,,3,A,test
"""
    overview_csv = """match_id,player,set,serve_pts,aces,dfs,first_in,first_won,second_in,second_won,bk_pts,bp_saved,return_pts,return_pts_won,winners,winners_fh,winners_bh,unforced,unforced_fh,unforced_bh
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,Total,73,9,3,43,36,30,14,3,2,69,26,0,0,0,0,0,0
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,Total,69,3,2,37,27,32,16,8,5,73,23,0,0,0,0,0,0
"""
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("charting-m-matches.csv", matches_csv)
        zf.writestr("charting-m-stats-Overview.csv", overview_csv)
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], charting=zpath)
    assert report["counts"]["identity_linked"] == 1
    assert len(staged) == 1
    assert not review
    assert not quarantine
    assert staged[0]["incoming_stats"]["p1_return_points_won"] == 26 / 69
