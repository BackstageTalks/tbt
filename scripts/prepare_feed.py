"""Fetch the small private serving snapshot before an Azure deployment."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed, read_feed
from tbt.services.countries import normalize_country_code
from tbt.services.publication import (
    validate_market_publication_candidate,
    restore_published_market_snapshots,
    validate_publication_candidate,
)


PREDICTION_ASSETS = {"feed.json", "ledger.json"}
PLAYER_PROFILE_ASSET = "player_profiles.json"
PLAYER_PHOTO_ASSET = "player_photos.zip"
TOURNAMENT_PROFILE_ASSET = "tournament_profiles.json"
TOURNAMENT_LOGO_ASSET = "tournament_logos.zip"
COMPARATOR_ASSET = "comparator.json"


def _prediction_asset_state(store: ReleaseStore) -> str:
    assets = store._asset_names()
    present = PREDICTION_ASSETS & assets
    if not present:
        return "absent"
    if present != PREDICTION_ASSETS:
        missing = sorted(PREDICTION_ASSETS - present)
        raise FileNotFoundError(
            "Prediction release is incomplete; missing assets: " + ", ".join(missing)
        )
    return "complete"


def _release_exists(repository: str, tag: str) -> bool:
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repository}/releases/tags/{tag}"],
            capture_output=True,
            text=True,
        )
    except OSError:
        # Optional presentation metadata must never make an otherwise valid
        # local/test deployment fail only because GitHub CLI is unavailable.
        return False
    return result.returncode == 0


def _load_player_profiles(path: Path) -> tuple[dict[str, dict], dict]:
    if not path.is_file():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return {}, {}
    players = payload.get("players")
    if not isinstance(players, dict):
        return {}, payload
    return {
        str(player_id): profile
        for player_id, profile in players.items()
        if isinstance(profile, dict)
    }, payload


def _feed_player_ids(payload: dict) -> set[str]:
    ids: set[str] = set()
    keys = (
        "upcoming",
        "results",
        "prime_picks",
        "top_daily_picks",
        "top_daily",
        "daily_picks",
        "value_picks",
        "value",
        "doubles_picks",
        "doubles",
        "ace_picks",
        "aces",
        "ace_markets",
        "sg_picks",
        "sets_games",
        "set_game_picks",
    )
    for key in keys:
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for player_key in ("player1", "player2"):
                player = row.get(player_key)
                if isinstance(player, dict):
                    player_id = str(player.get("id") or "").strip()
                    members = player.get("members") if isinstance(player.get("members"), list) else []
                    # Team IDs are not player photo IDs; only member IDs belong
                    # in the image bundle for doubles.
                    if player_id and not (row.get("prediction_family") == "doubles" or len(members) >= 2):
                        ids.add(player_id)
                    for member in members:
                        if not isinstance(member, dict):
                            continue
                        member_id = str(member.get("id") or "").strip()
                        if member_id:
                            ids.add(member_id)
    markets = payload.get("markets")
    if isinstance(markets, dict):
        for rows in markets.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for player_key in ("player1", "player2"):
                    player = row.get(player_key)
                    if isinstance(player, dict):
                        player_id = str(player.get("id") or "").strip()
                        members = player.get("members") if isinstance(player.get("members"), list) else []
                        if player_id and not (row.get("prediction_family") == "doubles" or len(members) >= 2):
                            ids.add(player_id)
                        for member in members:
                            if isinstance(member, dict) and member.get("id"):
                                ids.add(str(member["id"]).strip())
    return ids


def _feed_tournament_ids(payload: dict) -> set[str]:
    ids: set[str] = set()
    keys = (
        "upcoming", "results", "top200_picks", "prime_picks", "top_daily_picks", "top_daily", "daily_picks",
        "value_picks", "value", "doubles_picks", "doubles", "ace_picks", "aces", "ace_markets",
        "sg_picks", "sets_games", "set_game_picks",
    )
    for key in keys:
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            tournament_id = str(row.get("tournament_logo_id") or row.get("tournament_id") or row.get("tournamentId") or "").strip()
            if tournament_id:
                ids.add(tournament_id)
    markets = payload.get("markets")
    if isinstance(markets, dict):
        for rows in markets.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                tournament_id = str(row.get("tournament_logo_id") or row.get("tournament_id") or row.get("tournamentId") or "").strip()
                if tournament_id:
                    ids.add(tournament_id)
    return ids


def _load_tournament_profiles(path: Path) -> tuple[dict[str, dict], dict]:
    if not path.is_file():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return {}, payload if isinstance(payload, dict) else {}
    tournaments = payload.get("tournaments")
    if not isinstance(tournaments, dict):
        return {}, payload
    return {
        str(tournament_id): profile
        for tournament_id, profile in tournaments.items()
        if isinstance(profile, dict)
    }, payload


def _extract_current_tournament_logos(zip_path: Path, tournament_ids: set[str]) -> set[str]:
    target_dir = ROOT / "web" / "assets" / "tournaments"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted: set[str] = set()
    if not zip_path.is_file() or not tournament_ids:
        return extracted
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            filename = Path(info.filename).name
            if not filename:
                continue
            stem = Path(filename).stem
            if stem not in tournament_ids:
                continue
            if not filename.replace("-", "").replace("_", "").replace(".", "").isalnum():
                continue
            target = target_dir / filename
            with archive.open(info, "r") as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            extracted.add(filename)
    return extracted


def _extract_current_photos(zip_path: Path, player_ids: set[str]) -> set[str]:
    target_dir = ROOT / "web" / "assets" / "players"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted: set[str] = set()
    if not zip_path.is_file() or not player_ids:
        return extracted

    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            filename = Path(info.filename).name
            if not filename:
                continue
            stem = Path(filename).stem
            if stem not in player_ids:
                continue
            if not filename.replace("-", "").replace("_", "").replace(".", "").isalnum():
                continue
            target = target_dir / filename
            with archive.open(info, "r") as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            extracted.add(filename)
    return extracted


def _merge_player_profile(player: dict, profiles: dict[str, dict], photos: set[str]) -> None:
    player_id = str(player.get("id") or "").strip()
    profile = profiles.get(player_id)
    if not player_id:
        return
    profile = profile if isinstance(profile, dict) else {}
    if profile.get("rank") not in (None, ""):
        player["rank"] = profile.get("rank")
    for source, target in (
        ("previous_rank", "previous_rank"),
        ("best_rank", "best_rank"),
        ("ranking_points", "ranking_points"),
        ("country_code", "country_code"),
        ("country_code3", "country_code3"),
        ("country_name", "country_name"),
        ("birth_date", "birth_date"),
        ("birth_timestamp", "birth_timestamp"),
        ("height_cm", "height_cm"),
        ("hand", "hand"),
        ("birthplace", "birthplace"),
        ("residence", "residence"),
    ):
        if profile.get(source) not in (None, ""):
            player[target] = profile.get(source)
    normalized_country = normalize_country_code(player.get("country_code") or player.get("country_code3"))
    if normalized_country:
        player["country_code"] = normalized_country
    photo_file = Path(str(profile.get("photo_file") or "")).name
    if photo_file not in photos:
        # A profile and its photo archive can be refreshed separately. Recover
        # by exact player ID from files actually shipped; never invent a URL.
        photo_file = next((name for name in sorted(photos)
                           if Path(name).stem == player_id
                           and Path(name).suffix.lower() in {".webp", ".png", ".jpg", ".jpeg"}), "")
    if photo_file and photo_file in photos:
        player["photo_url"] = f"/assets/players/{photo_file}"


def _merge_player_profiles(payload: dict, profiles: dict[str, dict], photos: set[str]) -> None:
    def enrich_rows(rows):
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("player1", "player2"):
                player = row.get(key)
                if isinstance(player, dict):
                    _merge_player_profile(player, profiles, photos)
                    members = player.get("members") if isinstance(player.get("members"), list) else []
                    for member in members:
                        if isinstance(member, dict):
                            _merge_player_profile(member, profiles, photos)

    for key in (
        "upcoming", "results", "top200_picks", "prime_picks", "top_daily_picks", "top_daily", "daily_picks",
        "value_picks", "value", "doubles_picks", "doubles", "ace_picks", "aces", "ace_markets",
        "sg_picks", "sets_games", "set_game_picks",
    ):
        enrich_rows(payload.get(key))
    markets = payload.get("markets")
    if isinstance(markets, dict):
        for rows in markets.values():
            enrich_rows(rows)


def _merge_tournament_profiles(payload: dict, profiles: dict[str, dict], logos: set[str]) -> None:
    def enrich_rows(rows):
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            tournament_id = str(row.get("tournament_logo_id") or row.get("tournament_id") or row.get("tournamentId") or "").strip()
            profile = profiles.get(tournament_id)
            if not tournament_id or not isinstance(profile, dict):
                continue
            logo_file = Path(str(profile.get("logo_file") or "")).name
            if logo_file and logo_file in logos:
                row["tournament_logo_url"] = f"/assets/tournaments/{logo_file}"
    for key in (
        "upcoming", "results", "top200_picks", "prime_picks", "top_daily_picks", "top_daily", "daily_picks",
        "value_picks", "value", "doubles_picks", "doubles", "ace_picks", "aces", "ace_markets",
        "sg_picks", "sets_games", "set_game_picks",
    ):
        enrich_rows(payload.get(key))
    markets = payload.get("markets")
    if isinstance(markets, dict):
        for rows in markets.values():
            enrich_rows(rows)


def _attach_player_assets(payload: dict, repository: str) -> dict:
    # Presentation metadata is optional. The prediction release remains the sole
    # source of prediction commitments and is validated before this merge. A
    # temporary player/tournament asset release race or download failure must
    # never block an otherwise valid prediction deployment. The web client has
    # local player initials and tournament-type fallback assets.
    payload.setdefault("player_assets", {
        "schema": 1,
        "available": False,
        "presentation_only": True,
        "fallback": "initials_or_feed_fields",
    })
    payload.setdefault("tournament_assets", {
        "schema": 1,
        "available": False,
        "presentation_only": True,
        "fallback": "local_tournament_type_assets",
    })
    if not _release_exists(repository, "tbt-player-assets-v1"):
        return payload

    try:
        cache = ROOT / ".cache" / "tbt" / "deploy-player-assets"
        store = ReleaseStore(repository, "tbt-player-assets-v1", cache)
        assets = store._asset_names()
        required = {PLAYER_PROFILE_ASSET, PLAYER_PHOTO_ASSET}
        if not required <= assets:
            return payload
        optional = tuple(
            name for name in (TOURNAMENT_PROFILE_ASSET, TOURNAMENT_LOGO_ASSET)
            if name in assets
        )
        store.download(
            extra_names=(PLAYER_PROFILE_ASSET, PLAYER_PHOTO_ASSET, *optional),
            required_names=(PLAYER_PROFILE_ASSET, PLAYER_PHOTO_ASSET),
        )
        profiles, profile_payload = _load_player_profiles(cache / PLAYER_PROFILE_ASSET)
        player_ids = _feed_player_ids(payload)
        photos = _extract_current_photos(cache / PLAYER_PHOTO_ASSET, player_ids)
        _merge_player_profiles(payload, profiles, photos)
        payload["player_assets"] = {
            "schema": 1,
            "available": True,
            "generated_at": profile_payload.get("generated_at"),
            "profiles_cached": len(profiles),
            "photos_deployed": len(photos),
            "player_ids_requested": len(player_ids),
            "photo_coverage": round(len({Path(name).stem for name in photos}) / len(player_ids), 4) if player_ids else 0.0,
            "photos_missing": max(0, len(player_ids) - len({Path(name).stem for name in photos})),
            "presentation_only": True,
            "fallback": "local_atp_wta_artwork_then_initials",
        }
        if {TOURNAMENT_PROFILE_ASSET, TOURNAMENT_LOGO_ASSET} <= assets:
            tournament_profiles, tournament_payload = _load_tournament_profiles(cache / TOURNAMENT_PROFILE_ASSET)
            tournament_ids = _feed_tournament_ids(payload)
            logos = _extract_current_tournament_logos(cache / TOURNAMENT_LOGO_ASSET, tournament_ids)
            _merge_tournament_profiles(payload, tournament_profiles, logos)
            payload["tournament_assets"] = {
                "schema": 1,
                "available": True,
                "generated_at": tournament_payload.get("generated_at"),
                "profiles_cached": len(tournament_profiles),
                "logos_deployed": len(logos),
                "tournament_ids_requested": len(tournament_ids),
                "logo_coverage": round(len({Path(name).stem for name in logos}) / len(tournament_ids), 4) if tournament_ids else 0.0,
                "logos_missing": max(0, len(tournament_ids) - len({Path(name).stem for name in logos})),
                "presentation_only": True,
                "fallback": "local_tournament_type_assets",
            }
    except Exception as exc:
        # Keep the release deployable but preserve why real photos were absent.
        payload["player_assets"]["error_type"] = type(exc).__name__
        print(f"Optional player assets skipped: {type(exc).__name__}: {exc}")
    return payload



def _deploy_comparator_artifact(source: Path) -> dict:
    target = ROOT / "api/data/comparator.json"
    if not source.is_file():
        target.unlink(missing_ok=True)
        return {"available": False, "reason": "release_asset_missing"}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        target.unlink(missing_ok=True)
        raise ValueError("Invalid comparator JSON artifact") from exc
    if (
        not isinstance(payload, dict)
        or int(payload.get("schema") or 0) != 1
        or not isinstance(payload.get("model"), dict)
        or int((payload.get("model") or {}).get("schema") or 0) != 1
        or not isinstance(payload.get("feature_state"), dict)
        or not isinstance(payload.get("players"), list)
        or not payload.get("generated_at")
        or not payload.get("cutoff_utc")
    ):
        target.unlink(missing_ok=True)
        raise ValueError("Comparator artifact failed serving schema validation")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return {
        "available": True,
        "players": len(payload["players"]),
        "model_version": str((payload.get("model") or {}).get("model_version") or ""),
        "generated_at": payload.get("generated_at"),
        "cutoff_utc": payload.get("cutoff_utc"),
    }

def main() -> None:
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    comparator_target = ROOT / "api/data/comparator.json"
    comparator_target.unlink(missing_ok=True)
    repository = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")

    payload = empty_feed()
    if os.getenv("GH_TOKEN"):
        # Verify/download the complete private prediction candidate in cache.
        # Never download ledger.json into api/data, where it could be packaged
        # with the public serving API.
        cache = ROOT / ".cache/tbt/deploy-predictions"
        store = ReleaseStore(repository, "tbt-predictions-v1", cache)
        state = _prediction_asset_state(store)
        if state == "complete":
            assets = store._asset_names()
            optional = (COMPARATOR_ASSET,) if COMPARATOR_ASSET in assets else ()
            store.download(
                extra_names=("feed.json", "ledger.json", *optional),
                required_names=("feed.json", "ledger.json"),
            )
            comparator_status = (
                _deploy_comparator_artifact(cache / COMPARATOR_ASSET)
                if optional
                else {"available": False, "reason": "release_asset_missing"}
            )
            print("Comparator serving artifact:", json.dumps(comparator_status, ensure_ascii=False))
            payload = read_feed(cache / "feed.json")
            ledger = json.loads((cache / "ledger.json").read_text(encoding="utf-8"))
            validate_publication_candidate(payload, ledger)
            if (payload.get("market_selection") or {}).get("publication_schema") == 1:
                ace_before = len(payload.get("ace_picks") or []) if isinstance(payload.get("ace_picks"), list) else 0
                payload = restore_published_market_snapshots(payload, ledger)
                validate_market_publication_candidate(payload, ledger)
                ace_after = len(payload.get("ace_picks") or []) if isinstance(payload.get("ace_picks"), list) else 0
                if ace_after < ace_before:
                    print(
                        "Projection publication quarantine:",
                        ace_before - ace_after,
                        "legacy ESA card(s) omitted because no unique issued snapshot exists; "
                        "odds-backed sections remain strict.",
                    )
            payload = _attach_player_assets(payload, repository)

    # If no private prediction candidate exists, overwrite any checked-in stale
    # snapshot with an honest empty feed instead of silently deploying it.
    target.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(
        "Serving snapshot ready:",
        payload.get("ready", False),
        "player assets:",
        payload.get("player_assets", {}).get("photos_deployed", 0),
    )


if __name__ == "__main__":
    main()
