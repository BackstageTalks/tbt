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
from tbt.services.publication import (
    validate_market_publication_candidate,
    validate_publication_candidate,
)


PREDICTION_ASSETS = {"feed.json", "ledger.json"}
PLAYER_PROFILE_ASSET = "player_profiles.json"
PLAYER_PHOTO_ASSET = "player_photos.zip"


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
                    if player_id:
                        ids.add(player_id)
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
                        if player_id:
                            ids.add(player_id)
    return ids


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
    if not player_id or not isinstance(profile, dict):
        return
    if profile.get("rank") not in (None, ""):
        player["rank"] = profile.get("rank")
    for source, target in (
        ("country_code", "country_code"),
        ("country_code3", "country_code3"),
        ("country_name", "country_name"),
    ):
        if profile.get(source) not in (None, ""):
            player[target] = profile.get(source)
    photo_file = Path(str(profile.get("photo_file") or "")).name
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

    for key in (
        "upcoming", "results", "prime_picks", "top_daily_picks", "top_daily", "daily_picks",
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
    # temporary player-asset release race/corruption must not block a valid
    # prediction deployment; fail soft and deploy initials/no current metadata.
    if not _release_exists(repository, "tbt-player-assets-v1"):
        return payload

    try:
        cache = ROOT / ".cache" / "tbt" / "deploy-player-assets"
        store = ReleaseStore(repository, "tbt-player-assets-v1", cache)
        assets = store._asset_names()
        required = {PLAYER_PROFILE_ASSET, PLAYER_PHOTO_ASSET}
        if not required <= assets:
            return payload
        store.download(
            extra_names=(PLAYER_PROFILE_ASSET, PLAYER_PHOTO_ASSET),
            required_names=(PLAYER_PROFILE_ASSET, PLAYER_PHOTO_ASSET),
        )
        profiles, profile_payload = _load_player_profiles(cache / PLAYER_PROFILE_ASSET)
        player_ids = _feed_player_ids(payload)
        photos = _extract_current_photos(cache / PLAYER_PHOTO_ASSET, player_ids)
        _merge_player_profiles(payload, profiles, photos)
        payload["player_assets"] = {
            "schema": 1,
            "generated_at": profile_payload.get("generated_at"),
            "profiles_cached": len(profiles),
            "photos_deployed": len(photos),
            "presentation_only": True,
        }
    except Exception as exc:
        print(f"Optional player assets skipped: {type(exc).__name__}: {exc}")
    return payload


def main() -> None:
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
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
            store.download(
                extra_names=("feed.json", "ledger.json"),
                required_names=("feed.json", "ledger.json"),
            )
            payload = read_feed(cache / "feed.json")
            ledger = json.loads((cache / "ledger.json").read_text(encoding="utf-8"))
            validate_publication_candidate(payload, ledger)
            if (payload.get("market_selection") or {}).get("publication_schema") == 1:
                validate_market_publication_candidate(payload, ledger)
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
