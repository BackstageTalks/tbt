"""Compact, read-only serving index for canonical Match Comparator predictions.

Generated during deployment *only* from the verified release snapshot. The
portable champion, player states, H2H and source lineage stay identical; each
request loads only two canonical players' feature states. No training or
provider calls in the public runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import zlib
from typing import Mapping

from ..data.player_identity import normalize_player_name


INDEX_SCHEMA = 1


class ComparatorIndexError(ValueError):
    pass


def _encode(value: object) -> bytes:
    return zlib.compress(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"), level=6)


def _decode(raw: bytes):
    return json.loads(zlib.decompress(raw).decode("utf-8"))


def build_comparator_index(artifact: Mapping, target: Path) -> dict:
    """Write a replace-atomically indexed serving copy, without editing source."""
    target = Path(target)
    source = artifact.get("feature_state")
    if (
        int(artifact.get("schema") or 0) != 1
        or not isinstance(source, dict)
        or not isinstance(source.get("players"), dict)
        or not isinstance(artifact.get("players"), list)
        or not isinstance(artifact.get("model"), dict)
        or not artifact.get("generated_at")
    ):
        raise ComparatorIndexError("invalid comparator snapshot for indexing")

    allowed = {
        f'{str(row.get("tour") or "").lower()}:{str(row.get("player_id") or "")}'
        for row in artifact["players"] if isinstance(row, dict)
    }
    states = source["players"]
    if not allowed or not allowed.issubset(states):
        raise ComparatorIndexError("canonical directory and feature states disagree")

    core = {key: value for key, value in artifact.items() if key not in {"feature_state", "players"}}
    core["schema"] = 1
    source_schema = source.get("schema_version")
    if source_schema is None:
        raise ComparatorIndexError("missing feature state schema")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.unlink(missing_ok=True)
    conn = sqlite3.connect(temp)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        conn.execute("CREATE TABLE player_states(player_key TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        conn.execute(
            "CREATE TABLE h2h(left_key TEXT NOT NULL,right_key TEXT NOT NULL,"
            " surface TEXT NOT NULL,wins_left INTEGER NOT NULL,wins_right INTEGER NOT NULL,"
            " PRIMARY KEY(left_key,right_key,surface))"
        )
        conn.execute("CREATE INDEX h2h_reverse ON h2h(right_key,left_key)")
        conn.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", [
            ("schema", _encode(INDEX_SCHEMA)),
            ("core", _encode(core)),
            ("feature_state_schema", _encode(int(source_schema))),
        ])
        conn.executemany(
            "INSERT INTO player_states(player_key,payload) VALUES (?,?)",
            ((key, _encode(states[key])) for key in sorted(allowed)),
        )
        total_h2h = 0
        for surface_key, rows in (("", source.get("h2h") or []), ("surface", source.get("surface_h2h") or [])):
            batch = []
            for row in rows:
                left, right = str(row.get("left") or ""), str(row.get("right") or "")
                if left not in allowed or right not in allowed:
                    continue
                surface = str(row.get("surface") or "") if surface_key else ""
                batch.append((left, right, surface, int(row.get("wins_left") or 0), int(row.get("wins_right") or 0)))
                if len(batch) >= 2000:
                    conn.executemany("INSERT INTO h2h VALUES (?,?,?,?,?)", batch)
                    total_h2h += len(batch)
                    batch.clear()
            if batch:
                conn.executemany("INSERT INTO h2h VALUES (?,?,?,?,?)", batch)
                total_h2h += len(batch)
        conn.commit()
        verified = conn.execute("SELECT COUNT(*) FROM player_states").fetchone()[0]
        if verified != len(allowed):
            raise ComparatorIndexError("player state index row count mismatch")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ComparatorIndexError("comparator SQLite integrity failure")
    except Exception:
        conn.close()
        temp.unlink(missing_ok=True)
        raise
    else:
        conn.close()
        temp.replace(target)
    return {"players": len(allowed), "h2h": total_h2h, "bytes": target.stat().st_size, "model_version": str(core["model"].get("model_version") or "")}


def _canonical_lookup(directory: Mapping, value: str, tour: str) -> dict:
    """Exact canonical ID or unambiguous exact name; never fuzzy link."""
    raw = str(value or "").strip()
    normalized = normalize_player_name(raw)
    matches = []
    for row in directory.get("players") or ():
        if not isinstance(row, dict) or str(row.get("tour") or "").lower() != tour:
            continue
        if str(row.get("player_id") or "") == raw and raw:
            return row
        if raw and normalized and normalized in (
            normalize_player_name(row.get("name")),
            *(normalize_player_name(alias) for alias in (row.get("aliases") or ())),
        ):
            matches.append(row)
    unique = {str(row.get("player_id") or ""): row for row in matches}
    unique.pop("", None)
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        raise ComparatorIndexError("ambiguous_player")
    raise ComparatorIndexError("player_not_found")


def load_pair_artifact(path: Path, directory: Mapping, *, player1: str, player2: str, tour: str) -> dict:
    """Load just enough authentic canonical evidence for a two-player compare."""
    tour = str(tour or "").strip().lower()
    if tour not in {"atp", "wta"}:
        raise ComparatorIndexError("invalid_tour")
    left = _canonical_lookup(directory, player1, tour)
    right = _canonical_lookup(directory, player2, tour)
    key1 = f'{tour}:{left["player_id"]}'
    key2 = f'{tour}:{right["player_id"]}'
    if key1 == key2:
        raise ComparatorIndexError("same_player")
    uri = f"file:{Path(path).resolve()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        def metadata(key):
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            if row is None:
                raise ComparatorIndexError("index_metadata_missing")
            return _decode(row[0])
        if metadata("schema") != INDEX_SCHEMA:
            raise ComparatorIndexError("unsupported_index_schema")
        core = metadata("core")
        if (
            str(core.get("generated_at") or "") != str(directory.get("generated_at") or "")
            or str((core.get("model") or {}).get("model_version") or "") != str(directory.get("model_version") or "")
        ):
            raise ComparatorIndexError("comparator index / directory mismatch")
        states = {}
        for key in (key1, key2):
            row = conn.execute("SELECT payload FROM player_states WHERE player_key=?", (key,)).fetchone()
            if row is None:
                raise ComparatorIndexError("canonical_player_state_missing")
            states[key] = _decode(row[0])
        records = conn.execute(
            "SELECT left_key,right_key,surface,wins_left,wins_right FROM h2h"
            " WHERE (left_key=? AND right_key=?) OR (left_key=? AND right_key=?)",
            (key1, key2, key2, key1),
        ).fetchall()
        h2h, surface_h2h = [], []
        for l, r, surf, wins_l, wins_r in records:
            record = {"left": l, "right": r, "wins_left": wins_l, "wins_right": wins_r}
            if surf:
                surface_h2h.append({**record, "surface": surf})
            else:
                h2h.append(record)
        return {
            **core,
            "players": [left, right],
            "feature_state": {
                "schema_version": metadata("feature_state_schema"),
                "players": states,
                "h2h": h2h,
                "surface_h2h": surface_h2h,
            },
        }
