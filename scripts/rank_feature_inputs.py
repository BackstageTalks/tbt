from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
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
WTA_OFFICIAL_SUPPLEMENT_PATH = (
    "research/wta-official-2026/wta_official_singles_2026_post_sackmann.csv.gz"
)
WTA_OFFICIAL_SUPPLEMENT_AUDIT = "audit/wta-official-ranking-supplement-2026-10-07.json"


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


def _repo_json(repository: str, path: str) -> dict:
    raw = gh(
        "api",
        "-H",
        "Accept: application/vnd.github.raw+json",
        f"repos/{repository}/contents/{path}?ref=main",
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Invalid JSON document: {path}")
    return value


def _source_manifest(repository: str) -> dict:
    return _repo_json(repository, "research/source-acquisition/latest.json")


def _download_repo_binary(repository: str, path: str, destination: Path) -> None:
    """Download one private-repo binary file via Git blob base64 payload.

    GitHub CLI's raw contents transform can intermittently fail on private
    gzip assets with "transform: short source buffer". Resolving the content
    entry to its immutable blob SHA and decoding the blob's documented base64
    payload avoids any text/binary transform while remaining checksum-verifiable.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)

    meta = subprocess.run(
        [
            "gh", "api",
            f"repos/{repository}/contents/{path}?ref=main",
            "--jq", ".sha",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if meta.returncode:
        detail = (meta.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"GitHub repo metadata lookup failed for {path}: {detail[:500]}"
        )
    blob_sha = (meta.stdout or b"").decode("ascii", "strict").strip()
    if len(blob_sha) != 40:
        raise RuntimeError(f"GitHub repo metadata returned invalid blob SHA for {path}")

    blob = subprocess.run(
        [
            "gh", "api",
            f"repos/{repository}/git/blobs/{blob_sha}",
            "--jq", ".content",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if blob.returncode:
        detail = (blob.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"GitHub repo blob download failed for {path}: {detail[:500]}"
        )
    encoded = b"".join((blob.stdout or b"").split())
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError(f"GitHub repo blob base64 decode failed for {path}") from exc
    if not payload:
        raise RuntimeError(f"GitHub repo asset download was empty: {path}")
    temporary.write_bytes(payload)
    temporary.replace(destination)


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

    supplement_audit = _repo_json(repository, WTA_OFFICIAL_SUPPLEMENT_AUDIT)
    supplement_expected = str(
        ((supplement_audit.get("singles") or {}).get("gzip_sha256") or "")
    ).strip()
    if len(supplement_expected) != 64:
        raise ValueError("WTA official supplement audit lacks a valid singles SHA-256")
    wta_supplement = source / Path(WTA_OFFICIAL_SUPPLEMENT_PATH).name
    _download_repo_binary(
        repository,
        WTA_OFFICIAL_SUPPLEMENT_PATH,
        wta_supplement,
    )
    supplement_actual = _sha256(wta_supplement)
    if supplement_actual != supplement_expected:
        raise ValueError("WTA official supplement checksum mismatch")
    source_rows[wta_supplement.name] = {
        "sha256": supplement_actual,
        "bytes": int(wta_supplement.stat().st_size),
        "source": "Kaggle bwandowando/womens-tennis-association-rankings",
        "license": "Apache-2.0",
        "coverage": {
            "from": (supplement_audit.get("singles") or {}).get("date_min"),
            "to": (supplement_audit.get("singles") or {}).get("date_max"),
            "rows": (supplement_audit.get("singles") or {}).get("rows"),
        },
        "policy": "extension-only after pinned Sackmann max date",
    }

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
        supplement_csvs=(wta_supplement,),
    )

    report = {
        "schema": 1,
        "status": "verified",
        "provider_requests": 0,
        "research_release": RESEARCH_RELEASE,
        "sources": source_rows,
        "atp_ranking_files": len(atp_rankings),
        "wta_ranking_files": len(wta_rankings),
        "wta_official_supplement": {
            "path": WTA_OFFICIAL_SUPPLEMENT_PATH,
            "sha256": supplement_actual,
            "rows": (supplement_audit.get("singles") or {}).get("rows"),
            "date_min": (supplement_audit.get("singles") or {}).get("date_min"),
            "date_max": (supplement_audit.get("singles") or {}).get("date_max"),
            "source_max_date": supplement_audit.get("source", {}).get("source_max_date"),
            "policy": "extension-only; never overwrites pinned historical snapshots",
        },
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
