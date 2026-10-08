import base64
from types import SimpleNamespace

from scripts.rank_feature_inputs import _download_repo_binary


def test_private_binary_download_uses_git_blob_base64(monkeypatch, tmp_path):
    expected = b"\x1f\x8b\x08binary-gzip-payload\x00\xff"
    calls = []

    def fake_run(args, stdout=None, stderr=None):
        calls.append(args)
        if "/contents/" in args[2]:
            return SimpleNamespace(
                returncode=0,
                stdout=b"0123456789abcdef0123456789abcdef01234567\n",
                stderr=b"",
            )
        if "/git/blobs/" in args[2]:
            encoded = base64.b64encode(expected)
            # GitHub blob payloads may contain embedded newlines.
            wrapped = encoded[:12] + b"\n" + encoded[12:] + b"\n"
            return SimpleNamespace(returncode=0, stdout=wrapped, stderr=b"")
        raise AssertionError(args)

    monkeypatch.setattr("scripts.rank_feature_inputs.subprocess.run", fake_run)

    destination = tmp_path / "supplement.csv.gz"
    _download_repo_binary(
        "BackstageTalks/tbt-data",
        "research/wta-official-2026/supplement.csv.gz",
        destination,
    )

    assert destination.read_bytes() == expected
    assert len(calls) == 2
    assert calls[0][-2:] == ["--jq", ".sha"]
    assert calls[1][-2:] == ["--jq", ".content"]


def test_private_binary_download_rejects_invalid_blob_sha(monkeypatch, tmp_path):
    def fake_run(args, stdout=None, stderr=None):
        return SimpleNamespace(returncode=0, stdout=b"short\n", stderr=b"")

    monkeypatch.setattr("scripts.rank_feature_inputs.subprocess.run", fake_run)

    destination = tmp_path / "supplement.csv.gz"
    try:
        _download_repo_binary("repo/name", "asset.gz", destination)
    except RuntimeError as exc:
        assert "invalid blob SHA" in str(exc)
    else:
        raise AssertionError("invalid SHA must fail closed")

    assert not destination.exists()
