"""Build/import a fail-closed pre-2021 historical match foundation.

Sources are Jeff Sackmann-style ATP/WTA rows.  Historical source player IDs are
bridged to BlinQ canonical player IDs only when an overlap-period match proves
that mapping (player pair + tournament + round + winner inside a conservative
21-day tournament window).  Unproven players retain stable source-scoped IDs.

Historical ranks are kept only with explicit point-in-time provenance.  Service
statistics are converted to canonical rates from the same completed match and
therefore become observations for *future* matches only via FeatureBuilder's
chronological replay.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.offline_odds import norm_text, tournament_score
from tbt.schemas import MatchRecord


ROUND_ALIASES = {
    "f": "f", "final": "f", "the final": "f",
    "sf": "sf", "semifinal": "sf", "semifinals": "sf",
    "qf": "qf", "quarterfinal": "qf", "quarterfinals": "qf",
    "r16": "r16", "round of 16": "r16",
    "r32": "r32", "round of 32": "r32",
    "r64": "r64", "round of 64": "r64",
    "r128": "r128", "round of 128": "r128",
    "q1": "q1", "q2": "q2", "q3": "q3", "q4": "q4",
    "rr": "rr", "round robin": "rr",
    "br": "br",
}


def _round(value: object) -> str:
    text = norm_text(value)
    return ROUND_ALIASES.get(text, text)


def _date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            day = datetime.strptime(text, fmt)
            return day.replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _int(value: object) -> int | None:
    try:
        result = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _float(value: object) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(num: object, den: object) -> float | None:
    n, d = _float(num), _float(den)
    if n is None or d is None or d <= 0 or n < 0 or n > d:
        return None
    return n / d


def _source_type(path: Path, tour: str) -> str:
    name = path.name.lower()
    if tour == "wta":
        return "main"
    if "qual_chall" in name:
        return "qual_chall"
    if "futures" in name:
        return "futures"
    if "amateur" in name:
        return "amateur"
    return "main"


def _level(value: object, tour: str, source_type: str) -> str:
    raw = str(value or "").strip().upper()
    if source_type == "qual_chall":
        return "challenger"
    if source_type == "futures":
        return "itf futures"
    if source_type == "amateur":
        return "amateur"
    mapping = {
        "G": "grand slam",
        "M": "masters 1000" if tour == "atp" else "wta 1000",
        "A": "atp tour" if tour == "atp" else "wta tour",
        "C": "challenger",
        "F": "itf futures",
        "D": "team event",
        "O": "olympics",
        "P": "wta premier",
        "I": "wta international",
        "PM": "wta premier mandatory",
    }
    return mapping.get(raw, raw.lower() or "unknown")


def _surface(value: object) -> str:
    text = norm_text(value)
    if "hard" in text:
        return "hard"
    if "clay" in text:
        return "clay"
    if "grass" in text:
        return "grass"
    if "carpet" in text:
        return "carpet"
    return "unknown"


def _stats(row: dict[str, str]) -> dict[str, float | None]:
    """Orient source winner as p1 and loser as p2."""
    out: dict[str, float | None] = {}
    for prefix, source in (("p1", "w"), ("p2", "l")):
        aces = _float(row.get(f"{source}_ace"))
        dfs = _float(row.get(f"{source}_df"))
        svpt = _float(row.get(f"{source}_svpt"))
        first_in = _float(row.get(f"{source}_1stIn"))
        first_won = _float(row.get(f"{source}_1stWon"))
        second_won = _float(row.get(f"{source}_2ndWon"))

        if aces is not None and aces >= 0 and aces.is_integer():
            out[f"{prefix}_aces"] = float(aces)
        if dfs is not None and dfs >= 0 and dfs.is_integer():
            out[f"{prefix}_double_faults"] = float(dfs)

        first_rate = _rate(first_won, first_in)
        second_den = None
        if svpt is not None and first_in is not None and svpt >= first_in:
            second_den = svpt - first_in
        second_rate = _rate(second_won, second_den)
        service_won = None
        if first_won is not None and second_won is not None:
            service_won = _rate(first_won + second_won, svpt)
        if first_rate is not None:
            out[f"{prefix}_first_serve_win"] = first_rate
        if second_rate is not None:
            out[f"{prefix}_second_serve_win"] = second_rate
        if service_won is not None:
            out[f"{prefix}_service_points_won"] = service_won

    # Return points won are the opponent's service points lost.
    w_svpt = _float(row.get("w_svpt"))
    l_svpt = _float(row.get("l_svpt"))
    p1_service = out.get("p1_service_points_won")
    p2_service = out.get("p2_service_points_won")
    if l_svpt and p2_service is not None:
        out["p1_return_points_won"] = 1.0 - float(p2_service)
    if w_svpt and p1_service is not None:
        out["p2_return_points_won"] = 1.0 - float(p1_service)

    return {
        key: float(value)
        for key, value in out.items()
        if value is not None and math.isfinite(float(value))
    }


def _canonical_winner_name(match: MatchRecord) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return norm_text(match.player1_name)
    if str(match.winner_id or "") == str(match.player2_id):
        return norm_text(match.player2_name)
    return ""


@dataclass(frozen=True)
class SourceRow:
    tour: str
    source_type: str
    source_file: str
    source_row: int
    scheduled_at: datetime
    tourney_id: str
    tournament: str
    level: str
    surface: str
    match_num: str
    round_name: str
    best_of: int | None
    winner_source_id: str
    winner_name: str
    loser_source_id: str
    loser_name: str
    winner_rank: int | None
    loser_rank: int | None
    stats: dict[str, float | None]

    @property
    def year(self) -> int:
        return self.scheduled_at.year

    @property
    def pair(self) -> tuple[str, str]:
        return tuple(sorted((norm_text(self.winner_name), norm_text(self.loser_name))))

    @property
    def source_match_key(self) -> str:
        return "|".join((
            self.tour,
            self.source_type,
            self.tourney_id,
            self.match_num,
            _round(self.round_name),
            "|".join(self.pair),
        ))


def _read_sources(specs: list[tuple[str, str]], counts: Counter) -> list[SourceRow]:
    rows: list[SourceRow] = []
    seen: dict[str, SourceRow] = {}
    for tour, path_text in specs:
        path = Path(path_text)
        source_type = _source_type(path, tour)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                counts[f"{tour}_{source_type}_rows"] += 1
                scheduled = _date(row.get("tourney_date"))
                winner_name = str(row.get("winner_name") or "").strip()
                loser_name = str(row.get("loser_name") or "").strip()
                winner_sid = str(row.get("winner_id") or "").strip()
                loser_sid = str(row.get("loser_id") or "").strip()
                if (
                    scheduled is None
                    or not winner_name
                    or not loser_name
                    or norm_text(winner_name) == norm_text(loser_name)
                ):
                    counts["invalid_source_rows"] += 1
                    continue
                if not winner_sid:
                    winner_sid = "name:" + hashlib.sha256(
                        norm_text(winner_name).encode("utf-8")
                    ).hexdigest()[:16]
                if not loser_sid:
                    loser_sid = "name:" + hashlib.sha256(
                        norm_text(loser_name).encode("utf-8")
                    ).hexdigest()[:16]

                item = SourceRow(
                    tour=tour,
                    source_type=source_type,
                    source_file=path.name,
                    source_row=number,
                    scheduled_at=scheduled,
                    tourney_id=str(row.get("tourney_id") or "").strip(),
                    tournament=str(row.get("tourney_name") or "").strip(),
                    level=_level(row.get("tourney_level"), tour, source_type),
                    surface=_surface(row.get("surface")),
                    match_num=str(row.get("match_num") or number).strip(),
                    round_name=_round(row.get("round")),
                    best_of=_int(row.get("best_of")),
                    winner_source_id=winner_sid,
                    winner_name=winner_name,
                    loser_source_id=loser_sid,
                    loser_name=loser_name,
                    winner_rank=_int(row.get("winner_rank")),
                    loser_rank=_int(row.get("loser_rank")),
                    stats=_stats(row),
                )
                key = item.source_match_key
                prior = seen.get(key)
                if prior is not None:
                    if prior != item:
                        counts["source_key_conflicts"] += 1
                    else:
                        counts["source_exact_duplicates"] += 1
                    continue
                seen[key] = item
                rows.append(item)
                counts["usable_source_rows"] += 1
    return rows


def _crosswalk(
    overlap_rows: Iterable[SourceRow],
    canonical: list[MatchRecord],
    counts: Counter,
) -> tuple[dict[tuple[str, str], str], list[dict]]:
    """Prove source-player -> canonical-player mapping from overlap matches."""
    by_pair: dict[tuple[str, tuple[str, str]], list[MatchRecord]] = defaultdict(list)
    for match in canonical:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        by_pair[(str(match.tour or "").lower(), pair)].append(match)

    votes: dict[tuple[str, str], set[str]] = defaultdict(set)
    evidence_rows: list[dict] = []
    for source in overlap_rows:
        candidates = []
        for match in by_pair.get((source.tour, source.pair), []):
            delta = (match.scheduled_at.date() - source.scheduled_at.date()).days
            if delta < 0 or delta > 21:
                continue
            winner = _canonical_winner_name(match)
            if winner != norm_text(source.winner_name):
                continue
            tscore, tev = tournament_score(source.tournament, match.tournament)
            if tscore <= 0:
                continue
            sr, cr = _round(source.round_name), _round(match.round_name)
            if sr and cr and sr != cr:
                continue
            score = 4 + tscore + (2 if sr and cr and sr == cr else 0) + (2 if delta <= 14 else 0)
            candidates.append((score, match, tev, delta))

        if not candidates:
            counts["crosswalk_unmatched_overlap"] += 1
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        top_score = candidates[0][0]
        top = [item for item in candidates if item[0] == top_score]
        if len(top) != 1:
            counts["crosswalk_ambiguous_overlap"] += 1
            continue

        _, match, tev, delta = top[0]
        p1n, p2n = norm_text(match.player1_name), norm_text(match.player2_name)
        if norm_text(source.winner_name) == p1n and norm_text(source.loser_name) == p2n:
            winner_id, loser_id = str(match.player1_id), str(match.player2_id)
        elif norm_text(source.winner_name) == p2n and norm_text(source.loser_name) == p1n:
            winner_id, loser_id = str(match.player2_id), str(match.player1_id)
        else:
            counts["crosswalk_orientation_failed"] += 1
            continue

        votes[(source.tour, source.winner_source_id)].add(winner_id)
        votes[(source.tour, source.loser_source_id)].add(loser_id)
        evidence_rows.append({
            "tour": source.tour,
            "source_match_key": source.source_match_key,
            "canonical_match_id": str(match.match_id),
            "date_delta_days": delta,
            "tournament_evidence": tev,
            "winner_source_id": source.winner_source_id,
            "winner_canonical_id": winner_id,
            "loser_source_id": source.loser_source_id,
            "loser_canonical_id": loser_id,
        })
        counts["crosswalk_linked_overlap_matches"] += 1

    mapping = {}
    for key, values in votes.items():
        if len(values) == 1:
            mapping[key] = next(iter(values))
            counts["crosswalk_players_proven"] += 1
        else:
            counts["crosswalk_player_conflicts"] += 1
    return mapping, evidence_rows


def _historical_player_id(tour: str, source_id: str, mapping: dict[tuple[str, str], str]) -> str:
    proven = mapping.get((tour, source_id))
    if proven:
        return proven
    safe = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", source_id)
    return f"hist-js:{tour}:{safe}"


def _match_id(source: SourceRow) -> str:
    digest = hashlib.sha256(source.source_match_key.encode("utf-8")).hexdigest()[:24]
    return f"hist-js:{source.tour}:{digest}"


def _provider_payload(source: SourceRow, match_id: str, has_rank: bool, has_stats: bool) -> dict:
    payload = {
        "_tbt_event_identity": {
            "event_id": match_id,
            "home": source.winner_name,
            "away": source.loser_name,
            "status": "completed",
        },
        "_tbt_provider_event_id": match_id,
        "_tbt_source_category_name": f"historical_{source.source_type}",
    }
    if has_rank:
        payload["_tbt_rank_provenance"] = {
            "point_in_time": True,
            "source": f"jeff_sackmann_match_snapshot:{source.source_file}",
            "as_of": source.scheduled_at.replace(hour=0).isoformat(),
        }
    if has_stats:
        payload["_tbt_statistics"] = {
            "schema": 1,
            "event_id": match_id,
            "source": f"jeff_sackmann_match_snapshot:{source.source_file}",
            "fetched_at": source.scheduled_at.isoformat(),
            "status": "historical_observation",
        }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--atp-csv", action="append", default=[])
    ap.add_argument("--wta-csv", action="append", default=[])
    ap.add_argument("--import-through-year", type=int, default=2020)
    ap.add_argument("--crosswalk-from-year", type=int, default=2021)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write-partitions", action="store_true")
    ap.add_argument("--write-history-dir", default="")
    args = ap.parse_args()
    if not args.atp_csv and not args.wta_csv:
        ap.error("At least one source CSV is required")
    if args.write_history_dir and not args.write_partitions:
        ap.error("--write-history-dir requires --write-partitions")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    canonical, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    counts = Counter()
    specs = [("atp", p) for p in args.atp_csv] + [("wta", p) for p in args.wta_csv]
    sources = _read_sources(specs, counts)
    overlap = [row for row in sources if row.year >= args.crosswalk_from_year]
    historical = [row for row in sources if row.year <= args.import_through_year]
    mapping, crosswalk_evidence = _crosswalk(overlap, canonical, counts)

    existing = {str(match.match_id): match for match in canonical}
    staged: list[MatchRecord] = []
    quarantine: list[dict] = []
    changed_years = set()
    by_year = Counter()
    rank_rows = 0
    stats_rows = 0
    mapped_player_sides = 0
    scoped_player_sides = 0

    for source in sorted(historical, key=lambda x: (x.scheduled_at, x.source_match_key)):
        mid = _match_id(source)
        p1_id = _historical_player_id(source.tour, source.winner_source_id, mapping)
        p2_id = _historical_player_id(source.tour, source.loser_source_id, mapping)
        if p1_id == p2_id:
            counts["resolved_player_collision"] += 1
            quarantine.append({"source_match_key": source.source_match_key, "reason": "resolved_player_collision"})
            continue

        mapped_player_sides += int((source.tour, source.winner_source_id) in mapping)
        mapped_player_sides += int((source.tour, source.loser_source_id) in mapping)
        scoped_player_sides += int((source.tour, source.winner_source_id) not in mapping)
        scoped_player_sides += int((source.tour, source.loser_source_id) not in mapping)

        rank1, rank2 = source.winner_rank, source.loser_rank
        has_rank = rank1 is not None or rank2 is not None
        has_stats = bool(source.stats)
        item = MatchRecord(
            match_id=mid,
            tour=source.tour,
            scheduled_at=source.scheduled_at,
            player1_id=p1_id,
            player1_name=source.winner_name,
            player2_id=p2_id,
            player2_name=source.loser_name,
            surface=source.surface,
            tournament=source.tournament,
            tournament_id=source.tourney_id,
            tournament_level=source.level,
            round_name=source.round_name,
            player1_rank=rank1,
            player2_rank=rank2,
            winner_id=p1_id,
            status="completed",
            best_of=source.best_of,
            indoor=None,
            stats=source.stats,
            provider_payload=_provider_payload(source, mid, has_rank, has_stats),
        )

        prior = existing.get(mid)
        if prior is not None:
            same_identity = (
                str(prior.tour) == str(item.tour)
                and prior.scheduled_at.date() == item.scheduled_at.date()
                and norm_text(prior.player1_name) == norm_text(item.player1_name)
                and norm_text(prior.player2_name) == norm_text(item.player2_name)
                and norm_text(_canonical_winner_name(prior)) == norm_text(item.player1_name)
            )
            if same_identity:
                counts["already_present"] += 1
                continue
            counts["match_id_conflicts"] += 1
            quarantine.append({
                "match_id": mid,
                "source_match_key": source.source_match_key,
                "reason": "existing_match_id_conflict",
            })
            continue

        existing[mid] = item
        staged.append(item)
        changed_years.add(item.scheduled_at.year)
        by_year[str(item.scheduled_at.year)] += 1
        rank_rows += int(has_rank)
        stats_rows += int(has_stats)
        counts["staged_historical_matches"] += 1

    combined = canonical + staged
    verified, combined_safety = sanitize_history_identities(combined)
    if combined_safety.get("quarantined_rows"):
        raise SystemExit(
            f"Historical import would create identity quarantine: {combined_safety.get('quarantined_rows')}"
        )
    if len(verified) != len(combined):
        raise SystemExit("Historical import changed row count during safety validation")

    target = Path(args.write_history_dir) if args.write_history_dir else out / "history"
    if args.write_partitions:
        for year in sorted(changed_years):
            write_year_partition(
                combined,
                target,
                year,
                extra_manifest={"coverage_status": "verified_offline_historical_foundation"},
            )

    report = {
        "schema": 1,
        "canonical_before": len(canonical),
        "historical_source_rows": len(historical),
        "overlap_source_rows": len(overlap),
        "crosswalk_players": len(mapping),
        "staged_historical_matches": len(staged),
        "canonical_projected_after": len(combined),
        "rank_rows_staged": rank_rows,
        "stats_rows_staged": stats_rows,
        "mapped_player_sides": mapped_player_sides,
        "source_scoped_player_sides": scoped_player_sides,
        "changed_years": sorted(changed_years),
        "by_year": dict(sorted(by_year.items())),
        "counts": dict(counts),
        "identity_safety": combined_safety,
        "api_requests": 0,
        "production_mutated": False,
        "local_partitions_written": bool(args.write_partitions and changed_years),
        "rank_policy": "source match rank accepted only with explicit point-in-time provenance",
        "crosswalk_policy": "overlap pair+tournament+round+winner within 21-day tournament window; conflicts fail closed",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / "crosswalk.jsonl").open("w", encoding="utf-8") as handle:
        for row in crosswalk_evidence:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "quarantine.jsonl").open("w", encoding="utf-8") as handle:
        for row in quarantine:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
