from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tbt.data.history_snapshot import write_year_partition
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
