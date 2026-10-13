"""Offline invariants for the complete per-run immutable model-input backup."""
import json
from pathlib import Path

import pytest

from scripts import guarded_candidate_backup as backup


def test_training_will_not_start_without_verified_certificate(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "CERT", tmp_path / "nonexistent.json")
    with pytest.raises(RuntimeError, match="Missing independently verified"):
        backup.validate_certificate()


def test_mismatched_run_certificate_refused(tmp_path, monkeypatch):
    cert = tmp_path / "certificate.json"
    cert.write_text(json.dumps({"schema": 1, "status": "PREPARED", "run_id": "elsewhere"}))
    monkeypatch.setattr(backup, "CERT", cert)
    monkeypatch.setattr(backup, "verify_job_identity", lambda: None)
    with pytest.raises(RuntimeError, match="run-bound"):
        backup.validate_certificate()


def test_any_mutated_input_hash_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BASE", tmp_path)
    source = tmp_path / "history"
    source.mkdir()
    (source / "history-2026.parquet").write_bytes(b"original")
    path = source / "history-2026.parquet"
    snapshot = [{"path": "history/history-2026.parquet",
                 "asset": "frozen__history__history-2026.parquet",
                 "sha256": backup.sha(path), "bytes": path.stat().st_size}]
    backup.ensure_unchanged(snapshot)
    path.write_bytes(b"changed!")
    with pytest.raises(RuntimeError, match="input changed"):
        backup.ensure_unchanged(snapshot)


def test_candidate_release_is_run_scoped_and_never_overwrites_old_candidate():
    main = (Path(__file__).resolve().parents[1] / "scripts/pipeline.py").read_text()
    source = (Path(__file__).resolve().parents[1] / "scripts/guarded_candidate_backup.py").read_text()
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/protected-frozen-cdb-candidate.yml").read_text()
    assert 'training_certificate["candidate_tag"]' in main
    assert 'blinq-candidate-frozen-' in source
    assert 'blinq-full-training-backup-' in source
    assert "independent-readback" in source
    assert "verify_restore(" in source
    assert "candidate.upload_bundle" in main
    assert "production.upload_bundle" in main  # Existing branch still behind uncallable --promote
    assert "if args.promote:" in main
    assert "--promote" not in wf.split("Fit separate candidate only if immutable backup gate passed")[1].split("Write private aggregate candidate")[0].replace("# No --promote.", "")
    assert "cancel-in-progress: false" in wf
    assert "release --if-held" in wf


def test_inventory_includes_all_canonical_years_and_privately_backed_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BASE", tmp_path)
    for group in backup.SUBDIRS:
        (tmp_path / group).mkdir(parents=True, exist_ok=True)
    for year in range(1976, 2026):
        (tmp_path / "history" / f"history-{year}.parquet").write_bytes(b"example")
    mandatory = (
        "history/history_manifest.json", "history/_tbt_bundle_manifest.json",
        "production/model.joblib", "production/_tbt_bundle_manifest.json",
        "rank-feature-inputs/source/sackmann-atp-rankings.tar.gz",
        "rank-feature-inputs/source/sackmann-wta-rankings.tar.gz",
        "rank-feature-inputs/profiles/player_profiles.json",
        "training-backup/source-code/blinq-git-source.tar.gz",
    )
    for rel in mandatory:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"notempty")
    found = backup.inventory()
    assert len(found) == 50 + len(mandatory)
    assert len({x["asset"] for x in found}) == len(found)
    (tmp_path / "rank-feature-inputs/profiles/player_profiles.json").unlink()
    with pytest.raises(RuntimeError, match="Missing mandatory"):
        backup.inventory()
