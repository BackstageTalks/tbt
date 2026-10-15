"""Fail closed: count import may run on read-only request, but never publish unlicensed source."""
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / ".github/workflows/cdb-sackmann-counts-guarded.yml"

def test_explicit_commercial_or_verified_noncommercial_rights_for_write():
    text = WF.read_text()
    assert 'source_rights_disposition // empty' in text
    assert 'explicit_commercial_permission' in text
    assert 'verified_noncommercial_use' in text
    assert 'source_rights_evidence_ref // empty' in text
    assert 'Jeff Sackmann / Tennis Abstract' in text
    assert 'steps.request.outputs.mode == \'write\'' in text

def test_one_shot_readonly_push_stage_does_not_require_write_request():
    text=WF.read_text()
    assert 'get("mode") == "write"' in text
    assert 'steps.request.outputs.mode == \'dry-run\'' in text
    assert 'Source canonical manifest changed' in text or 'Source canonical manifest' in text
    assert 'cdb_global_writer_lock.py acquire' in text
    assert 'cdb_global_writer_lock.py release --if-held' in text
    assert 'COMMITTED CDB INTEGER BP COUNTS VERIFIED:' in text
    assert 'BP_INTEGER_COUNTS_REMOTE_SECOND_RUN_ZERO_DELTA_PASS' in text
