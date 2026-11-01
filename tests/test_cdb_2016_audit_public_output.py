"""Public-facing controls for the read-only 2016 post-import CDB audit."""

from pathlib import Path


WORKFLOW = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
            / "tennisapi-2016-cdb-native-audit.yml")


def test_public_cdb_2016_audit_excludes_player_and_match_rows():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"exact_claims":hits' not in text
    assert '"nearby_wimbledon_candidates":nearby[:40]' not in text
    assert '"private_player_or_match_ids_exposed":False' in text
    assert "audit-2016/native-identity-report.json" in text


def test_postimport_audit_checks_actual_persisted_partition_and_total():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "verified_window(" in text
    assert 'int(years["2016"]["rows"]) != len(df)' in text
    assert "canonical_total=sum(int(meta" in text
    assert "canonical_total < 1003037" in text
    assert "CDB_SNAPSHOT_STABLE_AFTER_READBACK" in text
    assert 'if _remote_lock("BackstageTalks/tbt-data") is not None:' in text
    assert "cdb_writes" in text


def test_2016_audit_waits_without_stealing_live_cdb_writer_lock():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "timeout-minutes: 90" in text
    assert 'while _remote_lock("BackstageTalks/tbt-data") is not None:' in text
    assert "deadline=time.monotonic()+60*60" in text
    assert "time.sleep(30)" in text
    assert "fail closed" in text
    assert "CDB_WRITER_LOCK_ABSENT" in text
    # Unrelated years can vary; only witnessed canonical partitions are required.
    assert '"2016" not in years or "2026" not in years' in text
    assert "len(years)<70" not in text
