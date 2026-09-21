"""Separate point-in-time doubles model and publication selector.

This module never reuses the singles model.  It learns only from completed
historical doubles matches and represents a doubles side by the provider team ID
plus (when available) the stable member IDs.  The first production version is a
conservative Elo-style model with pair, member and surface components.  It
fails closed when identity/history depth is insufficient and only publishes a
pick after a real provider Match Winner price is attached.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any, Iterable

from ..schemas import MatchRecord
from .engine import event_id

MODEL_VERSION = "DOUBLES-ELO-v1"
MIN_HISTORY_MATCHES = 200
MIN_PAIR_MATCHES = 3
MIN_MEMBER_MATCHES = 4
MIN_SURFACE_MATCHES = 2
MIN_DATA_DEPTH = 0.35
MIN_PUBLIC_PROBABILITY = 0.58
MIN_ODDS = 1.35
MAX_ODDS = 3.50
MIN_EXPECTED_VALUE = 0.02
MAX_PICKS = 10


def _surface(value: Any) -> str:
    text = str(value or "unknown").strip().lower().replace(" ", "_")
    return text or "unknown"


def _members_from_side(side: Any) -> list[dict[str, str]]:
    if not isinstance(side, dict):
        return []
    raw = side.get("players")
    if not isinstance(raw, list):
        raw = side.get("members")
    if not isinstance(raw, list):
        raw = side.get("subTeams")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or item.get("playerId") or item.get("teamId") or "").strip()
        name = str(item.get("name") or item.get("shortName") or item.get("slug") or "").strip()
        if pid or name:
            result.append({"id": pid, "name": name})
    return result[:4]


def match_members(match: MatchRecord, side: int) -> list[dict[str, str]]:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    key = "homeTeam" if side == 1 else "awayTeam"
    members = _members_from_side(payload.get(key))
    if members:
        return members
    # Some provider responses use player1/player2 objects even for team events.
    key = "player1" if side == 1 else "player2"
    return _members_from_side(payload.get(key))


def _history_members(row: dict[str, Any], side: int) -> list[dict[str, str]]:
    players = row.get("player1_members" if side == 1 else "player2_members")
    if not isinstance(players, list):
        return []
    result = []
    for item in players:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if pid or name:
            result.append({"id": pid, "name": name})
    return result[:4]


def _member_key(member: dict[str, str]) -> str:
    pid = str(member.get("id") or "").strip()
    if pid:
        return "id:" + pid
    name = " ".join(str(member.get("name") or "").casefold().split())
    return "name:" + name if name else ""


def _pair_key(team_id: Any, members: list[dict[str, str]], name: Any = "") -> str:
    member_keys = sorted(k for k in (_member_key(m) for m in members) if k)
    if len(member_keys) >= 2:
        return "members:" + "|".join(member_keys[:2])
    tid = str(team_id or "").strip()
    if tid:
        return "team:" + tid
    normalized = " ".join(str(name or "").casefold().split())
    return "name:" + normalized if normalized else ""


def compact_history_row(match: MatchRecord) -> dict[str, Any]:
    return {
        "event_id": event_id(match),
        "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
        "tour": match.tour,
        "tournament": match.tournament,
        "tournament_id": match.tournament_id,
        "surface": match.surface,
        "round_name": match.round_name,
        "player1_id": str(match.player1_id),
        "player1_name": match.player1_name,
        "player1_members": match_members(match, 1),
        "player2_id": str(match.player2_id),
        "player2_name": match.player2_name,
        "player2_members": match_members(match, 2),
        "winner_id": str(match.winner_id or ""),
        "status": match.status,
    }


def merge_history(existing: Iterable[dict[str, Any]], matches: Iterable[MatchRecord]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("event_id") or "").strip()
        if eid:
            merged[eid] = deepcopy(row)
    for match in matches:
        if not isinstance(match, MatchRecord) or not match.is_completed:
            continue
        row = compact_history_row(match)
        eid = str(row.get("event_id") or "").strip()
        if eid:
            merged[eid] = row
    return sorted(merged.values(), key=lambda row: str(row.get("scheduled_at") or ""))


def history_report(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if isinstance(row, dict) and row.get("winner_id")]
    with_members = sum(
        1 for row in valid
        if len(_history_members(row, 1)) >= 2 and len(_history_members(row, 2)) >= 2
    )
    return {
        "schema": 1,
        "model": MODEL_VERSION,
        "completed_matches": len(valid),
        "member_identity_matches": with_members,
        "member_identity_coverage": (with_members / len(valid)) if valid else 0.0,
        "activation_min_history": MIN_HISTORY_MATCHES,
        "ready": len(valid) >= MIN_HISTORY_MATCHES and (with_members / len(valid) if valid else 0.0) >= 0.90,
    }


class _RatingState:
    def __init__(self) -> None:
        self.pair = defaultdict(lambda: 1500.0)
        self.member = defaultdict(lambda: 1500.0)
        self.surface_pair = defaultdict(lambda: 1500.0)
        self.pair_matches = defaultdict(int)
        self.member_matches = defaultdict(int)
        self.surface_matches = defaultdict(int)

    @staticmethod
    def expected(diff: float) -> float:
        return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

    def member_average(self, members: list[dict[str, str]]) -> float:
        keys = [k for k in (_member_key(member) for member in members) if k]
        if not keys:
            return 1500.0
        return sum(self.member[key] for key in keys) / len(keys)

    def member_min_matches(self, members: list[dict[str, str]]) -> int:
        keys = [k for k in (_member_key(member) for member in members) if k]
        if not keys:
            return 0
        return min(self.member_matches[key] for key in keys)

    def side_rating(self, pair_key: str, members: list[dict[str, str]], surface: str) -> float:
        return (
            0.55 * self.pair[pair_key]
            + 0.30 * self.member_average(members)
            + 0.15 * self.surface_pair[(pair_key, surface)]
        )

    def update(self, row: dict[str, Any]) -> None:
        p1_id, p2_id = str(row.get("player1_id") or ""), str(row.get("player2_id") or "")
        winner = str(row.get("winner_id") or "")
        if not p1_id or not p2_id or winner not in {p1_id, p2_id}:
            return
        m1, m2 = _history_members(row, 1), _history_members(row, 2)
        k1 = _pair_key(p1_id, m1, row.get("player1_name"))
        k2 = _pair_key(p2_id, m2, row.get("player2_name"))
        if not k1 or not k2 or k1 == k2:
            return
        surface = _surface(row.get("surface"))
        r1, r2 = self.side_rating(k1, m1, surface), self.side_rating(k2, m2, surface)
        e1 = self.expected(r1 - r2)
        y1 = 1.0 if winner == p1_id else 0.0
        # Pair rating learns fastest; member ratings make unseen combinations usable.
        pair_k = 28.0 / (1.0 + min(self.pair_matches[k1], self.pair_matches[k2]) / 30.0)
        member_k = 12.0
        surface_k = 18.0
        delta = pair_k * (y1 - e1)
        self.pair[k1] += delta
        self.pair[k2] -= delta
        for member in m1:
            key = _member_key(member)
            if key:
                self.member[key] += member_k * (y1 - e1)
                self.member_matches[key] += 1
        for member in m2:
            key = _member_key(member)
            if key:
                self.member[key] -= member_k * (y1 - e1)
                self.member_matches[key] += 1
        self.surface_pair[(k1, surface)] += surface_k * (y1 - e1)
        self.surface_pair[(k2, surface)] -= surface_k * (y1 - e1)
        self.pair_matches[k1] += 1
        self.pair_matches[k2] += 1
        self.surface_matches[(k1, surface)] += 1
        self.surface_matches[(k2, surface)] += 1


def _confidence_band(probability: float) -> str:
    p = max(probability, 1.0 - probability)
    if p >= 0.70:
        return "high"
    if p >= 0.62:
        return "medium"
    return "low"


def build_predictions(history_rows: list[dict[str, Any]], upcoming: list[MatchRecord], *, now: datetime | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    report = history_report(history_rows)
    if not report.get("ready"):
        return [], {
            **report,
            "upcoming_seen": len(upcoming),
            "prediction_candidates": 0,
            "rejected": {"history_gate": len(upcoming)},
            "status": "backfill_required",
        }
    state = _RatingState()
    for row in sorted(history_rows, key=lambda item: str(item.get("scheduled_at") or "")):
        try:
            when = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None or when >= now:
            continue
        state.update(row)

    predictions: list[dict[str, Any]] = []
    rejected = defaultdict(int)
    for match in sorted(upcoming, key=lambda m: (m.scheduled_at, m.match_id)):
        if match.is_completed or match.scheduled_at <= now:
            continue
        m1, m2 = match_members(match, 1), match_members(match, 2)
        k1 = _pair_key(match.player1_id, m1, match.player1_name)
        k2 = _pair_key(match.player2_id, m2, match.player2_name)
        if not k1 or not k2 or k1 == k2:
            rejected["identity"] += 1
            continue
        pair1, pair2 = state.pair_matches[k1], state.pair_matches[k2]
        member1, member2 = state.member_min_matches(m1), state.member_min_matches(m2)
        surface = _surface(match.surface)
        surface1, surface2 = state.surface_matches[(k1, surface)], state.surface_matches[(k2, surface)]
        identity_ok = len(m1) >= 2 and len(m2) >= 2
        # Fail closed: one new pair can be supported by experienced members, but
        # both sides still need demonstrable doubles history.
        history_ok = (
            (pair1 >= MIN_PAIR_MATCHES or member1 >= MIN_MEMBER_MATCHES)
            and (pair2 >= MIN_PAIR_MATCHES or member2 >= MIN_MEMBER_MATCHES)
        )
        if not identity_ok:
            rejected["members"] += 1
            continue
        if not history_ok:
            rejected["history"] += 1
            continue

        r1 = state.side_rating(k1, m1, surface)
        r2 = state.side_rating(k2, m2, surface)
        p1 = state.expected(r1 - r2)
        p2 = 1.0 - p1
        pair_depth = min(1.0, min(pair1, pair2) / 10.0)
        member_depth = min(1.0, min(member1, member2) / 12.0)
        surface_depth = min(1.0, min(surface1, surface2) / 8.0)
        data_depth = 0.50 * pair_depth + 0.35 * member_depth + 0.15 * surface_depth
        if data_depth < MIN_DATA_DEPTH:
            rejected["depth"] += 1
            continue
        winner_id = str(match.player1_id if p1 >= 0.5 else match.player2_id)
        winner_name = match.player1_name if p1 >= 0.5 else match.player2_name
        probability = max(p1, p2)
        payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        tournament = payload.get("tournament") if isinstance(payload.get("tournament"), dict) else {}
        unique = tournament.get("uniqueTournament") if isinstance(tournament.get("uniqueTournament"), dict) else {}
        logo_id = str(unique.get("id") or match.tournament_id or "")
        quality = {
            "player1": {"matches": max(pair1, member1), "surface_matches": surface1},
            "player2": {"matches": max(pair2, member2), "surface_matches": surface2},
            "history_band": "doubles_pair_member",
            "surface_history_band": "doubles_pair_surface",
        }
        signals = []
        pair_diff = state.pair[k1] - state.pair[k2]
        member_diff = state.member_average(m1) - state.member_average(m2)
        surface_diff = state.surface_pair[(k1, surface)] - state.surface_pair[(k2, surface)]
        for label, diff in sorted(
            (("Pair history", pair_diff), ("Member doubles strength", member_diff), ("Surface pair form", surface_diff)),
            key=lambda item: abs(item[1]), reverse=True,
        ):
            if abs(diff) >= 10:
                signals.append({"label": label, "side": 1 if diff >= 0 else 2})
        predictions.append({
            "event_id": event_id(match),
            "model_version": MODEL_VERSION,
            "prediction_family": "doubles",
            "generated_at": now.astimezone(timezone.utc).isoformat(),
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
            "tour": match.tour,
            "tournament": match.tournament,
            "tournament_id": str(match.tournament_id or ""),
            "tournament_logo_id": logo_id,
            "surface": match.surface,
            "round": match.round_name,
            "round_name": match.round_name,
            "player1": {"id": str(match.player1_id), "name": match.player1_name, "probability": p1, "members": m1},
            "player2": {"id": str(match.player2_id), "name": match.player2_name, "probability": p2, "members": m2},
            "winner_id": winner_id,
            "pick": winner_name,
            "confidence": probability,
            "confidence_pct": probability * 100.0,
            "confidence_band": _confidence_band(probability),
            "data_depth": data_depth,
            "quality": quality,
            "signals": signals[:3],
            "doubles": {
                "model": MODEL_VERSION,
                "pair1_matches": pair1, "pair2_matches": pair2,
                "member1_min_matches": member1, "member2_min_matches": member2,
                "surface1_matches": surface1, "surface2_matches": surface2,
                "member_identity": True,
                "separate_from_singles": True,
            },
        })

    report = {
        **report,
        "upcoming_seen": len(upcoming),
        "prediction_candidates": len(predictions),
        "rejected": dict(rejected),
    }
    return predictions, report


def select_picks(enriched_predictions: list[dict[str, Any]], *, limit: int = MAX_PICKS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    rejected = defaultdict(int)
    for source in enriched_predictions:
        if not isinstance(source, dict) or source.get("prediction_family") != "doubles":
            continue
        betting = source.get("betting") if isinstance(source.get("betting"), dict) else {}
        if betting.get("market") != "match_winner":
            rejected["no_match_winner_odds"] += 1
            continue
        probability = betting.get("blinq_probability")
        odds = betting.get("odds")
        ev = betting.get("expected_value")
        try:
            probability, odds, ev = float(probability), float(odds), float(ev)
        except (TypeError, ValueError):
            rejected["invalid_price"] += 1
            continue
        if probability < MIN_PUBLIC_PROBABILITY:
            rejected["probability"] += 1
            continue
        if not MIN_ODDS <= odds <= MAX_ODDS:
            rejected["odds"] += 1
            continue
        if ev < MIN_EXPECTED_VALUE:
            rejected["ev"] += 1
            continue
        row = deepcopy(source)
        row["market"] = "match_winner"
        row["market_type"] = "Doubles Match Winner"
        row["selection"] = betting.get("selection")
        row["pick"] = betting.get("selection")
        row["selection_id"] = betting.get("selection_id")
        row["odds"] = odds
        row["probability"] = probability
        row["blinq_probability"] = probability
        row["edge"] = betting.get("edge")
        row["expected_value"] = ev
        row["fair_implied_probability"] = betting.get("fair_implied_probability")
        row["betting_day"] = betting.get("betting_day")
        selected.append(row)
    selected.sort(key=lambda row: (float(row.get("probability") or 0), float(row.get("data_depth") or 0)), reverse=True)
    selected = selected[: max(0, int(limit))]
    return selected, {
        "schema": 1,
        "model": MODEL_VERSION,
        "odds_backed": True,
        "selected": len(selected),
        "rejected": dict(rejected),
        "rules": {
            "min_probability": MIN_PUBLIC_PROBABILITY,
            "min_data_depth": MIN_DATA_DEPTH,
            "min_odds": MIN_ODDS,
            "max_odds": MAX_ODDS,
            "min_expected_value": MIN_EXPECTED_VALUE,
            "limit": int(limit),
        },
    }
