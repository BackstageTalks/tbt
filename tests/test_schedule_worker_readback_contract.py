from pathlib import Path


def test_worker_requires_durable_schedule_readback_after_upsert():
    source = (Path(__file__).resolve().parents[1] / "api" / "function_app.py").read_text()
    block = source.split("def internal_match_status_worker(req):", 1)[1].split(
        "def internal_account_inactivity_worker(", 1
    )[0]
    writer = block.index("saved = save_match_status_snapshot(snapshot)")
    reader = block.index("persisted = load_match_status_snapshot()")
    guard = block.index('persisted.get("schedule_updates") != saved.get("schedule_updates")')
    verified = block.index('saved["schedule_readback_verified"] = True')
    assert writer < reader < guard < verified
    assert 'raise AdminStorageUnavailable("Verified schedule read-back mismatch")' in block
