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


def canonical(*, match_id="m1", tournament="Brisbane", round_name="QF", stats=None, provider_event_id="1001"):
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
        provider_payload={"_tbt_provider_event_id": provider_event_id},
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


def run_linker(tmp_path: Path, matches: list[MatchRecord], source: Path | None = None, charting: Path | None = None, kaggle_hwaitt: Path | None = None):
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
    if kaggle_hwaitt is not None:
        cmd += ["--kaggle-hwaitt-csv", str(kaggle_hwaitt)]
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
    # Missing round removes the only discriminator between two same-day
    # canonical meetings; the linker must refuse to guess.
    write_source(source, round="")
    first = canonical(match_id="m1", round_name="QF")
    second = canonical(match_id="m2", round_name="SF", provider_event_id="1002")
    report, staged, review, _ = run_linker(tmp_path, [first, second], source=source)
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
    specialist = {
        "charting-m-stats-ServeBasics.csv": """match_id,player,row,pts,pts_won,aces,unret,forced_err,pts_won_lte_3_shots,wide,body,t
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,Total,73,50,9,4,6,30,20,5,48
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,Total,69,43,3,3,4,20,18,3,48
""",
        "charting-m-stats-ReturnOutcomes.csv": """match_id,player,row,pts,pts_won,returnable,returnable_won,in_play,in_play_won,winners,total_shots
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,Total,69,26,60,24,54,22,2,300
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,Total,73,23,64,21,48,18,1,280
""",
        "charting-m-stats-ReturnDepth.csv": """match_id,player,row,returnable,shallow,deep,very_deep,unforced,err_net,err_deep,err_wide,err_wide_deep
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,Total,60,15,42,10,3,0,1,2,0
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,Total,64,22,36,8,6,1,2,3,0
""",
        "charting-m-stats-NetPoints.csv": """match_id,player,row,net_pts,pts_won,net_winner,induced_forced,net_unforced,passed_at_net,passing_shot_induced_forced,total_shots
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,NetPoints,20,15,8,5,1,1,0,90
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,NetPoints,10,5,2,2,2,1,0,60
""",
        "charting-m-stats-KeyPointsServe.csv": """match_id,player,row,pts,pts_won,first_in,aces,svc_winners,rally_winners,rally_forced,unforced,dfs
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,BP,10,7,7,1,2,1,2,1,1
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,BP,8,4,5,0,1,1,1,2,1
""",
        "charting-m-stats-KeyPointsReturn.csv": """match_id,player,row,pts,pts_won,rally_winners,rally_forced,unforced
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,BPO,8,4,1,1,1
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,BPO,10,3,0,1,2
""",
        "charting-m-stats-ShotTypes.csv": """match_id,player,row,shots,pt_ending,winners,induced_forced,unforced,serve_return,shots_in_pts_won,shots_in_pts_lost
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Roman Safiullin,Total,280,50,20,15,15,60,120,160
20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi,Matteo Arnaldi,Total,270,50,12,10,28,64,100,170
""",
    }
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("charting-m-matches.csv", matches_csv)
        zf.writestr("charting-m-stats-Overview.csv", overview_csv)
        for name, payload in specialist.items():
            zf.writestr(name, payload)
    report, staged, review, quarantine = run_linker(tmp_path, [canonical()], charting=zpath)
    assert report["counts"]["identity_linked"] == 1
    assert len(staged) == 1
    assert not review
    assert not quarantine
    stats = staged[0]["incoming_stats"]
    assert stats["p1_return_points_won"] == 26 / 69
    assert stats["p1_first_strike_serve_win"] == 30 / 73
    assert stats["p2_first_strike_serve_win"] == 20 / 69
    assert stats["p1_return_in_play_rate"] == 54 / 60
    assert stats["p1_return_deep_rate"] == 42 / 60
    assert stats["p1_break_point_serve_win"] == 7 / 10
    assert stats["p1_break_point_return_win"] == 4 / 8
    assert stats["p1_net_points_win"] == 15 / 20
    assert stats["p1_attacking_points_rate"] == 35 / 50
    assert stats["p1_unforced_error_rate"] == 15 / 50


def _minimal_charting_zip(path: Path, *, tournament="Brisbane", round_name="QF"):
    mid = "20240105-M-Brisbane-QF-Roman_Safiullin-Matteo_Arnaldi"
    matches_csv = f"""match_id,Player 1,Player 2,Pl 1 hand,Pl 2 hand,Date,Tournament,Round,Time,Court,Surface,Umpire,Best of,Final TB?,Charted by
{mid},Roman Safiullin,Matteo Arnaldi,R,R,20240105,{tournament},{round_name},,,Hard,,3,A,test
"""
    overview_csv = f"""match_id,player,set,serve_pts,aces,dfs,first_in,first_won,second_in,second_won,bk_pts,bp_saved,return_pts,return_pts_won,winners,winners_fh,winners_bh,unforced,unforced_fh,unforced_bh
{mid},Roman Safiullin,Total,73,9,3,43,36,30,14,3,2,69,26,0,0,0,0,0,0
{mid},Matteo Arnaldi,Total,69,3,2,37,27,32,16,8,5,73,23,0,0,0,0,0,0
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("charting-m-matches.csv", matches_csv)
        zf.writestr("charting-m-stats-Overview.csv", overview_csv)


def test_charting_allows_tournament_alias_with_three_other_corroborators(tmp_path):
    zpath = tmp_path / "charting.zip"
    _minimal_charting_zip(zpath, tournament="Brisbane International")
    report, staged, review, quarantine = run_linker(
        tmp_path, [canonical(tournament="Brisbane")], charting=zpath
    )
    assert report["counts"]["identity_linked"] == 1
    assert len(staged) == 1
    assert not review
    assert not quarantine
    assert "tournament_mismatch" in staged[0]["sources"][0]["evidence"]


def test_charting_round_conflict_still_fails_closed(tmp_path):
    zpath = tmp_path / "charting.zip"
    _minimal_charting_zip(zpath, tournament="Brisbane", round_name="SF")
    report, staged, review, quarantine = run_linker(
        tmp_path, [canonical(tournament="Brisbane", round_name="QF")], charting=zpath
    )
    assert not staged
    assert not quarantine
    assert report["counts"]["weak_evidence"] == 1
    assert review[0]["reason"] == "weak_evidence"
    assert "round_conflict" in review[0]["evidence"]


def write_hwaitt_source(path: Path, **overrides):
    fields = [
        "ID", "GameD", "TName", "Name_1", "Name_2", "GRes_CUR_1", "Surface",
        "Aces_1", "DoubleFaults_1", "Serve1st_1", "ServesTotal_1",
        "Serve1stWon_1", "Serve2ndWon_1", "ReceivingPointsWon_1",
        "ReceivingPointsTotal_1", "BreakPointsConverted_1", "BreakPointsTotal_1",
        "Aces_2", "DoubleFaults_2", "Serve1st_2", "ServesTotal_2",
        "Serve1stWon_2", "Serve2ndWon_2", "ReceivingPointsWon_2",
        "ReceivingPointsTotal_2", "BreakPointsConverted_2", "BreakPointsTotal_2",
        "Aces_A_1", "Aces_L5_1", "Result_CUR_1",
    ]
    row = {
        "ID": "1", "GameD": "2024-01-05", "TName": "Brisbane",
        "Name_1": "Roman Safiullin", "Name_2": "Matteo Arnaldi",
        "GRes_CUR_1": "1.0", "Surface": "1.0",
        "Aces_1": "9", "DoubleFaults_1": "3", "Serve1st_1": "43",
        "ServesTotal_1": "73", "Serve1stWon_1": "36", "Serve2ndWon_1": "14",
        "ReceivingPointsWon_1": "26", "ReceivingPointsTotal_1": "69",
        "BreakPointsConverted_1": "3", "BreakPointsTotal_1": "8",
        "Aces_2": "3", "DoubleFaults_2": "2", "Serve1st_2": "37",
        "ServesTotal_2": "69", "Serve1stWon_2": "27", "Serve2ndWon_2": "16",
        "ReceivingPointsWon_2": "23", "ReceivingPointsTotal_2": "73",
        "BreakPointsConverted_2": "3", "BreakPointsTotal_2": "10",
        # Deliberately dangerous/derived fields: parser must ignore all of them.
        "Aces_A_1": "999", "Aces_L5_1": "888", "Result_CUR_1": "7-6 6-2",
    }
    row.update({k: str(v) for k, v in overrides.items()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def test_hwaitt_raw_match_stats_link_without_derived_feature_leakage(tmp_path):
    source = tmp_path / "atp.csv"
    write_hwaitt_source(source)
    report, staged, review, quarantine = run_linker(
        tmp_path, [canonical()], kaggle_hwaitt=source
    )
    assert report["api_requests"] == 0
    assert report["counts"]["identity_linked"] == 1
    assert report["counts"]["staged_matches"] == 1
    assert report["quality_ready_projected_added"] == 1
    assert not review
    assert not quarantine

    stats = staged[0]["incoming_stats"]
    assert stats["p1_aces"] == 9.0
    assert stats["p1_double_faults"] == 3.0
    assert stats["p1_first_serve_win"] == 36 / 43
    assert stats["p1_second_serve_win"] == 14 / (73 - 43)
    assert stats["p1_service_points_won"] == (36 + 14) / 73
    assert stats["p1_return_points_won"] == 26 / 69
    assert stats["p1_break_point_return_win"] == 3 / 8
    assert stats["p2_return_points_won"] == 23 / 73
    assert 999.0 not in stats.values()
    assert 888.0 not in stats.values()
    assert all("_A" not in key and "_L5" not in key and "CUR" not in key for key in stats)


def test_hwaitt_winner_conflict_fails_closed(tmp_path):
    source = tmp_path / "atp.csv"
    write_hwaitt_source(source, GRes_CUR_1="0.0")
    report, staged, review, quarantine = run_linker(
        tmp_path, [canonical()], kaggle_hwaitt=source
    )
    assert not staged
    assert not quarantine
    assert report["counts"]["weak_evidence"] == 1
    assert "winner_conflict" in review[0]["evidence"]
