"""Roll up verified hourly collector evidence for the private Admin diagnostics."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

from azure.core.exceptions import ResourceExistsError
from tbt.services.media_storage import _blob_service, _container_name

PREFIX = "admin/hourly-collection/"
PHASES = {"primary": "statistics_readback.json", "fallback": "extras_readback.json"}
VERIFIED = {"VERIFIED", "VERIFIED_NO_NEW_FIELDS", "VERIFIED_NO_NEW_MARKERS"}


def build_run(root, run_id, attempt, ended_at, fallback_expected):
    def read(name):
        path = root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    phases = {}
    for phase, readback_name in PHASES.items():
        if phase == "fallback" and not fallback_expected:
            continue
        observed = read(f"hourly_{phase}_collection.json")
        readback = read(readback_name)
        attempts = observed.get("attempts")
        endpoints = observed.get("endpoints", {})
        verified = (
            attempts is not None
            and attempts == sum(sum(counts.values()) for counts in endpoints.values())
            and readback.get("status") in VERIFIED
        )
        phases[phase] = {
            **observed,
            "verified": verified,
            "gain": ({
                "new_matches": 0,
                "enriched_matches": readback["persisted_enriched_matches"],
                "fields": readback["persisted_new_values_by_field"],
                "extras_markers": 0,
                "paid_fields": observed["paid_statistic_values"],
            } if phase == "primary" else {
                "new_matches": 0,
                "enriched_matches": readback["persisted_matches"],
                "fields": {},
                "extras_markers": readback["persisted_new_marker_count"],
                "paid_fields": 0,
            }) if verified else None,
        }
    run = {"schema": 1, "run_id": run_id, "attempt": attempt,
           "ended_at": ended_at.isoformat(), "phases": phases}
    run["totals"] = aggregate([run])
    return run


def aggregate(runs):
    endpoints = defaultdict(Counter)
    fields, conflicts, rejections, totals = (Counter() for _ in range(4))
    incomplete = 0
    for run in runs:
        phases = run["phases"].values()
        incomplete += any(not phase["verified"] for phase in phases)
        for phase in phases:
            totals["attempts"] += phase.get("attempts", 0)
            conflicts.update(phase.get("conflicts", {}))
            rejections.update(phase.get("rejections", {}))
            for endpoint, counts in phase.get("endpoints", {}).items():
                endpoints[endpoint].update(counts)
            if phase["verified"]:
                gain = phase["gain"]
                totals["verified_attempts"] += phase["attempts"]
                fields.update(gain["fields"])
                for key in ("new_matches", "enriched_matches", "extras_markers", "paid_fields"):
                    totals[key] += gain[key]
    denominator = totals["verified_attempts"]
    return {
        "runs": len(runs), "incomplete_runs": incomplete,
        **{key: totals[key] for key in ("attempts", "verified_attempts", "new_matches",
                                        "enriched_matches", "extras_markers", "paid_fields")},
        "fields": dict(fields), "conflicts": dict(conflicts), "rejections": dict(rejections),
        "endpoints": {endpoint: dict(counts) for endpoint, counts in endpoints.items()},
        "fields_per_1000": 1000 * sum(fields.values()) / denominator if denominator else None,
        "paid_fields_per_1000": 1000 * totals["paid_fields"] / denominator if denominator else None,
        "extras_markers_per_1000": 1000 * totals["extras_markers"] / denominator if denominator else None,
    }


def publish_run(run):
    # A stable key makes the same GitHub attempt immutable even across UTC midnight.
    name = f'{PREFIX}{int(run["run_id"])}-{int(run["attempt"])}.json'
    with _blob_service() as service:
        blob = service.get_blob_client(_container_name(), name)
        try:
            blob.upload_blob(json.dumps(run), overwrite=False)
        except ResourceExistsError:
            pass


def load_overview(now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=14)
    with _blob_service() as service:
        container = service.get_container_client(_container_name())
        names = [item.name for item in container.list_blobs(name_starts_with=PREFIX)
                 if item.last_modified >= start]

        def load(name):
            return json.loads(container.download_blob(name, max_concurrency=1).readall())

        with ThreadPoolExecutor(max_workers=12) as pool:
            recent = [run for run in pool.map(load, names)
                      if start <= datetime.fromisoformat(run["ended_at"]) <= now]
    recent.sort(key=lambda run: run["ended_at"], reverse=True)
    return {
        "available": True, **aggregate(recent),
        "recent": [{"ended_at": run["ended_at"], "run_id": run["run_id"],
                    "attempt": run["attempt"], **{key: run["totals"][key]
                    for key in ("attempts", "incomplete_runs")}} for run in recent[:12]],
    }
