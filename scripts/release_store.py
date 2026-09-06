import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

def gh(*args):
    result = subprocess.run(["gh", *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"GitHub CLI operation failed: {result.stderr.strip()[:500]}")
    return result.stdout


class ReleaseStore:
    def __init__(self, repository, tag, directory):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Expected owner/repository")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
            raise ValueError("Invalid release tag")
        self.repository, self.tag, self.directory = repository, tag, Path(directory)
        info = json.loads(gh("repo", "view", repository, "--json", "visibility"))
        if info.get("visibility") != "PRIVATE":
            raise ValueError("Training data destination must be PRIVATE")
        # Look up the exact tag directly. A long release history must not make
        # an existing fixed tag look absent merely because it fell off page 1.
        lookup = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repository}/releases/tags/{tag}",
            ],
            capture_output=True,
            text=True,
        )
        if lookup.returncode:
            stderr = lookup.stderr.strip()
            if (
                "HTTP 404" in stderr
                or "Not Found" in stderr
                or "not found" in stderr.lower()
            ):
                gh(
                    "release",
                    "create",
                    tag,
                    "--repo",
                    repository,
                    "--title",
                    "TBT private tennis history",
                    "--notes",
                    "Compact training partitions and resumable download progress. No API credentials.",
                )
            else:
                raise RuntimeError(
                    "GitHub release lookup failed: "
                    + stderr[:500]
                )
        self.directory.mkdir(parents=True, exist_ok=True)

    BUNDLE_MANIFEST = "_tbt_bundle_manifest.json"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _asset_names(self) -> set[str]:
        payload = json.loads(
            gh(
                "release",
                "view",
                self.tag,
                "--repo",
                self.repository,
                "--json",
                "assets",
            )
        )
        return {
            str(asset.get("name"))
            for asset in payload.get("assets", [])
            if asset.get("name")
        }

    def _read_local_bundle_manifest(self) -> dict:
        path = self.directory / self.BUNDLE_MANIFEST
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def download(
        self,
        extra_names=(),
        *,
        required_names=(),
        require_bundle_manifest=False,
    ):
        assets = self._asset_names()
        required = {str(name) for name in required_names}
        missing = sorted(required - assets)
        if missing:
            raise FileNotFoundError(
                "Required release assets are missing: " + ", ".join(missing)
            )

        bundle_manifest = {}
        bundle_files = {}
        if self.BUNDLE_MANIFEST in assets:
            gh(
                "release",
                "download",
                self.tag,
                "--repo",
                self.repository,
                "--pattern",
                self.BUNDLE_MANIFEST,
                "--dir",
                self.directory,
                "--clobber",
            )
            try:
                bundle_manifest = json.loads(
                    (self.directory / self.BUNDLE_MANIFEST).read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid committed bundle manifest") from exc
            if not isinstance(bundle_manifest, dict):
                raise ValueError("Invalid committed bundle manifest")
            bundle_files = bundle_manifest.get("files")
            if not isinstance(bundle_files, dict):
                raise ValueError("Invalid committed bundle manifest")
        elif require_bundle_manifest or required:
            raise FileNotFoundError(
                f"Required release bundle manifest is missing: {self.BUNDLE_MANIFEST}"
            )

        history_pattern = re.compile(r"history-\d{4}\.parquet")
        remote_history_assets = {name for name in assets if history_pattern.fullmatch(name)}
        committed_history_assets = {
            name for name in bundle_files if history_pattern.fullmatch(str(name))
        }
        history_evidence = bool(
            remote_history_assets
            or committed_history_assets
            or "history_manifest.json" in bundle_files
        )
        if history_evidence and "history_manifest.json" not in assets:
            raise FileNotFoundError(
                "Required history manifest is missing: history_manifest.json"
            )
        missing_committed_history = sorted(committed_history_assets - assets)
        if missing_committed_history:
            raise FileNotFoundError(
                "Committed history bundle references missing release assets: "
                + ", ".join(missing_committed_history)
            )

        selected = {
            name
            for name in assets
            if (
                name in required
                or name in extra_names
                or name in {
                    "history_manifest.json",
                    "download_progress.json",
                    "request_budget.json",
                }
                or re.fullmatch(r"history-\d{4}\.parquet", name)
            )
        }

        for name in sorted(selected):
            gh(
                "release",
                "download",
                self.tag,
                "--repo",
                self.repository,
                "--pattern",
                name,
                "--dir",
                self.directory,
                "--clobber",
            )

        # history_manifest.json is the authoritative partition inventory.
        # A missing remote partition must fail closed instead of silently
        # shrinking the training corpus to the assets that happen to exist.
        if "history_manifest.json" in assets:
            history_manifest_path = self.directory / "history_manifest.json"
            try:
                history_manifest = json.loads(
                    history_manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid history manifest") from exc

            years = history_manifest.get("years")
            if not isinstance(years, dict):
                raise ValueError("Invalid history manifest: missing years map")

            expected_history_assets = set()
            for year, metadata in years.items():
                if not isinstance(metadata, dict):
                    raise ValueError(f"Invalid history manifest entry for year {year}")
                asset = str(metadata.get("asset") or f"history-{int(year):04d}.parquet")
                if not re.fullmatch(r"history-\d{4}\.parquet", asset):
                    raise ValueError(f"Invalid history partition asset in manifest: {asset}")
                expected_history_assets.add(asset)

            missing_history = sorted(expected_history_assets - assets)
            if missing_history:
                raise FileNotFoundError(
                    "History manifest references missing release assets: "
                    + ", ".join(missing_history)
                )

            missing_local_history = sorted(
                name
                for name in expected_history_assets
                if not (self.directory / name).is_file()
            )
            if missing_local_history:
                raise FileNotFoundError(
                    "History download is incomplete: "
                    + ", ".join(missing_local_history)
                )

        manifest = bundle_manifest if self.BUNDLE_MANIFEST in assets else {}
        manifest_files = bundle_files if isinstance(bundle_files, dict) else {}
        integrity_required = set(required)
        if history_evidence:
            integrity_required.add("history_manifest.json")
            integrity_required.update(remote_history_assets)
        uncovered = [name for name in integrity_required if not (
            isinstance(manifest_files, dict)
            and isinstance(manifest_files.get(name), dict)
            and re.fullmatch(r"[0-9a-f]{64}", str(manifest_files[name].get("sha256", "")))
        )]
        if uncovered:
            raise RuntimeError("Required assets lack checksum coverage: " + ", ".join(sorted(uncovered)))
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if isinstance(files, dict):
            for name, meta in files.items():
                if name not in selected:
                    continue
                path = self.directory / name
                if not path.is_file():
                    raise RuntimeError(
                        f"Release bundle is incomplete: missing local asset {name}"
                    )
                expected = (
                    meta.get("sha256")
                    if isinstance(meta, dict)
                    else None
                )
                if expected and self._sha256(path) != expected:
                    raise RuntimeError(
                        f"Release bundle checksum mismatch for {name}"
                    )

        return sorted(selected)

    def upload(self, paths):
        paths = [str(p) for p in paths if Path(p).is_file()]
        if paths:
            gh(
                "release",
                "upload",
                self.tag,
                *paths,
                "--repo",
                self.repository,
                "--clobber",
            )

    def _remote_bundle_files(self):
        assets = self._asset_names()
        if self.BUNDLE_MANIFEST not in assets:
            return {}
        # Read this release's committed manifest, never another tag's local cache.
        with tempfile.TemporaryDirectory(dir=self.directory) as temporary:
            gh("release", "download", self.tag, "--repo", self.repository,
               "--pattern", self.BUNDLE_MANIFEST, "--dir", temporary, "--clobber")
            value = json.loads((Path(temporary) / self.BUNDLE_MANIFEST).read_text(encoding="utf-8"))
        files = value.get("files")
        if not isinstance(files, dict):
            raise ValueError("Invalid committed bundle manifest")
        return dict(files)

    def upload_bundle(self, paths, *, before_upload=None, remove_names=()):
        """Upload related assets, then commit their checksums last.

        Readers that see a partial overwrite will fail checksum verification
        instead of silently consuming a mixed generation.  Removals are applied
        before the replacement manifest is committed so a reader can fail closed,
        but can never silently consume a stale deleted partition.
        """
        files = [Path(p) for p in paths]
        removals = {str(name) for name in remove_names}
        previous = self._remote_bundle_files()
        if before_upload is not None:
            before_upload()
        if any(not path.is_file() for path in files):
            raise FileNotFoundError("Bundle asset is missing")
        if len({path.name for path in files}) != len(files):
            raise ValueError("Duplicate bundle asset names")
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in removals):
            raise ValueError("Invalid release asset name")
        if removals & {path.name for path in files}:
            raise ValueError("Cannot upload and remove the same bundle asset")
        if not files and not removals:
            return

        remote_assets = self._asset_names() if removals else set()
        for name in sorted(removals & remote_assets):
            gh(
                "release",
                "delete-asset",
                self.tag,
                name,
                "--repo",
                self.repository,
                "--yes",
            )

        retained = {
            name: meta
            for name, meta in previous.items()
            if name not in removals
        }
        manifest = {
            "schema": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                **retained,
                **{path.name: {
                    "sha256": self._sha256(path),
                    "bytes": int(path.stat().st_size),
                } for path in files},
            },
        }

        self.upload(files)

        manifest_path = self.directory / self.BUNDLE_MANIFEST
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(manifest_path)
        self.upload([manifest_path])

