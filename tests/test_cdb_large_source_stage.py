"""Contract: large ATP/WTA serve-return files remain SOURCE ONLY, never CDB writes."""
import csv
import hashlib
import json

import pytest

from scripts.cdb_large_source_stage import stage, sha256


def test_sha_pinned_large_source_chunks_without_any_cdb_write(tmp_path):
    source = tmp_path / "serve.csv"
    with source.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=["match_id", "player_id", "serve"])
        writer.writeheader()
        for index in range(5):
            writer.writerow({"match_id": f"unverified-{index}", "player_id": "raw-1",
                             "serve": index})
    output = tmp_path / "stage"
    report = stage(source, output, "serve", sha256(source), chunk_rows=2)
    assert report["state"] == "SOURCE_ONLY_NEEDS_EXACT_IDENTITY_MAPPING"
    assert report["production_mutated"] is False
    assert report["cdb_eligible_matches"] == 0
    assert report["api_requests"] == 0
    assert report["requires_independent_match_identity"] is True
    assert report["rows"] == 5
    assert [x["rows"] for x in report["shards"]] == [2, 2, 1]
    for shard in report["shards"]:
        assert hashlib.sha256((output / shard["file"]).read_bytes()).hexdigest() == shard["sha256"]
    assert json.loads((output / "manifest.json").read_text()) == report
    with pytest.raises(ValueError, match="Output stage must be empty"):
        stage(source, output, "serve", sha256(source), 2)


def test_fails_closed_on_wrong_hash_unknown_kind_and_bad_header(tmp_path):
    source = tmp_path / "return.csv"
    source.write_text("id,value\na,1\n")
    with pytest.raises(ValueError, match="Pinned source SHA"):
        stage(source, tmp_path / "wrong", "return", "0" * 64)
    with pytest.raises(ValueError, match="Unknown large-source kind"):
        stage(source, tmp_path / "bad-kind", "match", sha256(source))
    source.write_text("id,id\na,1\n")
    with pytest.raises(ValueError, match="Duplicate or unbounded"):
        stage(source, tmp_path / "headers", "return", sha256(source))
    assert not (tmp_path / "headers" / "manifest.json").exists()


def test_malformed_row_cannot_be_silently_staged(tmp_path):
    source = tmp_path / "return.csv"
    source.write_text("match,return\na,1,extra\n")
    with pytest.raises(ValueError, match="Malformed CSV"):
        stage(source, tmp_path / "out", "return", sha256(source))
    assert not (tmp_path / "out" / "manifest.json").exists()
