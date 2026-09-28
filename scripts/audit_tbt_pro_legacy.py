#!/usr/bin/env python3
"""Audit legacy tbt-pro data against the current canonical BlinQ history.

Read-only. Produces summary evidence plus candidate sidecars; never mutates history.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities


def norm_name(value: Any) -> str:
    text = str(value or "").strip().translate(str.maketrans({
        "ł":"l","Ł":"L","đ":"d","Đ":"D","ð":"d","Ð":"D","þ":"th","Þ":"Th",
        "ß":"ss","ø":"o","Ø":"O","æ":"ae","Æ":"Ae","œ":"oe","Œ":"Oe",
    })).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def canonical_event_id(match: Any) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    candidates = []
    identity = payload.get("_tbt_event_identity")
    if isinstance(identity, dict):
        candidates.append(identity.get("event_id"))
    for key in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id"):
        candidates.append(payload.get(key))
    event = payload.get("event")
    if isinstance(event, dict):
        candidates.append(event.get("id"))
    for value in candidates:
        if value not in (None, ""):
            return str(value)
    return None


def pair_key(a: Any, b: Any) -> tuple[str, str]:
    return tuple(sorted((norm_name(a), norm_name(b))))


def match_orientation(match: Any, p1: str, p2: str) -> str | None:
    a, b = norm_name(p1), norm_name(p2)
    m1, m2 = norm_name(match.player1_name), norm_name(match.player2_name)
    if a == m1 and b == m2:
        return "direct"
    if a == m2 and b == m1:
        return "swapped"
    return None


def score_summary(event: dict[str, Any], orientation: str) -> dict[str, Any]:
    home = event.get("homeScore") if isinstance(event.get("homeScore"), dict) else {}
    away = event.get("awayScore") if isinstance(event.get("awayScore"), dict) else {}
    periods = []
    for i in range(1, 6):
        hk = f"period{i}"
        ak = f"period{i}"
        if home.get(hk) is None or away.get(ak) is None:
            continue
        periods.append({
            "set": i,
            "home_games": home.get(hk),
            "away_games": away.get(ak),
            "home_tiebreak": home.get(f"period{i}TieBreak"),
            "away_tiebreak": away.get(f"period{i}TieBreak"),
        })
    if orientation == "direct":
        p1_score, p2_score = home, away
    else:
        p1_score, p2_score = away, home
    total_games = 0
    for row in periods:
        try:
            total_games += int(row["home_games"]) + int(row["away_games"])
        except Exception:
            pass
    return {
        "periods": periods,
        "total_sets": len(periods) or None,
        "total_games": total_games or None,
        "p1_sets": p1_score.get("current"),
        "p2_sets": p2_score.get("current"),
    }


def write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--legacy-dir", default=".cache/tbt-pro")
    ap.add_argument("--out-dir", default=".cache/tbt/legacy-audit")
    args = ap.parse_args()

    history_dir = Path(args.history_dir)
    legacy = Path(args.legacy_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load_partitions(history_dir)
    matches, identity = sanitize_history_identities(raw)

    by_event: dict[str, list[Any]] = defaultdict(list)
    by_pair_date: dict[tuple[tuple[str, str], str], list[Any]] = defaultdict(list)
    for match in matches:
        eid = canonical_event_id(match)
        if eid:
            by_event[eid].append(match)
        date = match.scheduled_at.astimezone(timezone.utc).date().isoformat()
        by_pair_date[(pair_key(match.player1_name, match.player2_name), date)].append(match)

    canonical = {
        "rows": len(matches),
        "with_provider_event_id": sum(1 for m in matches if canonical_event_id(m)),
        "unique_provider_event_ids": len(by_event),
        "duplicate_provider_event_ids": sum(1 for rows in by_event.values() if len(rows) > 1),
        "identity_safety": identity,
    }

    # ------------------------------------------------------------------
    # Market snapshot audit
    # ------------------------------------------------------------------
    market_dir = legacy / "data" / "marq_ai" / "odds_snapshots" / "events"
    market_files = sorted(market_dir.glob("*.json"))
    grouped: dict[str, dict[str, Any]] = {}
    market_parse_errors = 0
    for path in market_files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            market_parse_errors += 1
            continue
        eid = str(doc.get("event_id") or "")
        if not eid:
            eid = f"file:{path.name}"
        bucket = grouped.setdefault(eid, {
            "event_id": str(doc.get("event_id") or ""),
            "player1": doc.get("player1"),
            "player2": doc.get("player2"),
            "start_time_utc": doc.get("start_time_utc"),
            "files": [],
            "snapshots": [],
        })
        bucket["files"].append(path.name)
        if not bucket.get("player1") and doc.get("player1"):
            bucket["player1"] = doc.get("player1")
        if not bucket.get("player2") and doc.get("player2"):
            bucket["player2"] = doc.get("player2")
        if not bucket.get("start_time_utc") and doc.get("start_time_utc"):
            bucket["start_time_utc"] = doc.get("start_time_utc")
        snaps = doc.get("snapshots") if isinstance(doc.get("snapshots"), list) else []
        bucket["snapshots"].extend(s for s in snaps if isinstance(s, dict))

    market_counts = Counter()
    movement_sizes: list[float] = []
    market_candidates: list[dict[str, Any]] = []

    for eid, event in grouped.items():
        market_counts["unique_events"] += 1
        if len(event["files"]) > 1:
            market_counts["duplicate_event_files_collapsed"] += 1
        p1, p2 = str(event.get("player1") or ""), str(event.get("player2") or "")
        start = parse_dt(event.get("start_time_utc"))

        canon = by_event.get(str(event.get("event_id") or ""), [])
        link_method = None
        match = None
        if len(canon) == 1:
            match = canon[0]
            link_method = "event_id"
            market_counts["linked_by_event_id"] += 1
        elif len(canon) > 1:
            market_counts["ambiguous_event_id"] += 1
        else:
            date_candidates: list[Any] = []
            if start:
                pk = pair_key(p1, p2)
                for off in (-1, 0, 1):
                    day = (start.date() + timedelta(days=off)).isoformat()
                    date_candidates.extend(by_pair_date.get((pk, day), []))
                # Deduplicate object identities through match_id.
                uniq = {m.match_id: m for m in date_candidates}
                date_candidates = list(uniq.values())
            if len(date_candidates) == 1:
                match = date_candidates[0]
                link_method = "pair_date"
                market_counts["linked_by_pair_date"] += 1
            elif len(date_candidates) > 1:
                market_counts["ambiguous_pair_date"] += 1
            else:
                market_counts["unmatched"] += 1

        orientation = match_orientation(match, p1, p2) if match else None
        if match and orientation:
            market_counts["orientation_verified"] += 1
        elif match:
            market_counts["orientation_unverified"] += 1

        # Deduplicate snapshots and keep only legitimate pre-match observations.
        unique_snaps: dict[tuple[Any, ...], dict[str, Any]] = {}
        for s in event["snapshots"]:
            sig = (
                s.get("snapshot_time_utc"), s.get("odds_player1"), s.get("odds_player2"),
                s.get("snapshot_source"), s.get("provider_name"),
            )
            unique_snaps[sig] = s
        snapshots = list(unique_snaps.values())
        market_counts["snapshots_total"] += len(snapshots)

        pre: list[tuple[datetime, dict[str, Any]]] = []
        post = 0
        for s in snapshots:
            ts = parse_dt(s.get("snapshot_time_utc"))
            if not ts:
                continue
            is_pre = True
            if start is not None:
                is_pre = ts <= start
            elif as_float(s.get("hours_to_start")) is not None:
                is_pre = float(s["hours_to_start"]) >= 0.0
            if is_pre:
                pre.append((ts, s))
            else:
                post += 1
        pre.sort(key=lambda x: x[0])
        market_counts["pre_match_snapshots"] += len(pre)
        market_counts["post_start_snapshots_excluded"] += post
        if pre:
            market_counts["events_with_pre_match_snapshot"] += 1
        if len(pre) >= 2:
            market_counts["events_with_multi_snapshot_pre_match"] += 1

        provider_initial = None
        for _, s in pre:
            i1, i2 = as_float(s.get("initial_odds_player1")), as_float(s.get("initial_odds_player2"))
            if i1 and i2 and i1 > 1 and i2 > 1:
                provider_initial = (i1, i2)
                break
        if provider_initial:
            market_counts["events_with_provider_initial_opening"] += 1

        first = pre[0][1] if pre else None
        last = pre[-1][1] if pre else None
        if first and last:
            f1, f2 = as_float(first.get("odds_player1")), as_float(first.get("odds_player2"))
            l1, l2 = as_float(last.get("odds_player1")), as_float(last.get("odds_player2"))
            if all(v is not None and v > 1 for v in (f1, f2, l1, l2)):
                market_counts["events_with_valid_first_and_last_odds"] += 1
                if abs(float(f1)-float(l1)) > 1e-12 or abs(float(f2)-float(l2)) > 1e-12:
                    market_counts["events_with_observed_movement"] += 1
                    movement_sizes.append(abs(float(l1)-float(f1)) + abs(float(l2)-float(f2)))

        if match and orientation and pre and first and last:
            def orient_pair(a: float | None, b: float | None) -> tuple[float | None, float | None]:
                return (a, b) if orientation == "direct" else (b, a)
            fo1, fo2 = orient_pair(as_float(first.get("odds_player1")), as_float(first.get("odds_player2")))
            lp1, lp2 = orient_pair(as_float(last.get("odds_player1")), as_float(last.get("odds_player2")))
            po1 = po2 = None
            if provider_initial:
                po1, po2 = orient_pair(provider_initial[0], provider_initial[1])
            market_candidates.append({
                "schema": 1,
                "match_id": match.match_id,
                "provider_event_id": str(event.get("event_id") or ""),
                "link_method": link_method,
                "orientation": orientation,
                "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                "player1_name": match.player1_name,
                "player2_name": match.player2_name,
                "legacy_player1": p1,
                "legacy_player2": p2,
                "first_observed": {
                    "time_utc": first.get("snapshot_time_utc"),
                    "odds_p1": fo1,
                    "odds_p2": fo2,
                    "source": first.get("snapshot_source"),
                },
                "last_pre_match": {
                    "time_utc": last.get("snapshot_time_utc"),
                    "odds_p1": lp1,
                    "odds_p2": lp2,
                    "source": last.get("snapshot_source"),
                },
                "provider_initial_opening": {
                    "odds_p1": po1,
                    "odds_p2": po2,
                } if provider_initial else None,
                "pre_match_snapshot_count": len(pre),
                "opening_quality": "PROVIDER_INITIAL" if provider_initial else "FIRST_OBSERVED_ONLY",
                "source_repository": "BackstageTalks/tbt-pro",
            })

    market_summary = {
        "event_files": len(market_files),
        "parse_errors": market_parse_errors,
        "counts": dict(market_counts),
        "candidate_rows": len(market_candidates),
        "candidate_provider_initial": sum(1 for r in market_candidates if r["opening_quality"] == "PROVIDER_INITIAL"),
        "candidate_first_observed_only": sum(1 for r in market_candidates if r["opening_quality"] == "FIRST_OBSERVED_ONLY"),
        "observed_movement_mean_abs_odds_sum": (sum(movement_sizes)/len(movement_sizes) if movement_sizes else None),
        "policy": {
            "provider_initial_opening": "safe as true provider opening when explicitly present in snapshot payload",
            "first_observed": "usable as first-observed market snapshot only; never label as bookmaker opening",
            "last_pre_match": "latest stored snapshot at or before event start only",
            "post_start": "excluded",
        },
    }

    # ------------------------------------------------------------------
    # Previous-matches cache audit
    # ------------------------------------------------------------------
    prev_dir = legacy / "blinq" / "data" / "form" / "previous_matches"
    prev_files = sorted(prev_dir.glob("*.json"))
    prev_events: dict[str, dict[str, Any]] = {}
    prev_counts = Counter()
    prev_parse_errors = 0
    for path in prev_files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            prev_parse_errors += 1
            continue
        events = doc.get("events") if isinstance(doc.get("events"), list) else []
        prev_counts["raw_event_rows"] += len(events)
        for event in events:
            if not isinstance(event, dict):
                continue
            eid = str(event.get("id") or "")
            if not eid:
                continue
            home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
            away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
            categories = event.get("eventFilters") if isinstance(event.get("eventFilters"), dict) else {}
            category = categories.get("category")
            singles = (
                home.get("type") == 1 and away.get("type") == 1
                and (not isinstance(category, list) or "singles" in [str(x).lower() for x in category])
            )
            if not singles:
                prev_counts["non_singles_excluded"] += 1
                continue
            if eid not in prev_events:
                prev_events[eid] = event

    previous_candidates: list[dict[str, Any]] = []
    for eid, event in prev_events.items():
        prev_counts["unique_singles_events"] += 1
        canon = by_event.get(eid, [])
        if len(canon) != 1:
            if len(canon) > 1:
                prev_counts["ambiguous_event_id"] += 1
            else:
                prev_counts["unmatched_event_id"] += 1
            continue
        match = canon[0]
        home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
        away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
        orientation = match_orientation(match, home.get("name"), away.get("name"))
        if not orientation:
            prev_counts["orientation_unverified"] += 1
            continue
        prev_counts["linked_orientation_verified"] += 1

        stats = match.stats if isinstance(match.stats, dict) else {}
        missing_score = not all(stats.get(k) is not None for k in ("total_sets", "total_games"))
        missing_round = not str(match.round_name or "").strip()
        missing_surface = str(match.surface or "").strip().lower() in {"", "unknown", "none"}
        round_info = event.get("roundInfo") if isinstance(event.get("roundInfo"), dict) else {}
        score = score_summary(event, orientation)
        score_available = score.get("total_sets") is not None and score.get("total_games") is not None
        if score_available:
            prev_counts["linked_with_structured_score_available"] += 1
        if missing_score and score_available:
            prev_counts["score_fill_candidates"] += 1
        if missing_round and round_info.get("name"):
            prev_counts["round_fill_candidates"] += 1
        if missing_surface and event.get("groundType"):
            prev_counts["surface_fill_candidates"] += 1

        if (missing_score and score_available) or (missing_round and round_info.get("name")) or (missing_surface and event.get("groundType")):
            previous_candidates.append({
                "schema": 1,
                "match_id": match.match_id,
                "provider_event_id": eid,
                "orientation": orientation,
                "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                "player1_name": match.player1_name,
                "player2_name": match.player2_name,
                "candidate_score": score if missing_score and score_available else None,
                "candidate_round_name": round_info.get("name") if missing_round else None,
                "candidate_surface_raw": event.get("groundType") if missing_surface else None,
                "winner_code": event.get("winnerCode"),
                "start_timestamp": event.get("startTimestamp"),
                "source_repository": "BackstageTalks/tbt-pro",
                "source_family": "API_PRO_PREVIOUS_MATCHES_CACHE",
            })

    previous_summary = {
        "cache_files": len(prev_files),
        "parse_errors": prev_parse_errors,
        "counts": dict(prev_counts),
        "candidate_rows": len(previous_candidates),
        "safety": {
            "ranking_fields": "not proposed for historical import: cached player ranking may reflect retrieval-time state rather than match-time provenance",
            "score_round_surface": "candidate only when event_id and orientation are exact",
        },
    }

    # ------------------------------------------------------------------
    # Player registry / alias / TA profile / Elo inventory
    # ------------------------------------------------------------------
    def load_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    registry_path = legacy / "thinq" / "data" / "players" / "player_registry.json"
    alias_path = legacy / "thinq" / "data" / "players" / "tennis_name_alias_database.json"
    ta_path = legacy / "thinq" / "data" / "ta_profiles" / "ta_player_profiles.json"
    elo_path = legacy / "thinq" / "data" / "elo" / "ta_elo_ratings.json"

    registry = load_json(registry_path)
    aliases = load_json(alias_path)
    ta = load_json(ta_path)
    elo = load_json(elo_path)

    def dict_or_list_count(value: Any, preferred: tuple[str, ...] = ()) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for key in preferred:
                v = value.get(key)
                if isinstance(v, (list, dict)):
                    return len(v)
            return len(value)
        return 0

    elo_players = elo.get("players", {}) if isinstance(elo, dict) and isinstance(elo.get("players"), dict) else {}
    elo_cov = Counter()
    elo_tours = Counter()
    elo_updated = []
    for row in elo_players.values():
        if not isinstance(row, dict):
            continue
        tour = str(row.get("tour") or "unknown").lower()
        elo_tours[tour] += 1
        for key in ("elo", "hard_elo", "clay_elo", "grass_elo", "yelo", "hard_yelo", "clay_yelo", "grass_yelo"):
            if row.get(key) is not None:
                elo_cov[key] += 1
        if row.get("updated_at"):
            elo_updated.append(str(row.get("updated_at")))

    player_inventory = {
        "registry_path": str(registry_path.relative_to(legacy)) if registry_path.exists() else None,
        "registry_records": dict_or_list_count(registry, ("players", "registry", "items")),
        "alias_path": str(alias_path.relative_to(legacy)) if alias_path.exists() else None,
        "alias_records": dict_or_list_count(aliases, ("aliases", "players", "items")),
        "ta_profile_path": str(ta_path.relative_to(legacy)) if ta_path.exists() else None,
        "ta_profile_records": dict_or_list_count(ta, ("players", "profiles", "items")),
        "elo_path": str(elo_path.relative_to(legacy)) if elo_path.exists() else None,
        "elo_players": len(elo_players),
        "elo_tours": dict(elo_tours),
        "elo_field_coverage": dict(elo_cov),
        "elo_snapshot_min_updated_at": min(elo_updated) if elo_updated else None,
        "elo_snapshot_max_updated_at": max(elo_updated) if elo_updated else None,
        "tennis_abstract_sources": {
            "atp_elo": "https://tennisabstract.com/reports/atp_elo_ratings.html",
            "wta_elo": "https://tennisabstract.com/reports/wta_elo_ratings.html",
            "atp_season_yelo": "https://tennisabstract.com/reports/atp_season_yelo_ratings.html",
            "wta_season_yelo": "https://tennisabstract.com/reports/wta_season_yelo_ratings.html",
        },
        "yelo_cached_in_legacy_repo": bool(elo_cov.get("yelo")),
        "policy": {
            "current_elo_yelo": "current/live sidecar only unless snapshot timestamp is before target match",
            "historical_training": "never backfill current TA ratings into past matches; use historical snapshots or reconstruct ratings point-in-time",
        },
    }

    report = {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "zero_provider_api_requests": True,
        "legacy_repository": "BackstageTalks/tbt-pro",
        "canonical": canonical,
        "market": market_summary,
        "previous_matches": previous_summary,
        "player_identity_and_ta": player_inventory,
        "recommended_order": [
            "market-v1 sidecar from exact event-id/orientation verified pre-match snapshots",
            "previous-match exact score/round/surface gap fill dry-run",
            "player alias/registry bridge for unresolved identities",
            "TA current Elo/yElo scheduled snapshots for future point-in-time history",
        ],
    }

    write_jsonl_gz(out_dir / "market_candidates.jsonl.gz", market_candidates)
    write_jsonl_gz(out_dir / "previous_match_candidates.jsonl.gz", previous_candidates)
    (out_dir / "legacy_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
