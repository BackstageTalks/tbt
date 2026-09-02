from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import quote

import httpx


BUCKET = "tbt-models"
OBJECT = "production/model.joblib"


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


def ensure_bucket(
    client: httpx.Client,
    url: str,
    key: str,
) -> None:
    """
    Ensure the private model bucket exists.

    First check the bucket directly. This makes retraining idempotent and
    avoids Supabase returning HTTP 400 when the bucket already exists.
    """

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

    # Some Supabase Storage deployments return HTTP 400 for an existing
    # bucket instead of HTTP 409. Accept that only when the response
    # explicitly states that the bucket already exists.
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


def upload(path: Path) -> None:
    if (
        not path.is_file()
        or path.stat().st_size == 0
    ):
        raise SystemExit(
            f"Model artifact missing or empty: {path}"
        )

    url, key = _settings()

    object_path = quote(
        OBJECT,
        safe="/",
    )

    with httpx.Client(
        timeout=120.0,
    ) as client:
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
                "Unable to upload production model to "
                f"{BUCKET}/{OBJECT}: "
                f"HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

    print(
        f"Uploaded {path.stat().st_size} bytes "
        f"to {BUCKET}/{OBJECT}"
    )


def download(path: Path) -> None:
    url, key = _settings()

    object_path = quote(
        OBJECT,
        safe="/",
    )

    with httpx.Client(
        timeout=120.0,
    ) as client:
        response = client.get(
            (
                f"{url}/storage/v1/object/"
                f"{BUCKET}/{object_path}"
            ),
            headers=_headers(key),
        )

        if response.status_code == 404:
            raise SystemExit(
                "Production model is not in Supabase "
                "Storage yet. Run Retrain, backtest "
                "and deploy first."
            )

        if response.is_error:
            raise RuntimeError(
                "Unable to download production model "
                f"from {BUCKET}/{OBJECT}: "
                f"HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(
        response.content
    )

    if path.stat().st_size == 0:
        raise SystemExit(
            "Downloaded model artifact is empty"
        )

    print(
        f"Downloaded {path.stat().st_size} bytes "
        f"to {path}"
    )


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

    args = parser.parse_args()
    path = Path(args.file)

    if args.action == "upload":
        upload(path)
    else:
        download(path)


if __name__ == "__main__":
    main()
