"""Quota-safe paid Live Tennis API history collector for canonical quality gaps.

The public Zenodo sample is kept as an audit source, but it added no new
quality-ready canonical matches. This collector therefore uses the paid history
API only when /usage proves the expected daily entitlement.

It is deliberately fail-closed:
- exact UTC date + exact normalized player pair only;
- unique canonical match required;
- provider must explicitly expose a complete point basis;
- only server/winner point facts are used for serve/return rates;
- no fuzzy identity or inferred server;
- existing conflicting statistics are never overwritten.
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text
from tbt.errors import ProviderError
from tbt.models.feature_builder import FeatureBuilder
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.livetennisapi import LiveTennisApiClient


def _quality(stats: dict) -> bool:
    return all(
        FeatureBuilder._extract_quality(stats or {}, side)[0] is not None
        and FeatureBuilder._extract_quality(stats or {}, side)[1] is not None
        for side in ("p1", "p2")
    )


def _signature(match) -> dict[str, str]:
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _pair(a: Any, b: Any) -> tuple[str, str]:
    return tuple(sorted((norm_text(str(a or "")), norm_text(str(b or "")))))


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _player_names(source_match: dict[str, Any]) -> tuple[str, str] | None:
    players = source_match.get("players")
    if not isinstance(players, dict):
        return None
    p1 = players.get("p1")
    p2 = players.get("p2")
    if not isinstance(p1, dict) or not isinstance(p2, dict):
        return None
    n1 = str(p1.get("name") or "").strip()
    n2 = str(p2.get("name") or "").strip()
    if not n1 or not n2:
        return None
    return n1, n2


def _canonical_index(matches):
    index: dict[tuple[str, tuple[str, str]], list] = defaultdict(list)
    for match in matches:
        if _quality(dict(match.stats or {})):
            continue
        index[(match.scheduled_at.date().isoformat(), _pair(match.player1_name, match.player2_name))].append(match)
    return index


def _resolve_match(source_match: dict[str, Any], index):
    names = _player_names(source_match)
    scheduled = _parse_time(source_match.get("scheduled_time"))
    if names is None or scheduled is None:
        return None, "source_identity_unusable"
    candidates = list(index.get((scheduled.date().isoformat(), _pair(*names)), []))
    if not candidates:
        return None, "unmatched"

    source_tour = str(source_match.get("tour") or "").strip().lower()
    if source_tour and len(candidates) > 1:
        exact = [m for m in candidates if str(m.tour or "").lower() == source_tour]
        if exact:
            candidates = exact

    source_surface = norm_text(source_match.get("surface"))
    if source_surface and len(candidates) > 1:
        exact = [m for m in candidates if norm_text(m.surface) == source_surface]
        if exact:
            candidates = exact

    source_tournament = norm_text(source_match.get("tournament"))
    if source_tournament and len(candidates) > 1:
        exact = [m for m in candidates if norm_text(m.tournament) == source_tournament]
        if exact:
            candidates = exact

    if len(candidates) != 1:
        return None, "ambiguous"
    return candidates[0], ""


def _explicit_complete(payload: dict[str, Any]) -> bool:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return False
    points = meta.get("points")
    if isinstance(points, dict) and points.get("available_complete") is True:
        return True
    return meta.get("points_complete") is True


def _derive_rates(tape: list[dict[str, Any]]) -> tuple[dict[int, dict[str, float]] | None, dict[str, int]]:
    counts = {
        1: Counter(),
        2: Counter(),
    }
    audit = Counter()
    for row in tape:
        if not isinstance(row, dict):
            audit["invalid_rows"] += 1
            continue
        winner = row.get("winner")
        if winner in (None, ""):
            winner = row.get("point_winner")
        try:
            winner = int(winner)
        except (TypeError, ValueError):
            winner = None
        if winner not in (1, 2):
            audit["non_point_rows"] += 1
            continue
        try:
            server = int(row.get("server"))
        except (TypeError, ValueError):
            server = None
        if server not in (1, 2):
            audit["point_rows_missing_server"] += 1
            continue
        receiver = 3 - server
        counts[server]["service_points"] += 1
        counts[receiver]["return_points"] += 1
        if winner == server:
            counts[server]["service_won"] += 1
        else:
            counts[receiver]["return_won"] += 1
        audit["usable_points"] += 1

    if audit["point_rows_missing_server"]:
        return None, dict(audit)
    if audit["usable_points"] < 40:
        audit["too_few_points"] += 1
        return None, dict(audit)

    rates: dict[int, dict[str, float]] = {}
    for side in (1, 2):
        sp = int(counts[side]["service_points"])
        rp = int(counts[side]["return_points"])
        if sp <= 0 or rp <= 0:
            audit["missing_denominator"] += 1
            return None, dict(audit)
        rates[side] = {
            "service_points_won": float(counts[side]["service_won"]) / sp,
            "return_points_won": float(counts[side]["return_won"]) / rp,
        }
    return rates, dict(audit)


def _winner_name(match) -> str:
    wid = str(match.winner_id or "")
    if wid == str(match.player1_id):
        return norm_text(match.player1_name)
    if wid == str(match.player2_id):
        return norm_text(match.player2_name)
    return ""


def _stage_row(source_payload: dict[str, Any], canonical) -> tuple[dict[str, Any] | None, str, dict[str, int]]:
    if not _explicit_complete(source_payload):
        return None, "complete_basis_not_explicit", {}
    source_match = source_payload.get("match")
    tape = source_payload.get("tape")
    if not isinstance(source_match, dict) or not isinstance(tape, list):
        return None, "invalid_tape_payload", {}

    names = _player_names(source_match)
    if names is None:
        return None, "source_identity_unusable", {}
    n1, n2 = map(norm_text, names)
    cp1, cp2 = norm_text(canonical.player1_name), norm_text(canonical.player2_name)
    if n1 == cp1 and n2 == cp2:
        mapping = ((1, "p1"), (2, "p2"))
    elif n1 == cp2 and n2 == cp1:
        mapping = ((1, "p2"), (2, "p1"))
    else:
        return None, "orientation_failed", {}

    source_winner = source_match.get("winner")
    try:
        source_winner = int(source_winner)
    except (TypeError, ValueError):
        source_winner = None
    if source_winner in (1, 2):
        source_winner_name = n1 if source_winner == 1 else n2
        canonical_winner = _winner_name(canonical)
        if canonical_winner and source_winner_name != canonical_winner:
            return None, "winner_mismatch", {}

    rates, rate_audit = _derive_rates(tape)
    if rates is None:
        return None, "point_facts_incomplete", rate_audit

    incoming = {}
    for source_side, prefix in mapping:
        incoming[f"{prefix}_service_points_won"] = rates[source_side]["service_points_won"]
        incoming[f"{prefix}_return_points_won"] = rates[source_side]["return_points_won"]

    existing = dict(canonical.stats or {})
    if _quality(existing):
        return None, "already_quality_ready", rate_audit
    conflicts = [
        key for key, value in incoming.items()
        if existing.get(key) is not None
        and abs(float(existing[key]) - float(value)) > 0.02
    ]
    if conflicts:
        return None, "stat_conflicts", rate_audit

    clean = {key: value for key, value in incoming.items() if existing.get(key) is None}
    projected = dict(existing)
    projected.update(clean)
    if not clean:
        return None, "already_present", rate_audit
    if not _quality(projected):
        return None, "partial_only_no_quality_gain", rate_audit

    return {
        "schema": 1,
        "match_id": str(canonical.match_id),
        "canonical": _signature(canonical),
        "incoming_stats": clean,
        "provenance": [{
            "source": "live_tennis_api_paid_history",
            "provider_match_id": source_match.get("id"),
            "evidence": [
                "scheduled_date_utc_exact",
                "player_pair_exact",
                "canonical_candidate_unique",
                "provider_points_complete_true",
                "server_and_point_winner_explicit",
            ],
        }],
        "import_ready": True,
    }, "", rate_audit


def _meta_count(payload: dict[str, Any]) -> int | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    try:
        value = int(meta.get("count"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-calls", type=int, default=700)
    ap.add_argument("--daily-reserve", type=int, default=200)
    ap.add_argument("--expected-min-daily", type=int, default=1000)
    ap.add_argument("--target-new", type=int, default=450)
    ap.add_argument("--max-list-pages-per-tour", type=int, default=60)
    ap.add_argument("--tours", default="wta,itf,challenger,atp")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    canonical, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")
    index = _canonical_index(canonical)
    before = sum(1 for match in canonical if _quality(dict(match.stats or {})))

    counts = Counter()
    review = []
    staged_by_match: dict[str, dict[str, Any]] = {}
    usage_initial = {}
    coverage = {}
    stop_reason = ""
    raw_path = out / "raw-tapes.jsonl.gz"

    client = LiveTennisApiClient(
        max_calls=args.max_calls,
        daily_reserve=args.daily_reserve,
        usage_ttl_seconds=3600,
        timeout_seconds=30,
    )
    try:
        usage_initial = client.usage(force=True)
        limits = usage_initial.get("limits") or {}
        today = usage_initial.get("today") or {}
        per_day = int(limits.get("per_day") or 0)
        remaining = int(today.get("remaining_day") or 0)
        if per_day < args.expected_min_daily:
            raise SystemExit(
                f"Live Tennis API daily entitlement is {per_day}, expected at least {args.expected_min_daily}"
            )
        if remaining <= args.daily_reserve:
            stop_reason = "daily_reserve_already_reached"
        per_minute = max(1, int(limits.get("per_minute") or 60))
        interval = min(2.0, 63.0 / per_minute)
        last_billable = [0.0]

        def paced(callable_, *call_args, **call_kwargs):
            wait = interval - (time.monotonic() - last_billable[0])
            if wait > 0:
                time.sleep(wait)
            result = callable_(*call_args, **call_kwargs)
            last_billable[0] = time.monotonic()
            return result

        if not stop_reason:
            coverage = paced(client.history_coverage)
            counts["coverage_calls"] += 1

        with gzip.open(raw_path, "wt", encoding="utf-8") as raw_handle:
            for tour in [part.strip().lower() for part in args.tours.split(",") if part.strip()]:
                if stop_reason or len(staged_by_match) >= args.target_new:
                    break
                offset = 0
                for _page in range(max(1, args.max_list_pages_per_tour)):
                    if len(staged_by_match) >= args.target_new:
                        stop_reason = "target_new_reached"
                        break
                    try:
                        listing = paced(
                            client.history_matches,
                            from_date=args.from_date,
                            to_date=args.to_date,
                            tour=tour,
                            draw="singles",
                            points_complete=True,
                            limit=100,
                            offset=offset,
                        )
                    except RequestBudgetExceeded as exc:
                        stop_reason = "budget_guard:" + str(exc)
                        break
                    counts["list_calls"] += 1
                    rows = listing.get("data") if isinstance(listing, dict) else None
                    rows = rows if isinstance(rows, list) else []
                    total = _meta_count(listing)
                    counts["listed_rows"] += len(rows)

                    for source_match in rows:
                        if not isinstance(source_match, dict):
                            counts["invalid_listing_rows"] += 1
                            continue
                        canonical_match, reason = _resolve_match(source_match, index)
                        if canonical_match is None:
                            counts[reason] += 1
                            continue
                        mid = str(canonical_match.match_id)
                        if mid in staged_by_match:
                            counts["duplicate_canonical_candidate"] += 1
                            continue

                        provider_id = source_match.get("id")
                        if provider_id in (None, ""):
                            counts["provider_id_missing"] += 1
                            continue
                        try:
                            tape_payload = paced(client.history_tape, provider_id, complete=True)
                        except RequestBudgetExceeded as exc:
                            stop_reason = "budget_guard:" + str(exc)
                            break
                        counts["tape_calls"] += 1
                        raw_handle.write(json.dumps(tape_payload, ensure_ascii=False) + "\n")

                        source_from_tape = tape_payload.get("match")
                        if not isinstance(source_from_tape, dict):
                            counts["invalid_tape_payload"] += 1
                            continue
                        resolved_again, reason = _resolve_match(source_from_tape, index)
                        if resolved_again is None or str(resolved_again.match_id) != mid:
                            counts["tape_identity_changed"] += 1
                            review.append({
                                "provider_match_id": provider_id,
                                "match_id": mid,
                                "reason": reason or "tape_identity_changed",
                            })
                            continue

                        staged, reason, point_audit = _stage_row(tape_payload, canonical_match)
                        for key, value in point_audit.items():
                            counts[f"point_{key}"] += int(value)
                        if staged is None:
                            counts[reason] += 1
                            if reason in {"stat_conflicts", "winner_mismatch", "orientation_failed"}:
                                review.append({
                                    "provider_match_id": provider_id,
                                    "match_id": mid,
                                    "reason": reason,
                                })
                            continue
                        staged_by_match[mid] = staged
                        counts["staged_matches"] += 1

                    if stop_reason:
                        break
                    offset += 100
                    if total is not None and offset >= total:
                        break
                    if total is None and not rows:
                        counts["empty_pages_without_count"] += 1
                        if counts["empty_pages_without_count"] >= 3:
                            break

        usage_final = client.usage(force=True)
    except ProviderError as exc:
        raise SystemExit(f"Live Tennis API provider error: {exc}") from exc
    finally:
        client.close()

    staged = list(staged_by_match.values())
    with (out / "auto_linked.jsonl").open("w", encoding="utf-8") as handle:
        for row in staged:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "review.jsonl").open("w", encoding="utf-8") as handle:
        for row in review:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Live Tennis API paid history",
        "canonical_rows": len(canonical),
        "quality_ready_before": before,
        "quality_ready_projected_after": before + len(staged),
        "quality_ready_projected_added": len(staged),
        "counts": dict(counts),
        "usage_initial": usage_initial,
        "usage_final": usage_final if "usage_final" in locals() else None,
        "coverage": coverage,
        "configured": {
            "from": args.from_date,
            "to": args.to_date,
            "max_calls": args.max_calls,
            "daily_reserve": args.daily_reserve,
            "expected_min_daily": args.expected_min_daily,
            "target_new": args.target_new,
            "tours": [part.strip() for part in args.tours.split(",") if part.strip()],
        },
        "stop_reason": stop_reason or "source_exhausted",
        "production_mutated": False,
        "raw_redistribution": False,
        "link_policy": (
            "exact UTC date + exact normalized player pair; unique canonical match; "
            "provider complete point basis; explicit server and point winner only"
        ),
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
