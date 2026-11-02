"""Fetch the small private serving snapshot before an Azure deployment."""
from __future__ import annotations

import base64
import gzip
import json
import math
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed, read_feed
from tbt.services.comparator_index import build_comparator_index
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
COMPARATOR_ASSET = "comparator.json.gz"


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
    target = ROOT / "api/data/comparator.json.gz"
    directory = ROOT / "api/data/comparator-players.json"
    index_path = ROOT / "api/data/comparator-serving.sqlite3"
    if not source.is_file():
        target.unlink(missing_ok=True)
        directory.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
        return {"available": False, "reason": "release_asset_missing"}
    try:
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        target.unlink(missing_ok=True)
        directory.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
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
        directory.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
        raise ValueError("Comparator artifact failed serving schema validation")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Search never needs the ~30 MB compressed feature/model artifact. Publish
    # only the validated canonical directory, without features or model weights.
    # Generated solely from the same checksum-verified prediction release.
    search_directory = {
        "schema": 1,
        "players": payload["players"],
        "generated_at": payload["generated_at"],
        "cutoff_utc": payload["cutoff_utc"],
        "model_version": str((payload.get("model") or {}).get("model_version") or ""),
    }
    temporary = directory.with_suffix(".json.tmp")
    try:
        index_report = build_comparator_index(payload, index_path)
        temporary.write_text(json.dumps(search_directory, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        # The checksum-verified source stays in the private release/cache. Do
        # not ship the bulky gzip alongside the indexed serving copy; it is no
        # longer needed by any public comparator request and would inflate the
        # Azure Functions package.
        target.unlink(missing_ok=True)
        temporary.replace(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        directory.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
        raise
    return {
        "indexed": index_report, 
        "available": True,
        "players": len(payload["players"]),
        "model_version": str((payload.get("model") or {}).get("model_version") or ""),
        "generated_at": payload.get("generated_at"),
        "cutoff_utc": payload.get("cutoff_utc"),
    }

def _utc(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def overlay_confirmed_telegram_aces_ou(feed: dict, state: dict) -> dict:
    """Attach only EXACT, PRE-START, confirmed Telegram O/U reissues to web Results.

    The private prediction ledger remains untouched. We do not derive missing
    historical thresholds from the model or from a player's opponent count.
    """
    if not isinstance(feed, dict) or not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("Invalid confirmed Telegram snapshot")
    rows = feed.get("ace_picks")
    if not isinstance(rows, list):
        return feed
    candidates: dict[tuple[str, str], tuple[dict, datetime]] = {}
    ambiguous: set[tuple[str, str]] = set()
    for batch in (state.get("reposts") or {}).values():
        if (not isinstance(batch, dict) or batch.get("status") != "sent"
                or batch.get("supersedes_daily") is not True
                or not batch.get("message_ids")):
            continue
        sent_at = _utc(batch.get("sent_at"))
        if sent_at is None or not isinstance(batch.get("rows"), list):
            continue
        for ref in batch["rows"]:
            if not isinstance(ref, dict) or ref.get("channel") != "aces" or ref.get("market") != "aces":
                continue
            event, selection = str(ref.get("event_id") or ""), str(ref.get("selection_id") or "")
            key = (event, selection)
            line, price = _number(ref.get("market_line")), _number(ref.get("odds"))
            side = str(ref.get("projection_direction") or "").lower()
            pubkey = str(ref.get("publication_key") or "")
            scheduled = _utc(ref.get("scheduled_at"))
            projection = _number(ref.get("projection"))
            if (not all(key) or side not in {"over", "under"} or line is None or line <= 0
                    or price is None or price <= 1 or scheduled is None
                    or sent_at >= scheduled or projection is None
                    or ref.get("price_basis") != "local_aces_statistical_v1"
                    or pubkey != f"local-aces-ou-v1:{event}:{selection}:{side}:{line:.1f}"):
                continue
            if key in candidates and candidates[key][0] != ref:
                ambiguous.add(key)
                continue
            candidates[key] = (ref, sent_at)
    amended = 0
    updated_rows = []
    for row in rows:
        if not isinstance(row, dict):
            updated_rows.append(row)
            continue
        event, selection = str(row.get("event_id") or ""), str((row.get("betting") or {}).get("selection_id") or row.get("selection_id") or row.get("winner_id") or "")
        key = (event, selection)
        match = candidates.get(key)
        if not match or key in ambiguous:
            updated_rows.append(row)
            continue
        ref, sent_at = match
        scheduled = _utc(row.get("scheduled_at"))
        projection = _number(row.get("projection"))
        if (not scheduled or sent_at >= scheduled or
                abs((projection if projection is not None else float("inf")) - ref["projection"]) > 0.011
                or selection not in {str((row.get("player1") or {}).get("id") or ""),
                                     str((row.get("player2") or {}).get("id") or "")}):
            updated_rows.append(row)
            continue
        existing = [p for p in (row.get("market_publications") or []) if isinstance(p, dict)]
        if any(p.get("market") == "aces" and p.get("price_contract") == "player_total_ou"
               and (p.get("publication_key") != ref["publication_key"]
                    or _number(p.get("market_line")) != _number(ref["market_line"])
                    or str(p.get("ou_side") or "") != ref["projection_direction"]) for p in existing):
            updated_rows.append(row)  # conflicting canonical contract: no override
            continue
        if any(p.get("publication_key") == ref["publication_key"] for p in existing):
            updated_rows.append(row)
            continue
        pub = {
            "section": "ace", "market": "aces", "selection_id": selection,
            "publication_key": ref["publication_key"],
            "publication_status": "published",
            "price_contract": "player_total_ou",
            "ou_side": ref["projection_direction"],
            "market_line": ref["market_line"],
            "selection": f"{ref['name']} {ref['projection_direction'].title()} {ref['market_line']:.1f} Aces",
            "projection_scope": "player", "projection_metric": "aces",
            "projection": row.get("projection"),
            "issued_at": sent_at.isoformat(),
            "odds": ref["odds"], "price_status": "priced_projection",
            "price_basis": ref["price_basis"],
            "source": "confirmed_telegram_ou_reissue",
        }
        updated_rows.append({**row, "market_publications": [*existing, pub]})
        amended += 1
    print("Confirmed Telegram O/U Results bridge:", json.dumps({
        "candidate_events": len(candidates), "linked": amended, "ambiguous": len(ambiguous)
    }))
    return {**feed, "ace_picks": updated_rows}


def _read_confirmed_telegram_state(repository: str) -> dict | None:
    """Fetch one private read-only sent ledger; never package its full contents."""
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{repository}/contents/ops/telegram-bot-state.json?ref=telegram-bot-state"],
            text=True, capture_output=True, timeout=25, check=True,
        )
        metadata = json.loads(proc.stdout)
        raw = base64.b64decode(metadata["content"], validate=False)
        if len(raw) > 2_000_000:
            raise ValueError("Telegram state exceeds bounded read")
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        print("::warning::Confirmed Telegram O/U reissue ledger unavailable:", type(exc).__name__)
        return None


def main() -> None:
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    comparator_target = ROOT / "api/data/comparator.json.gz"
    ace_ou_sidecar = ROOT / "api/data/confirmed_aces_ou.json"
    ace_ou_sidecar.unlink(missing_ok=True)
    comparator_target.unlink(missing_ok=True)
    (ROOT / "api/data/comparator-players.json").unlink(missing_ok=True)
    (ROOT / "api/data/comparator-serving.sqlite3").unlink(missing_ok=True)
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
            telegram_state = _read_confirmed_telegram_state(repository)
            if telegram_state is not None:
                bridged = overlay_confirmed_telegram_aces_ou(payload, telegram_state)
                links = []
                for ace_row in bridged.get("ace_picks") or []:
                    if not isinstance(ace_row, dict):
                        continue
                    for pub in ace_row.get("market_publications") or []:
                        if isinstance(pub, dict) and pub.get("source") == "confirmed_telegram_ou_reissue":
                            links.append({
                                "event_id": ace_row.get("event_id"),
                                "selection_id": str((ace_row.get("betting") or {}).get("selection_id") or ace_row.get("selection_id") or ace_row.get("winner_id") or ""),
                                "scheduled_at": ace_row.get("scheduled_at"),
                                "projection": ace_row.get("projection"),
                                "publication": pub,
                            })
                if links:
                    ace_ou_sidecar.write_text(
                        json.dumps({"schema": 1, "issued_aces_ou": links},
                                   ensure_ascii=False, allow_nan=False),
                        encoding="utf-8",
                    )
                    print("Confirmed Aces O/U read-only sidecar:", len(links))


    # If no private prediction candidate exists, overwrite any checked-in stale
    # snapshot with an honest empty feed instead of silently deploying it.
    target.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    # Validate the actual packaged snapshot after optional presentation enrichment.
    # Prevent a deploy that would later exceed the API reader cap.
    read_feed(target)
    print("Packaged serving feed bytes:", target.stat().st_size)
    print(
        "Serving snapshot ready:",
        payload.get("ready", False),
        "player assets:",
        payload.get("player_assets", {}).get("photos_deployed", 0),
    )


if __name__ == "__main__":
    main()
