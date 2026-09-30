"""Build a canonical-match keyed sidecar from the historical moneyline dataset.

This is deliberately benchmark-only. The source has a date attached to quotes,
but no trustworthy capture timestamp, so it must never be interpreted as
opening/closing/CLV evidence or used as a same-match training feature.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_large_tennis_market import (
    SourceMoneylineMatch,
    build_market_sidecar,
    candidate_link,
    parse_date,
    parse_moneyline_row,
    parse_tournament_row,
    safe_group_match_date,
    source_match_id,
)
from tbt.data.offline_odds import norm_text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_signature(match) -> dict[str, str]:
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


def _write_jsonl_gz(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--moneyline-csv", required=True)
    ap.add_argument("--tournaments-csv", required=True)
    ap.add_argument("--source-label", default="large_tennis_betting_dataset")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    moneyline_path = Path(args.moneyline_csv)
    tournaments_path = Path(args.tournaments_csv)
    moneyline_sha = _sha256(moneyline_path)
    tournaments_sha = _sha256(tournaments_path)

    matches, identity = sanitize_history_identities(load_partitions(args.history_dir))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    tournaments = {}
    counts = Counter()
    with tournaments_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            meta = parse_tournament_row(row)
            if meta is None:
                counts["invalid_tournament_rows"] += 1
                continue
            key = (meta.start_date, norm_text(meta.tournament))
            if key in tournaments:
                counts["duplicate_tournament_keys"] += 1
                continue
            tournaments[key] = meta
    counts["usable_tournament_rows"] = len(tournaments)

    grouped = defaultdict(list)
    group_meta = {}
    with moneyline_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            counts["source_rows"] += 1
            start = parse_date(row.get("start_date"))
            tournament_name = str(row.get("tournament") or "").strip()
            meta = tournaments.get((start, norm_text(tournament_name))) if start else None
            if meta is None:
                counts["missing_tournament_metadata"] += 1
                continue
            quote = parse_moneyline_row(row, row_number=number, tournament=meta)
            if quote is None:
                counts["invalid_source_rows"] += 1
                continue
            key = (
                meta.start_date,
                norm_text(meta.tournament),
                norm_text(quote.player_a),
                norm_text(quote.player_b),
            )
            grouped[key].append(quote)
            group_meta[key] = meta
            counts["usable_source_rows"] += 1

    sources = []
    for key, quotes in grouped.items():
        meta = group_meta[key]
        safe_date = safe_group_match_date(quotes, meta)
        if safe_date is None:
            in_window_dates = {
                q.betting_date for q in quotes if meta.start_date <= q.betting_date <= meta.end_date
            }
            if not in_window_dates:
                counts["source_groups_no_in_window_date"] += 1
            else:
                counts["source_groups_multiple_in_window_dates"] += 1
            continue

        safe_quotes = tuple(q for q in quotes if q.betting_date == safe_date)
        if len(safe_quotes) < len(quotes):
            counts["discarded_offdate_quote_rows"] += len(quotes) - len(safe_quotes)
        first = safe_quotes[0]
        sid = source_match_id(
            tournament=meta,
            match_date=safe_date,
            player_a=first.player_a,
            player_b=first.player_b,
        )
        sources.append(
            SourceMoneylineMatch(
                source_match_id=sid,
                tournament=meta,
                match_date=safe_date,
                player_a=first.player_a,
                player_b=first.player_b,
                quotes=safe_quotes,
            )
        )
    counts["source_match_groups"] = len(grouped)
    counts["safe_source_match_groups"] = len(sources)

    by_pair_date = defaultdict(list)
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        by_pair_date[(match.scheduled_at.date(), pair)].append(match)

    staged = []
    review = []
    quarantine = []
    linked_canonical_ids = set()
    for source in sources:
        pair = tuple(sorted((norm_text(source.player_a), norm_text(source.player_b))))
        candidates = by_pair_date.get((source.match_date, pair), [])
        accepted = []
        for match in candidates:
            linked = candidate_link(
                source,
                canonical_date=match.scheduled_at.date(),
                canonical_player1=match.player1_name,
                canonical_player2=match.player2_name,
                canonical_tournament=match.tournament,
                canonical_surface=match.surface,
            )
            if linked.get("accepted"):
                accepted.append((match, linked))

        if not accepted:
            counts["unmatched_safe_source_matches"] += 1
            continue
        if len(accepted) != 1:
            counts["ambiguous_canonical_links"] += 1
            review.append(
                {
                    "source_match_id": source.source_match_id,
                    "reason": "ambiguous_canonical_link",
                    "candidate_match_ids": [str(item[0].match_id) for item in accepted],
                }
            )
            continue

        match, linked = accepted[0]
        mid = str(match.match_id)
        if mid in linked_canonical_ids:
            counts["duplicate_canonical_match_links"] += 1
            quarantine.append(
                {
                    "match_id": mid,
                    "source_match_id": source.source_match_id,
                    "reason": "duplicate_canonical_match_link",
                }
            )
            continue

        sidecar = build_market_sidecar(
            source,
            orientation=str(linked["orientation"]),
            source_label=args.source_label,
            source_file_sha256=moneyline_sha,
        )
        staged.append(
            {
                "schema": 1,
                "match_id": mid,
                "canonical": _canonical_signature(match),
                "historical_market": sidecar,
                "link": {
                    "score": linked["score"],
                    "evidence": linked["evidence"],
                    "orientation": linked["orientation"],
                },
                "import_ready": True,
            }
        )
        linked_canonical_ids.add(mid)
        counts["staged_matches"] += 1
        if int(sidecar.get("bookmaker_count") or 0) >= 2:
            counts["staged_multi_book_consensus"] += 1

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "source": {
            "label": args.source_label,
            "moneyline_file": moneyline_path.name,
            "moneyline_sha256": moneyline_sha,
            "tournaments_file": tournaments_path.name,
            "tournaments_sha256": tournaments_sha,
        },
        "counts": dict(counts),
        "production_mutated": False,
        "api_requests": 0,
        "price_kind": "historical_moneyline_unspecified_quote_time",
        "model_feature_policy": "benchmark_only_no_training_feature",
        "note": (
            "Strict sidecar linker. betting_date is used only when exactly one source date "
            "falls inside the tournament window. It is not treated as an odds capture "
            "timestamp, opening line, closing line, or CLV observation."
        ),
    }

    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_jsonl_gz(out / "market-sidecar.jsonl.gz", staged)
    _write_jsonl_gz(out / "review.jsonl.gz", review)
    _write_jsonl_gz(out / "quarantine.jsonl.gz", quarantine)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
