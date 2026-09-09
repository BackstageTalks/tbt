"""Build cached current player presentation metadata for BlinQ cards.

The enrichment is deliberately separate from historical training data. It reads the
current private prediction feed, refreshes current ATP/WTA ranking snapshots, fills
country metadata, optionally falls back to the per-player ranking endpoint, and
caches player images from the verified ``/player/{id}/image`` endpoint.

Output is published to the private ``tbt-player-assets-v1`` release as:
- player_profiles.json
- player_photos.zip
- player_enrichment_report.json

No API credentials are written to artifacts.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.budget import RequestBudgetExceeded
from tbt.utils import safe_int

PROFILE_ASSET = "player_profiles.json"
PHOTO_ASSET = "player_photos.zip"
REPORT_ASSET = "player_enrichment_report.json"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if candidate not in (None, ""):
            return candidate
    return None


def _participant(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("team", "player", "participant", "competitor", "athlete"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return row


def _rank_value(row: dict[str, Any], participant: dict[str, Any]) -> int | None:
    for source in (row, participant):
        for key in ("ranking", "rank", "position", "currentRanking", "current_rank"):
            value = source.get(key)
            if isinstance(value, dict):
                value = _first(value, "ranking", "rank", "position", "value")
            parsed = safe_int(value)
            if parsed is not None and parsed > 0:
                return parsed
    return None


def profile_from_ranking_row(
    row: dict[str, Any],
    *,
    tour: str | None = None,
    assumed_player_id: str | int | None = None,
) -> dict[str, Any] | None:
    """Normalise one provider ranking record.

    ``getPlayerRankings`` is already scoped to a concrete player id. Some of its
    ranking-history rows can omit the nested team id, so callers may pass that
    known id as ``assumed_player_id``. An explicit conflicting id is never
    overwritten.
    """
    participant = _participant(row)
    explicit_player_id = _first(participant, "id", "playerId", "player_id", "teamId") or _first(
        row, "playerId", "player_id", "teamId"
    )
    player_id = explicit_player_id if explicit_player_id not in (None, "") else assumed_player_id
    if player_id in (None, ""):
        return None

    country = _as_dict(participant.get("country")) or _as_dict(row.get("country"))
    alpha2 = _first(country, "alpha2", "code", "countryCode")
    alpha3 = _first(country, "alpha3")
    name = _first(participant, "name", "fullName", "shortName", "playerName") or _first(
        row, "name", "playerName"
    )
    rank = _rank_value(row, participant)

    profile: dict[str, Any] = {
        "id": str(player_id),
        "name": str(name or "").strip(),
        "rank": rank,
        "country_code": str(alpha2).upper() if alpha2 else None,
        "country_code3": str(alpha3).upper() if alpha3 else None,
        "country_name": str(country.get("name") or "").strip() or None,
    }
    if tour:
        profile["tour"] = str(tour).upper()
    return profile


def _ranking_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rankings", "data", "result", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _merge_profile(base: dict[str, Any], update: dict[str, Any], *, source: str) -> dict[str, Any]:
    merged = dict(base)
    for key in ("name", "rank", "country_code", "country_code3", "country_name", "tour"):
        value = update.get(key)
        if value not in (None, ""):
            merged[key] = value
    merged["ranking_source"] = source
    merged["metadata_updated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return default
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_extract_photos(zip_path: Path, photos_dir: Path) -> None:
    if not zip_path.is_file():
        return
    photos_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name or name != info.filename and not info.filename.startswith("players/"):
                continue
            if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
                continue
            target = photos_dir / name
            with archive.open(info, "r") as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)


def _build_photo_zip(photos_dir: Path, zip_path: Path) -> None:
    temporary = zip_path.with_suffix(zip_path.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(photos_dir.glob("*")):
            if path.is_file():
                archive.write(path, arcname=f"players/{path.name}")
    temporary.replace(zip_path)


def _photo_extension(data: bytes, media_type: str) -> str | None:
    media = str(media_type or "").lower()
    if "png" in media or data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if "webp" in media or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return "webp"
    if "jpeg" in media or "jpg" in media or data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def _recently_unavailable(profile: dict[str, Any], *, days: int = 30) -> bool:
    if profile.get("photo_status") != "unavailable":
        return False
    stamp = profile.get("photo_checked_at")
    if not isinstance(stamp, str):
        return False
    try:
        checked = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - checked.astimezone(timezone.utc) < timedelta(days=days)


def _current_players(feed: dict[str, Any]) -> list[dict[str, Any]]:
    """Return unique current players, prioritising the strongest visible picks."""
    scored: dict[str, dict[str, Any]] = {}
    rows = feed.get("upcoming") if isinstance(feed, dict) else []
    if not isinstance(rows, list):
        return []
    for row in rows:
        if not isinstance(row, dict):
            continue
        confidence = row.get("confidence")
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = 0.0
        tour = str(row.get("tour") or "").upper()
        for key in ("player1", "player2"):
            player = row.get(key)
            if not isinstance(player, dict):
                continue
            player_id = str(player.get("id") or "").strip()
            if not player_id or not player_id.isdigit():
                continue
            item = scored.get(player_id)
            candidate = {
                "id": player_id,
                "name": str(player.get("name") or "").strip(),
                "tour": tour,
                "priority": score,
            }
            if item is None or candidate["priority"] > item["priority"]:
                scored[player_id] = candidate
    return sorted(scored.values(), key=lambda row: (-row["priority"], row["name"], row["id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument("--max-players", type=int, default=0, help="0 = all current feed players")
    parser.add_argument("--max-photo-requests", type=int, default=250)
    parser.add_argument("--max-fallback-ranking-requests", type=int, default=100)
    parser.add_argument("--refresh-photos", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(ROOT / ".cache" / "tbt" / "player-enrichment"),
    )
    args = parser.parse_args()

    for name, value in (
        ("max_players", args.max_players),
        ("max_photo_requests", args.max_photo_requests),
        ("max_fallback_ranking_requests", args.max_fallback_ranking_requests),
    ):
        if value < 0:
            parser.error(f"{name} must be >= 0")

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    prediction_store = ReleaseStore(args.data_repository, "tbt-predictions-v1", cache / "predictions")
    prediction_store.download(extra_names=("feed.json",), required_names=("feed.json",))
    feed = _load_json(cache / "predictions" / "feed.json", {})
    players = _current_players(feed)
    if args.max_players > 0:
        players = players[: args.max_players]
    if not players:
        raise SystemExit("Current prediction feed contains no numeric player IDs to enrich")

    asset_store = ReleaseStore(args.data_repository, "tbt-player-assets-v1", cache / "assets")
    existing_assets = asset_store._asset_names()
    relevant_assets = {PROFILE_ASSET, PHOTO_ASSET, REPORT_ASSET} & existing_assets
    if relevant_assets:
        asset_store.download(extra_names=tuple(sorted(relevant_assets)))

    profile_path = cache / "assets" / PROFILE_ASSET
    photo_zip_path = cache / "assets" / PHOTO_ASSET
    report_path = cache / "assets" / REPORT_ASSET
    photos_dir = cache / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    _safe_extract_photos(photo_zip_path, photos_dir)

    cached = _load_json(profile_path, {"schema": 1, "players": {}})
    cached_players = cached.get("players") if isinstance(cached, dict) else {}
    if not isinstance(cached_players, dict):
        cached_players = {}

    profiles: dict[str, dict[str, Any]] = {
        str(key): dict(value)
        for key, value in cached_players.items()
        if isinstance(value, dict)
    }

    provider = RapidTennisClient(request_budget=None)
    provider.request_limit = 2 + args.max_fallback_ranking_requests + args.max_photo_requests
    report: dict[str, Any] = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "current tbt-predictions-v1 upcoming players",
        "players_requested": len(players),
        "ranking_snapshot_requests": 0,
        "ranking_snapshot_matches": 0,
        "fallback_ranking_requests": 0,
        "fallback_ranking_matches": 0,
        "photo_requests": 0,
        "photos_downloaded": 0,
        "photos_cached": 0,
        "photos_unavailable": 0,
        "players_with_rank": 0,
        "players_with_country": 0,
        "errors": [],
    }

    try:
        ranking_index: dict[str, dict[str, Any]] = {}
        for tour in ("atp", "wta"):
            try:
                report["ranking_snapshot_requests"] += 1
                rows = provider.rankings(tour)
            except Exception as exc:
                report["errors"].append(f"{tour.upper()} ranking snapshot: {type(exc).__name__}: {exc}")
                continue
            for row in rows:
                parsed = profile_from_ranking_row(row, tour=tour)
                if parsed is not None:
                    ranking_index[parsed["id"]] = parsed

        for item in players:
            player_id = item["id"]
            base = profiles.get(player_id, {"id": player_id})
            base.setdefault("name", item["name"])
            base.setdefault("tour", item["tour"])
            ranked = ranking_index.get(player_id)
            if ranked:
                profiles[player_id] = _merge_profile(base, ranked, source="tour_ranking_snapshot")
                report["ranking_snapshot_matches"] += 1
            else:
                profiles[player_id] = base

        fallback_budget = args.max_fallback_ranking_requests
        for item in players:
            if fallback_budget <= 0:
                break
            player_id = item["id"]
            profile = profiles[player_id]
            if profile.get("rank") not in (None, "") and profile.get("country_code"):
                continue
            try:
                report["fallback_ranking_requests"] += 1
                fallback_budget -= 1
                payload = provider.player_rankings(player_id)
                candidates = []
                for row in _ranking_rows(payload):
                    parsed = profile_from_ranking_row(
                        row, tour=item["tour"], assumed_player_id=player_id
                    )
                    if parsed is None:
                        continue
                    if parsed.get("id") != player_id:
                        # Some payloads omit id on the ranking record but carry the
                        # player's team data on another row. Do not cross-assign.
                        continue
                    candidates.append(parsed)
                if candidates:
                    candidates.sort(key=lambda p: (p.get("rank") is None, p.get("rank") or 10**9))
                    profiles[player_id] = _merge_profile(
                        profile, candidates[0], source="player_rankings_fallback"
                    )
                    report["fallback_ranking_matches"] += 1
            except RequestBudgetExceeded as exc:
                report["errors"].append(f"ranking request budget stopped: {exc}")
                break
            except Exception as exc:
                report["errors"].append(
                    f"ranking {player_id} {item['name']}: {type(exc).__name__}: {exc}"
                )

        photo_budget = args.max_photo_requests
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in players:
            player_id = item["id"]
            profile = profiles[player_id]
            existing_file = str(profile.get("photo_file") or "")
            if existing_file and (photos_dir / Path(existing_file).name).is_file() and not args.refresh_photos:
                report["photos_cached"] += 1
                continue
            if not args.refresh_photos and _recently_unavailable(profile):
                report["photos_unavailable"] += 1
                continue
            if photo_budget <= 0:
                break
            try:
                report["photo_requests"] += 1
                photo_budget -= 1
                result = provider.player_image(player_id)
                profile["photo_checked_at"] = now_iso
                if result is None:
                    profile["photo_status"] = "unavailable"
                    report["photos_unavailable"] += 1
                    continue
                data, media_type = result
                ext = _photo_extension(data, media_type)
                if ext is None:
                    profile["photo_status"] = "invalid_media"
                    report["errors"].append(
                        f"photo {player_id} {item['name']}: unsupported media type {media_type or 'unknown'}"
                    )
                    continue
                # Remove an older format if the provider changed it.
                for old in photos_dir.glob(f"{player_id}.*"):
                    if old.name != f"{player_id}.{ext}":
                        old.unlink(missing_ok=True)
                filename = f"{player_id}.{ext}"
                (photos_dir / filename).write_bytes(data)
                profile["photo_file"] = filename
                profile["photo_status"] = "available"
                profile["photo_fetched_at"] = now_iso
                report["photos_downloaded"] += 1
            except RequestBudgetExceeded as exc:
                report["errors"].append(f"photo request budget stopped: {exc}")
                break
            except Exception as exc:
                report["errors"].append(
                    f"photo {player_id} {item['name']}: {type(exc).__name__}: {exc}"
                )

    finally:
        provider.client.close()

    for item in players:
        profile = profiles[item["id"]]
        if profile.get("rank") not in (None, ""):
            report["players_with_rank"] += 1
        if profile.get("country_code"):
            report["players_with_country"] += 1

    report["rapidapi_requests"] = provider.request_count
    report["rapidapi_remaining"] = provider.rate_limit_remaining
    report["profiles_total_cached"] = len(profiles)
    report["photo_files_total_cached"] = len([p for p in photos_dir.glob("*") if p.is_file()])

    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "presentation_only": True,
        "historical_training_eligible": False,
        "players": profiles,
    }
    _write_json(profile_path, payload)
    _build_photo_zip(photos_dir, photo_zip_path)
    _write_json(report_path, report)
    asset_store.upload_bundle([profile_path, photo_zip_path, report_path])

    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, default=str))


if __name__ == "__main__":
    main()
