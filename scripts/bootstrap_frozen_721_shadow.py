"""One-time, zero-provider-request prospective v7.2.1 paired snapshot.

Use ONLY already issued production pre-match predictions, and compute frozen
7.2.1 probabilities for the same still-future fixtures using canonical history
and the same archived point-in-time priors as normal serving. Not a historical
backfill, a completed calibration, or a production model promotion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.atp_leaderboards import ATPLeaderboardPriors
from tbt.data.wta_season_stats import WTASeasonPriors
from tbt.models.artifact import load_model
from tbt.schemas import MatchRecord
from frozen_721_shadow_capture import (
    SHADOW_TAG, capture_frozen_721_shadow,
)

CHAMPION_SHA256 = "a96e61f1942a3ee9cd35f1e754b4981e420f26ba08049a66d65c00ae4f09c4a7"
CHAMPION_VERSION = "v201-20260925T204608601094Z"
DATA_REPO = "BackstageTalks/tbt-data"


def utc(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing immutable pre-match timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone-naive immutable pre-match timestamp")
    return dt.astimezone(timezone.utc)


def eligible_issued_fixtures(feed: dict, now: datetime):
    """Pair only genuinely issued, previously stored champion predictions."""
    if (feed.get("model") or {}).get("version") != CHAMPION_VERSION:
        raise ValueError("Wrong production feed model version")
    rows = feed.get("upcoming")
    if not isinstance(rows, list):
        raise ValueError("Missing independently stored upcoming feed")
    matched = []
    fixtures = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("model_version") != CHAMPION_VERSION:
            continue
        try:
            issued = utc(row.get("issued_at"))
            scheduled = utc(row.get("scheduled_at"))
            captured = utc(row.get("created_at"))
        except (ValueError, TypeError):
            continue
        if not (captured <= issued <= now < scheduled <= now + timedelta(days=4)):
            continue
        mid = str(row.get("id") or "").strip()
        a = row.get("player1")
        b = row.get("player2")
        if not mid or not isinstance(a, dict) or not isinstance(b, dict):
            continue
        aid, bid = str(a.get("id") or "").strip(), str(b.get("id") or "").strip()
        if not aid or not bid or aid == bid or mid in seen:
            continue
        tour = str(row.get("tour") or "").upper()
        if tour not in {"ATP", "WTA"}:
            continue
        try:
            p1 = float(a.get("probability"))
            p2 = float(b.get("probability"))
        except (TypeError, ValueError):
            continue
        if not (0 < p1 < 1 and 0 < p2 < 1 and abs(p1 + p2 - 1.0) < 1e-8):
            continue
        seen.add(mid)
        matched.append(row)
        fixtures.append(MatchRecord(
            match_id=mid, tour=tour.lower(), scheduled_at=scheduled,
            player1_id=aid, player1_name=str(a.get("name") or aid),
            player2_id=bid, player2_name=str(b.get("name") or bid),
            surface=str(row.get("surface") or "unknown"),
            tournament=str(row.get("tournament") or ""),
            tournament_id=str(row.get("tournament_id") or ""),
            tournament_level=str(row.get("competition") or ""),
            round_name=str(row.get("round") or ""),
            player1_rank=(int(a["rank"]) if a.get("rank") is not None else None),
            player2_rank=(int(b["rank"]) if b.get("rank") is not None else None),
            best_of=(int(row["best_of"]) if row.get("best_of") is not None else None),
            status="upcoming",
        ))
    return matched, fixtures


def verified_private_priors(repo, cache):
    atp_name = "atp_leaderboards_1991_2026_52week_career.csv"
    wta_name = "wta_stats_2010_2026_serving_returning.csv"
    atp_store = ReleaseStore(repo, "tbt-atp-leaderboards-v1", cache / "atp-leaderboards")
    atp_store.download(
        extra_names=(atp_name,), required_names=(atp_name,), require_bundle_manifest=True
    )
    wta_store = ReleaseStore(repo, "tbt-wta-season-stats-v1", cache / "wta-season-stats")
    wta_store.download(
        extra_names=(wta_name,), required_names=(wta_name,), require_bundle_manifest=True
    )
    return (ATPLeaderboardPriors.from_csv(atp_store.directory / atp_name),
            WTASeasonPriors.from_csv(wta_store.directory / wta_name))


def bootstrap(*, repo=DATA_REPO, cache=None, now=None):
    if repo != DATA_REPO:
        raise ValueError("Unexpected private repository")
    root = Path(cache or ROOT / ".cache/tbt/frozen-721-offline-bootstrap")
    root.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware capture time required")
    now = now.astimezone(timezone.utc)

    # This one-time bootstrap is not allowed to race or rewrite an existing
    # private shadow cohort. No fabricated data, no duplicate release creation.
    from release_store import _run_gh
    probe = _run_gh(["api", f"repos/{repo}/releases/tags/{SHADOW_TAG}"])
    if probe.returncode == 0:
        return {"status": "SKIPPED_EXISTING_PRIVATE_SHADOW", "provider_requests": 0}
    if "HTTP 404" not in probe.stderr and "Not Found" not in probe.stderr:
        raise RuntimeError("Cannot verify absence of shadow release")

    feed_store = ReleaseStore(repo, "tbt-predictions-v1", root / "predictions")
    feed_store.download(
        extra_names=("feed.json", "ledger.json"),
        required_names=("feed.json", "ledger.json"),
        require_bundle_manifest=True,
    )
    feed = json.loads((feed_store.directory / "feed.json").read_text(encoding="utf-8"))
    predictions, fixtures = eligible_issued_fixtures(feed, now)
    if not fixtures:
        return {
            "status": "NO_ELIGIBLE_ISSUED_FUTURE_FIXTURES",
            "provider_requests": 0,
            "private_release_created": False,
        }

    champion_store = ReleaseStore(repo, "tbt-model-production-v1", root / "production")
    champion_store.download(
        extra_names=("model.joblib",),
        required_names=("model.joblib",),
        require_bundle_manifest=True,
    )
    path = champion_store.directory / "model.joblib"
    if hashlib.sha256(path.read_bytes()).hexdigest() != CHAMPION_SHA256:
        raise ValueError("Frozen champion hash mismatch")
    champion = load_model(str(path))
    if champion.version != CHAMPION_VERSION or not champion.fitted:
        raise ValueError("Frozen champion version/fitted mismatch")

    canonical = ReleaseStore(repo, "tbt-data-v1", root / "history")
    canonical.download(require_bundle_manifest=True)
    source = load_partitions(canonical.directory)
    history, safety = sanitize_history_identities(source)
    if safety.get("unresolved"):
        raise ValueError("Unresolved canonical tennis identity before 7.2.1 scoring")
    if len(history) < 500000:
        raise ValueError("Incomplete canonical history in offline bootstrap")
    atp, wta = verified_private_priors(repo, root)

    # Critical: protect hourly CDB publication from interference. The one-time
    # private writer only acquires the existing global lock immediately before
    # scoring/upload, never starts an API collection and will not forcibly
    # clear another run's lock. The normal catch-up writer takes priority.
    from cdb_global_writer_lock import acquire, release
    lock = root / "research-global-lock.json"
    acquire(repo, lock, wait_seconds=0)
    try:
        result = capture_frozen_721_shadow(
            data_repository=repo, cache=root, champion_model=champion,
            production_predictions=predictions, matches=history,
            upcoming=fixtures, prediction_now=now,
            atp_leaderboards=atp, wta_season_stats=wta,
        )
    finally:
        release(repo, lock, if_held=True)
    if result.get("remote_readback") != "VERIFIED" or result.get("captured", 0) < 1:
        raise RuntimeError("No independently read-back prospective 7.2.1 prediction")
    result["evidence_source"] = "previously_issued_champion_feed_plus_current_offline_candidate_inference"
    result["publication_unchanged"] = True
    result["source_fixtures_issued_before_candidate_scoring"] = len(fixtures)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default=DATA_REPO)
    parser.add_argument("--output", default=".cache/tbt/frozen-721-offline-bootstrap-status.json")
    args = parser.parse_args()
    result = bootstrap(repo=args.data_repository)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
