from pathlib import Path


def test_rapidapi_runtime_import_does_not_eagerly_require_history_stack():
    source = Path("api/tbt/providers/rapidapi.py").read_text(encoding="utf-8")
    assert "from ..data.history_snapshot import merge_matches" in source
    # It must live inside the lazy helper, not at module import level.
    prefix = source.split("def _merge_matches", 1)[0]
    assert "history_snapshot" not in prefix


def test_runtime_requirements_intentionally_exclude_training_stack():
    runtime = Path("api/requirements.txt").read_text(encoding="utf-8").lower()
    train = Path("api/requirements-train.txt").read_text(encoding="utf-8").lower()
    assert "pandas" not in runtime
    assert "pyarrow" not in runtime
    assert "pandas" in train
    assert "pyarrow" in train
