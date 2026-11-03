"""Shared read-only contract for web release assets used by deploy scripts.

Keep the committed source tree unchanged; optimizer and stamper operate on
staging artifacts at deployment time.
"""
from __future__ import annotations

import json
from pathlib import Path

OPTIMIZED_ASSETS = ("app.js", "blinq-app.css")
DEPLOYED_ASSETS = ("blinq-app.css", "app.js", "auth.js", "responsive.js")


def read_release(web: Path) -> dict:
    """Read the existing release manifest; do not synthesize defaults."""
    return json.loads((web / "release.json").read_text(encoding="utf-8"))
