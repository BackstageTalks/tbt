from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Iterable


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stable_hash(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def deterministic_id(parts: Iterable[Any]) -> str:
    text = "|".join(str(p or "") for p in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip().replace("%", "").replace(",", ".")
        try:
            result = float(text)
        except ValueError:
            return None
        if "%" in value or result > 1.5:
            return result / 100.0
        return result
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


RATE_STAT_SUFFIXES = frozenset({
    "first_serve_win",
    "second_serve_win",
    "service_points_won",
    "ace_rate",
    "return_points_won",
    "break_points_won",
})


def is_rate_stat_field(name: Any) -> bool:
    text = str(name or "").strip().lower()
    if text.startswith("p1_") or text.startswith("p2_"):
        text = text[3:]
    return text in RATE_STAT_SUFFIXES


def normalize_rate(value: Any, *, percent_hint: bool = False) -> float | None:
    """Normalize an explicitly rate-like value without guessing count units.

    Numeric strings and numeric JSON values have identical semantics.
    - 0..1 is accepted as an already-normalized fraction.
    - an explicit trailing '%' is accepted as 0..100 percent.
    - with percent_hint=True, values >1 and <=100 are accepted as percent.
    - values >1 without an explicit percent signal are rejected rather than guessed.
    - missing/invalid/non-finite values remain missing.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None

    explicit_percent = False
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        if text.endswith("%"):
            explicit_percent = True
            text = text[:-1].strip()
        try:
            result = float(text)
        except ValueError:
            return None
    else:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

    if not math.isfinite(result) or result < 0:
        return None

    if explicit_percent:
        return result / 100.0 if result <= 100 else None

    if result <= 1:
        return result

    if percent_hint and result <= 100:
        return result / 100.0

    return None


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_datetime(value: Any) -> datetime:
    """Parse a required provider timestamp without manufacturing a fallback time."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if not math.isfinite(ts):
            raise ValueError(f"Invalid datetime value: {value!r}")
        # Provider timestamps may be seconds or milliseconds.
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(f"Invalid datetime value: {value!r}") from exc
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        dt = None
        for candidate in (text, text.replace(" ", "T", 1)):
            try:
                dt = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
        if dt is None:
            for fmt in (
                "%Y-%m-%d",
                "%d.%m.%Y",
                "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"Invalid datetime value: {value!r}")
    else:
        raise ValueError("Missing datetime value")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_surface(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(token in text for token in ("i.hard", "indoor hard", "indoor")):
        return "indoor_hard"
    if "clay" in text:
        return "clay"
    if "grass" in text:
        return "grass"
    if "carpet" in text:
        return "carpet"
    if "hard" in text or "acrylic" in text:
        return "hard"
    return "unknown"


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def dig(mapping: Any, *path: str) -> Any:
    cur = mapping
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def logit(p: float) -> float:
    p = clamp(p, 1e-6, 1 - 1e-6)
    return math.log(p / (1 - p))
