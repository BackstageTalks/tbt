"""GitHub Actions egress guard for historical TBT data.

Python imports ``sitecustomize`` automatically whenever ``api/`` is on
``PYTHONPATH``. In GitHub Actions this module redirects bulk completed-history
reads to a verified GitHub Release snapshot. If the snapshot cannot be fetched
or verified, the job fails closed instead of falling back to a potentially
multi-GB Supabase history scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return bool(os.getenv("GITHUB_ACTIONS")) and not _truthy("TBT_ALLOW_SUPABASE_FULL_HISTORY")


if _enabled():
    try:
        from tbt.data.history_snapshot import load_snapshot
        from tbt.repositories.supabase import SupabaseRepository

        _original_get_completed = SupabaseRepository.get_completed_matches
        _original_get_year = getattr(SupabaseRepository, "get_matches_for_year", None)
        _original_select_all = SupabaseRepository.select_all

        def _token() -> str:
            return str(
                os.getenv("TBT_DATA_GH_TOKEN")
                or os.getenv("GH_TOKEN")
                or os.getenv("GITHUB_TOKEN")
                or ""
            ).strip()

        def _repository() -> str:
            return str(os.getenv("TBT_DATA_REPOSITORY") or "").strip()

        def _snapshot_path() -> Path:
            configured = str(os.getenv("TBT_HISTORY_SNAPSHOT") or "").strip()
            return Path(configured or ".cache/tbt/training_snapshot.parquet")

        def _meta_path(target: Path) -> Path:
            configured = str(os.getenv("TBT_HISTORY_META") or "").strip()
            return Path(configured) if configured else target.with_name("training_snapshot.meta.json")

        def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
            token = _token()
            if not token:
                raise RuntimeError(
                    "TBT egress guard: TBT_DATA_GH_TOKEN/GH_TOKEN is missing. "
                    "A private history repository must never fall back to Supabase."
                )
            return {
                "Accept": accept,
                "Authorization": f"Bearer {token}",
                "User-Agent": "tbt-egress-guard",
                "X-GitHub-Api-Version": "2022-11-28",
            }

        def _sha256(path: Path) -> str:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            return digest.hexdigest()

        def _verify_local_snapshot(target: Path, meta: Path) -> None:
            if not target.is_file() or target.stat().st_size <= 0:
                raise RuntimeError("TBT egress guard: history snapshot is missing or empty")
            if not meta.is_file() or meta.stat().st_size <= 0:
                raise RuntimeError("TBT egress guard: history snapshot metadata is missing")
            payload = json.loads(meta.read_text(encoding="utf-8"))
            expected = str(payload.get("sha256") or "").strip().lower()
            if not expected:
                raise RuntimeError("TBT egress guard: snapshot metadata has no sha256")
            actual = _sha256(target)
            if actual != expected:
                raise RuntimeError(
                    f"TBT egress guard: snapshot checksum mismatch: expected={expected} actual={actual}"
                )
            schema = int(payload.get("snapshot_schema_version") or 0)
            if schema != 1:
                raise RuntimeError(f"TBT egress guard: unsupported snapshot schema version {schema}")

        def _download_asset(asset_api_url: str, target: Path) -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(target.suffix + ".part")
            if temp.exists():
                temp.unlink()
            with urlopen(Request(asset_api_url, headers=_headers("application/octet-stream")), timeout=300) as response:
                with temp.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            if not temp.is_file() or temp.stat().st_size <= 0:
                raise RuntimeError(f"TBT egress guard: downloaded asset is empty: {target.name}")
            temp.replace(target)

        def _download_snapshot(target: Path) -> Path:
            meta = _meta_path(target)
            if target.is_file() and meta.is_file():
                _verify_local_snapshot(target, meta)
                return target

            repo = _repository()
            if not repo:
                raise RuntimeError(
                    "TBT egress guard: TBT_DATA_REPOSITORY is missing. "
                    "Set it to the dedicated private data repository."
                )

            tag = str(os.getenv("TBT_HISTORY_RELEASE_TAG") or "tbt-data-v1").strip()
            snapshot_asset = str(os.getenv("TBT_HISTORY_ASSET") or "training_snapshot.parquet").strip()
            meta_asset = str(os.getenv("TBT_HISTORY_META_ASSET") or "training_snapshot.meta.json").strip()
            api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"

            try:
                with urlopen(Request(api_url, headers=_headers()), timeout=30) as response:
                    release = json.loads(response.read().decode("utf-8"))
                assets = {str(item.get("name") or ""): item for item in release.get("assets", [])}
                snapshot_info = assets.get(snapshot_asset)
                meta_info = assets.get(meta_asset)
                if not snapshot_info or not meta_info:
                    raise RuntimeError(
                        f"TBT egress guard: required assets are missing from {repo} release {tag}"
                    )
                _download_asset(str(snapshot_info.get("url")), target)
                _download_asset(str(meta_info.get("url")), meta)
                _verify_local_snapshot(target, meta)
            except (HTTPError, URLError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "TBT egress guard: unable to download/verify GitHub history snapshot. "
                    "Do NOT fall back to a full Supabase scan. Run the V20.1 history sync workflow."
                ) from exc

            print(
                f"TBT egress guard: verified GitHub snapshot {target} ({target.stat().st_size} bytes)",
                file=sys.stderr,
            )
            return target

        def _completed_from_snapshot(self, before=None):
            return load_snapshot(_download_snapshot(_snapshot_path()), before=before)

        def _year_from_snapshot(self, year: int):
            rows = load_snapshot(_download_snapshot(_snapshot_path()))
            return [row for row in rows if row.scheduled_at.astimezone(timezone.utc).year == int(year)]

        def _guarded_select_all(self, table, filters=None, select="*", order=None, page_size=1000, max_rows=None):
            if str(table) == "matches" and max_rows is None:
                active = filters or {}
                narrow = any(key in active for key in ("match_id", "scheduled_at", "updated_at"))
                if not narrow:
                    raise RuntimeError(
                        "TBT egress guard blocked an unrestricted public.matches scan in GitHub Actions. "
                        "Use the verified history snapshot. Only the dedicated sync workflow may set "
                        "TBT_ALLOW_SUPABASE_FULL_HISTORY=1."
                    )
            return _original_select_all(
                self,
                table,
                filters=filters,
                select=select,
                order=order,
                page_size=page_size,
                max_rows=max_rows,
            )

        SupabaseRepository.get_completed_matches = _completed_from_snapshot
        if _original_get_year is not None:
            SupabaseRepository.get_matches_for_year = _year_from_snapshot
        SupabaseRepository.select_all = _guarded_select_all
    except Exception as exc:
        print(f"TBT egress guard initialization failed: {exc}", file=sys.stderr)
        raise
