"""Settle genuine frozen 7.2.1 pre-match pairs from verified canonical outcomes.

Offline; no betting/tennis provider requests, no training, no champion mutation.
Only the original exact model-pair release is updated, under the CDB writer lock.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401; safe api:scripts imports
from release_store import ReleaseStore, gh
from cdb_global_writer_lock import acquire, release
from frozen_721_shadow_capture import SHADOW_TAG, LEDGER_ASSET, REPORT_ASSET
from tbt.data.history_snapshot import load_snapshot
from tbt.models.metrics import evaluate_probabilities, wilson_interval
from tbt.services.frozen_721_research import validate_frozen_evidence, research_frozen_721, exclude_repeated_events
from tbt.services.shadow_evaluation import update_shadow_ledger

DATA_REPO = "BackstageTalks/tbt-data"
HISTORY_TAG = "tbt-data-v1"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive settlement schedule")
    return dt.astimezone(timezone.utc)


def _clean_metrics(rows, field):
    if not rows:
        return {"n": 0}
    probs = [float(row[field]) for row in rows]
    truths = [int(row["target_player1_win"]) for row in rows]
    result = evaluate_probabilities(truths, probs)
    correct = sum((p >= 0.5) == bool(y) for p, y in zip(probs, truths))
    return {
        "n": len(rows),
        "correct": int(correct),
        "accuracy": result["accuracy"],
        "accuracy_ci95_wilson": wilson_interval(correct, len(rows)),
        "brier_score": result["brier_score"],
        "log_loss": result["log_loss"],
        "ece_10": result["ece_10"],
        "roc_auc": result["roc_auc"] if math.isfinite(result["roc_auc"]) else None,
    }


def preliminary_scoreboard(rows):
    """Descriptive only, never a promotion or TOP-odds decision."""
    result = {}
    for name, tour in (("overall", None), ("ATP", "ATP"), ("WTA", "WTA")):
        sample = [
            row for row in rows if row.get("status") == "settled"
            and (tour is None or str(row.get("tour") or "").upper() == tour)
        ]
        champion = _clean_metrics(sample, "production_player1_probability")
        challenger = _clean_metrics(sample, "challenger_player1_probability")
        result[name] = {
            "n": len(sample), "champion": champion, "candidate": challenger,
            "candidate_minus_champion": {
                key: (round(challenger[key] - champion[key], 9) if sample else None)
                for key in ("accuracy", "brier_score", "log_loss", "ece_10")
            },
        }
    return {
        "status": "PRELIMINARY_SCORES_ONLY_NOT_PROMOTION",
        "note": "Post-issued results only; small cohorts have wide uncertainty. No odds-based TOP ROI validation.",
        "groups": result,
        "automatic_promotion": False,
    }


MAX_VERIFIED_LATER_POSTPONEMENT_SECONDS = 72 * 3600


def _alias_schedule_safe(source, match):
    """Accept ordinary <=24h corrections or witnessed later shifts <=72h.

    This predicate is NEVER sufficient on its own: the caller must prove the
    unique native event, exact native participant witness, tour and prestart
    chronology. Earlier shifts beyond 24h are deliberately not accepted.
    """
    delta = (match.scheduled_at - _utc(source["scheduled_at"])).total_seconds()
    return -86400 <= delta <= MAX_VERIFIED_LATER_POSTPONEMENT_SECONDS


def _alias_identity_category(source, match, event, now):
    """Classify one provider-event alias without accepting or rewriting its identity.

    A native event ID alone is not proof that the captured players are the
    canonical players. Only aggregate reason codes may leave the private run.
    """
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    identity = raw.get("_tbt_event_identity")
    identity = identity if isinstance(identity, dict) else {}
    if (str(raw.get("_tbt_provider_event_id") or "") != event
            or str(identity.get("event_id") or "") != event
            or identity.get("status") != "finished"):
        return "unverified_native_event_witness"
    canonical_pair = {str(match.player1_id), str(match.player2_id)}
    witnessed_pair = {str(identity.get("home") or ""), str(identity.get("away") or "")}
    captured_pair = {str(source.get("player1_id") or ""), str(source.get("player2_id") or "")}
    if witnessed_pair != canonical_pair:
        return "provider_witness_canonical_player_conflict"
    if captured_pair != canonical_pair:
        return "captured_canonical_player_id_conflict"
    if str(match.tour or "").upper() != str(source.get("tour") or "").upper():
        return "tour_conflict"
    delta = (match.scheduled_at - _utc(source["scheduled_at"])).total_seconds()
    if not _alias_schedule_safe(source, match):
        return "schedule_outside_witnessed_postponement_window"
    if (_utc(source["captured_at"]) >= match.scheduled_at
            or _utc(source["captured_at"]) >= _utc(source["scheduled_at"])):
        return "capture_not_before_canonical_start"
    if match.scheduled_at >= now or _utc(source["scheduled_at"]) >= now:
        return "not_yet_played"
    if not match.is_completed:
        return "canonical_not_completed"
    if delta > 86400:
        return "verified_later_postponement_24_72h"
    return "strict_alias_eligible"


def completed_matches_for_pending(rows, matches, now):
# end of aggregate classification

    """Join exact internal IDs or independently recorded provider event IDs.

    Alias lookup requires both stored provider IDs, the provider's player IDs,
    canonical players/tour, and pre-start capture. Never join on names/date alone.
    Canonical objects are copied only for the shadow ledger; CDB is not changed.
    """
    exact = {}
    events = {}
    for match in matches:
        exact.setdefault(str(match.match_id), []).append(match)
        raw = match.provider_payload or {}
        identity = raw.get("_tbt_event_identity") or {}
        # Index every claimed event so contradictory evidence cannot hide a
        # duplicate and make another row look uniquely verified.
        for event in {str(raw.get("_tbt_provider_event_id") or ""),
                      str(identity.get("event_id") or "")} - {""}:
            events.setdefault(event, []).append(match)
    accepted = []
    audit = {"identity_mismatch": 0, "not_yet_played": 0,
             "not_canonically_completed": 0, "matched_canonical_rows": 0,
             "verified_provider_event_aliases": 0, "ambiguous_provider_events": 0,
             "capture_not_before_canonical_start": 0, "provider_alias_evidence": {},
             "matched_exact_candidates": 0, "matched_alias_candidates": 0,
             "exact_player_or_tour_conflicts": 0, "alias_identity_categories": {}}
    for source in rows:
        if source.get("status") != "pending":
            continue
        original_id = str(source["match_id"])
        candidates = exact.get(original_id, [])
        alias = not candidates
        event = str(source.get("event_id") or "")
        if alias:
            candidates = events.get(event, []) if event else []
        if not candidates:
            continue
        if len(candidates) != 1:
            audit["ambiguous_provider_events"] += 1
            continue
        match = candidates[0]
        audit["matched_canonical_rows"] += 1
        players = {str(match.player1_id), str(match.player2_id)}
        source_players = {str(source["player1_id"]), str(source["player2_id"])}
        if alias:
            audit["matched_alias_candidates"] += 1
            category = _alias_identity_category(source, match, event, now)
            categories = audit["alias_identity_categories"]
            categories[category] = categories.get(category, 0) + 1
        else:
            audit["matched_exact_candidates"] += 1
            if (str(match.tour or "").upper() != str(source["tour"]).upper()
                    or players != source_players):
                audit["exact_player_or_tour_conflicts"] += 1
        if (str(match.tour or "").upper() != str(source["tour"]).upper()
                or players != source_players):
            audit["identity_mismatch"] += 1
            continue
        if alias:
            raw = match.provider_payload or {}
            identity = raw.get("_tbt_event_identity") or {}
            if (str(raw.get("_tbt_provider_event_id") or "") != event
                    or str(identity.get("event_id") or "") != event
                    or {str(identity.get("home") or ""), str(identity.get("away") or "")} != players
                    or identity.get("status") != "finished"
                    or not _alias_schedule_safe(source, match)
                    or _utc(source["captured_at"]) >= _utc(source["scheduled_at"])):
                audit["identity_mismatch"] += 1
                continue
        if match.scheduled_at >= now or _utc(source["scheduled_at"]) >= now:
            audit["not_yet_played"] += 1
            continue
        if _utc(source["captured_at"]) >= match.scheduled_at:
            audit["capture_not_before_canonical_start"] += 1
            continue
        if not match.is_completed:
            audit["not_canonically_completed"] += 1
            continue
        if alias:
            audit["verified_provider_event_aliases"] += 1
            audit["provider_alias_evidence"][original_id] = {
                "canonical_match_id": str(match.match_id), "provider_event_id": event,
                "canonical_scheduled_at": match.scheduled_at.isoformat(),
                "method": ("exact_verified_provider_event_and_players_later_postponed_72h"
                           if (match.scheduled_at - _utc(source["scheduled_at"])).total_seconds() > 86400
                           else "exact_verified_provider_event_and_players"),
            }
            match = replace(match, match_id=original_id)
        accepted.append(match)
    return accepted, audit



def pending_schedule_diagnostics(rows, matches, now):
    """Read-only cohort timing and linkage diagnostics; never settle by fuzzy join.

    Same-player and date similarities are aggregated for investigation only.
    A different match ID is NEVER substituted for the recorded pre-match ID.
    """
    pending = [row for row in rows if row.get("status") == "pending"]
    schedule_dates = {}
    tour_counts = {"ATP": 0, "WTA": 0}
    earliest = latest = None
    starts_next_24h = scheduled_not_started = started = overdue_6h = overdue_24h = 0
    by_exact_id = {str(m.match_id): m for m in matches}
    # Potential identity drift is a diagnostic, not a trusted join.
    by_players_day = {}
    for match in matches:
        if not match.player1_id or not match.player2_id:
            continue
        key = (
            str(match.tour or "").upper(),
            match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
            frozenset((str(match.player1_id), str(match.player2_id))),
        )
        by_players_day.setdefault(key, []).append(match)

    exact_id = exact_completed = alternate_id_same_players_day = 0
    alternate_id_completed = 0
    for row in pending:
        scheduled = _utc(row["scheduled_at"])
        day = scheduled.date().isoformat()
        schedule_dates[day] = schedule_dates.get(day, 0) + 1
        tour = str(row.get("tour") or "").upper()
        if tour in tour_counts:
            tour_counts[tour] += 1
        if earliest is None or scheduled < earliest:
            earliest = scheduled
        if latest is None or scheduled > latest:
            latest = scheduled
        if scheduled > now:
            scheduled_not_started += 1
            if (scheduled - now).total_seconds() <= 86400:
                starts_next_24h += 1
        else:
            started += 1
            hours = (now - scheduled).total_seconds() / 3600
            overdue_6h += int(hours >= 6)
            overdue_24h += int(hours >= 24)
        if (matching := by_exact_id.get(str(row["match_id"]))) is not None:
            exact_id += 1
            exact_completed += int(matching.is_completed)
        else:
            key = (
                tour, day, frozenset((
                    str(row["player1_id"]), str(row["player2_id"])
                ))
            )
            others = [
                match for match in by_players_day.get(key, [])
                if abs((match.scheduled_at - scheduled).total_seconds()) <= 12 * 3600
            ]
            if len(others) == 1:
                alternate_id_same_players_day += 1
                alternate_id_completed += int(others[0].is_completed)
    return {
        "pending": len(pending),
        "by_tour": tour_counts,
        "scheduled_utc_days": dict(sorted(schedule_dates.items())),
        "earliest_scheduled_utc": earliest.isoformat() if earliest else None,
        "latest_scheduled_utc": latest.isoformat() if latest else None,
        "scheduled_not_started": scheduled_not_started,
        "starts_next_24h": starts_next_24h,
        "scheduled_at_or_before_now": started,
        "at_least_6h_after_schedule": overdue_6h,
        "at_least_24h_after_schedule": overdue_24h,
        "exact_id_in_canonical": exact_id,
        "exact_id_canonically_completed": exact_completed,
        "alternate_id_same_players_day_diagnostic_only": alternate_id_same_players_day,
        "alternate_id_canonically_completed_diagnostic_only": alternate_id_completed,
        "alternate_id_join_used_for_settlement": False,
        "provider_requests": 0,
    }

def download_verified_years(repo, directory, years):
    """Only download year partitions containing issued shadow fixtures.

    Verify BOTH GitHub release asset checksums and the committed private
    release bundle manifest, avoiding the entire million-row training corpus.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if not years:
        return [], {}
    meta = json.loads(gh("api", f"repos/{repo}/releases/tags/{HISTORY_TAG}"))
    assets = {a["name"]: a for a in meta.get("assets", []) if isinstance(a, dict)}
    names = {"history_manifest.json", "_tbt_bundle_manifest.json"} | {
        f"history-{year}.parquet" for year in years
    }
    if not names <= set(assets):
        raise FileNotFoundError("Canonical year partition/manifest missing from private release")
    args = ["release", "download", HISTORY_TAG, "--repo", repo, "--dir", str(directory)]
    for name in sorted(names):
        args.extend(["--pattern", name])
    gh(*args)
    for name in names:
        path = directory / name
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError(f"Missing canonical history download: {name}")
        expected = str(assets[name].get("digest") or "")
        if not expected.startswith("sha256:") or _sha(path) != expected[7:]:
            raise ValueError(f"Canonical release asset checksum mismatch: {name}")
    bundle = json.loads((directory / "_tbt_bundle_manifest.json").read_text())
    inventory = bundle.get("files")
    if not isinstance(inventory, dict):
        raise ValueError("Invalid canonical history bundle manifest")
    # The bundle manifest cannot contain its own SHA-256 (self-reference).
    # Its digest is independently checked against GitHub release metadata
    # above. All DATA assets must be checksum-covered by the manifest.
    for name in sorted(names - {"_tbt_bundle_manifest.json"}):
        if (inventory.get(name) or {}).get("sha256") != _sha(directory / name):
            raise ValueError(f"Committed canonical history checksum mismatch: {name}")
    history_manifest = json.loads((directory / "history_manifest.json").read_text())
    history_years = history_manifest.get("years")
    if not isinstance(history_years, dict):
        raise ValueError("Missing authoritative canonical history year map")
    for year in years:
        if (history_years.get(str(year)) or {}).get("asset", f"history-{year}.parquet") != f"history-{year}.parquet":
            raise ValueError(f"Invalid year partition identity for {year}")
    matches = []
    for year in sorted(years):
        matches.extend(load_snapshot(directory / f"history-{year}.parquet"))
    return matches, {
        "source_release": HISTORY_TAG,
        "verified_partition_sha256": {
            str(year): _sha(directory / f"history-{year}.parquet") for year in sorted(years)
        },
        "provider_requests": 0,
    }


def settle(*, repo=DATA_REPO, workdir=None, now=None):
    if repo != DATA_REPO:
        raise ValueError("Unexpected CDB repository")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware settlement time required")
    now = now.astimezone(timezone.utc)
    base = Path(workdir or ROOT / ".cache/tbt/frozen-721-settlement")
    base.mkdir(parents=True, exist_ok=True)

    # A nonexistent private release is NOT a zero-row cohort. Fail closed.
    # Constructing a ReleaseStore can create a missing tag: probe it first.
    gh("api", f"repos/{repo}/releases/tags/{SHADOW_TAG}")
    store = ReleaseStore(repo, SHADOW_TAG, base / "ledger-preflight")
    store.download(
        extra_names=(LEDGER_ASSET, REPORT_ASSET),
        required_names=(LEDGER_ASSET, REPORT_ASSET),
        require_bundle_manifest=True,
    )
    source = json.loads((store.directory / LEDGER_ASSET).read_text())
    prod_version = (source.get("source") or {}).get("production_version")
    rows, before = validate_frozen_evidence(source, production_version=prod_version)
    rows = exclude_repeated_events(rows)
    pending = [r for r in rows if r.get("status") == "pending"]
    duplicate_exclusions = sum(r["status"] == "excluded" for r in rows) - before["excluded"]
    if not pending and not duplicate_exclusions:
        return {
            "status": "NO_PENDING_SHADOW_MATCHES", "counts": before,
            "provider_requests": 0, "production_mutated": False,
        }

    years = {_utc(r["scheduled_at"]).year for r in pending}
    history, history_evidence = download_verified_years(repo, base / "canonical", years)
    accepted, matching = completed_matches_for_pending(rows, history, now)
    diagnostics = pending_schedule_diagnostics(rows, history, now)

    if not accepted and not duplicate_exclusions:
        return {
            "status": "WAITING_FOR_VERIFIED_CANONICAL_RESULTS",
            "counts": before, "canonical_matching": {k: v for k, v in matching.items() if k != "provider_alias_evidence"},
            "pending_diagnostics": diagnostics,
            "canonical_provenance": history_evidence,
            "provider_requests": 0, "production_mutated": False,
        }

    lock_path = base / "research-global-lock.json"
    acquire(repo, lock_path, wait_seconds=1200, interval_seconds=20)
    try:
        # Re-read AFTER taking the cross-repo lock so an intervening normal
        # refresh cannot be accidentally overwritten.
        current = ReleaseStore(repo, SHADOW_TAG, base / "ledger-current")
        current.download(
            extra_names=(LEDGER_ASSET, REPORT_ASSET),
            required_names=(LEDGER_ASSET, REPORT_ASSET),
            require_bundle_manifest=True,
        )
        payload = json.loads((current.directory / LEDGER_ASSET).read_text())
        current_rows, current_counts = validate_frozen_evidence(
            payload, production_version=prod_version
        )
        unique_rows = exclude_repeated_events(current_rows)
        # Resolve again against the locked, re-read cohort, not stale preflight rows.
        accepted, matching = completed_matches_for_pending(unique_rows, history, now)
        updated = update_shadow_ledger(
            unique_rows, completed_matches=accepted, now=now
        )
        for row in updated:
            evidence = matching["provider_alias_evidence"].get(row["match_id"])
            if evidence and row.get("status") in {"settled", "void", "excluded"}:
                row["settlement_identity"] = evidence
        if len(updated) != len(current_rows):
            raise RuntimeError("Settlement may never append/remove paired predictions")
        for old, row in zip(current_rows, updated):
            for key in (
                "match_id", "event_id", "tour", "player1_id", "player2_id", "scheduled_at",
                "production_player1_probability", "challenger_player1_probability",
                "production_model_version", "challenger_model_version", "captured_at",
            ):
                if old[key] != row[key]:
                    raise RuntimeError(f"Settlement mutated immutable pre-match field: {key}")
        payload["rows"] = updated
        _, after = validate_frozen_evidence(payload, production_version=prod_version)
        newly = after["settled"] - current_counts["settled"]
        new_void = after["void"] - current_counts["void"]
        new_excluded = after["excluded"] - current_counts["excluded"]
        if min(newly, new_void, new_excluded) < 0:
            raise RuntimeError("Previously evaluated frozen shadow rows were changed")
        if not (newly or new_void or new_excluded):
            return {
                "status": "NO_NEW_VERIFIED_SETTLEMENTS",
                "counts": after, "canonical_matching": {k: v for k, v in matching.items() if k != "provider_alias_evidence"},
                "pending_diagnostics": diagnostics,
                "provider_requests": 0, "production_mutated": False,
            }
        report = research_frozen_721(payload, production_version=prod_version)
        report["preliminary"] = preliminary_scoreboard(updated)
        report["canonical_provenance"] = history_evidence
        report["canonical_matching"] = matching
        report["pending_diagnostics_before_settlement"] = diagnostics
        report["new_settled"] = newly
        report["new_void"] = new_void
        report["new_excluded"] = new_excluded
        report["provider_requests"] = 0
        report["automatic_promotion"] = False
        files = [
            (LEDGER_ASSET, json.dumps(payload, sort_keys=True, allow_nan=False)+"\n"),
            (REPORT_ASSET, json.dumps(report, sort_keys=True, allow_nan=False)+"\n"),
        ]
        for filename, contents in files:
            (current.directory / filename).write_text(contents, encoding="utf-8")
        current.upload_bundle([current.directory / filename for filename, _ in files])

        # Independent post-upload download; never treat a local write as a
        # successful settlement if the remote release is missing/corrupted.
        remote = ReleaseStore(repo, SHADOW_TAG, base / "ledger-readback")
        remote.download(
            extra_names=(LEDGER_ASSET, REPORT_ASSET),
            required_names=(LEDGER_ASSET, REPORT_ASSET),
            require_bundle_manifest=True,
        )
        for filename, _ in files:
            if (remote.directory / filename).read_bytes() != (current.directory / filename).read_bytes():
                raise RuntimeError(f"Frozen shadow settlement remote readback mismatch: {filename}")
        readback = json.loads((remote.directory / LEDGER_ASSET).read_text())
        _, remote_counts = validate_frozen_evidence(readback, production_version=prod_version)
        if remote_counts != after:
            raise RuntimeError("Frozen shadow readback counts differ")
        return {
            "status": "VERIFIED_SETTLEMENT_PUBLISHED",
            "remote_readback": "VERIFIED",
            "counts": remote_counts,
            "new_settled": newly,
            "new_void": new_void,
            "new_excluded": new_excluded,
            "candidate_minus_champion": report["preliminary"]["groups"]["overall"]["candidate_minus_champion"],
            "canonical_matching": {k: v for k, v in matching.items() if k != "provider_alias_evidence"},
            "pending_diagnostics_before_settlement": diagnostics,
            "provider_requests": 0, "production_mutated": False,
            "automatic_promotion": False,
        }
    finally:
        release(repo, lock_path, if_held=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=DATA_REPO)
    parser.add_argument("--out", default=".cache/tbt/frozen-721-settlement-status.json")
    args = parser.parse_args()
    result = settle(repo=args.data_repository)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n",
        encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
