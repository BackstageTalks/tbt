"""Validate that presentation enrichment is actually present in the serving feed.

This is a deployment guard, not a model-quality gate. It verifies that a non-empty
current feed has been merged with the freshly published player/tournament asset
release before Azure deployment. Provider gaps are allowed for individual rows,
but a completely un-enriched feed is rejected.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROW_KEYS = (
    "upcoming", "results", "prime_picks", "top_daily_picks", "top_daily",
    "daily_picks", "value_picks", "value", "doubles_picks", "doubles",
    "ace_picks", "aces", "ace_markets", "sg_picks", "sets_games",
    "set_game_picks",
)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(items: Any) -> None:
        if not isinstance(items, list):
            return
        for row in items:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("event_id") or row.get("id") or ""),
                str((row.get("player1") or {}).get("id") if isinstance(row.get("player1"), dict) else ""),
                str((row.get("player2") or {}).get("id") if isinstance(row.get("player2"), dict) else ""),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(row)

    for key in ROW_KEYS:
        add(payload.get(key))
    markets = payload.get("markets")
    if isinstance(markets, dict):
        for items in markets.values():
            add(items)
    return out


def audit(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    players: list[dict[str, Any]] = []
    tournaments = 0
    tournament_logos = 0

    for row in rows:
        tournament_id = row.get("tournament_logo_id") or row.get("tournament_id") or row.get("tournamentId")
        if tournament_id not in (None, ""):
            tournaments += 1
            if row.get("tournament_logo_url"):
                tournament_logos += 1
        for key in ("player1", "player2"):
            player = row.get(key)
            if isinstance(player, dict) and player.get("id") not in (None, ""):
                players.append(player)

    def count(field: str) -> int:
        return sum(1 for p in players if p.get(field) not in (None, "", 0))

    enriched_players = sum(
        1
        for p in players
        if any(
            p.get(field) not in (None, "", 0)
            for field in ("rank", "country_code", "photo_url", "best_rank", "ranking_points")
        )
    )

    def presentation_count(field: str) -> int:
        total = 0
        for player in players:
            presentation = player.get("presentation") if isinstance(player.get("presentation"), dict) else {}
            value = presentation.get(field)
            if isinstance(value, dict):
                if value.get("matches") not in (None, "", 0) or value.get("win_pct") not in (None, ""):
                    total += 1
            elif value not in (None, "", 0):
                total += 1
        return total

    return {
        "ready": bool(payload.get("ready")),
        "rows": len(rows),
        "player_instances": len(players),
        "player_instances_enriched": enriched_players,
        "rank": count("rank"),
        "country": count("country_code"),
        "photo": count("photo_url"),
        "best_rank": count("best_rank"),
        "ranking_points": count("ranking_points"),
        "recent_form": presentation_count("recent_form"),
        "surface_form": presentation_count("surface_form"),
        "h2h_wins": presentation_count("h2h_wins"),
        "tournament_instances": tournaments,
        "tournament_logos": tournament_logos,
        "player_assets": payload.get("player_assets") or {},
        "tournament_assets": payload.get("tournament_assets") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("feed", nargs="?", default="api/data/feed.json")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    path = Path(args.feed)
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = audit(payload)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Empty/not-ready feeds are valid in environments without a published candidate.
    if not report["ready"] or report["rows"] == 0:
        return

    if report["player_instances"] and not report["player_assets"]:
        raise SystemExit("Serving feed has current players but no player_assets merge metadata")
    if report["player_instances"] and report["player_instances_enriched"] == 0:
        raise SystemExit("Serving feed has current players but zero player presentation enrichment")
    # A current prediction release built with the analytics-aware engine must
    # carry point-in-time Form LXX fields. If this is zero across a non-empty
    # feed, we are deploying an old prediction candidate and player-card
    # enrichment alone cannot repair it.
    if report["player_instances"] and report["recent_form"] == 0:
        raise SystemExit("Serving feed has no point-in-time recent_form data; refresh current predictions before deployment")
    if report["rows"] and report["tournament_instances"] == 0:
        raise SystemExit("Serving feed rows contain no tournament IDs; refresh current predictions before deployment")
    if report["tournament_instances"] and not report["tournament_assets"]:
        raise SystemExit("Serving feed has tournaments but no tournament_assets merge metadata")

    if args.summary:
        print(
            f"Presentation enrichment OK: {report['player_instances_enriched']}/"
            f"{report['player_instances']} player instances enriched; "
            f"Form LXX {report['recent_form']}/{report['player_instances']}; "
            f"surface LXX {report['surface_form']}/{report['player_instances']}; "
            f"{report['tournament_logos']}/{report['tournament_instances']} tournament logos."
        )


if __name__ == "__main__":
    main()
