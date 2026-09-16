from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_post_deploy_confirmation_imports_without_scientific_dependencies():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(root / "api"), str(root / "scripts")])
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import confirm_prediction_publication"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
