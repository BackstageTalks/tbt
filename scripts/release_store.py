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
        elif require_bundle_manifest or required:
            raise FileNotFoundError(
                f"Required release bundle manifest is missing: {self.BUNDLE_MANIFEST}"
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

        manifest = self._read_local_bundle_manifest() if self.BUNDLE_MANIFEST in assets else {}
        manifest_files = manifest.get("files", {})
        uncovered = [name for name in required if not (
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
        return {name: meta for name, meta in files.items() if name in assets}

    def upload_bundle(self, paths, *, before_upload=None):
        """Upload related assets, then commit their checksums last.

        Readers that see a partial overwrite will fail checksum verification
        instead of silently consuming a mixed generation.
        """
        files = [Path(p) for p in paths]
        previous = self._remote_bundle_files()
        if before_upload is not None:
            before_upload()
        if any(not path.is_file() for path in files):
            raise FileNotFoundError("Bundle asset is missing")
        if len({path.name for path in files}) != len(files):
            raise ValueError("Duplicate bundle asset names")
        if not files:
            return

        manifest = {
            "schema": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                **previous,
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

