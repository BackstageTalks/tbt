"""Strict linker for operator-supplied Tennis-Data historical Match Winner odds.

The source files are Winner/Loser-oriented. This script uses that orientation only
for identity linking and immediately rewrites every persisted quote to canonical
player1/player2 orientation. Historical quote times are unknown, so these prices
are benchmark-only and must not be treated as opening/closing/CLV observations or
same-match model features.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import (
    build_market_marker,
    candidate_link,
    decimal_odds,
    fair_market,
    norm_text,
    parse_legacy_row,
)

BOOKS = (
    ("PS", "Pinnacle", "bookmaker"),
    ("B365", "Bet365", "bookmaker"),
    ("B&W", "BetAndWin", "bookmaker"),
    ("CB", "Centrebet", "bookmaker"),
    ("EX", "Expekt", "bookmaker"),
    ("GB", "Gamebookers", "bookmaker"),
    ("IW", "Interwetten", "bookmaker"),
    ("LB", "Ladbrokes", "bookmaker"),
    ("SB", "Sportingbet", "bookmaker"),
    ("SJ", "StanJames", "bookmaker"),
    ("UB", "Unibet", "bookmaker"),
    ("Avg", "MarketAverage", "aggregate"),
    ("Max", "MarketMaximum", "aggregate"),
)
REFERENCE_ORDER = tuple(code for code, _, kind in BOOKS if kind == "bookmaker")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def quote_pairs(row: dict[str, Any]) -> list[dict[str, Any]]:
    quotes = []
    for code, name, kind in BOOKS:
        winner = decimal_odds(row.get(f"{code}W"))
        loser = decimal_odds(row.get(f"{code}L"))
        if winner is None or loser is None:
            continue
        fair = fair_market(winner, loser)
        quotes.append(
            {
                "code": code,
                "bookmaker": name,
                "quote_kind": kind,
                "winner_odds": float(winner),
                "loser_odds": float(loser),
                "winner_fair_probability": float(fair["player1_implied_probability"]),
                "loser_fair_probability": float(fair["player2_implied_probability"]),
                "raw_overround": float(fair["raw_overround"]),
            }
        )
    return quotes


def preferred_link_quote(quotes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not quotes:
        return None
    by_code = {str(item["code"]): item for item in quotes}
    for code in REFERENCE_ORDER + ("Avg", "Max"):
        if code in by_code:
            return by_code[code]
    return quotes[0]


def preferred_real_quote(quotes: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_code = {str(item["code"]): item for item in quotes}
    for code in REFERENCE_ORDER:
        if code in by_code:
            return by_code[code]
    return None


def source_row(row: dict[str, Any], *, row_number: int, tour: str):
    quotes = quote_pairs(row)
    reference = preferred_link_quote(quotes)
    if reference is None:
        return None, []
    normalized = {
        "Date": row.get("Date"),
        "Tournament": row.get("Tournament"),
        "Surface": row.get("Surface"),
        "Round": row.get("Round"),
        "Best of": row.get("Best of"),
        "Player_1": row.get("Winner"),
        "Player_2": row.get("Loser"),
        "Winner": row.get("Winner"),
        "Rank_1": row.get("WRank"),
        "Rank_2": row.get("LRank"),
        "Odd_1": reference["winner_odds"],
        "Odd_2": reference["loser_odds"],
    }
    return parse_legacy_row(normalized, row_number=row_number, tour=tour), quotes


def orient_quote(quote: dict[str, Any], orientation: str) -> dict[str, Any]:
    if orientation == "direct":
        p1, p2 = float(quote["winner_odds"]), float(quote["loser_odds"])
    elif orientation == "swapped":
        p1, p2 = float(quote["loser_odds"]), float(quote["winner_odds"])
    else:
        raise ValueError(f"Unexpected orientation: {orientation}")
    fair = fair_market(p1, p2)
    return {
        "code": str(quote["code"]),
        "bookmaker": str(quote["bookmaker"]),
        "quote_kind": str(quote["quote_kind"]),
        "player1_odds": p1,
        "player2_odds": p2,
        "player1_fair_probability": float(fair["player1_implied_probability"]),
        "player2_fair_probability": float(fair["player2_implied_probability"]),
        "raw_overround": float(fair["raw_overround"]),
    }


def build_sidecar(
    quotes: list[dict[str, Any]],
    *,
    orientation: str,
    source_label: str,
    source_match_id: str,
    source_file_sha256: str,
) -> dict[str, Any]:
    oriented = [orient_quote(item, orientation) for item in quotes]
    real = [item for item in oriented if item["quote_kind"] == "bookmaker"]
    consensus_input = real or [item for item in oriented if item["code"] == "Avg"] or oriented
    p1 = float(median(float(item["player1_fair_probability"]) for item in consensus_input))
    overround = float(median(float(item["raw_overround"]) for item in consensus_input))
    return {
        "schema": 1,
        "status": "linked",
        "source": source_label,
        "source_match_id": source_match_id,
        "source_file_sha256": source_file_sha256,
        "price_kind": "historical_two_way_unspecified_timestamp",
        "model_feature_policy": "benchmark_only_no_same_match_training_feature",
        "bookmaker_count": len(real),
        "quote_count": len(oriented),
        "consensus": {
            "method": "median_no_vig_real_bookmakers_else_average_else_all",
            "player1_fair_probability": p1,
            "player2_fair_probability": 1.0 - p1,
            "median_raw_overround": overround,
        },
        "quotes": oriented,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--atp-source", action="append", default=[])
    ap.add_argument("--wta-source", action="append", default=[])
    ap.add_argument("--source-label", default="operator_supplied_tennis_data")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    if not args.atp_source and not args.wta_source:
        ap.error("At least one --atp-source or --wta-source is required")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, identity = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    by_day = defaultdict(list)
    for match in matches:
        by_day[(str(match.tour or "").lower(), match.scheduled_at.date())].append(match)

    source_specs = [("atp", Path(path)) for path in args.atp_source]
    source_specs += [("wta", Path(path)) for path in args.wta_source]

    counts = Counter()
    staged_reference = []
    sidecars_by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    review = []
    quarantine = []
    linked_ids: set[str] = set()
    source_manifest = []

    for tour, path in source_specs:
        file_sha = _sha256(path)
        source_manifest.append({"tour": tour, "file": path.name, "sha256": file_sha})
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                counts["source_rows"] += 1
                parsed, quotes = source_row(row, row_number=row_number, tour=tour)
                if parsed is None:
                    counts["invalid_or_unpriced_source_rows"] += 1
                    continue
                counts["usable_source_rows"] += 1

                candidates = []
                for delta in (-1, 0, 1):
                    from datetime import timedelta
                    candidates.extend(by_day.get((tour, parsed.event_date + timedelta(days=delta)), []))
                unique_candidates = {str(item.match_id): item for item in candidates}
                scored = []
                for match in unique_candidates.values():
                    linked = candidate_link(
                        parsed,
                        canonical_tour=str(match.tour or "").lower(),
                        canonical_date=match.scheduled_at.date(),
                        canonical_player1=match.player1_name,
                        canonical_player2=match.player2_name,
                        canonical_winner=_winner_name(match),
                        canonical_tournament=match.tournament,
                        canonical_surface=match.surface,
                        canonical_round=match.round_name,
                        canonical_best_of=match.best_of,
                        canonical_rank1=match.player1_rank,
                        canonical_rank2=match.player2_rank,
                    )
                    if linked.get("score", -100) > -100:
                        scored.append((int(linked["score"]), bool(linked["accepted"]), match, linked))
                scored.sort(key=lambda item: item[0], reverse=True)

                if not scored:
                    counts["unmatched"] += 1
                    continue
                best_score = scored[0][0]
                best = [item for item in scored if item[0] == best_score]
                if len(best) != 1:
                    counts["ambiguous"] += 1
                    review.append(
                        {
                            "source_file": path.name,
                            "row_number": row_number,
                            "reason": "ambiguous",
                            "score": best_score,
                            "candidate_match_ids": [str(item[2].match_id) for item in best],
                        }
                    )
                    continue
                _, accepted, match, linked = best[0]
                if not accepted:
                    counts["weak_evidence"] += 1
                    continue

                mid = str(match.match_id)
                if mid in linked_ids:
                    counts["duplicate_canonical_links"] += 1
                    quarantine.append(
                        {
                            "match_id": mid,
                            "source_file": path.name,
                            "row_number": row_number,
                            "reason": "duplicate_canonical_link",
                        }
                    )
                    continue

                rich = build_sidecar(
                    quotes,
                    orientation=str(linked["orientation"]),
                    source_label=args.source_label,
                    source_match_id=parsed.source_match_id,
                    source_file_sha256=file_sha,
                )
                year = int(match.scheduled_at.year)
                sidecars_by_year[year].append(
                    {
                        "schema": 1,
                        "match_id": mid,
                        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
                        "historical_market": rich,
                    }
                )
                linked_ids.add(mid)
                counts["linked_matches"] += 1
                if rich["bookmaker_count"] >= 2:
                    counts["multi_book_linked_matches"] += 1

                payload = match.provider_payload or {}
                if isinstance(payload.get("_tbt_match_winner_odds"), dict):
                    counts["existing_reference_preserved"] += 1
                    continue

                real_reference = preferred_real_quote(quotes)
                if real_reference is None:
                    counts["no_real_book_reference"] += 1
                    continue
                oriented = orient_quote(real_reference, str(linked["orientation"]))
                marker = build_market_marker(
                    {
                        "player1_odds": oriented["player1_odds"],
                        "player2_odds": oriented["player2_odds"],
                        "player1_implied_probability": oriented["player1_fair_probability"],
                        "player2_implied_probability": oriented["player2_fair_probability"],
                        "raw_overround": oriented["raw_overround"],
                    },
                    source=args.source_label,
                    source_match_id_value=parsed.source_match_id,
                    source_file_sha256=file_sha,
                )
                staged_reference.append(
                    {
                        "schema": 1,
                        "match_id": mid,
                        "canonical": _signature(match),
                        "incoming_market": marker,
                        "source": {
                            "source_file": path.name,
                            "row_number": row_number,
                            "reference_bookmaker": real_reference["bookmaker"],
                            "score": linked["score"],
                            "evidence": linked["evidence"],
                            "orientation": linked["orientation"],
                        },
                        "import_ready": True,
                    }
                )
                counts["reference_markers_staged"] += 1

    _write_jsonl(out / "reference_stage.jsonl", staged_reference)
    for year, rows in sorted(sidecars_by_year.items()):
        _write_jsonl_gz(out / f"market-sidecar-{year}.jsonl.gz", rows)
    _write_jsonl_gz(out / "review.jsonl.gz", review)
    _write_jsonl_gz(out / "quarantine.jsonl.gz", quarantine)

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "source_files": source_manifest,
        "counts": dict(counts),
        "sidecar_years": {str(year): len(rows) for year, rows in sorted(sidecars_by_year.items())},
        "production_mutated": False,
        "api_requests": 0,
        "price_kind": "historical_two_way_unspecified_timestamp",
        "model_feature_policy": "benchmark_only_no_same_match_training_feature",
        "orientation_policy": "source Winner/Loser is used only for linking; persisted prices are canonical player1/player2",
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
