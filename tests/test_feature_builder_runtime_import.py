from pathlib import Path


def test_feature_builder_keeps_pandas_lazy_for_runtime_snapshots():
    source = Path("api/tbt/models/feature_builder.py").read_text(encoding="utf-8")
    prefix = source.split("def build_training_frame", 1)[0]
    assert "import pandas" not in prefix
    method = source.split("def build_training_frame", 1)[1].split("def replay", 1)[0]
    assert "import pandas as pd" in method
