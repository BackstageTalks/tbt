"""Pure offline no-op verification: no CDB, Kaggle, or GitHub dependency."""
import gzip
import hashlib
from pathlib import Path

import pytest

from scripts.verify_alimoh89_existing_sidecars import verify_existing


def _write(path: Path, body: bytes, *, mtime: int) -> None:
    with path.open("wb") as fd:
        with gzip.GzipFile(fileobj=fd, mode="wb", filename="", mtime=mtime) as gz:
            gz.write(body)


def fixture(tmp_path):
    local, remote = tmp_path / "local", tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    files = []
    sidecar_years = {}
    for year in range(2014, 2026):
        name = f"market-sidecar-{year}.jsonl.gz"
        content = f'{{"year":{year}}}\n'.encode()
        _write(local / name, content, mtime=999)
        _write(remote / name, content, mtime=1)
        binary = (remote / name).read_bytes()
        files.append(dict(name=name, sha256=hashlib.sha256(binary).hexdigest(),
                          bytes=len(binary), rows=1))
        sidecar_years[str(year)] = 1
    source = {"file_sha256": "8bc187158931957d92ffaa5dc7e5a3e4bd58b30023e8c470bcb85521a58bee16"}
    prep = {"canonical_market_stage_rows": 0, "canonical_mutated": False,
            "model_promoted": False, "provider_api_requests": 0, "source": source,
            "staged_rows": 12, "sidecar_years": sidecar_years}
    manifest = {"release_tag": "blinq-alimoh89-markets-2026-10-07",
                "preparation": {"source": source, "staged_rows": 12,
                                "sidecar_years": sidecar_years},
                "canonical_import": {"stage_rows": 20342,
                                      "counts": {"updated": 20342}},
                "files": files}
    release = {"tag_name": manifest["release_tag"],
               "assets": [{"name": e["name"], "digest": "sha256:" + e["sha256"],
                           "size": e["bytes"]} for e in files]}
    return prep, manifest, release, local, remote


def test_verified_identical_jsonl_with_different_gzip_header(tmp_path):
    x = fixture(tmp_path)
    result = verify_existing(*x)
    assert result["canonical_rows_added"] == 0
    assert result["research_sidecar_matches"] == 12
    assert result["sidecar_files_sha256_verified"] == 12


def test_rejects_fresh_mapped_difference(tmp_path):
    prep, manifest, release, local, remote = fixture(tmp_path)
    _write(local / "market-sidecar-2025.jsonl.gz", b'{"year":999}\n', mtime=3)
    with pytest.raises(ValueError, match="differs"):
        verify_existing(prep, manifest, release, local, remote)


def test_rejects_staged_new_market(tmp_path):
    prep, manifest, release, local, remote = fixture(tmp_path)
    prep["canonical_market_stage_rows"] = 1
    with pytest.raises(ValueError, match="nonzero"):
        verify_existing(prep, manifest, release, local, remote)


def test_rejects_missing_or_tampered_remote_asset(tmp_path):
    prep, manifest, release, local, remote = fixture(tmp_path)
    (remote / "market-sidecar-2020.jsonl.gz").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        verify_existing(prep, manifest, release, local, remote)
    _write(remote / "market-sidecar-2020.jsonl.gz", b'{"year":2020}\n', mtime=7)
    with pytest.raises(ValueError, match="SHA-256"):
        verify_existing(prep, manifest, release, local, remote)


def test_rejects_source_and_manifest_drift(tmp_path):
    prep, manifest, release, local, remote = fixture(tmp_path)
    prep["source"] = {"file_sha256": "0" * 64}
    with pytest.raises(ValueError, match="checksum"):
        verify_existing(prep, manifest, release, local, remote)
