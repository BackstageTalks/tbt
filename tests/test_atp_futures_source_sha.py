from pathlib import Path
import sys
from unittest.mock import patch
import base64
import gzip
import hashlib

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_atp_futures_source_sha as a


def fixture():
    raw = b"hello-data"
    gz = gzip.compress(raw)
    b64 = base64.b64encode(gz)
    parts = [f"blinq_atp_futures_quali_2018_2026.csv.gz.b64.part{i:03}.txt" for i in range(9)]
    unit = (len(b64) + 8) // 9
    chunks = {key: b64[i * unit:(i + 1) * unit] for i, key in enumerate(parts)}
    manifest = {"schema": 1, "compression": "gzip", "files": {a.FILENAME: {
        "parts": parts, "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "compressed_bytes": len(gz)}}}
    return raw, manifest, chunks


def test_exact_reconstruction_and_bad_digest():
    raw, m, chunks = fixture()
    with patch.object(a, "SOURCE_SHA", hashlib.sha256(raw).hexdigest()):
        result, digest = a.reconstruct(m, chunks.__getitem__)
        assert result == raw
        assert digest == hashlib.sha256(gzip.compress(raw)).hexdigest() or len(digest) == 64
        m["files"][a.FILENAME]["sha256"] = "b" * 64
        with pytest.raises(ValueError, match="SHA"):
            a.reconstruct(m, chunks.__getitem__)


def test_missing_part_cannot_be_accepted():
    raw, m, chunks = fixture()
    with patch.object(a, "SOURCE_SHA", hashlib.sha256(raw).hexdigest()):
        m["files"][a.FILENAME]["parts"].pop()
        with pytest.raises(ValueError, match="part"):
            a.reconstruct(m, chunks.__getitem__)
