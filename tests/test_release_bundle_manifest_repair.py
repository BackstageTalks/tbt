from scripts.repair_release_bundle_manifest import (
    BUNDLE_MANIFEST,
    build_manifest,
)


def test_build_manifest_uses_github_asset_digests_and_excludes_itself():
    release = {
        "assets": [
            {
                "name": "data.csv",
                "state": "uploaded",
                "size": 12,
                "digest": "sha256:" + "a" * 64,
            },
            {
                "name": "summary.json",
                "state": "uploaded",
                "size": 5,
                "digest": "sha256:" + "b" * 64,
            },
            {
                "name": BUNDLE_MANIFEST,
                "state": "uploaded",
                "size": 99,
                "digest": "sha256:" + "c" * 64,
            },
        ]
    }
    manifest = build_manifest(release, required_assets=("data.csv",))
    assert manifest["schema"] == 1
    assert set(manifest["files"]) == {"data.csv", "summary.json"}
    assert manifest["files"]["data.csv"]["sha256"] == "a" * 64
    assert manifest["files"]["data.csv"]["bytes"] == 12


def test_build_manifest_fails_closed_when_required_asset_missing():
    import pytest

    with pytest.raises(FileNotFoundError):
        build_manifest({"assets": []}, required_assets=("data.csv",))
