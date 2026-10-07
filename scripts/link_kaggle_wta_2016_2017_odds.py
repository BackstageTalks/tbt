"""Strict linker for Kaggle WTA 2016-2017 two-way Match Winner odds.

Source:
  Kaggle dataset serangu/woman-tennis-2016-2017-years
  file 2016-2017_orig.csv

The source stores every match twice in mirrored orientation. This linker first
requires the two rows to be an exact, internally consistent mirror, then reduces
them to one neutral source match. Only valid two-way decimal odds are eligible.

Canonical identity is fail-closed:
  * WTA only;
  * exact calendar date;
  * exact normalized unordered player pair;
  * unique canonical candidate after winner filtering;
  * canonical winner must agree;
  * when both canonical ranks and non-capped source ratings are present, large
    rank disagreement is rejected.

The source does not document quote timestamp or bookmaker identity in the file.
Persisted prices are therefore benchmark-only historical two-way observations,
never opening/closing/CLV labels and never same-match model features.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import (
    build_market_marker,
    decimal_odds,
    fair_market,
    norm_text,
    source_match_id,
)


SOURCE_SLUG = "serangu/woman-tennis-2016-2017-years"
SOURCE_FILENAME = "2016-2017_orig.csv"
SOURCE_LABEL = "operator_kaggle_wta_2016_2017"


@dataclass(frozen=True)
class SourceMatch:
    source_row_numbers: tuple[int, int]
    event_date: object
    player_a: str
    player_b: str
    winner: str
    rank_a: int | None
    rank_b: int | None
    odds_a: float
    odds_b: float
    source_match_id: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_date(value: object):
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return None


def _rank(value: object) -> int | None:
    try:
        rank = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    # The source uses 1000 as an effective lower-rank cap. It is not reliable
    # enough for identity validation at that boundary.
    return rank if 1 <= rank < 1000 else None


def _flag(value: object) -> int | None:
    text = str(value or "").strip()
    if text == "1":
        return 1
    if text == "0":
        return 0
    return None


def _same_float(left: object, right: object, *, tolerance: float = 1e-12) -> bool:
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return False
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def _pair_key(row: dict[str, str]) -> tuple[str, tuple[str, str]] | None:
    day = _parse_date(row.get("date"))
    a = norm_text(row.get("name_1"))
    b = norm_text(row.get("name_2"))
    if day is None or not a or not b or a == b:
        return None
    return day.isoformat(), tuple(sorted((a, b)))


def _strict_mirror(first: dict[str, str], second: dict[str, str]) -> bool:
    return (
        norm_text(first.get("name_1")) == norm_text(second.get("name_2"))
        and norm_text(first.get("name_2")) == norm_text(second.get("name_1"))
        and _same_float(first.get("age_1"), second.get("age_2"))
        and _same_float(first.get("age_2"), second.get("age_1"))
        and _same_float(first.get("rating_1"), second.get("rating_2"))
        and _same_float(first.get("rating_2"), second.get("rating_1"))
        and _same_float(first.get("k1"), second.get("k2"))
        and _same_float(first.get("k2"), second.get("k1"))
        and str(first.get("result") or "").strip() == str(second.get("result") or "").strip()
        and {_flag(first.get("player1_is_win?")), _flag(second.get("player1_is_win?"))}
        == {0, 1}
    )


def deduplicate_source(path: Path) -> tuple[list[SourceMatch], dict[str, int]]:
    groups: dict[tuple[str, tuple[str, str]], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    counts = Counter()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        expected = {
            "date", "name_1", "name_2", "age_1", "age_2",
            "rating_1", "rating_2", "k1", "k2", "result", "player1_is_win?",
        }
        missing = sorted(expected - set(reader.fieldnames or []))
        if missing:
            raise SystemExit(f"Missing source columns: {missing}")
        for row_number, row in enumerate(reader, start=2):
            counts["source_rows"] += 1
            key = _pair_key(row)
            if key is None:
                counts["invalid_identity_rows"] += 1
                continue
            groups[key].append((row_number, row))

    output: list[SourceMatch] = []
    for (day_text, _pair), rows in sorted(groups.items()):
        counts["source_match_groups"] += 1
        if len(rows) != 2:
            counts["mirror_group_size_invalid"] += 1
            continue
        (n1, a), (n2, b) = rows
        if not _strict_mirror(a, b):
            counts["mirror_inconsistent"] += 1
            continue

        o1 = decimal_odds(a.get("k1"))
        o2 = decimal_odds(a.get("k2"))
        if o1 is None or o2 is None:
            counts["invalid_or_unpriced_match_groups"] += 1
            continue

        flag = _flag(a.get("player1_is_win?"))
        if flag is None:
            counts["invalid_winner_flag"] += 1
            continue
        player_a = str(a.get("name_1") or "").strip()
        player_b = str(a.get("name_2") or "").strip()
        winner = player_a if flag == 1 else player_b
        day = _parse_date(a.get("date"))
        assert day is not None

        sid = source_match_id(
            "wta",
            day_text,
            SOURCE_SLUG,
            *sorted((norm_text(player_a), norm_text(player_b))),
            norm_text(winner),
            f"{o1:.12g}",
            f"{o2:.12g}",
        )
        output.append(
            SourceMatch(
                source_row_numbers=(n1, n2),
                event_date=day,
                player_a=player_a,
                player_b=player_b,
                winner=winner,
                rank_a=_rank(a.get("rating_1")),
                rank_b=_rank(a.get("rating_2")),
                odds_a=float(o1),
                odds_b=float(o2),
                source_match_id=sid,
            )
        )
        counts["usable_deduplicated_matches"] += 1

    return output, dict(counts)


def _winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


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


def _orientation(source: SourceMatch, match) -> str | None:
    sa, sb = norm_text(source.player_a), norm_text(source.player_b)
    p1, p2 = norm_text(match.player1_name), norm_text(match.player2_name)
    direct = sa == p1 and sb == p2
    swapped = sa == p2 and sb == p1
    if direct == swapped:
        return None
    return "direct" if direct else "swapped"


def _oriented_market(source: SourceMatch, orientation: str) -> dict[str, float]:
    if orientation == "direct":
        p1, p2 = source.odds_a, source.odds_b
    elif orientation == "swapped":
        p1, p2 = source.odds_b, source.odds_a
    else:
        raise ValueError(f"Unexpected orientation: {orientation}")
    fair = fair_market(p1, p2)
    return {
        "player1_odds": float(p1),
        "player2_odds": float(p2),
        "player1_implied_probability": float(fair["player1_implied_probability"]),
        "player2_implied_probability": float(fair["player2_implied_probability"]),
        "raw_overround": float(fair["raw_overround"]),
    }


def _rank_evidence(source: SourceMatch, match, orientation: str) -> tuple[bool, str]:
    if orientation == "direct":
        src = (source.rank_a, source.rank_b)
    else:
        src = (source.rank_b, source.rank_a)
    target = (match.player1_rank, match.player2_rank)

    if not all(value is not None for value in (*src, *target)):
        return True, "ranks_partial_or_capped"
    diffs = [abs(int(a) - int(b)) for a, b in zip(src, target)]
    if max(diffs) <= 5:
        return True, "ranks_close_5"
    if max(diffs) <= 25:
        return True, "ranks_close_25"
    return False, "rank_conflict_gt25"


def build_sidecar(
    source: SourceMatch,
    *,
    orientation: str,
    source_file_sha256: str,
    evidence: list[str],
) -> dict[str, Any]:
    market = _oriented_market(source, orientation)
    return {
        "schema": 1,
        "status": "linked",
        "source": SOURCE_LABEL,
        "source_slug": SOURCE_SLUG,
        "source_match_id": source.source_match_id,
        "source_file_sha256": source_file_sha256,
        "price_kind": "historical_two_way_unspecified_timestamp",
        "quote_kind": "bookmaker_two_way_source_unspecified",
        "bookmaker": None,
        "model_feature_policy": "benchmark_only_no_same_match_training_feature",
        "player1_odds": market["player1_odds"],
        "player2_odds": market["player2_odds"],
        "player1_fair_probability": market["player1_implied_probability"],
        "player2_fair_probability": market["player2_implied_probability"],
        "raw_overround": market["raw_overround"],
        "identity_evidence": evidence,
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
    ap.add_argument("--source-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    source_path = Path(args.source_csv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_sha = _sha256(source_path)

    source_matches, source_counts = deduplicate_source(source_path)

    matches, identity = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    index = defaultdict(list)
    for match in matches:
        if str(match.tour or "").lower() != "wta":
            continue
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        if pair[0] and pair[1] and pair[0] != pair[1]:
            index[(match.scheduled_at.date().isoformat(), pair)].append(match)

    counts = Counter(source_counts)
    stage = []
    sidecars_by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    review = []
    quarantine = []
    linked_ids: set[str] = set()

    for source in source_matches:
        pair = tuple(sorted((norm_text(source.player_a), norm_text(source.player_b))))
        candidates = list(index.get((source.event_date.isoformat(), pair), []))
        if not candidates:
            counts["unmatched"] += 1
            continue

        source_winner = norm_text(source.winner)
        winner_matches = [
            match for match in candidates
            if norm_text(_winner_name(match)) == source_winner
        ]
        if not winner_matches:
            counts["winner_conflict"] += 1
            continue
        candidates = winner_matches

        if len(candidates) != 1:
            counts["ambiguous"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "reason": "ambiguous_exact_date_pair_winner",
                "candidate_match_ids": [str(m.match_id) for m in candidates],
            })
            continue

        match = candidates[0]
        orientation = _orientation(source, match)
        if orientation is None:
            counts["orientation_failed"] += 1
            continue

        rank_ok, rank_note = _rank_evidence(source, match, orientation)
        if not rank_ok:
            counts["rank_conflict"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "match_id": str(match.match_id),
                "reason": rank_note,
            })
            continue

        mid = str(match.match_id)
        if mid in linked_ids:
            counts["duplicate_canonical_links"] += 1
            quarantine.append({
                "source_match_id": source.source_match_id,
                "match_id": mid,
                "reason": "duplicate_canonical_link",
            })
            continue
        linked_ids.add(mid)

        evidence = [
            "source_mirror_pair_exact",
            "date_exact",
            "player_pair_exact_normalized",
            "canonical_candidate_unique",
            "winner_exact",
            rank_note,
        ]
        rich = build_sidecar(
            source,
            orientation=orientation,
            source_file_sha256=source_sha,
            evidence=evidence,
        )
        sidecars_by_year[int(match.scheduled_at.year)].append({
            "schema": 1,
            "match_id": mid,
            "scheduled_date_utc": match.scheduled_at.date().isoformat(),
            "historical_market": rich,
        })
        counts["linked_matches"] += 1

        payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        if isinstance(payload.get("_tbt_match_winner_odds"), dict):
            counts["existing_reference_preserved"] += 1
            continue

        market = _oriented_market(source, orientation)
        marker = build_market_marker(
            market,
            source=SOURCE_LABEL,
            source_match_id_value=source.source_match_id,
            source_file_sha256=source_sha,
        )
        stage.append({
            "schema": 1,
            "match_id": mid,
            "canonical": _signature(match),
            "incoming_market": marker,
            "source": {
                "source_slug": SOURCE_SLUG,
                "source_file": source_path.name,
                "source_row_numbers": list(source.source_row_numbers),
                "orientation": orientation,
                "evidence": evidence,
                "bookmaker": None,
                "quote_timestamp": None,
            },
            "import_ready": True,
        })
        counts["reference_markers_staged"] += 1

    _write_jsonl(out / "reference_stage.jsonl", stage)
    for year, rows in sorted(sidecars_by_year.items()):
        _write_jsonl_gz(out / f"market-sidecar-{year}.jsonl.gz", rows)
    _write_jsonl_gz(out / "review.jsonl.gz", review)
    _write_jsonl_gz(out / "quarantine.jsonl.gz", quarantine)

    report = {
        "schema": 1,
        "source": {
            "platform": "Kaggle",
            "slug": SOURCE_SLUG,
            "file": source_path.name,
            "sha256": source_sha,
        },
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "counts": dict(counts),
        "sidecar_years": {
            str(year): len(rows) for year, rows in sorted(sidecars_by_year.items())
        },
        "production_mutated": False,
        "api_requests": 0,
        "price_kind": "historical_two_way_unspecified_timestamp",
        "quote_provenance": "bookmaker identity and quote timestamp are not present in the source file",
        "model_feature_policy": "benchmark_only_no_same_match_training_feature",
        "result_policy": "source result/winner used only to validate identity; never persisted as a same-match feature",
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
