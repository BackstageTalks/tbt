import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_champion_rollback import BUNDLE, MANIFEST, hash_file, reference_frame, verify_complete_bundle


def build(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "files": {}}
    for name in BUNDLE:
        raw = (name + "::test payload").encode()
        (path / name).write_bytes(raw)
        manifest["files"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (path / MANIFEST).write_text(json.dumps(manifest))
    return manifest


def test_manifest_proves_full_bundle(tmp_path):
    build(tmp_path)
    checked = verify_complete_bundle(tmp_path)
    assert set(checked) == {*BUNDLE, MANIFEST}
    assert checked["model.joblib"]["sha256"] == hash_file(tmp_path / "model.joblib")


@pytest.mark.parametrize("kind", ["missing", "changed", "extra", "manifest_invalid"])
def test_bundle_verification_fails_closed(tmp_path, kind):
    manifest = build(tmp_path)
    if kind == "missing":
        (tmp_path / "model.joblib").unlink()
    elif kind == "changed":
        (tmp_path / "training_report.json").write_text("tampered")
    elif kind == "extra":
        manifest["files"]["unknown"] = {}
        (tmp_path / MANIFEST).write_text(json.dumps(manifest))
    else:
        (tmp_path / MANIFEST).write_text('{"schema":0}')
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_complete_bundle(tmp_path)


def test_restore_reference_probes_are_reproducible_and_outcome_free():
    names = ["elo_probability", "season_yelo_probability", "rank_known_both", "tour_atp"]
    frame = reference_frame(names)
    assert list(frame.columns) == names and len(frame) == 3
    assert all(0 < x < 1 for x in frame["elo_probability"])
    assert frame["rank_known_both"].tolist() == [1.0] * 3
    assert not any("target" in x or "winner" in x for x in frame.columns)


def test_workflow_cannot_write_production_model_or_clobber_backup():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/champion-rollback-rehearsal.yml").read_text()
    assert "gh release create" in wf
    assert "gh release download tbt-model-production-v1" in wf
    assert "gh release upload" not in wf and "--clobber" not in wf
    assert "gh release edit" not in wf and "tbt-model-production-v1 --" not in wf
    assert "verify_champion_rollback.py" in wf
