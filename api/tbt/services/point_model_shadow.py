"""Read a precomputed point-model snapshot, independently of the serving feed."""
from functools import lru_cache
import json
import os
from pathlib import Path

FLAG = "BLINQ_POINT_MODEL_SHADOW"
SNAPSHOT = "BLINQ_POINT_MODEL_SHADOW_FILE"


def enabled():
    return os.getenv(FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=2)
def _read(path, signature):
    with path.open(encoding="utf-8") as source:
        opened = os.fstat(source.fileno())
        if _signature(opened) != signature:
            raise OSError("Shadow file was replaced while opening")
        payload = json.load(source)
    if not isinstance(payload, dict) or payload.get("schema") != 3 or payload.get("candidate") != "blinq-candidate-frozen-45525499354-1" or not isinstance(payload.get("cards"), dict):
        raise ValueError("Invalid shadow snapshot")
    return payload["cards"]


def _signature(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def shadow_card(match_id):
    path = os.getenv(SNAPSHOT, "").strip()
    if not path:
        raise FileNotFoundError("Shadow snapshot path unavailable")
    path = Path(path).resolve(strict=True)
    try:
        return _read(path, _signature(path.stat())).get(match_id)
    except OSError:
        # An operator may atomically rotate a serving file during this request.
        return _read(path, _signature(path.stat())).get(match_id)
