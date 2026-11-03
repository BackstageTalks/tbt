"""Only test-proven constraints are permitted into the Azure runtime lock."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "api"


def _pins(filename):
    text = (ROOT / filename).read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    pairs = {}
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*==[0-9][A-Za-z0-9_.-]*", line), line
        name, version = line.split("==", 1)
        key = name.casefold().replace("_", "-").replace(".", "-")
        assert key not in pairs, key
        pairs[key] = version
    return pairs


def test_runtime_dependency_constraints_snapshot_is_pinned_and_used():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "-c requirements-runtime.lock"
    runtime = _pins("requirements-runtime.lock")
    assert len(runtime) >= 50
    for package in ("azure-functions", "httpx", "azure-data-tables",
                    "firebase-admin", "azure-storage-blob", "pywebpush"):
        assert package in runtime and text.count(package) == 1
    assert runtime["azure-functions"] == "1.26.0"
    assert runtime["firebase-admin"] == "7.7.0"
    assert runtime["pywebpush"] == "2.5.0"
    assert runtime["azure-storage-blob"] == "12.31.1"


def test_training_constraints_snapshot_does_not_replace_runtime_guard():
    text = (ROOT / "requirements-train.txt").read_text(encoding="utf-8")
    assert text.splitlines()[:2] == [
        "-c requirements-train.lock",
        "-r requirements.txt",
    ]
    training = _pins("requirements-train.lock")
    for package in ("numpy", "pandas", "scikit-learn", "pyarrow", "pytest"):
        assert package in training
    assert training["scikit-learn"] == "1.9.0"
    assert not set(training) & set(_pins("requirements-runtime.lock"))
