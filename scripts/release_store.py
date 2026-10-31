import hashlib
import os
import shutil
import uuid
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_TRANSIENT_GH_ERROR = re.compile(
    r"(?:HTTP\s+(?:429|500|502|503|504)\b|connection reset|timed? out|timeout|temporary failure|TLS handshake|unexpected EOF|EOF)",
    re.IGNORECASE,
)


def _run_gh(args, *, max_attempts=5):
    """Run gh with bounded retries for transient GitHub/API failures.

    Release asset replacement is idempotent in our callers (uploads use
    --clobber), so retrying a transient 5xx/429 avoids wasting a completed
    provider refresh because GitHub briefly failed while persisting the bundle.
    """
    command = ["gh", *map(str, args)]
    result = None
    for attempt in range(max_attempts):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return result
        stderr = result.stderr.strip()
        transient = bool(_TRANSIENT_GH_ERROR.search(stderr))
        if not transient or attempt + 1 >= max_attempts:
            return result
        delay = min(2 ** (attempt + 1), 16)
        print(
            f"GitHub CLI transient failure; retrying in {delay}s "
            f"({attempt + 2}/{max_attempts}): {stderr[:220]}",
            file=sys.stderr,
        )
        time.sleep(delay)
    return result


def gh(*args):
    result = _run_gh(args)
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
        lookup = _run_gh(
            [
                "api",
                f"repos/{repository}/releases/tags/{tag}",
            ]
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

    def _download_current_asset_after_stale_404(self, name: str) -> None:
        """Recover when tag-based GitHub release metadata points to a deleted asset.

        A --clobber upload deletes and recreates asset IDs. GitHub can cache the
        tag view used by 'gh release download' after the exact release-ID asset
        listing has already been refreshed. Never turn a 404 into an empty feed:
        resolve the current asset by ID and verify the downloaded byte count.
        The committed bundle SHA-256 check still runs after all downloads.
        """
        release_id = int(gh(
            "api", f"repos/{self.repository}/releases/tags/{self.tag}",
            "--jq", ".id",
        ).strip())
        pages = json.loads(gh(
            "api", "--paginate", "--slurp",
            f"repos/{self.repository}/releases/{release_id}/assets?per_page=100",
        ))
        if not isinstance(pages, list):
            raise ValueError("Invalid release asset inventory")
        assets = [
            asset
            for page in pages
            for asset in (page if isinstance(page, list) else [page])
            if isinstance(asset, dict)
        ]
        current = next(
            (asset for asset in assets if asset.get("name") == name
             and asset.get("state") == "uploaded"), None,
        )
        if current is None:
            raise FileNotFoundError(
                f"Release asset {name} disappeared during deployment; "
                "retry when the prediction release upload is complete"
            )
        asset_id = int(current["id"])
        expected_bytes = int(current["size"])
        if expected_bytes <= 0:
            raise ValueError(f"Release asset {name} is empty")
        self.directory.mkdir(parents=True, exist_ok=True)
        # A partial response must never overwrite an existing verified file.
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".blinq-asset-", suffix=".part",
            dir=self.directory, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            result = subprocess.run(
                [
                    "gh", "api", "-H", "Accept: application/octet-stream",
                    f"repos/{self.repository}/releases/assets/{asset_id}",
                ],
                stdout=handle,
                stderr=subprocess.PIPE,
            )
        try:
            if result.returncode:
                detail = (result.stderr or b"").decode("utf-8", "replace").strip()
                raise RuntimeError(
                    f"Current release asset {name} (id {asset_id}) could not be "
                    f"downloaded: {detail[:350]}"
                )
            received = temporary.stat().st_size
            if received != expected_bytes:
                raise RuntimeError(
                    f"Current release asset {name} (id {asset_id}) has "
                    f"{received} bytes; expected {expected_bytes}; refusing "
                    "a partial or non-binary GitHub API response"
                )
            temporary.replace(self.directory / name)
        finally:
            temporary.unlink(missing_ok=True)

    def _download_asset(self, name: str) -> None:
        try:
            gh(
                "release", "download", self.tag,
                "--repo", self.repository, "--pattern", name,
                "--dir", self.directory, "--clobber",
            )
        except RuntimeError as exc:
            # Only recover a stale GitHub asset ID. Auth errors, rate limits and
            # other failures retain their existing fail-closed behavior.
            if not re.search(r"HTTP\s+404\b", str(exc)):
                raise
            print(
                f"Stale tag release asset for {name}; refreshing by release ID",
                file=sys.stderr,
            )
            self._download_current_asset_after_stale_404(name)

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
            self._download_asset(self.BUNDLE_MANIFEST)
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
            self._download_asset(name)

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
        # Use the same stale-ID 404 recovery as initial bundle downloads.
        # A direct gh release download can reference a deleted asset ID after
        # concurrent release --clobber; resolve the current asset by ID instead.
        self._download_asset(self.BUNDLE_MANIFEST)
        value = json.loads(
            (self.directory / self.BUNDLE_MANIFEST).read_text(encoding="utf-8")
        )
        files = value.get("files")
        if not isinstance(files, dict):
            raise ValueError("Invalid committed bundle manifest")
        return dict(files)

    def _release_asset_inventory(self):
        """Current release asset IDs and GitHub-computed digests, across all pages."""
        release_id = int(gh(
            "api", f"repos/{self.repository}/releases/tags/{self.tag}", "--jq", ".id",
        ).strip())
        pages = json.loads(gh(
            "api", "--paginate", "--slurp",
            f"repos/{self.repository}/releases/{release_id}/assets?per_page=100",
        ))
        if not isinstance(pages, list):
            raise ValueError("Invalid release assets response")
        assets = {}
        for page in pages:
            for asset in (page if isinstance(page, list) else [page]):
                if isinstance(asset, dict) and asset.get("name") and asset.get("state") == "uploaded":
                    assets[asset["name"]] = asset
        return assets

    def _asset_api(self, method, asset_id, *, name=None):
        args = ["api", "--method", method,
                f"repos/{self.repository}/releases/assets/{int(asset_id)}"]
        if name is not None:
            args.extend(["-f", f"name={name}"])
        return gh(*args)

    def _verified_asset(self, assets, name, path):
        asset = assets.get(name)
        return bool(
            asset and asset.get("digest") == "sha256:" + self._sha256(path)
            and int(asset.get("size") or -1) == path.stat().st_size
        )

    def _guarded_publish(self, path, token):
        """Stage bytes before renaming the previous canonical asset.

        --clobber directly on the canonical name can destroy its sole copy on
        an HTTP 500. The old asset is instead renamed to a rollback alias,
        retained until the bundle checksum commit is independently verified.
        """
        path = Path(path)
        name = path.name
        assets = self._release_asset_inventory()
        old = assets.get(name)
        if self._verified_asset(assets, name, path):
            return None
        if old is None:
            # New names have no existing copy to lose, but must still be
            # rolled back if a later manifest/checksum commit fails.
            self.upload([path])
            uploaded = self._release_asset_inventory().get(name)
            if not self._verified_asset({name: uploaded}, name, path):
                raise RuntimeError(f"Release upload verification failed for {name}")
            return (name, None, int(uploaded["id"]), None)

        candidate = f"blinq-candidate-{token}-{name}"
        backup = f"blinq-rollback-{token}-{name}"
        with tempfile.TemporaryDirectory() as staged_dir:
            staged_path = Path(staged_dir) / candidate
            shutil.copyfile(path, staged_path)
            try:
                self.upload([staged_path])  # A unique filename; never clobbers canonical.
            except RuntimeError:
                # A 5xx can happen after a successful upload. Accept only the
                # exact server-side SHA-256 and byte count, not just an HTTP code.
                if not self._verified_asset(self._release_asset_inventory(), candidate, path):
                    raise
        staged = self._release_asset_inventory().get(candidate)
        if not staged or not self._verified_asset({candidate: staged}, candidate, path):
            raise RuntimeError(f"Staged release asset verification failed: {name}")

        old_id, staged_id = int(old["id"]), int(staged["id"])
        try:
            self._asset_api("PATCH", old_id, name=backup)
            self._asset_api("PATCH", staged_id, name=name)
            if not self._verified_asset(self._release_asset_inventory(), name, path):
                raise RuntimeError(f"Published release digest mismatch: {name}")
        except Exception:
            # Restore the previous name if the failure happened during swap.
            # Preserve the old alias if GitHub itself is unavailable.
            try:
                current = self._release_asset_inventory()
                if backup in current:
                    if name in current:
                        self._asset_api("DELETE", int(current[name]["id"]))
                    self._asset_api("PATCH", old_id, name=name)
            except Exception as restore_error:
                print(f"ERROR: retained release rollback {backup}: {restore_error}", file=sys.stderr)
            raise
        return (name, old_id, staged_id, backup)

    def _rollback_guarded(self, swaps):
        """Reverse completed swaps after a later upload/checksum failure."""
        for name, old_id, new_id, backup in reversed(swaps):
            try:
                current = self._release_asset_inventory()
                if old_id is None:
                    if name in current and int(current[name]["id"]) == new_id:
                        self._asset_api("DELETE", new_id)
                    continue
                if backup not in current:
                    continue
                if name in current:
                    self._asset_api("DELETE", int(current[name]["id"]))
                self._asset_api("PATCH", old_id, name=name)
            except Exception as exc:
                print(f"ERROR: manual recovery may be needed for {backup}: {exc}", file=sys.stderr)

    def _cleanup_guarded(self, swaps):
        for _name, old_id, _new_id, backup in swaps:
            if old_id is None:
                continue
            try:
                self._asset_api("DELETE", old_id)
            except Exception as exc:
                # A leftover backup can be recovered/cleaned on the next run.
                print(f"WARNING: retained verified rollback {backup}: {exc}", file=sys.stderr)

    def recover_interrupted_swaps(self):
        """No provider requests. Call only while owning the global CDB lock.

        Keep a fully valid committed generation. Otherwise roll back all
        surviving aliases from an interrupted transaction, then read back.
        """
        if self.repository != "BackstageTalks/tbt-data" or self.tag != "tbt-data-v1":
            raise ValueError("Recovery requires the canonical CDB release")
        from cdb_global_writer_lock import verify
        verify(self.repository, Path(".cdb-global-writer-lock.json"))
        assets = self._release_asset_inventory()
        groups = {}
        for name, asset in assets.items():
            match = re.fullmatch(r"blinq-rollback-([0-9a-f]{32})-(.+)", name)
            if match:
                groups.setdefault(match.group(1), []).append((match.group(2), asset))
        if not groups:
            return {"pending_transactions": 0, "status": "clean"}
        if len(groups) > 1:
            raise RuntimeError("Multiple pending bundle swaps; manual review required")

        # An interrupted cleanup after a *successful* commit needs no rollback.
        try:
            with tempfile.TemporaryDirectory() as directory:
                original_directory = self.directory
                try:
                    self.directory = Path(directory)
                    self.download()
                finally:
                    self.directory = original_directory
            committed = True
        except (RuntimeError, ValueError, FileNotFoundError, OSError):
            committed = False
        token, entries = next(iter(groups.items()))
        if committed:
            for _name, asset in entries:
                self._asset_api("DELETE", int(asset["id"]))
            return {"pending_transactions": 1, "status": "committed_generation_verified"}
        for name, old in reversed(entries):
            current = self._release_asset_inventory()
            if name in current:
                self._asset_api("DELETE", int(current[name]["id"]))
            self._asset_api("PATCH", int(old["id"]), name=name)
        with tempfile.TemporaryDirectory() as directory:
            original_directory = self.directory
            try:
                self.directory = Path(directory)
                self.download()
            finally:
                self.directory = original_directory
        return {"pending_transactions": 1, "status": "previous_generation_restored"}

    def upload_bundle(self, paths, *, before_upload=None, remove_names=()):
        """Upload related assets, then commit their checksums last.

        Readers that see a partial overwrite will fail checksum verification
        instead of silently consuming a mixed generation.  Removals are applied
        before the replacement manifest is committed so a reader can fail closed,
        but can never silently consume a stale deleted partition.
        """
        # Cross-repository Actions concurrency does not exist. A lock check at
        # the actual production release writer prevents future workflows from
        # silently bypassing the explicit acquire/release job steps.
        if (
            self.repository == "BackstageTalks/tbt-data"
            and self.tag in {"tbt-data-v1", "tbt-training-table-v1"}
            and os.environ.get("GITHUB_ACTIONS") == "true"
        ):
            from cdb_global_writer_lock import verify
            verify(self.repository, Path(".cdb-global-writer-lock.json"))
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

        guarded = (
            self.repository == "BackstageTalks/tbt-data"
            and self.tag == "tbt-data-v1"
        )
        remote_assets = self._asset_names() if removals else set()
        if not guarded:
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

        # Never clobber the authoritative history inventory in the same GitHub
        # upload as the larger parquet payloads. A transient GitHub 5xx can
        # fail a multi-asset --clobber halfway through, leaving the manifest
        # deleted even though an earlier version had been readable.
        history_inventory = [p for p in files if p.name == "history_manifest.json"]
        payload_files = [p for p in files if p.name != "history_manifest.json"]
        if not guarded:
            if payload_files:
                self.upload(payload_files)
            if history_inventory:
                self.upload(history_inventory)

        manifest_path = self.directory / self.BUNDLE_MANIFEST
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(manifest_path)
        if not guarded:
            self.upload([manifest_path])
            return

        token = uuid.uuid4().hex
        swaps = []
        try:
            # Retention/identity repairs must not delete the only partition
            # copy before the new committed inventory is available.
            for name in sorted(removals & remote_assets):
                asset = self._release_asset_inventory().get(name)
                if asset is None:
                    raise FileNotFoundError(f"Partition vanished during removal: {name}")
                old_id = int(asset["id"])
                backup = f"blinq-rollback-{token}-{name}"
                self._asset_api("PATCH", old_id, name=backup)
                swaps.append((name, old_id, None, backup))
            for path in [*payload_files, *history_inventory, manifest_path]:
                result = self._guarded_publish(path, token)
                if result is not None:
                    swaps.append(result)
        except Exception:
            self._rollback_guarded(swaps)
            raise
        self._cleanup_guarded(swaps)

