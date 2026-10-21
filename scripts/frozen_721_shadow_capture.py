"""Opt-in private v7.2.1 prospective shadow capture inside an authorized refresh.

Uses the very same provider-discovered upcoming fixtures and same frozen
point-in-time history as serving. Neither new provider requests nor production
model/feed writes are made here. Only the independent private shadow release
is updated, under the caller's existing global CDB writer lock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json

from release_store import ReleaseStore
from rank_feature_inputs import load_rank_feature_inputs
from tbt.models.artifact import load_model
from tbt.services.engine import predict
from tbt.services.shadow_evaluation import update_shadow_ledger
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256,
    research_frozen_721, validate_frozen_evidence, exclude_repeated_events,
)

SHADOW_TAG = "blinq-frozen-721-private-shadow-v1"
LEDGER_ASSET = "frozen_721_paired_shadow.json"
REPORT_ASSET = "frozen_721_calibration_research.json"


def capture_frozen_721_shadow(
    *, data_repository, cache, champion_model, production_predictions,
    matches, upcoming, prediction_now, atp_leaderboards=None,
    atp_rank_history=None, wta_rank_history=None, wta_season_stats=None,
):
    """Fail closed for wrong artifact/source. Caller must isolate exceptions.

    Called ONLY from an already authorized refresh after the normal paid
    discovery; it has no provider object or provider credential.
    """
    from tbt.data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES
    from tbt.data.wta_rank_history import WTA_RANK_HISTORY_FEATURE_NAMES

    root = Path(cache)
    frozen = ReleaseStore(data_repository, FROZEN_721_TAG, root / "frozen-721-model")
    frozen.download(
        extra_names=("model.joblib",),
        required_names=("model.joblib",),
        require_bundle_manifest=True,
    )
    model_file = frozen.directory / "model.joblib"
    actual_sha = sha256(model_file.read_bytes()).hexdigest()
    if actual_sha != FROZEN_721_MODEL_SHA256:
        raise ValueError("Frozen candidate artifact SHA-256 mismatch")
    candidate = load_model(str(model_file))
    if not candidate.fitted or candidate.version != FROZEN_721_VERSION:
        raise ValueError("Frozen candidate version/fitted state mismatch")

    prod_version = str(getattr(champion_model, "version", "") or "")
    if not prod_version or prod_version == FROZEN_721_VERSION:
        raise ValueError("Invalid champion for isolated frozen-721 research")
    if any(row.get("model_version") != prod_version for row in production_predictions):
        raise ValueError("Serving predictions do not match loaded champion")

    features = set(getattr(candidate, "feature_names", None) or ())
    needs_rank = (
        bool(features & set(ATP_RANK_HISTORY_FEATURE_NAMES)) and atp_rank_history is None
    ) or (
        bool(features & set(WTA_RANK_HISTORY_FEATURE_NAMES)) and wta_rank_history is None
    )
    if needs_rank:
        ranks = load_rank_feature_inputs(
            data_repository, root / "frozen-721-rank-feature-inputs", matches,
        )
        if ranks.report.get("status") != "verified":
            raise ValueError("Frozen shadow rank input provenance unavailable")
        atp_rank_history = ranks.atp
        wta_rank_history = ranks.wta

    # Both model probabilities correspond to the same already-discovered
    # upcoming fixture. We do not refetch any fixture or odds from a provider.
    challenger_predictions = predict(
        candidate, matches, upcoming, now=prediction_now,
        atp_leaderboards=atp_leaderboards,
        atp_rank_history=atp_rank_history,
        wta_rank_history=wta_rank_history,
        wta_season_stats=wta_season_stats,
    )
    captured_at = datetime.now(timezone.utc)
    ledger_store = ReleaseStore(data_repository, SHADOW_TAG, root / "frozen-721-shadow")
    names = ledger_store._asset_names()
    expected = {LEDGER_ASSET, REPORT_ASSET}
    if names & expected and not expected <= names:
        raise ValueError("Incomplete existing frozen-721 shadow release")
    if expected <= names:
        ledger_store.download(
            extra_names=tuple(sorted(expected)),
            required_names=tuple(sorted(expected)),
            require_bundle_manifest=True,
        )
        prior = json.loads((ledger_store.directory / LEDGER_ASSET).read_text(encoding="utf-8"))
        validate_frozen_evidence(prior, production_version=prod_version)
        ledger = prior["rows"]
    else:
        ledger = []

    updated = update_shadow_ledger(
        exclude_repeated_events(ledger),
        production_predictions=production_predictions,
        challenger_predictions=challenger_predictions,
        completed_matches=matches,
        production_model_version=prod_version,
        challenger_model_version=FROZEN_721_VERSION,
        now=captured_at,
    )
    updated = exclude_repeated_events(updated)
    source = {
        "candidate_tag": FROZEN_721_TAG,
        "candidate_version": FROZEN_721_VERSION,
        "candidate_model_sha256": actual_sha,
        "production_version": prod_version,
        # Incremental provider requests caused by this offline comparison.
        "provider_requests": 0,
    }
    payload = {"schema": 1, "source": source, "rows": updated}
    report = research_frozen_721(payload, production_version=prod_version)

    ledger_file = ledger_store.directory / LEDGER_ASSET
    report_file = ledger_store.directory / REPORT_ASSET
    ledger_file.write_text(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    report_file.write_text(json.dumps(report, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    ledger_store.upload_bundle([ledger_file, report_file])

    # Never report a successful capture based on a local upload command alone.
    # A separate directory forces a remote download and verifies the committed
    # manifest/checksums, then we byte-compare both assets with the submitted
    # generation. No provider calls or public-feed mutations are involved.
    remote = ReleaseStore(
        data_repository, SHADOW_TAG, root / "frozen-721-shadow-readback"
    )
    remote.download(
        extra_names=(LEDGER_ASSET, REPORT_ASSET),
        required_names=(LEDGER_ASSET, REPORT_ASSET),
        require_bundle_manifest=True,
    )
    for asset, local in ((LEDGER_ASSET, ledger_file), (REPORT_ASSET, report_file)):
        if (remote.directory / asset).read_bytes() != local.read_bytes():
            raise RuntimeError("Frozen 7.2.1 remote shadow read-back mismatch: " + asset)
    verified = json.loads(
        (remote.directory / LEDGER_ASSET).read_text(encoding="utf-8")
    )
    verified_rows, verified_counts = validate_frozen_evidence(
        verified, production_version=prod_version
    )
    if len(verified_rows) != len(updated) or verified_counts != report["cohort_counts"]:
        raise RuntimeError("Frozen 7.2.1 shadow cohort failed remote read-back")

    return {
        "status": report["status"],
        "remote_readback": "VERIFIED",
        "candidate_version": FROZEN_721_VERSION,
        "champion_version": prod_version,
        "captured": len(updated),
        "settled": report["cohort_counts"]["settled"],
        "fit_rows": report["fit_rows"],
        "evaluation_rows": report["evaluation_rows"],
        "incremental_provider_requests": 0,
        "production_mutated": False,
        "shadow_release": SHADOW_TAG,
    }
