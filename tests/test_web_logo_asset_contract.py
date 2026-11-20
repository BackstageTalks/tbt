"""BlinQ logo transport contract: compact raster, valid SVG, valid WebP payload."""
from __future__ import annotations

import base64
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_logo_is_compact_and_preserves_public_svg_semantics():
    raw = (ROOT / "web/assets/blinq_logo.svg").read_bytes()
    assert len(raw) < 100_000, "Logo regression: the old embedded PNG was 229 kB"
    content = raw.decode("utf-8")
    root = ET.fromstring(content)
    assert root.get("viewBox") == "0 0 900 450"
    assert root.get("role") == "img"
    assert root.get("aria-label") == "BlinQ"
    images = list(root.iter("{http://www.w3.org/2000/svg}image"))
    assert len(images) == 1
    src = images[0].get("href") or images[0].get("{http://www.w3.org/1999/xlink}href")
    assert src and src.startswith("data:image/webp;base64,")
    assert images[0].get("width") == "900"
    assert images[0].get("height") == "450"

    payload = base64.b64decode(src.split(",", 1)[1], validate=True)
    assert payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    assert int.from_bytes(payload[4:8], "little") + 8 == len(payload)
    assert len(payload) < 70_000, "Logo transport budget regressed"
