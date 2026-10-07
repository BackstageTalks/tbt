"""Prepare alimoh89 Tennis Results and Betting Odds 2014-2025 for BlinQ.

License-gated preparation only:
- verifies source identity and exact bytes upstream in CI;
- maps rows to canonical history using date/player/tour/tournament/surface/round/winner;
- extracts opening and recorded-final market snapshots to ephemeral staging;
- excludes score/result/completed-derived fields from feature payloads;
- writes reports/review/quarantine locally only;
- never mutates canonical history and never promotes a model.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import (
    decimal_odds,
    legacy_name_matches,
    norm_round,
    norm_surface,
    norm_text,
    round_evidence,
    source_match_id,
    tournament_score,
)

SOURCE_SLUG = "alimoh89/tennis-results-and-betting-odds-20142025"
SOURCE_LABEL = "kaggle_alimoh89_tennis_results_odds_2014_2025"
SOURCE_FILE = "tennis_matches_2014_2025.csv"

BOOKS = {
    "bet365": {
        "money_open": ("bet365_odds_a_opening", "bet365_odds_b_opening"),
        "money_final": ("bet365_odds_a", "bet365_odds_b"),
        "handicap_open": ("bet365_odds_handicap_a_opening", "bet365_odds_handicap_b_opening"),
        "handicap_final": ("bet365_odds_handicap_a", "bet365_odds_handicap_b"),
        "handicap_line": "bet365_handicap",
        "total_open": ("bet365_odds_over_opening", "bet365_odds_under_opening"),
        "total_final": ("bet365_odds_over", "bet365_odds_under"),
        "total_line": "bet365_total_games_line",
    },
    "betfair": {
        "money_open": ("Betfair_odds_a_opening", "Betfair_odds_b_opening"),
        "money_final": ("Betfair_odds_a", "Betfair_odds_b"),
    },
    "ladbrokes": {
        "money_open": ("Ladbrokes_odds_a_opening", "Ladbrokes_odds_b_opening"),
        "money_final": ("Ladbrokes_odds_a", "Ladbrokes_odds_b"),
        "handicap_open": ("Ladbrokes_odds_handicap_a_opening", "Ladbrokes_odds_handicap_b_opening"),
        "handicap_final": ("Ladbrokes_odds_handicap_a", "Ladbrokes_odds_handicap_b"),
        "handicap_line": "Ladbrokes_handicap",
        "total_open": ("Ladbrokes_odds_over_opening", "Ladbrokes_odds_under_opening"),
        "total_final": ("Ladbrokes_odds_over", "Ladbrokes_odds_under"),
        "total_line": "Ladbrokes_total_games_line",
    },
    "unibet": {
        "money_open": ("Unibet_odds_a_opening", "Unibet_odds_b_opening"),
        "money_final": ("Unibet_odds_a", "Unibet_odds_b"),
        "handicap_open": ("Unibet_odds_handicap_a_opening", "Unibet_odds_handicap_b_opening"),
        "handicap_final": ("Unibet_odds_handicap_a", "Unibet_odds_handicap_b"),
        "handicap_line": "Unibet_handicap",
        "total_open": ("Unibet_odds_over_opening", "Unibet_odds_under_opening"),
        "total_final": ("Unibet_odds_over", "Unibet_odds_under"),
        "total_line": "Unibet_total_games_line",
    },
}

FORBIDDEN_MODEL_COLUMNS = {
    "completed", "comment",
    "set1_score_a", "set1_score_b", "set2_score_a", "set2_score_b",
    "set3_score_a", "set3_score_b", "set4_score_a", "set4_score_b",
    "set5_score_a", "set5_score_b",
    "total_games_a", "total_games_b", "total_games",
    "total_sets_a", "total_sets_b", "games_per_set_a", "games_per_set_b",
}

@dataclass(frozen=True)
class SourceRow:
    row_number: int
    event_date: object
    tour: str
    tournament: str
    surface: str
    round_name: str
    player_a: str
    player_b: str
    source_winner: str
    source_match_id: str
    markets: dict[str, Any]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_date_value(value: object):
    text = str(value or "").strip()
    if not text:
        return None
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None

def infer_tour(value: object) -> str | None:
    text = norm_text(value)
    if not text:
        return None
    if "wta" in text or "women" in text or "female" in text:
        return "wta"
    if "atp" in text or "challenger" in text or "men" in text or "male" in text:
        return "atp"
    return None

def number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x

def odds_pair(row: dict[str, str], keys: tuple[str, str]) -> dict[str, float] | None:
    a = decimal_odds(row.get(keys[0]))
    b = decimal_odds(row.get(keys[1]))
    if a is None or b is None:
        return None
    return {"a": float(a), "b": float(b)}

def extract_markets(row: dict[str, str]) -> dict[str, Any]:
    books: dict[str, Any] = {}
    for book, cfg in BOOKS.items():
        item: dict[str, Any] = {}
        for label in ("money_open", "money_final", "handicap_open", "handicap_final", "total_open", "total_final"):
            keys = cfg.get(label)
            if keys:
                pair = odds_pair(row, keys)
                if pair:
                    item[label] = pair
        if cfg.get("handicap_line"):
            line = number(row.get(cfg["handicap_line"]))
            if line is not None:
                item["handicap_line_recorded"] = line
        if cfg.get("total_line"):
            line = number(row.get(cfg["total_line"]))
            if line is not None:
                item["total_line_recorded"] = line
        if item:
            books[book] = item

    best: dict[str, Any] = {}
    for label, keys in {
        "money_open": ("best_odds_a_opening", "best_odds_b_opening"),
        "money_final": ("best_odds_a", "best_odds_b"),
    }.items():
        pair = odds_pair(row, keys)
        if pair:
            best[label] = pair
    if str(row.get("best_odds_a_bookmaker") or "").strip():
        best["final_bookmaker_a"] = str(row["best_odds_a_bookmaker"]).strip()
    if str(row.get("best_odds_b_bookmaker") or "").strip():
        best["final_bookmaker_b"] = str(row["best_odds_b_bookmaker"]).strip()

    return {"bookmakers": books, "best": best}

def parse_source(path: Path) -> tuple[list[SourceRow], dict[str, int], dict[str, int]]:
    rows: list[SourceRow] = []
    counts = Counter()
    tour_values = Counter()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "match_date", "tour", "tournament", "surface", "player_a", "player_b",
            "round", "completed",
        }
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise SystemExit(f"Missing columns: {missing}")
        for row_number, row in enumerate(reader, start=2):
            counts["source_rows"] += 1
            raw_tour = str(row.get("tour") or "").strip()
            tour_values[raw_tour] += 1
            tour = infer_tour(raw_tour)
            if tour is None:
                counts["tour_unmapped"] += 1
                continue
            day = parse_date_value(row.get("match_date") or row.get("match_date_formatted"))
            a = str(row.get("player_a") or "").strip()
            b = str(row.get("player_b") or "").strip()
            if day is None or not a or not b or norm_text(a) == norm_text(b):
                counts["invalid_identity"] += 1
                continue

            completed = norm_text(row.get("completed"))
            if completed not in {"1", "true", "yes", "completed", "complete"}:
                counts["not_completed_or_unknown"] += 1
                continue

            # Dataset contract: player_a is winner for completed rows.
            winner = a
            markets = extract_markets(row)
            if not markets["bookmakers"] and not markets["best"]:
                counts["no_market"] += 1
                continue

            sid = source_match_id(
                SOURCE_SLUG, tour, day.isoformat(), row.get("tournament"),
                row.get("round"), a, b
            )
            rows.append(SourceRow(
                row_number=row_number,
                event_date=day,
                tour=tour,
                tournament=str(row.get("tournament") or "").strip(),
                surface=norm_surface(row.get("surface")),
                round_name=str(row.get("round") or "").strip(),
                player_a=a,
                player_b=b,
                source_winner=winner,
                source_match_id=sid,
                markets=markets,
            ))
            counts["usable_source_rows"] += 1
    return rows, dict(counts), dict(tour_values)

def winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""

def orientation(src: SourceRow, match) -> str | None:
    direct = legacy_name_matches(src.player_a, match.player1_name) and legacy_name_matches(src.player_b, match.player2_name)
    swapped = legacy_name_matches(src.player_a, match.player2_name) and legacy_name_matches(src.player_b, match.player1_name)
    if direct == swapped:
        return None
    return "direct" if direct else "swapped"

def orient_pair(pair: dict[str, float], orient: str) -> dict[str, float]:
    if orient == "direct":
        return {"player1": pair["a"], "player2": pair["b"]}
    return {"player1": pair["b"], "player2": pair["a"]}

def orient_markets(markets: dict[str, Any], orient: str) -> dict[str, Any]:
    out = {"bookmakers": {}, "best": {}}
    for book, item in markets["bookmakers"].items():
        mapped = {}
        for key, value in item.items():
            if isinstance(value, dict) and set(value) == {"a", "b"}:
                mapped[key] = orient_pair(value, orient)
            else:
                mapped[key] = value
        out["bookmakers"][book] = mapped
    for key, value in markets["best"].items():
        if isinstance(value, dict) and set(value) == {"a", "b"}:
            out["best"][key] = orient_pair(value, orient)
        else:
            out["best"][key] = value
    return out

def candidate_ok(src: SourceRow, match) -> tuple[bool, list[str], int]:
    evidence: list[str] = []
    if src.tour != norm_text(match.tour):
        return False, ["tour_mismatch"], -100

    orient = orientation(src, match)
    if orient is None:
        return False, ["pair_mismatch"], -100

    delta = abs((match.scheduled_at.date() - src.event_date).days)
    if delta > 1:
        return False, ["date_mismatch"], -100
    score = 4 if delta == 0 else 1
    evidence.append("date_exact" if delta == 0 else "date_plusminus_1")

    if not legacy_name_matches(src.source_winner, winner_name(match)):
        return False, evidence + ["winner_conflict"], score
    score += 3
    evidence.append("winner")

    ss, cs = norm_surface(src.surface), norm_surface(match.surface)
    if ss not in {"", "unknown"} and cs not in {"", "unknown"}:
        if ss != cs:
            return False, evidence + ["surface_conflict"], score
        score += 1
        evidence.append("surface")

    tscore, te = tournament_score(src.tournament, match.tournament)
    if tscore <= 0:
        return False, evidence + [te], score
    score += tscore
    evidence.append(te)

    rscore, re = round_evidence(src.round_name, match.round_name)
    if rscore < 0:
        return False, evidence + [re], score
    score += rscore
    evidence.append(re)

    accepted = score >= (9 if delta == 0 else 8)
    return accepted, evidence, score

def write_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    source_path = Path(args.source_csv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    source_file_sha256 = sha256(source_path)
    source_rows, source_counts, tour_values = parse_source(source_path)
    matches, identity = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")

    index = defaultdict(list)
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        if pair[0] and pair[1] and pair[0] != pair[1]:
            index[(match.scheduled_at.date().isoformat(), pair)].append(match)

    counts = Counter(source_counts)
    staging: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    linked_canonical: set[str] = set()
    market_counts = Counter()

    for src in source_rows:
        pair = tuple(sorted((norm_text(src.player_a), norm_text(src.player_b))))
        candidates = []
        for offset in (-1, 0, 1):
            day = (src.event_date + timedelta(days=offset)).isoformat()
            candidates.extend(index.get((day, pair), []))

        if not candidates:
            counts["unmatched_exact_pair"] += 1
            continue

        accepted = []
        for match in candidates:
            ok, evidence, score = candidate_ok(src, match)
            if ok:
                accepted.append((score, match, evidence))
        if not accepted:
            counts["identity_rejected"] += 1
            continue

        accepted.sort(key=lambda item: item[0], reverse=True)
        best_score = accepted[0][0]
        best = [item for item in accepted if item[0] == best_score]
        if len(best) != 1:
            counts["ambiguous"] += 1
            review.append({
                "source_match_id": src.source_match_id,
                "row_number": src.row_number,
                "reason": "ambiguous_best_candidate",
                "candidate_match_ids": [str(item[1].match_id) for item in best],
            })
            continue

        _, match, evidence = best[0]
        mid = str(match.match_id)
        if mid in linked_canonical:
            counts["duplicate_canonical_links"] += 1
            quarantine.append({
                "source_match_id": src.source_match_id,
                "row_number": src.row_number,
                "match_id": mid,
                "reason": "duplicate_canonical_link",
            })
            continue
        linked_canonical.add(mid)

        orient = orientation(src, match)
        assert orient is not None
        oriented = orient_markets(src.markets, orient)
        for book, item in oriented["bookmakers"].items():
            for key in item:
                market_counts[f"{book}:{key}"] += 1
        for key in oriented["best"]:
            market_counts[f"best:{key}"] += 1

        staging.append({
            "schema": 1,
            "match_id": mid,
            "scheduled_date_utc": match.scheduled_at.date().isoformat(),
            "source": SOURCE_LABEL,
            "source_slug": SOURCE_SLUG,
            "source_match_id": src.source_match_id,
            "source_file_sha256": source_file_sha256,
            "identity_evidence": evidence,
            "markets": oriented,
            "feature_policy": {
                "allowed_after_license_review": [
                    "opening_moneyline",
                    "opening_handicap_price_on_recorded_line",
                    "opening_total_price_on_recorded_line",
                ],
                "research_only_not_prematch_feature": [
                    "recorded_final_moneyline",
                    "recorded_final_handicap_price",
                    "recorded_final_total_price",
                ],
                "forbidden_source_columns": sorted(FORBIDDEN_MODEL_COLUMNS),
            },
            "license_gate": "blocked_pending_rights_confirmation",
        })
        counts["linked_matches"] += 1

    write_gz(out / "staging.jsonl.gz", staging)
    write_gz(out / "review.jsonl.gz", review)
    write_gz(out / "quarantine.jsonl.gz", quarantine)

    report = {
        "schema": 1,
        "source": {
            "platform": "Kaggle",
            "slug": SOURCE_SLUG,
            "file": source_path.name,
            "file_sha256": source_file_sha256,
            "license_status": "review_required_other",
        },
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "counts": dict(counts),
        "source_tour_values": tour_values,
        "market_counts": dict(market_counts),
        "staged_rows": len(staging),
        "review_rows": len(review),
        "quarantine_rows": len(quarantine),
        "canonical_mutated": False,
        "provider_api_requests": 0,
        "model_promoted": False,
        "persist_row_level_output": False,
        "license_gate": "blocked_pending_rights_confirmation",
        "ready_after_license": (
            len(staging) > 0
            and counts.get("duplicate_canonical_links", 0) == 0
            and identity.get("quarantined_rows", 0) == 0
        ),
        "leakage_policy": {
            "winner_orientation": "identity_validation_only",
            "score_result_fields": "excluded",
            "recorded_final_markets": "research_only_not_prematch_feature",
            "opening_markets": "eligible_only_after_license_and_timestamp/provenance review",
        },
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
