from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from typing import Iterable

from release_store import ReleaseStore, gh
from tbt.data.atp_rank_history import ATPRankHistory
from tbt.data.player_identity import (
    build_canonical_players,
    build_crosswalk,
    crosswalk_mapping,
    load_profiles,
    load_sackmann_players,
)
from tbt.data.wta_rank_history import WTARankHistory


RESEARCH_RELEASE = "tbt-research-sources-v1"
PLAYER_ASSET_RELEASE = "tbt-player-assets-v1"
ATP_ASSET = "sackmann-atp-rankings.tar.gz"
WTA_ASSET = "sackmann-wta-rankings.tar.gz"


@dataclass(frozen=True)
class RankFeatureInputs:
    atp: ATPRankHistory
    wta: WTARankHistory
    report: dict


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(repository: str) -> dict:
    raw = gh(
        "api",
        "-H",
        "Accept: application/vnd.github.raw+json",
        f"repos/{repository}/contents/research/source-acquisition/latest.json?ref=main",
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid research source acquisition manifest")
    return value


def _manifest_asset(manifest: dict, asset: str) -> dict:
    rows = [
        row for row in manifest.get("downloaded", [])
        if isinstance(row, dict) and str(row.get("asset") or "") == asset
    ]
    if len(rows) != 1:
        raise ValueError(f"Research manifest must contain exactly one {asset} entry")
    row = rows[0]
    expected = str(row.get("sha256") or "")
    if len(expected) != 64:
        raise ValueError(f"Research manifest lacks SHA-256 for {asset}")
    return row


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            if member.issym() or member.islnk():
                raise ValueError(f"Refusing linked tar member: {member.name}")
            target = (destination / member.name).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"Refusing path traversal in tar: {member.name}")
        handle.extractall(destination)


def _exact_file(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one {name}; found {len(matches)}")
    return matches[0]


def _ranking_files(root: Path, prefix: str) -> list[Path]:
    rows = sorted(path for path in root.rglob(f"{prefix}_rankings_*.csv") if path.is_file())
    if not rows:
        raise FileNotFoundError(f"No {prefix} weekly ranking CSVs found")
    return rows


def load_rank_feature_inputs(
    repository: str,
    cache_root: str | Path,
    matches: Iterable,
) -> RankFeatureInputs:
    """Load the exact same verified rank-history sources for train and serving.

    The inputs are private release assets already acquired and checksum-audited.
    No provider/RapidAPI requests are made here. WTA canonical identity mapping
    is rebuilt fail-closed from the same canonical history and cached player
    profiles used by the research finalizer.
    """
    root = Path(cache_root)
    source = root / "source"
    profiles = root / "profiles"
    atp_dir = root / "atp"
    wta_dir = root / "wta"
    for path in (source, profiles):
        path.mkdir(parents=True, exist_ok=True)
    for path in (atp_dir, wta_dir):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    manifest = _source_manifest(repository)
    research = ReleaseStore(repository, RESEARCH_RELEASE, source)
    available = research._asset_names()
    required_assets = {ATP_ASSET, WTA_ASSET}
    missing = sorted(required_assets - available)
    if missing:
        raise FileNotFoundError(
            "Verified rank-history research assets missing: " + ", ".join(missing)
        )
    research.download(extra_names=tuple(sorted(required_assets)))

    source_rows = {}
    for asset in sorted(required_assets):
        path = source / asset
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Downloaded rank-history asset missing: {asset}")
        row = _manifest_asset(manifest, asset)
        actual = _sha256(path)
        if actual != row["sha256"]:
            raise ValueError(f"Rank-history checksum mismatch for {asset}")
        source_rows[asset] = {
            "sha256": actual,
            "bytes": int(path.stat().st_size),
            "source": row.get("source"),
            "source_commit": row.get("source_commit"),
            "license": row.get("license"),
        }

    _safe_extract(source / ATP_ASSET, atp_dir)
    _safe_extract(source / WTA_ASSET, wta_dir)

    atp_players = _exact_file(atp_dir, "atp_players.csv")
    wta_players = _exact_file(wta_dir, "wta_players.csv")
    atp_rankings = _ranking_files(atp_dir, "atp")
    wta_rankings = _ranking_files(wta_dir, "wta")

    profile_store = ReleaseStore(repository, PLAYER_ASSET_RELEASE, profiles)
    profile_store.download(
        extra_names=("player_profiles.json",),
        required_names=("player_profiles.json",),
        require_bundle_manifest=True,
    )
    profile_path = profiles / "player_profiles.json"
    by_tour_id, by_id = load_profiles(profile_path)

    materialized = list(matches)
    canonical_wta = build_canonical_players(
        materialized,
        tour="wta",
        profile_by_tour_id=by_tour_id,
        profile_by_id=by_id,
    )
    sackmann_wta = load_sackmann_players(wta_players)
    crosswalk_rows, crosswalk_report = build_crosswalk(canonical_wta, sackmann_wta)
    mapping = crosswalk_mapping(crosswalk_rows)

    # Large production history should never silently lose the identity bridge.
    if len(canonical_wta) >= 1000 and int(crosswalk_report.get("resolved") or 0) < 1000:
        raise ValueError(
            "WTA rank-history crosswalk unexpectedly resolved fewer than 1000 players"
        )

    atp = ATPRankHistory.from_sackmann(atp_players, atp_rankings)
    wta = WTARankHistory.from_sackmann(
        wta_players,
        wta_rankings,
        canonical_to_sackmann=mapping,
    )

    report = {
        "schema": 1,
        "status": "verified",
        "provider_requests": 0,
        "research_release": RESEARCH_RELEASE,
        "sources": source_rows,
        "atp_ranking_files": len(atp_rankings),
        "wta_ranking_files": len(wta_rankings),
        "wta_crosswalk": {
            "canonical_players": crosswalk_report.get("canonical_players"),
            "resolved": crosswalk_report.get("resolved"),
            "unresolved": crosswalk_report.get("unresolved"),
            "coverage": crosswalk_report.get("coverage"),
            "evidence_counts": crosswalk_report.get("evidence_counts"),
        },
        "policy": (
            "same verified private rank-history inputs for train and serving; "
            "weekly snapshots strictly before match date; fail-closed WTA identity"
        ),
    }
    return RankFeatureInputs(atp=atp, wta=wta, report=report)
