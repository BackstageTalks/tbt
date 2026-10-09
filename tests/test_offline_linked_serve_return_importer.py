from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tbt.data.history_snapshot import write_year_partition, load_partitions
from tbt.schemas import MatchRecord

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_offline_linked_serve_return.py"


def match(stats=None):
    return MatchRecord(
        match_id="m1", tour="atp",
        scheduled_at=datetime(2024,1,5,12,tzinfo=timezone.utc),
        player1_id="p1", player1_name="Roman Safiullin",
        player2_id="p2", player2_name="Matteo Arnaldi",
        surface="hard", tournament="Brisbane", tournament_id="t1",
        tournament_level="A", round_name="QF",
        winner_id="p1", status="completed", best_of=3,
        stats=stats or {}, provider_payload={}
    )


def signature(m):
    return {
        "tour":"atp","scheduled_date_utc":"2024-01-05",
        "player1_id":"p1","player1_name":"Roman Safiullin",
        "player2_id":"p2","player2_name":"Matteo Arnaldi",
        "surface":"hard","tournament":"Brisbane","round_name":"QF","winner_id":"p1",
    }


def run(tmp_path, row, existing=None):
    history=tmp_path/"history"; history.mkdir()
    m=match(existing)
    write_year_partition([m],history,2024)
    stage=tmp_path/"stage.jsonl"; stage.write_text(json.dumps(row)+"\n")
    out=tmp_path/"out"
    subprocess.run([sys.executable,str(SCRIPT),"--stage",str(stage),"--history-dir",str(history),"--out-dir",str(out)],cwd=ROOT,check=True)
    return json.loads((out/"report.json").read_text()), [json.loads(x) for x in (out/"review.jsonl").read_text().splitlines() if x]


def base_row(m=None):
    m=m or match()
    return {
        "schema":1,"match_id":"m1","canonical":signature(m),
        "incoming_stats":{
            "p1_service_points_won":0.68,"p1_return_points_won":0.38,
            "p2_service_points_won":0.62,"p2_return_points_won":0.32,
        },
        "sources":[{"source":"test"}],"import_ready":True,
    }


def test_dry_run_accepts_identity_stable_quality_update(tmp_path):
    report, review=run(tmp_path,base_row())
    assert report["counts"]["updated"]==1
    assert report["quality_ready_added"]==1
    assert report["local_partitions_written"] is False
    assert report["api_requests"]==0
    assert not review


def test_identity_change_fails_closed(tmp_path):
    row=base_row(); row["canonical"]["tournament"]="Wrong"
    report, review=run(tmp_path,row)
    assert report["counts"]["identity_changed"]==1
    assert review[0]["reason"]=="identity_changed"


def test_existing_stat_conflict_fails_closed(tmp_path):
    report, review=run(tmp_path,base_row(),existing={"p1_service_points_won":0.9})
    assert report["counts"]["stat_conflicts"]==1
    assert "p1_service_points_won" in review[0]["keys"]

def test_accepts_bounded_rich_charting_rates(tmp_path):
    row=base_row()
    row["incoming_stats"].update({
        "p1_first_strike_serve_win":0.44,
        "p2_first_strike_serve_win":0.36,
        "p1_return_in_play_rate":0.88,
        "p2_return_in_play_rate":0.79,
        "p1_return_deep_rate":0.62,
        "p2_return_deep_rate":0.51,
        "p1_break_point_serve_win":0.67,
        "p2_break_point_serve_win":0.55,
        "p1_break_point_return_win":0.45,
        "p2_break_point_return_win":0.35,
        "p1_net_points_win":0.71,
        "p2_net_points_win":0.58,
        "p1_attacking_points_rate":0.56,
        "p2_attacking_points_rate":0.43,
        "p1_unforced_error_rate":0.22,
        "p2_unforced_error_rate":0.31,
    })
    report, review=run(tmp_path,row)
    assert report["counts"]["updated"]==1
    assert not review


def test_rejects_out_of_range_rich_charting_rate(tmp_path):
    row=base_row()
    row["incoming_stats"]["p1_return_deep_rate"]=1.2
    report, review=run(tmp_path,row)
    assert report["counts"]["invalid_stats"]==1
    assert review[0]["reason"]=="invalid_stats"
    assert "p1_return_deep_rate" in review[0]["keys"]



def test_pit_quarantined_pbpx_archives_only_private_metadata_without_stats_leakage(tmp_path):
    observed_on = datetime(2016, 5, 5, tzinfo=timezone.utc)
    tournament_start = datetime(2016, 5, 2, 12, tzinfo=timezone.utc)
    m = match({"p1_service_points_won": 0.62})
    m.match_id = "hist-js:atp:trusted-event"
    m.scheduled_at = tournament_start
    m.tournament = "Madrid"
    m.round_name = "R16"
    m.surface = "clay"
    history = tmp_path / "history"
    history.mkdir()
    write_year_partition([m], history, 2016)
    from scripts.import_offline_linked_serve_return import _signature

    stats = {
        f"{side}_{field}": float(2 if field in {"aces", "double_faults"} else 0.6)
        for side in ("p1", "p2")
        for field in ("service_points_won", "return_points_won", "aces", "double_faults")
    }
    marker = {
        "schema": 1, "source": "tennisvisuals_validated_pointbypoint",
        "source_ref": "a" * 40,
        "source_file": "ATP_Singles_pbpx.csv", "source_row": 12,
        "source_date": observed_on.date().isoformat(),
        "status": "pit_quarantined_unconsumed", "score_validated": True,
        "stats": stats,
    }
    stage = {
        "schema": 1, "match_id": m.match_id, "canonical": _signature(m),
        "incoming_stats": {}, "baseline_stats": dict(m.stats),
        "delayed_observation": marker, "import_ready": True,
        "quality_ready_added": False,
    }
    stagefile = tmp_path / "stage.jsonl"
    stagefile.write_text(json.dumps(stage) + "\n")
    out = tmp_path / "out"
    subprocess.run([
        sys.executable, str(SCRIPT), "--stage", str(stagefile),
        "--history-dir", str(history), "--out-dir", str(out),
        "--write-partitions", "--write-history-dir", str(history),
    ], cwd=ROOT, check=True)
    report = json.loads((out / "report.json").read_text())
    assert report["counts"]["pit_observations_added"] == 1
    assert report["counts"].get("stat_fields_added", 0) == 0
    assert report["quality_ready_added"] == 0
    assert report["changed_years"] == [2016]
    rows = load_partitions(history)
    assert len(rows) == 1
    assert rows[0].scheduled_at == tournament_start
    assert rows[0].winner_id == m.winner_id
    assert rows[0].stats == m.stats
    assert rows[0].provider_payload["_tbt_pbpx_delayed_observation"] == marker


def test_pit_delayed_observation_fails_closed_on_wrong_source_date(tmp_path):
    m = match()
    history = tmp_path / "history"
    history.mkdir()
    write_year_partition([m], history, 2024)
    from scripts.import_offline_linked_serve_return import _signature
    row = {
        "schema": 1, "match_id": m.match_id, "canonical": _signature(m),
        "incoming_stats": {}, "baseline_stats": dict(m.stats),
        "delayed_observation": {
            "schema": 1, "source": "tennisvisuals_validated_pointbypoint",
            "source_ref": "a" * 40, "source_file": "ATP_Singles_pbpx.csv",
            "source_row": 2, "source_date": "2024-01-06",
            "status": "pit_quarantined_unconsumed",
            "score_validated": True, "stats": {},
        },
        "import_ready": True,
    }
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(row) + "\n")
    out = tmp_path / "out"
    subprocess.run([
        sys.executable, str(SCRIPT), "--stage", str(stage),
        "--history-dir", str(history), "--out-dir", str(out),
    ], cwd=ROOT, check=True)
    report = json.loads((out / "report.json").read_text())
    assert report["counts"]["invalid_delayed_observation"] == 1
    assert report["quality_ready_added"] == 0
