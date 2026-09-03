from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import quote

import httpx


BUCKET = "tbt-models"
LEGACY_PRODUCTION_OBJECT = "production/model.joblib"


def _settings() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required"
        )

    return url, key


def _headers(
    key: str,
    content_type: str | None = None,
) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }

    if content_type:
        headers["Content-Type"] = content_type

    return headers


def _object_for_version(model_version: str) -> str:
    version = str(model_version or "").strip()

    if not version:
        raise ValueError("model_version is required")

    if "/" in version or "\\" in version or ".." in version:
        raise ValueError("Invalid model_version")

    return f"versions/{version}/model.joblib"


def ensure_bucket(
    client: httpx.Client,
    url: str,
    key: str,
) -> None:
    check = client.get(
        f"{url}/storage/v1/bucket/{BUCKET}",
        headers=_headers(key),
    )

    if check.status_code == 200:
        return

    if check.status_code != 404:
        raise RuntimeError(
            "Unable to check Supabase Storage bucket "
            f"{BUCKET}: HTTP {check.status_code}: "
            f"{check.text[:500]}"
        )

    response = client.post(
        f"{url}/storage/v1/bucket",
        headers=_headers(
            key,
            "application/json",
        ),
        json={
            "id": BUCKET,
            "name": BUCKET,
            "public": False,
        },
    )

    if response.status_code in {
        200,
        201,
        409,
    }:
        return

    if response.status_code == 400:
        body = response.text.lower()

        if (
            "already exists" in body
            or "duplicate" in body
        ):
            return

    raise RuntimeError(
        "Unable to create Supabase Storage bucket "
        f"{BUCKET}: HTTP {response.status_code}: "
        f"{response.text[:500]}"
    )


def _champion_version() -> str:
    url, key = _settings()

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{url}/rest/v1/model_versions",
            headers=_headers(key),
            params={
                "select": "model_version",
                "lifecycle_status": "eq.champion",
                "order": "promoted_at.desc",
                "limit": "1",
            },
        )

        if response.is_error:
            raise RuntimeError(
                "Unable to resolve champion model: "
                f"HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        rows = response.json()

    if not isinstance(rows, list) or not rows:
        raise SystemExit(
            "No champion model is registered in Supabase."
        )

    version = str(
        rows[0].get("model_version")
        or ""
    ).strip()

    if not version:
        raise SystemExit(
            "Champion row has no model_version."
        )

    return version


def upload(
    path: Path,
    model_version: str,
) -> None:
    if (
        not path.is_file()
        or path.stat().st_size == 0
    ):
        raise SystemExit(
            f"Model artifact missing or empty: {path}"
        )

    url, key = _settings()
    object_name = _object_for_version(model_version)

    object_path = quote(
        object_name,
        safe="/",
    )

    with httpx.Client(timeout=120.0) as client:
        ensure_bucket(
            client,
            url,
            key,
        )

        response = client.post(
            (
                f"{url}/storage/v1/object/"
                f"{BUCKET}/{object_path}"
            ),
            headers={
                **_headers(
                    key,
                    "application/octet-stream",
                ),
                "x-upsert": "true",
            },
            content=path.read_bytes(),
        )

        if response.is_error:
            raise RuntimeError(
                "Unable to upload model artifact to "
                f"{BUCKET}/{object_name}: "
                f"HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

    print(
        f"Uploaded {path.stat().st_size} bytes "
        f"to {BUCKET}/{object_name}"
    )


def _download_object(
    path: Path,
    object_name: str,
    *,
    allow_not_found: bool = False,
) -> bool:
    url, key = _settings()

    object_path = quote(
        object_name,
        safe="/",
    )

    with httpx.Client(timeout=120.0) as client:
        response = client.get(
            (
                f"{url}/storage/v1/object/"
                f"{BUCKET}/{object_path}"
            ),
            headers=_headers(key),
        )

    if response.status_code == 404:
        if allow_not_found:
            return False

        raise SystemExit(
            f"Model artifact not found: "
            f"{BUCKET}/{object_name}"
        )

    if response.is_error:
        raise RuntimeError(
            "Unable to download model artifact "
            f"{BUCKET}/{object_name}: "
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(response.content)

    if path.stat().st_size == 0:
        raise SystemExit(
            "Downloaded model artifact is empty"
        )

    print(
        f"Downloaded {path.stat().st_size} bytes "
        f"from {BUCKET}/{object_name} "
        f"to {path}"
    )

    return True


def download_version(
    path: Path,
    model_version: str,
) -> None:
    object_name = _object_for_version(model_version)

    if _download_object(
        path,
        object_name,
        allow_not_found=True,
    ):
        return

    # Backward-compatible bootstrap:
    # the currently deployed champion may still exist only
    # under the legacy mutable production alias.
    champion = _champion_version()

    if champion != model_version:
        raise SystemExit(
            f"Versioned artifact for {model_version} "
            "does not exist."
        )

    print(
        "Versioned champion artifact is missing; "
        "falling back to legacy production alias."
    )

    _download_object(
        path,
        LEGACY_PRODUCTION_OBJECT,
    )


def download_champion(path: Path) -> str:
    version = _champion_version()

    download_version(
        path,
        version,
    )

    print(
        f"Resolved champion model version: {version}"
    )

    return version


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "action",
        choices={
            "upload",
            "download",
        },
    )

    parser.add_argument(
        "--file",
        default="api/artifacts/model.joblib",
    )

    parser.add_argument(
        "--version",
        default=None,
    )

    parser.add_argument(
        "--champion",
        action="store_true",
    )

    args = parser.parse_args()
    path = Path(args.file)

    if args.action == "upload":
        if args.champion:
            raise SystemExit(
                "--champion is valid only for download"
            )

        if not args.version:
            raise SystemExit(
                "upload requires --version"
            )

        upload(
            path,
            args.version,
        )

        return

    if args.champion:
        if args.version:
            raise SystemExit(
                "Use either --champion or --version, not both"
            )

        download_champion(path)
        return

    if not args.version:
        raise SystemExit(
            "download requires --version or --champion"
        )

    download_version(
        path,
        args.version,
    )


if __name__ == "__main__":
    main()
