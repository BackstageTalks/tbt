"""MoviOdds tennis observation journal (Azure Table / existing BlinQ storage).

Live observations are append-only and NOT importable. Finished /results?stats=1
records are persisted separately with a source digest and immutable readback.
CDB enrichment happens only in the scheduled guarded canonical writer, never here.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from typing import Any

from .admin_storage import AdminStorageUnavailable, _table

TABLE = "BlinQMoviOddsStats"
ROOT = "https://moviodds.com"
MAX_BYTES = 4_000_000
_VALID_ID = re.compile(r"^[0-9]{3,20}$")


def _when(value: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return value.astimezone(timezone.utc) if value.tzinfo is not None else None


def _get(path: str, *, params: dict[str, str], opener=None) -> dict:
    url = ROOT + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "BlinQ-StatsArchive/1.0",
    })
    with (opener or urllib.request.urlopen)(req, timeout=20) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("MoviOdds stats response too large")
        if str(response.headers.get("Content-Encoding", "")).lower() == "gzip":
            body = gzip.decompress(body)
            if len(body) > MAX_BYTES:
                raise ValueError("MoviOdds decoded stats response too large")
    out = json.loads(body)
    if not isinstance(out, dict) or out.get("warming") is True:
        raise ValueError("MoviOdds stats invalid or warming")
    return out


def _payload(record: dict, *, completed: bool) -> tuple[str, dict] | None:
    fixture = str(record.get("fixture_id" if completed else "id") or "")
    if not _VALID_ID.fullmatch(fixture):
        return None
    if completed:
        if str(record.get("status")) != "finished" or not str(record.get("final_score") or ""):
            return None
        finished = _when(record.get("finished_at"))
        if finished is None:
            return None
    elif record.get("in_play") is not True:
        return None
    else:
        finished = None
    stats = record.get("stats")
    if not isinstance(stats, dict) or stats.get("sport") != "tennis":
        return None
    home, away = stats.get("home"), stats.get("away")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    if not str(record.get("home") or "") or not str(record.get("away") or ""):
        return None
    for side in (home, away):
        for field in ("aces", "double_faults"):
            value = side.get(field)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return None
            if value < 0 or value > 250 or int(value) != value:
                return None
        for field in ("first_serve_win_pct", "break_point_conversion_pct"):
            value = side.get(field)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return None
            if value < 0 or value > 100:
                return None
    captured = _when(stats.get("updated_at")) or _when(record.get("last_live_seen"))
    if not captured:
        return None
    fields = {
        "schema": 1, "source": "moviodds", "fixture_id": fixture,
        "home": str(record["home"])[:160], "away": str(record["away"])[:160],
        "league": str(record.get("league") or "")[:160],
        "kickoff_utc": str(record.get("kickoff_utc") or ""),
        "observed_at": captured.isoformat(), "stats": stats,
    }
    if completed:
        fields.update({
            "status": "finished", "finished_at": finished.isoformat(),
            "final_score": str(record.get("final_score") or "")[:100],
            "periods": record.get("periods") or [],
        })
    else:
        fields.update({"status": "live", "score": str(record.get("score") or "")[:100]})
    return fixture, fields


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def save_observations(table, records: list[dict], *, completed: bool,
                      collected_at: datetime) -> dict[str, int]:
    """One final record per fixture, append-only live snapshots (15m buckets).

    Existing final differing payloads are review conflicts; a later source
    correction cannot silently replace a previously accepted observation.
    """
    report = {"raw": len(records), "valid": 0, "written": 0,
              "duplicate": 0, "conflict": 0, "rejected": 0}
    slot = collected_at.astimezone(timezone.utc).strftime("%Y%m%dT%H") + f"{collected_at.minute // 15:01d}"
    for record in records:
        item = _payload(record, completed=completed) if isinstance(record, dict) else None
        if item is None:
            report["rejected"] += 1
            continue
        fixture, data = item
        report["valid"] += 1
        source_date = (data["finished_at"][:10] if completed else collected_at.date().isoformat())
        part = source_date.replace("-", "")
        key = "final:" + fixture if completed else f"live:{fixture}:{slot}"
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 45000:
            report["rejected"] += 1
            continue
        digest = _hash(data)
        entity = {"PartitionKey": part, "RowKey": key, "schema": 1,
                  "kind": "final" if completed else "live",
                  "source": "moviodds", "fixture_id": fixture,
                  "sha256": digest, "payload_json": serialized,
                  "collected_at": collected_at.isoformat()}
        try:
            table.create_entity(entity)
            # Independent same-run readback; HTTP success is not proof.
            saved = table.get_entity(partition_key=part, row_key=key)
            if saved.get("sha256") != digest or saved.get("payload_json") != serialized:
                raise AdminStorageUnavailable("MoviOdds stats readback mismatch")
            report["written"] += 1
        except Exception as exc:
            # Azure's ResourceExists/412 and Firestore's AlreadyExists wrapper.
            status = getattr(exc, "status_code", None)
            conflict = status in (409, 412) or "already" in str(type(exc)).lower() or (
                type(exc).__name__ == "_StorageWriteConflict"
            )
            if not conflict:
                raise AdminStorageUnavailable("MoviOdds stats persistence failed") from exc
            try:
                prior = table.get_entity(partition_key=part, row_key=key)
            except Exception as read_exc:
                raise AdminStorageUnavailable("MoviOdds stats existing-row readback unavailable") from read_exc
            if prior.get("sha256") == digest:
                report["duplicate"] += 1
            else:
                report["conflict"] += 1
    return report


def collect(*, now: datetime | None = None, opener=None, table=None,
            collect_live: bool = True, collect_finished: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("MoviOdds requires an aware timestamp")
    table = table or _table(TABLE)
    report = {"source": "moviodds", "stored": "azure_table",
              "as_of": now.astimezone(timezone.utc).isoformat(),
              "live": {}, "final": {}, "errors": []}
    if collect_live:
        try:
            data = _get("/odds", params={"sport": "tennis", "in_play": "1",
                                         "groups": "67", "stats": "1"}, opener=opener)
            if not isinstance(data.get("matches"), list):
                raise ValueError("Missing live matches")
            report["live"] = save_observations(table, data["matches"],
                                                completed=False, collected_at=now)
        except Exception as exc:
            report["errors"].append("live_" + type(exc).__name__)
    if collect_finished:
        # Avoid gaps over midnight/late provider index propagation.
        for day in (now.date() - timedelta(days=1), now.date()):
            key = day.isoformat()
            try:
                data = _get("/results", params={"sport": "tennis", "date": key,
                                                "stats": "1"}, opener=opener)
                if not isinstance(data.get("results"), list):
                    raise ValueError("Missing finished results")
                report["final"][key] = save_observations(
                    table, data["results"], completed=True, collected_at=now)
            except Exception as exc:
                report["errors"].append("results_" + key + "_" + type(exc).__name__)
    report["ok"] = not report["errors"]
    return report


def export_final(*, days: list[str], table=None) -> dict:
    table = table or _table(TABLE)
    if not days or len(days) > 3:
        raise ValueError("Invalid MoviOdds export days")
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for day in days:
        parsed = date.fromisoformat(str(day))
        partition = parsed.strftime("%Y%m%d")
        records = table.query_entities(query_filter=f"PartitionKey eq '{partition}'")
        for row in records:
            if row.get("kind") != "final" or row.get("source") != "moviodds":
                continue
            raw = str(row.get("payload_json") or "")
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                raise AdminStorageUnavailable("Corrupt MoviOdds final stats") from exc
            if _hash(payload) != row.get("sha256") or payload.get("status") != "finished":
                raise AdminStorageUnavailable("MoviOdds final stats digest mismatch")
            identity = (day, str(payload.get("fixture_id") or ""))
            if identity in seen:
                raise AdminStorageUnavailable("Duplicate MoviOdds final fixture")
            seen.add(identity)
            out.append({"payload": payload, "sha256": row["sha256"]})
    out.sort(key=lambda row: (row["payload"]["finished_at"], row["payload"]["fixture_id"]))
    return {"schema": 1, "source": "moviodds", "days": days,
            "count": len(out), "records": out, "verified": True}
