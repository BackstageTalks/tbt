"""Offline linker for owned tennis CSVs and Match Charting Project data.

Read-only by design. It never writes canonical history or calls a provider.

It links offline rows to the private canonical history using exact normalized
player pairs plus date/tour and independent metadata evidence. Ambiguous,
conflicting, or weak matches fail closed.

Typical use:
  PYTHONPATH=api:scripts python scripts/link_offline_serve_return.py \
    --history-dir .cache/tbt/history \
    --source-csv atp_matches_2024.csv --source-csv wta_matches_2024.csv \
    --charting-zip tennis_project_old.zip \
    --out-dir .cache/tbt/offline-linker
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder


RICH_CHARTING_FIELDS = {
    "first_strike_serve_win",
    "return_in_play_rate",
    "return_deep_rate",
    "break_point_serve_win",
    "break_point_return_win",
    "net_points_win",
    "attacking_points_rate",
    "unforced_error_rate",
}


STAT_FIELDS = {
    "aces",
    "double_faults",
    "first_serve_win",
    "second_serve_win",
    "service_points_won",
    "return_points_won",
    # Normalized Match Charting Project rates. Every value is bounded 0..1;
    # FeatureBuilder later turns these into rolling point-in-time features.
    "first_strike_serve_win",
    "return_in_play_rate",
    "return_deep_rate",
    "break_point_serve_win",
    "break_point_return_win",
    "net_points_win",
    "attacking_points_rate",
    "unforced_error_rate",
}


def _ascii(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _norm_text(value: object) -> str:
    text = _ascii(value).lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _norm_name(value: object) -> str:
    text = _norm_text(value)
    # "Last, First" is uncommon in the supplied files, but normalize it when
    # the original representation clearly uses a comma.
    raw = _ascii(value)
    if "," in raw:
        left, right = raw.split(",", 1)
        swapped = _norm_text(f"{right} {left}")
        if swapped:
            return swapped
    return text


ROUND_ALIASES = {
    "f": "f",
    "final": "f",
    "sf": "sf",
    "semifinal": "sf",
    "semi final": "sf",
    "qf": "qf",
    "quarterfinal": "qf",
    "quarter final": "qf",
    "r16": "r16",
    "round of 16": "r16",
    "r32": "r32",
    "round of 32": "r32",
    "r64": "r64",
    "round of 64": "r64",
    "r128": "r128",
    "q1": "q1",
    "q2": "q2",
    "q3": "q3",
    "rr": "rr",
}


def _norm_round(value: object) -> str:
    text = _norm_text(value)
    return ROUND_ALIASES.get(text, text)


def _norm_surface(value: object) -> str:
    text = _norm_text(value)
    if "clay" in text:
        return "clay"
    if "grass" in text:
        return "grass"
    if "hard" in text:
        return "hard"
    if "carpet" in text:
        return "carpet"
    return text or "unknown"


def _tour_from_path(path: str) -> str:
    name = Path(path).name.lower()
    if "wta" in name or "charting-w-" in name:
        return "wta"
    return "atp"


def _parse_yyyymmdd(value: object) -> date | None:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    if len(text) != 8:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(numerator: object, denominator: object) -> float | None:
    num, den = _num(numerator), _num(denominator)
    if num is None or den is None or den <= 0 or num < 0 or num > den:
        return None
    value = num / den
    return value if 0 <= value <= 1 else None


def _service_stats(prefix: str, row: dict[str, object]) -> dict[str, float]:
    svpt = _num(row.get(f"{prefix}_svpt"))
    first_in = _num(row.get(f"{prefix}_1stIn"))
    first_won = _num(row.get(f"{prefix}_1stWon"))
    second_won = _num(row.get(f"{prefix}_2ndWon"))
    aces = _num(row.get(f"{prefix}_ace"))
    dfs = _num(row.get(f"{prefix}_df"))
    result: dict[str, float] = {}
    for field, value in (("aces", aces), ("double_faults", dfs)):
        if value is not None and value >= 0 and float(value).is_integer():
            result[field] = float(value)
    first = _rate(first_won, first_in)
    second_den = None if svpt is None or first_in is None else svpt - first_in
    second = _rate(second_won, second_den)
    service = None
    if first_won is not None and second_won is not None and svpt and svpt > 0:
        service = _rate(first_won + second_won, svpt)
    for field, value in (
        ("first_serve_win", first),
        ("second_serve_win", second),
        ("service_points_won", service),
    ):
        if value is not None:
            result[field] = value
    return result


def _return_rate(opponent_prefix: str, row: dict[str, object]) -> float | None:
    svpt = _num(row.get(f"{opponent_prefix}_svpt"))
    first_won = _num(row.get(f"{opponent_prefix}_1stWon"))
    second_won = _num(row.get(f"{opponent_prefix}_2ndWon"))
    if svpt is None or first_won is None or second_won is None or svpt <= 0:
        return None
    lost = svpt - first_won - second_won
    return _rate(lost, svpt)


@dataclass(frozen=True)
class OfflineMatch:
    source: str
    source_match_id: str
    tour: str
    event_date: date
    player_a: str
    player_b: str
    winner: str
    tournament: str
    surface: str
    round_name: str
    best_of: int | None
    stats_a: dict[str, float]
    stats_b: dict[str, float]

    @property
    def pair_key(self) -> tuple[str, str]:
        return tuple(sorted((_norm_name(self.player_a), _norm_name(self.player_b))))


def _sackmann_rows(paths: Iterable[str]) -> Iterable[OfflineMatch]:
    for raw_path in paths:
        path = Path(raw_path)
        tour = _tour_from_path(path.name)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle), start=2):
                day = _parse_yyyymmdd(row.get("tourney_date"))
                winner = str(row.get("winner_name") or "").strip()
                loser = str(row.get("loser_name") or "").strip()
                if not day or not winner or not loser:
                    continue
                w_stats = _service_stats("w", row)
                l_stats = _service_stats("l", row)
                w_ret = _return_rate("l", row)
                l_ret = _return_rate("w", row)
                if w_ret is not None:
                    w_stats["return_points_won"] = w_ret
                if l_ret is not None:
                    l_stats["return_points_won"] = l_ret
                if not w_stats and not l_stats:
                    continue
                bo = _num(row.get("best_of"))
                yield OfflineMatch(
                    source=f"sackmann:{path.name}",
                    source_match_id=str(row.get("tourney_id") or "") + ":" + str(row.get("match_num") or idx),
                    tour=tour,
                    event_date=day,
                    player_a=winner,
                    player_b=loser,
                    winner=winner,
                    tournament=str(row.get("tourney_name") or ""),
                    surface=_norm_surface(row.get("surface")),
                    round_name=_norm_round(row.get("round")),
                    best_of=int(bo) if bo in (3.0, 5.0) else None,
                    stats_a=w_stats,
                    stats_b=l_stats,
                )


def _charting_rows(path: str) -> Iterable[OfflineMatch]:
    """Yield charting matches with Overview plus high-confidence specialist rates.

    Specialist tables are normalized at match level here, not in the model.
    Only rows with unambiguous denominators are accepted; missing/zero
    denominators remain missing. This keeps raw charting quirks out of the
    canonical history and preserves a bounded 0..1 importer contract.
    """
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for code, tour in (("m", "atp"), ("w", "wta")):
            match_name = f"charting-{code}-matches.csv"
            overview_name = f"charting-{code}-stats-Overview.csv"
            if match_name not in names or overview_name not in names:
                continue

            def load_stat_rows(dataset: str, wanted_row: str) -> dict[str, dict[str, dict[str, str]]]:
                filename = f"charting-{code}-stats-{dataset}.csv"
                values: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
                if filename not in names:
                    return values
                with archive.open(filename) as raw:
                    text = (line.decode("utf-8-sig", errors="replace") for line in raw)
                    for stat in csv.DictReader(text):
                        if str(stat.get("row") or "").strip().lower() != wanted_row.lower():
                            continue
                        mid = str(stat.get("match_id") or "")
                        player = _norm_name(stat.get("player"))
                        if mid and player:
                            values[mid][player] = stat
                return values

            overview: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
            with archive.open(overview_name) as raw:
                text = (line.decode("utf-8-sig", errors="replace") for line in raw)
                for row in csv.DictReader(text):
                    if str(row.get("set") or "").strip().lower() != "total":
                        continue
                    overview[str(row.get("match_id") or "")][_norm_name(row.get("player"))] = row

            serve_basics = load_stat_rows("ServeBasics", "Total")
            return_outcomes = load_stat_rows("ReturnOutcomes", "Total")
            return_depth = load_stat_rows("ReturnDepth", "Total")
            net_points = load_stat_rows("NetPoints", "NetPoints")
            key_serve = load_stat_rows("KeyPointsServe", "BP")
            key_return = load_stat_rows("KeyPointsReturn", "BPO")
            shot_types = load_stat_rows("ShotTypes", "Total")

            def specialist_stats(mid: str, player_name: str) -> dict[str, float]:
                key = _norm_name(player_name)
                result: dict[str, float] = {}

                src = serve_basics.get(mid, {}).get(key)
                if src:
                    value = _rate(src.get("pts_won_lte_3_shots"), src.get("pts"))
                    if value is not None:
                        result["first_strike_serve_win"] = value

                src = return_outcomes.get(mid, {}).get(key)
                if src:
                    value = _rate(src.get("in_play"), src.get("returnable"))
                    if value is not None:
                        result["return_in_play_rate"] = value

                src = return_depth.get(mid, {}).get(key)
                if src:
                    # MCP very_deep is a subset of deep; deep alone is the
                    # correct numerator rather than deep + very_deep.
                    value = _rate(src.get("deep"), src.get("returnable"))
                    if value is not None:
                        result["return_deep_rate"] = value

                src = key_serve.get(mid, {}).get(key)
                if src:
                    value = _rate(src.get("pts_won"), src.get("pts"))
                    if value is not None:
                        result["break_point_serve_win"] = value

                src = key_return.get(mid, {}).get(key)
                if src:
                    value = _rate(src.get("pts_won"), src.get("pts"))
                    if value is not None:
                        result["break_point_return_win"] = value

                src = net_points.get(mid, {}).get(key)
                if src:
                    value = _rate(src.get("pts_won"), src.get("net_pts"))
                    if value is not None:
                        result["net_points_win"] = value

                src = shot_types.get(mid, {}).get(key)
                if src:
                    ending = _num(src.get("pt_ending"))
                    winners = _num(src.get("winners"))
                    forced = _num(src.get("induced_forced"))
                    unforced = _num(src.get("unforced"))
                    attacking = None if winners is None or forced is None else winners + forced
                    attack_rate = _rate(attacking, ending)
                    error_rate = _rate(unforced, ending)
                    if attack_rate is not None:
                        result["attacking_points_rate"] = attack_rate
                    if error_rate is not None:
                        result["unforced_error_rate"] = error_rate
                return result

            with archive.open(match_name) as raw:
                text = (line.decode("utf-8-sig", errors="replace") for line in raw)
                for row in csv.DictReader(text):
                    mid = str(row.get("match_id") or "")
                    day = _parse_yyyymmdd(row.get("Date"))
                    p1, p2 = str(row.get("Player 1") or "").strip(), str(row.get("Player 2") or "").strip()
                    if not mid or not day or not p1 or not p2:
                        continue
                    stat_rows = overview.get(mid, {})
                    a_raw = stat_rows.get(_norm_name(p1))
                    b_raw = stat_rows.get(_norm_name(p2))
                    if not a_raw or not b_raw:
                        continue

                    def stats(src: dict[str, str], player_name: str) -> dict[str, float]:
                        serve_pts = _num(src.get("serve_pts"))
                        first_in = _num(src.get("first_in"))
                        first_won = _num(src.get("first_won"))
                        second_in = _num(src.get("second_in"))
                        second_won = _num(src.get("second_won"))
                        return_pts = _num(src.get("return_pts"))
                        return_won = _num(src.get("return_pts_won"))
                        result: dict[str, float] = {}
                        for field, key_name in (("aces", "aces"), ("double_faults", "dfs")):
                            value = _num(src.get(key_name))
                            if value is not None and value >= 0 and value.is_integer():
                                result[field] = float(value)
                        for field, value in (
                            ("first_serve_win", _rate(first_won, first_in)),
                            ("second_serve_win", _rate(second_won, second_in)),
                            ("service_points_won", _rate(
                                None if first_won is None or second_won is None else first_won + second_won,
                                serve_pts,
                            )),
                            ("return_points_won", _rate(return_won, return_pts)),
                        ):
                            if value is not None:
                                result[field] = value
                        result.update(specialist_stats(mid, player_name))
                        return result

                    bo = _num(row.get("Best of"))
                    yield OfflineMatch(
                        source=f"charting:{Path(path).name}:{code}",
                        source_match_id=mid,
                        tour=tour,
                        event_date=day,
                        player_a=p1,
                        player_b=p2,
                        winner="",
                        tournament=str(row.get("Tournament") or ""),
                        surface=_norm_surface(row.get("Surface")),
                        round_name=_norm_round(row.get("Round")),
                        best_of=int(bo) if bo in (3.0, 5.0) else None,
                        stats_a=stats(a_raw, p1),
                        stats_b=stats(b_raw, p2),
                    )


def _livetennisapi_reconstructed_rows(paths: Iterable[str]) -> Iterable[OfflineMatch]:
    """Read private, derived LiveTennisAPI reconstructed pressure stages.

    The raw reconstructed tapes are intentionally not accepted here. This
    parser consumes only an internal derived CSV whose rows carry match
    identity plus bounded break-point serve/return rates. The raw source stays
    outside the repository and the derived stage is fetched from private
    tbt-data by the guarded workflow.
    """
    for raw_path in paths:
        path = Path(raw_path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle), start=2):
                source_match_id = str(row.get("source_match_id") or "").strip()
                day_text = str(row.get("scheduled_date_utc") or "").strip()
                p1 = str(row.get("player1_name") or "").strip()
                p2 = str(row.get("player2_name") or "").strip()
                if not source_match_id or not day_text or not p1 or not p2:
                    continue
                try:
                    event_day = datetime.strptime(day_text, "%Y-%m-%d").date()
                except ValueError:
                    continue

                def rate(key: str) -> float | None:
                    value = _num(row.get(key))
                    if value is None or not 0.0 <= value <= 1.0:
                        return None
                    return float(value)

                a_stats = {}
                b_stats = {}
                for field, key in (
                    ("break_point_serve_win", "p1_break_point_serve_win"),
                    ("break_point_return_win", "p1_break_point_return_win"),
                ):
                    value = rate(key)
                    if value is not None:
                        a_stats[field] = value
                for field, key in (
                    ("break_point_serve_win", "p2_break_point_serve_win"),
                    ("break_point_return_win", "p2_break_point_return_win"),
                ):
                    value = rate(key)
                    if value is not None:
                        b_stats[field] = value
                if not a_stats and not b_stats:
                    continue

                winner_side = str(row.get("winner") or "").strip()
                winner = p1 if winner_side == "1" else p2 if winner_side == "2" else ""
                best_of = _num(row.get("best_of"))
                yield OfflineMatch(
                    source=f"livetennisapi-reconstructed:{path.name}",
                    source_match_id=source_match_id,
                    tour="wta",
                    event_date=event_day,
                    player_a=p1,
                    player_b=p2,
                    winner=winner,
                    tournament=str(row.get("tournament") or ""),
                    surface=_norm_surface(row.get("surface")),
                    round_name=_norm_round(row.get("round")),
                    best_of=int(best_of) if best_of in (3.0, 5.0) else None,
                    stats_a=a_stats,
                    stats_b=b_stats,
                )


def _tournament_score(a: str, b: str) -> tuple[int, str]:
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return 0, "tournament_missing"
    if na == nb:
        return 2, "tournament_exact"
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / max(1, len(ta | tb))
    if overlap >= 0.6:
        return 1, "tournament_tokens"
    return 0, "tournament_mismatch"


def _canonical_winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _candidate_score(source: OfflineMatch, match) -> tuple[int, list[str], bool]:
    evidence: list[str] = []
    score = 0
    source_names = source.pair_key
    canonical_names = tuple(sorted((_norm_name(match.player1_name), _norm_name(match.player2_name))))
    if source_names != canonical_names or source.tour != str(match.tour or "").lower():
        return -100, ["pair_or_tour_mismatch"], False

    delta = abs((match.scheduled_at.astimezone(timezone.utc).date() - source.event_date).days)
    if delta == 0:
        score += 4
        evidence.append("date_exact")
    elif delta == 1:
        score += 1
        evidence.append("date_plusminus_1")
    else:
        return -100, ["date_mismatch"], False

    canonical_surface = _norm_surface(match.surface)
    if source.surface not in ("", "unknown") and canonical_surface not in ("", "unknown"):
        if source.surface == canonical_surface:
            score += 1
            evidence.append("surface")
        else:
            evidence.append("surface_conflict")
            return score, evidence, False

    ts, te = _tournament_score(source.tournament, match.tournament)
    score += ts
    evidence.append(te)

    cr, sr = _norm_round(match.round_name), source.round_name
    if cr and sr:
        if cr == sr:
            score += 1
            evidence.append("round")
        else:
            evidence.append("round_conflict")

    if source.best_of and match.best_of:
        if int(source.best_of) == int(match.best_of):
            score += 1
            evidence.append("best_of")
        else:
            evidence.append("best_of_conflict")
            return score, evidence, False

    if source.winner:
        canonical_winner = _canonical_winner_name(match)
        if not canonical_winner:
            evidence.append("canonical_winner_missing")
            return score, evidence, False
        if _norm_name(source.winner) != _norm_name(canonical_winner):
            evidence.append("winner_conflict")
            return score, evidence, False
        score += 3
        evidence.append("winner")

    # Source-specific gates. Match Charting identity is already constrained by
    # exact normalized player pair + tour and a narrow date window. Requiring an
    # exact tournament string discarded many legitimate rows because event names
    # differ across sources (sponsor/location aliases). Keep this fail-closed:
    # exact match date is mandatory, round conflicts are rejected, and at least
    # three corroboration points beyond the pair/date must be present. Exact
    # tournament agreement is worth two points; token-level tournament agreement,
    # surface, round and best-of are each worth one.
    if source.source.startswith("charting:"):
        corroboration_points = 0
        if "tournament_exact" in evidence:
            corroboration_points += 2
        elif "tournament_tokens" in evidence:
            corroboration_points += 1
        corroboration_points += int("surface" in evidence)
        corroboration_points += int("round" in evidence)
        corroboration_points += int("best_of" in evidence)
        accepted = (
            "date_exact" in evidence
            and "round_conflict" not in evidence
            and corroboration_points >= 3
            and score >= 7
        )
    elif source.source.startswith("livetennisapi-reconstructed:"):
        # Restricted reconstructed stages are date-exact and winner-verified.
        # Rows with an honest missing winner stay out of the automatic stage.
        accepted = "date_exact" in evidence and "winner" in evidence and score >= 8
    else:
        accepted = "winner" in evidence and score >= 8
    return score, evidence, accepted


def _orientation(source: OfflineMatch, match) -> tuple[dict[str, float], dict[str, str]] | None:
    a, b = _norm_name(source.player_a), _norm_name(source.player_b)
    p1, p2 = _norm_name(match.player1_name), _norm_name(match.player2_name)
    if a == p1 and b == p2:
        mapping = {"a": "p1", "b": "p2"}
    elif a == p2 and b == p1:
        mapping = {"a": "p2", "b": "p1"}
    else:
        return None
    incoming: dict[str, float] = {}
    for side, stats in (("a", source.stats_a), ("b", source.stats_b)):
        prefix = mapping[side]
        for field, value in stats.items():
            if field not in STAT_FIELDS:
                continue
            incoming[f"{prefix}_{field}"] = float(value)
    return incoming, mapping


def _quality_ready(stats: dict[str, float | None]) -> bool:
    return all(
        FeatureBuilder._extract_quality(stats, prefix)[0] is not None
        and FeatureBuilder._extract_quality(stats, prefix)[1] is not None
        for prefix in ("p1", "p2")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", action="append", default=[])
    ap.add_argument("--charting-zip", default="")
    ap.add_argument("--livetennisapi-reconstructed-csv", action="append", default=[])
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing offline linking")

    canonical_by_day_pair: dict[tuple[str, date, tuple[str, str]], list] = defaultdict(list)
    by_id = {str(m.match_id): m for m in matches}
    for match in matches:
        pair = tuple(sorted((_norm_name(match.player1_name), _norm_name(match.player2_name))))
        canonical_by_day_pair[(str(match.tour or "").lower(), match.scheduled_at.date(), pair)].append(match)

    sources: list[OfflineMatch] = list(_sackmann_rows(args.source_csv))
    if args.charting_zip:
        sources.extend(_charting_rows(args.charting_zip))
    sources.extend(_livetennisapi_reconstructed_rows(args.livetennisapi_reconstructed_csv))

    counts = Counter()
    per_source = Counter()
    weak_review: list[dict] = []
    linked: dict[str, list[dict]] = defaultdict(list)

    for source in sources:
        counts["source_rows"] += 1
        per_source[source.source] += 1
        candidates = []
        for delta in (-1, 0, 1):
            day = source.event_date + timedelta(days=delta)
            candidates.extend(canonical_by_day_pair.get((source.tour, day, source.pair_key), []))
        # Same canonical row can only appear once, but de-duplicate defensively.
        unique = {str(m.match_id): m for m in candidates}
        scored = []
        for match in unique.values():
            score, evidence, accepted = _candidate_score(source, match)
            if score > -100:
                scored.append((score, accepted, match, evidence))
        scored.sort(key=lambda item: item[0], reverse=True)

        if not scored:
            counts["unmatched"] += 1
            continue
        top_score = scored[0][0]
        top = [item for item in scored if item[0] == top_score]
        if len(top) != 1:
            counts["ambiguous"] += 1
            weak_review.append({
                "source": source.source,
                "source_match_id": source.source_match_id,
                "reason": "ambiguous",
                "candidate_match_ids": [str(item[2].match_id) for item in top],
                "score": top_score,
            })
            continue
        score, accepted, match, evidence = top[0]
        if not accepted:
            counts["weak_evidence"] += 1
            weak_review.append({
                "source": source.source,
                "source_match_id": source.source_match_id,
                "reason": "weak_evidence",
                "candidate_match_id": str(match.match_id),
                "score": score,
                "evidence": evidence,
            })
            continue
        oriented = _orientation(source, match)
        if not oriented:
            counts["orientation_unverified"] += 1
            continue
        incoming, mapping = oriented
        if not incoming:
            counts["no_supported_stats"] += 1
            continue
        counts["identity_linked"] += 1
        linked[str(match.match_id)].append({
            "source": source.source,
            "source_match_id": source.source_match_id,
            "score": score,
            "evidence": evidence,
            "mapping": mapping,
            "stats": incoming,
        })

    staged: list[dict] = []
    quarantine: list[dict] = []
    staged_field_counts = Counter()
    quality_before = sum(1 for m in matches if _quality_ready(m.stats or {}))
    projected_quality = quality_before

    for mid, rows in linked.items():
        match = by_id[mid]
        existing = dict(match.stats or {})
        merged: dict[str, float] = {}
        conflict = []
        provenance = []
        for row in rows:
            provenance.append({k: row[k] for k in ("source", "source_match_id", "score", "evidence", "mapping")})
            for key, value in row["stats"].items():
                old = existing.get(key)
                prior = merged.get(key)
                if old is not None and abs(float(old) - float(value)) > 1e-6:
                    conflict.append({"key": key, "reason": "canonical_conflict", "existing": old, "incoming": value})
                elif prior is not None and abs(float(prior) - float(value)) > 1e-6:
                    conflict.append({"key": key, "reason": "source_conflict", "existing": prior, "incoming": value})
                elif old is None:
                    merged[key] = float(value)
        if conflict:
            counts["stat_conflict_matches"] += 1
            quarantine.append({"match_id": mid, "conflicts": conflict, "sources": provenance})
            continue
        if not merged:
            counts["already_present"] += 1
            continue

        projected = dict(existing)
        projected.update(merged)
        was_ready = _quality_ready(existing)
        is_ready = _quality_ready(projected)
        if is_ready and not was_ready:
            projected_quality += 1
        staged_field_counts.update(merged.keys())
        if any(
            key.split("_", 1)[1] in RICH_CHARTING_FIELDS
            for key in merged
            if "_" in key
        ):
            counts["rich_staged_matches"] += 1
        staged.append({
            "schema": 1,
            "match_id": mid,
            "canonical": {
                "tour": str(match.tour or "").lower(),
                "scheduled_date_utc": match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
                "player1_id": str(match.player1_id),
                "player1_name": str(match.player1_name),
                "player2_id": str(match.player2_id),
                "player2_name": str(match.player2_name),
                "surface": str(match.surface or ""),
                "tournament": str(match.tournament or ""),
                "round_name": str(match.round_name or ""),
                "winner_id": str(match.winner_id or ""),
            },
            "incoming_stats": merged,
            "sources": provenance,
            "quality_ready_before": was_ready,
            "quality_ready_after": is_ready,
            "import_ready": True,
        })
        counts["staged_matches"] += 1

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "source_rows": len(sources),
        "counts": dict(counts),
        "source_rows_by_source": dict(per_source),
        "staged_field_counts": dict(sorted(staged_field_counts.items())),
        "quality_ready_before": quality_before,
        "quality_ready_projected_after": projected_quality,
        "quality_ready_projected_added": projected_quality - quality_before,
        "production_mutated": False,
        "api_requests": 0,
        "note": "Read-only linker. No canonical history write and no provider call occurred.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / "auto_linked.jsonl").open("w", encoding="utf-8") as handle:
        for row in staged:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "review.jsonl").open("w", encoding="utf-8") as handle:
        for row in weak_review:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "quarantine.jsonl").open("w", encoding="utf-8") as handle:
        for row in quarantine:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
