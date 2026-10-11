from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from audit_all_private_release_assets import audit


def sample(data=b"verified"):
    return {"tag_name":"private-checkpoint","assets":[{"id":1,"name":"source.bin",
             "size":len(data),"digest":"sha256:"+sha256(data).hexdigest()}]}


def test_full_active_asset_sha_and_size_match():
    with tempfile.TemporaryDirectory() as tmp:
        def downloader(_repo,_tag,dest):
            (dest/"source.bin").write_bytes(b"verified")
        report, items=audit([sample()],"BackstageTalks/tbt-data",Path(tmp),downloader=downloader)
        assert report["status"]=="ALL_ACTIVE_RELEASE_ASSET_BYTES_SHA256_VERIFIED"
        assert report["counts"]["assets_byte_verified"]==1
        assert items[0]["verified"]
        assert report["canonical_cdb_writes"]==0


def test_equal_size_modified_bytes_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        def downloader(_repo,_tag,dest):
            (dest/"source.bin").write_bytes(b"modified")
        report,items=audit([sample()],"private",Path(tmp),downloader=downloader)
        assert report["status"]!="ALL_ACTIVE_RELEASE_ASSET_BYTES_SHA256_VERIFIED"
        assert report["counts"]["digest_mismatches"]==1
        assert items[0]["reason"]=="SHA256_MISMATCH"


def test_missing_file_is_not_silently_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        report,items=audit([sample()],"private",Path(tmp),
                          downloader=lambda *_: None)
        assert report["assets_not_byte_verified"]==1
        assert items[0]["reason"]=="MISSING_ASSET"


def test_download_exception_is_explicit_failure():
    with tempfile.TemporaryDirectory() as tmp:
        def failed(*_):
            raise OSError("offline")
        report,items=audit([sample()],"private",Path(tmp),downloader=failed)
        assert report["counts"]["release_download_failures"]==1
        assert report["assets_not_byte_verified"]==1


def test_duplicate_asset_name_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        x=sample()
        x["assets"].append({"id":2,"name":"source.bin","size":1,
                           "digest":"sha256:"+"a"*64})
        try:
            audit([x],"private",Path(tmp),downloader=lambda *_: None)
            assert False,"duplicate was accepted"
        except ValueError:
            pass
