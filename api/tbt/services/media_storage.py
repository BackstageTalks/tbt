"""Private Azure Blob media storage exposed through a same-origin read proxy.

Admin uploads stay binary end-to-end. The container is private; public pages use
an opaque `/api/v1/media/<id>` URL served by the API, so no anonymous Blob
container access or SAS token needs to be embedded in BlinQ configuration.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import re
import uuid


class MediaStorageUnavailable(RuntimeError):
    pass


_ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}
_MEDIA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,180}$")
_MAX_UPLOAD_BYTES = 12 * 1024 * 1024


def _connection_string() -> str:
    return str(
        os.getenv("BLINQ_MEDIA_STORAGE_CONNECTION_STRING")
        or os.getenv("BLINQ_ADMIN_STORAGE_CONNECTION_STRING")
        or os.getenv("AzureWebJobsStorage")
        or ""
    ).strip()


def _container_name() -> str:
    raw = str(os.getenv("BLINQ_MEDIA_CONTAINER") or "blinq-media").strip().lower()
    raw = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    return (raw or "blinq-media")[:63]


def _blob_service():
    connection = _connection_string()
    if not connection:
        raise MediaStorageUnavailable("Media storage is not configured")
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise MediaStorageUnavailable("azure-storage-blob is unavailable") from exc
    try:
        return BlobServiceClient.from_connection_string(connection)
    except Exception as exc:
        raise MediaStorageUnavailable("Media storage connection is unavailable") from exc


def _container():
    service = _blob_service()
    client = service.get_container_client(_container_name())
    try:
        client.create_container()
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = exc.__class__.__name__.lower()
        if status != 409 and "resourceexists" not in name:
            # Accessing an existing private container can still work even when
            # create is denied. Probe it before declaring storage unavailable.
            try:
                client.get_container_properties()
            except Exception as inner:
                raise MediaStorageUnavailable("Media container is unavailable") from inner
    return client


def _validate_image_bytes(data: bytes, content_type: str) -> None:
    """Reject obvious MIME spoofing without adding a heavyweight image stack."""
    if content_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Uploaded file is not a valid PNG")
    if content_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("Uploaded file is not a valid JPEG")
    if content_type == "image/webp" and not (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise ValueError("Uploaded file is not a valid WebP")
    if content_type == "image/gif" and not (data.startswith(b"GIF87a") or data.startswith(b"GIF89a")):
        raise ValueError("Uploaded file is not a valid GIF")
    if content_type == "image/avif" and not (len(data) >= 16 and b"ftyp" in data[4:12] and b"avif" in data[:32]):
        raise ValueError("Uploaded file is not a valid AVIF")


def upload_media(data: bytes, *, content_type: str, original_name: str = "", actor_id: str = "") -> dict:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("Upload is empty")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValueError("Image is too large (maximum 12 MB)")
    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    extension = _ALLOWED_CONTENT_TYPES.get(content_type)
    if not extension:
        raise ValueError("Unsupported image type. Use PNG, JPG, WebP, GIF or AVIF")
    data = bytes(data)
    _validate_image_bytes(data, content_type)

    digest = hashlib.sha256(data).hexdigest()[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    media_id = f"banner-{stamp}-{digest}-{uuid.uuid4().hex[:8]}{extension}"
    metadata = {
        "uploaded_by": str(actor_id or "")[:128],
        "original_name": re.sub(r"[^A-Za-z0-9._ -]+", "_", str(original_name or ""))[:180],
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    try:
        blob = _container().get_blob_client(media_id)
        blob.upload_blob(
            data,
            overwrite=False,
            content_settings=_content_settings(content_type),
            metadata=metadata,
        )
    except MediaStorageUnavailable:
        raise
    except Exception as exc:
        raise MediaStorageUnavailable("Unable to upload media") from exc
    return {
        "ok": True,
        "media_id": media_id,
        "url": f"/api/v1/media/{media_id}",
        "content_type": content_type,
        "size": len(data),
    }


def _content_settings(content_type: str):
    try:
        from azure.storage.blob import ContentSettings
    except ImportError as exc:  # pragma: no cover
        raise MediaStorageUnavailable("azure-storage-blob is unavailable") from exc
    return ContentSettings(
        content_type=content_type,
        cache_control="public, max-age=31536000, immutable",
        content_disposition="inline",
    )


def download_media(media_id: str) -> tuple[bytes, str, str]:
    media_id = str(media_id or "").strip()
    if not _MEDIA_ID.fullmatch(media_id):
        raise ValueError("Invalid media id")
    try:
        blob = _container().get_blob_client(media_id)
        properties = blob.get_blob_properties()
        data = blob.download_blob(max_concurrency=1).readall()
        content_type = str(getattr(properties.content_settings, "content_type", None) or "application/octet-stream")
        etag = str(getattr(properties, "etag", None) or "").strip('"')
        return data, content_type, etag
    except MediaStorageUnavailable:
        raise
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = exc.__class__.__name__.lower()
        if status == 404 or "notfound" in name:
            raise FileNotFoundError(media_id) from exc
        raise MediaStorageUnavailable("Unable to read media") from exc


def media_storage_diagnostics() -> dict:
    configured = bool(_connection_string())
    if not configured:
        return {"configured": False, "available": False, "container": _container_name()}
    try:
        client = _container()
        client.get_container_properties()
        available = True
    except Exception:
        available = False
    return {"configured": True, "available": available, "container": _container_name()}
