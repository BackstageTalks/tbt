"""Year-checkpointed point-in-time feature build (bit-identical, faster reruns).

The training frame is a strictly sequential replay: features for a match
depend on every earlier completed match. A full replay of ~1M matches takes
~50 min. Between runs, history usually changes only in the most recent
period, so we persist, per calendar year Y (UTC):

* ``state-Y.pkl``  – the FeatureBuilder state just BEFORE the first match of Y
* ``frame-Y.pkl``  – the feature rows produced for matches of year Y
* ``manifest.json`` – a config fingerprint and, per year, the SHA-256 of every
  completed match that precedes Y (the full prefix, all fields)

On the next run we resume from the latest year whose prefix hash and config
fingerprint still match, reuse the stored rows of earlier years and replay
only the rest. Any change to an older match, to the builder code or to the
profile flags changes the hash/fingerprint, so the build falls back to an
earlier year or a full replay. Year boundaries coincide with the builder's
calendar-day batches, so the result is identical to one full replay
(verified with ``assert_frame_equal(check_exact=True)``).
"""
from __future__ import annotations

from datetime import timezone
from hashlib import sha256
import json
import pickle
from pathlib import Path
from typing import Callable

import pandas as pd

SCHEMA = 1
KEEP_STATES = 3  # states are large; keep only the most recent years


def _config_fingerprint(builder) -> str:
    from . import feature_builder as fb_module
    from .. import schemas as schemas_module
    digest = sha256()
    for module in (fb_module, schemas_module):
        digest.update(Path(module.__file__).read_bytes())
    flags = {k: v for k, v in sorted(vars(builder).items())
             if isinstance(v, (bool, int, float, str))}
    digest.update(json.dumps({"schema": SCHEMA, "flags": flags,
                              "features": list(fb_module.FEATURE_NAMES)},
                             sort_keys=True).encode())
    return digest.hexdigest()


def _year(match) -> int:
    return match.scheduled_at.astimezone(timezone.utc).year


def _prefix_hashes(completed) -> dict[int, str]:
    """{Y: sha256 of all completed matches strictly before year Y}."""
    out: dict[int, str] = {}
    digest = sha256()
    current = None
    for match in completed:
        year = _year(match)
        if year != current:
            out[year] = digest.copy().hexdigest()
            current = year
        digest.update(repr(match).encode("utf-8"))
        digest.update(b"\x00")
    return out


def build_with_checkpoints(builder_factory: Callable[[], object], matches,
                           cache_dir: Path, *, log=print) -> tuple[pd.DataFrame, dict]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    completed = sorted((m for m in matches if m.is_completed),
                       key=lambda m: (m.scheduled_at, m.match_id))
    builder = builder_factory()
    config = _config_fingerprint(builder)
    hashes = _prefix_hashes(completed)
    years = sorted(hashes)
    manifest_path = cache_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        manifest = {}
    stored = manifest.get("years", {}) if manifest.get("config") == config else {}

    resume_year = None
    for year in reversed(years):
        entry = stored.get(str(year))
        if (entry and entry.get("prefix_sha256") == hashes[year]
                and (cache_dir / f"state-{year}.pkl").is_file()
                and all((cache_dir / f"frame-{y}.pkl").is_file()
                        and stored.get(str(y), {}).get("prefix_sha256") == hashes[y]
                        for y in years if y < year)):
            resume_year = year
            break

    frames: list[pd.DataFrame] = []
    if resume_year is not None:
        builder = pickle.loads((cache_dir / f"state-{resume_year}.pkl").read_bytes())
        for y in years:
            if y < resume_year:
                frames.append(pd.read_pickle(cache_dir / f"frame-{y}.pkl"))
    start = resume_year if resume_year is not None else years[0] if years else None
    log(json.dumps({"feature_checkpoint": {
        "resume_year": resume_year, "years": len(years),
        "reused_rows": int(sum(len(f) for f in frames)),
        "replay_years": [y for y in years if start is not None and y >= start]}}))

    new_years = dict(stored) if resume_year is not None else {}
    by_year: dict[int, list] = {}
    for match in completed:
        by_year.setdefault(_year(match), []).append(match)
    for y in years:
        if start is None or y < start:
            continue
        (cache_dir / f"state-{y}.pkl").write_bytes(pickle.dumps(builder, protocol=5))
        frame = builder.build_training_frame(by_year[y])
        frame.to_pickle(cache_dir / f"frame-{y}.pkl")
        new_years[str(y)] = {"prefix_sha256": hashes[y], "rows": int(len(frame))}
        frames.append(frame)

    keep = set(years[-KEEP_STATES:])
    for path in cache_dir.glob("state-*.pkl"):
        if int(path.stem.split("-")[1]) not in keep:
            path.unlink()
    for path in cache_dir.glob("frame-*.pkl"):
        if int(path.stem.split("-")[1]) not in hashes:
            path.unlink()
    manifest_path.write_text(json.dumps({"schema": SCHEMA, "config": config,
                                         "years": {k: v for k, v in new_years.items()
                                                   if int(k) in hashes}},
                                        sort_keys=True, indent=1))
    frame = pd.concat(frames, ignore_index=True) if frames else builder.build_training_frame([])
    return frame, {"resume_year": resume_year, "replayed_years": len(
        [y for y in years if start is not None and y >= start])}
