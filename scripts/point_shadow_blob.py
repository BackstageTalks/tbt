"""Private rolling point-model blob. Conditional writes preserve the first capture."""
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CANDIDATE = "blinq-candidate-frozen-45525499354-1"
CONTAINER = "point-model-shadow"
BLOB = "point_model_shadow.json"


def _derived_url(write):
    """SAS URL from the existing media storage connection string (no manual SAS).

    Explicit BLINQ_POINT_BLOB_*_URL secrets still win when they are set."""
    conn = os.getenv("BLINQ_MEDIA_STORAGE_CONNECTION_STRING", "").strip()
    if not conn:
        return ""
    try:
        from azure.storage.blob import (BlobSasPermissions, BlobServiceClient,
                                        generate_blob_sas)
    except ImportError:
        return ""
    service = BlobServiceClient.from_connection_string(conn)
    container = service.get_container_client(CONTAINER)
    if write and not container.exists():
        container.create_container()  # private by default
    key = service.credential.account_key
    sas = generate_blob_sas(
        account_name=service.account_name, container_name=CONTAINER, blob_name=BLOB,
        account_key=key,
        permission=BlobSasPermissions(read=True, add=write, create=write, write=write),
        expiry=datetime.now(timezone.utc) + timedelta(hours=2))
    return f"{container.url}/{BLOB}?{sas}"


def _url(kind):
    explicit = os.getenv(f"BLINQ_POINT_BLOB_{kind}_URL", "").strip()
    return explicit or _derived_url(kind == "WRITE")


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
    url = _url("WRITE")
    if not url:
        raise RuntimeError("Point shadow storage not configured")
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
            elif (key in merged and card.get("sg_shadow")
                  and all(merged[key].get(k) == card.get(k) for k in ("event_id", "players", "scheduled_at"))
                  and datetime.fromisoformat(card["scheduled_at"]) > now):
                # Tomorrow's card can precede today's quote. Append each market once.
                evidence = {**card["sg_shadow"], **merged[key].get("sg_shadow", {})}
                merged[key] = {**merged[key], "sg_shadow": evidence}
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
    url = _url("READ")
    if url:
        cards, _ = read_blob(url)
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps(envelope(cards), allow_nan=False), encoding="utf-8")
        pending.replace(path)
