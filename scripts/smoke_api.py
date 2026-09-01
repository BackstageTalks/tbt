from __future__ import annotations

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="e.g. https://my-function.azurewebsites.net")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    for path in ("/api/health", "/api/v1/model/status", "/api/v1/predictions/upcoming?days=2"):
        response = httpx.get(base + path, timeout=30)
        print(path, response.status_code)
        try:
            print(json.dumps(response.json(), indent=2)[:3000])
        except ValueError:
            print(response.text[:1000])
        response.raise_for_status()


if __name__ == "__main__":
    main()
