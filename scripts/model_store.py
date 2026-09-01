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


def _headers(key: str, content_type: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def ensure_bucket(client: httpx.Client, url: str, key: str) -> None:
    response = client.post(
        f"{url}/storage/v1/bucket",
        headers=_headers(key, "application/json"),
        json={"id": BUCKET, "name": BUCKET, "public": False},
    )
    if response.status_code not in {200, 201, 409}:
        response.raise_for_status()


def upload(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Model artifact missing or empty: {path}")

    url, key = _settings()
    object_path = quote(OBJECT, safe="/")
    with httpx.Client(timeout=120.0) as client:
        ensure_bucket(client, url, key)
        response = client.post(
            f"{url}/storage/v1/object/{BUCKET}/{object_path}",
            headers={
                **_headers(key, "application/octet-stream"),
                "x-upsert": "true",
            },
            content=path.read_bytes(),
        )
        response.raise_for_status()

    print(f"Uploaded {path.stat().st_size} bytes to {BUCKET}/{OBJECT}")


def download(path: Path) -> None:
    url, key = _settings()
    object_path = quote(OBJECT, safe="/")
    with httpx.Client(timeout=120.0) as client:
        response = client.get(
            f"{url}/storage/v1/object/{BUCKET}/{object_path}",
            headers=_headers(key),
        )
        if response.status_code == 404:
            raise SystemExit(
                "Production model is not in Supabase Storage yet. "
                "Run Retrain, backtest and deploy first."
            )
        response.raise_for_status()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    if path.stat().st_size == 0:
        raise SystemExit("Downloaded model artifact is empty")
    print(f"Downloaded {path.stat().st_size} bytes to {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices={"upload", "download"})
    parser.add_argument("--file", default="api/artifacts/model.joblib")
    args = parser.parse_args()
    path = Path(args.file)

    if args.action == "upload":
        upload(path)
    else:
        download(path)


if __name__ == "__main__":
    main()
