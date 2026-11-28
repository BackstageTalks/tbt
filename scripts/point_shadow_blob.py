"""Private rolling point-model blob. Conditional writes preserve the first capture."""
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CANDIDATE = "blinq-candidate-frozen-45525499354-1"


def read_blob(url):
    try:
        with urlopen(url, timeout=25) as response:
            data = json.loads(gzip.decompress(response.read()))
            if data["schema"] != 3 or data["candidate"] != CANDIDATE:
                raise ValueError("Unexpected point shadow schema")
            return data["cards"], response.headers["ETag"]
    except HTTPError as error:
        if error.code != 404:
            raise
        return {}, None


def envelope(cards):
    return {"schema": 3, "candidate": CANDIDATE, "cards": cards}


def publish(cards):
    url = os.environ["BLINQ_POINT_BLOB_WRITE_URL"]
    for _ in range(4):
        previous, etag = read_blob(url)
        now = datetime.now(timezone.utc)
        keep_since = now - timedelta(days=14)
        merged = {k: v for k, v in previous.items()
                  if datetime.fromisoformat(v["scheduled_at"]) >= keep_since}
        events = {v["event_id"] for v in merged.values()}
        for key, card in cards.items():
            if (key not in merged and card["event_id"] not in events
                    and datetime.fromisoformat(card["scheduled_at"]) > now):
                merged[key] = card
                events.add(card["event_id"])
        if merged == previous:
            return
        body = gzip.compress(json.dumps(envelope(merged), allow_nan=False).encode())
        headers = {"x-ms-blob-type": "BlockBlob", "x-ms-version": "2021-12-02",
                   ("If-Match" if etag else "If-None-Match"): etag or "*"}
        try:
            with urlopen(Request(url, data=body, method="PUT", headers=headers), timeout=25):
                return
        except HTTPError as error:
            if error.code not in (409, 412):
                raise
    raise RuntimeError("Point shadow blob contention")


def package(path):
    url = os.getenv("BLINQ_POINT_BLOB_READ_URL")
    if url:
        cards, _ = read_blob(url)
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps(envelope(cards), allow_nan=False), encoding="utf-8")
        pending.replace(path)
