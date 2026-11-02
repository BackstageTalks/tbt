"""Synthetic end-to-end CDB Inbox -> strict native linker -> exact write -> readback."""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.cdb_inbox_adapter import run as normalize
from scripts.cdb_inbox_stage import run as stage
from scripts.offline_exact_cdb_write import verify_persisted
from tbt.data.history_snapshot import write_year_partition, load_snapshot
from tbt.schemas import MatchRecord

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("start_only", "start_offset", "expected_window"), [
    (False, 0, False), (True, 0, True), (True, 1, True), (True, 5, True),
])
def test_real_native_linker_exact_writer_and_readback(tmp_path, start_only, start_offset, expected_window):
    before, after, source = (tmp_path / n for n in ("before", "after", "source"))
    before.mkdir()
    source.mkdir()
    original = MatchRecord(
        match_id="inbox-example-2026", tour="atp",
        scheduled_at=datetime(2026, 10, 17, 12, tzinfo=timezone.utc),
        player1_id="canonical-alpha", player1_name="Alpha One",
        player2_id="canonical-beta", player2_name="Beta Two",
        surface="hard", tournament="Vienna", tournament_id="vienna-2026",
        tournament_level="A", round_name="QF",
        winner_id="canonical-alpha", status="completed",
        best_of=3, stats={}, provider_payload={}
    )
    write_year_partition([original], before, 2026)
    with (source / "atp_test.csv").open("w", encoding="utf-8", newline="") as handle:
        row = {
            "tour": "ATP",
            "match_date": "" if start_only else "2026-10-17",
            "tourney_date": f"2026-10-{17 - start_offset:02d}" if start_only else "",
            "tournament": "Vienna",
            "winner": "Alpha One", "loser": "Beta Two", "round": "QF",
            # Provider-side IDs are preserved as provenance, never CDB IDs.
            "winner_id": "external-100", "loser_id": "external-200",
            "surface": "hard", "best_of": 3,
            "w_svpt": 70, "w_1stIn": 40, "w_1stWon": 30, "w_2ndWon": 14,
            "w_ace": 5, "w_df": 2, "w_bpSaved": 4, "w_bpFaced": 6,
            "l_svpt": 60, "l_1stIn": 35, "l_1stWon": 25, "l_2ndWon": 11,
            "l_ace": 3, "l_df": 1, "l_bpSaved": 2, "l_bpFaced": 5,
        }
        writer = csv.DictWriter(handle, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    report = normalize(source, tmp_path / "normalized")
    assert report["counts"]["normalized_rows"] == 1

    linked = stage(tmp_path / "normalized/report.json", before, tmp_path / "link")
    assert linked["eligible_matches"] == 1, linked
    assert linked["eligible_new_values"] >= 8

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "api"), str(ROOT / "scripts"), str(ROOT), environment.get("PYTHONPATH", "")]
    )
    importer = ROOT / "scripts/import_offline_linked_serve_return.py"
    subprocess.run(
        [sys.executable, str(importer), "--stage", str(tmp_path / "link/eligible.jsonl"),
         "--history-dir", str(before), "--out-dir", str(tmp_path / "dryrun")],
        check=True, capture_output=True, text=True, env=environment, timeout=60
    )
    dry = json.loads((tmp_path / "dryrun/report.json").read_text())
    assert dry["production_mutated"] is False
    assert dry["counts"]["updated"] == 1

    shutil.copytree(before, after)
    subprocess.run(
        [sys.executable, str(importer), "--stage", str(tmp_path / "link/eligible.jsonl"),
         "--history-dir", str(after), "--out-dir", str(tmp_path / "local"),
         "--write-partitions", "--write-history-dir", str(after), "--exact-stats-only"],
        check=True, capture_output=True, text=True, env=environment, timeout=60
    )
    staged = [json.loads(x) for x in (tmp_path / "link/eligible.jsonl").read_text().splitlines()]
    evidence = staged[0]["sources"][0]
    assert ("date_tournament_window" in evidence["evidence"]) is expected_window
    assert ("date_exact" in evidence["evidence"]) is (not start_only)
    assert evidence["source_player_a_id"] == "external-100"
    assert evidence["source_player_b_id"] == "external-200"
    assert evidence["source_id_namespace"] == "drive-unverified"
    assert staged[0]["canonical"]["player1_id"] == "canonical-alpha"
    assert staged[0]["canonical"]["player2_id"] == "canonical-beta"
    assert "verified_player_id_pair" not in evidence["evidence"]
    proof = verify_persisted(before, after, staged, [2026])
    assert proof["enriched_matches"] == 1
    assert proof["added_values"] == linked["eligible_new_values"]
    assert proof["existing_values_overwritten"] == 0
    original_stored = load_snapshot(before / "history-2026.parquet")[0]
    after_stored = load_snapshot(after / "history-2026.parquet")[0]
    assert original_stored.stats == {}
    assert len(after_stored.stats) == linked["eligible_new_values"]
    assert after_stored.match_id == original_stored.match_id
    assert (after_stored.player1_id, after_stored.player2_id) == (
        original_stored.player1_id, original_stored.player2_id
    )
    assert after_stored.provider_payload == original_stored.provider_payload


def test_known_provider_collisions_are_excluded_from_linking_but_preserved_on_exact_write(tmp_path):
    before, after, source = (tmp_path / n for n in ("before", "after", "source"))
    before.mkdir()
    source.mkdir()
    def row(mid, a, b, provider):
        return MatchRecord(
            match_id=mid, tour="atp",
            scheduled_at=datetime(2026, 10, 17, 12, tzinfo=timezone.utc),
            player1_id=a.lower(), player1_name=a,
            player2_id=b.lower(), player2_name=b,
            surface="hard", tournament="Vienna", tournament_id="vienna-2026",
            tournament_level="A", round_name="QF", winner_id=a.lower(),
            status="completed", best_of=3, stats={},
            provider_payload={"_tbt_provider_event_id": provider},
        )
    original = row("safe-2026", "Alpha One", "Beta Two", "provider-good")
    collision_a = row("collision-a", "Gamma Three", "Delta Four", "provider-collision")
    collision_b = row("collision-b", "Epsilon Five", "Zeta Six", "provider-collision")
    write_year_partition([original, collision_a, collision_b], before, 2026)
    with (source / "atp_test.csv").open("w", newline="", encoding="utf-8") as stream:
        data = {
            "tour": "ATP", "match_date": "2026-10-17", "tournament": "Vienna",
            "winner": "Alpha One", "loser": "Beta Two", "round": "QF",
            "surface": "hard", "best_of": 3,
            "w_svpt": 70, "w_1stIn": 40, "w_1stWon": 30, "w_2ndWon": 14,
            "w_ace": 5, "w_df": 2, "w_bpSaved": 4, "w_bpFaced": 6,
            "l_svpt": 60, "l_1stIn": 35, "l_1stWon": 25, "l_2ndWon": 11,
            "l_ace": 3, "l_df": 1, "l_bpSaved": 2, "l_bpFaced": 5,
        }
        writer = csv.DictWriter(stream, fieldnames=list(data))
        writer.writeheader()
        writer.writerow(data)
    normalized = normalize(source, tmp_path / "normalized")
    assert normalized["counts"]["normalized_rows"] == 1
    with pytest.raises(RuntimeError, match="quarantine"):
        stage(tmp_path / "normalized/report.json", before, tmp_path / "blocked")
    with pytest.raises(RuntimeError, match="quarantine"):
        stage(tmp_path / "normalized/report.json", before, tmp_path / "wrong",
              expected_provider_quarantine=3)
    linked = stage(tmp_path / "normalized/report.json", before, tmp_path / "linked",
                   expected_provider_quarantine=2)
    assert linked["excluded_ambiguous_provider_rows"] == 2
    assert linked["full_canonical_rows"] == 3
    assert linked["eligible_matches"] == 1
    stage_file = tmp_path / "linked/eligible.jsonl"
    staged = [json.loads(x) for x in stage_file.read_text().splitlines() if x.strip()]
    assert len(staged) == 1 and staged[0]["match_id"] == "safe-2026"
    importer = ROOT / "scripts/import_offline_linked_serve_return.py"
    common = ["--isolate-provider-collisions", "--expected-provider-quarantine", "2",
              "--stage", str(stage_file)]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "api"), str(ROOT / "scripts"), str(ROOT), env.get("PYTHONPATH", "")]
    )
    dry = tmp_path / "dry"
    subprocess.run([sys.executable, str(importer), *common,
                    "--history-dir", str(before), "--out-dir", str(dry)],
                   cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    dry_report = json.loads((dry / "report.json").read_text())
    assert dry_report["counts"]["stat_fields_added"] == linked["eligible_new_values"]
    assert dry_report["excluded_ambiguous_provider_rows"] == 2
    shutil.copytree(before, after)
    subprocess.run([sys.executable, str(importer), *common,
                    "--history-dir", str(after), "--out-dir", str(tmp_path / "write"),
                    "--write-partitions", "--write-history-dir", str(after),
                    "--exact-stats-only"],
                   cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    verified = verify_persisted(before, after, staged, [2026])
    assert verified["canonical_rows_checked"] == 3
    assert verified["enriched_matches"] == 1
    assert verified["added_values"] == linked["eligible_new_values"]
    assert verified["existing_values_overwritten"] == 0
    left = {m.match_id: m for m in load_snapshot(before / "history-2026.parquet")}
    right = {m.match_id: m for m in load_snapshot(after / "history-2026.parquet")}
    for mid in ("collision-a", "collision-b"):
        assert left[mid].to_storage_dict() == right[mid].to_storage_dict()
