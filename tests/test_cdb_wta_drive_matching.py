"""Fail-closed offline contracts for pinned WTA Drive ingestion and CDB matching."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.cdb_wta_pinned_preflight import (
    FIELDS, normalize, fetch_pinned, sha256,
)
from scripts.cdb_wta_strict_stage import filter_links
from scripts.cdb_wta_verified_window import verified_window


def make_source(path):
    headers = ["", *FIELDS]
    rows = [
        {"GameD": "2017-04-02", "TName": "Test Open", "Name_1": "Ana Alpha",
         "Name_2": "Bea Beta", "GRes_CUR_1": "1", "Surface": "1",
         "Aces_1": "4", "ID": "1"},
        {"GameD": "2018-06-03", "TName": "Wimbledon", "Name_1": "Carol C",
         "Name_2": "Dana D", "GRes_CUR_1": "0", "Surface": "5",
         "ServesTotal_2": "75", "ID": "2"},
        {"GameD": "2018-06-03", "TName": "Wimbledon", "Name_1": "Dana D",
         "Name_2": "Carol C", "GRes_CUR_1": "1", "Surface": "5",
         "ServesTotal_2": "75", "ID": "3"},
        {"GameD": "2012-06-03", "TName": "Test Open", "Name_1": "E E",
         "Name_2": "F F", "GRes_CUR_1": "1", "Surface": "1",
         "Aces_1": "2", "ID": "4"},
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({"": "source detail", **row})


def test_pinned_wta_normalization_excludes_duplicates_and_pre2016(tmp_path):
    source, out = tmp_path / "wta.csv", tmp_path / "view.csv"
    make_source(source)
    report = normalize(source, out, expected_sha256=sha256(source))
    assert report["production_mutated"] is False
    assert report["api_requests"] == 0
    assert report["counts"]["staged_unique_rows"] == 1
    assert report["counts"]["quarantined_ambiguous_identity_rows"] == 2
    assert report["counts"]["excluded_outside_window"] == 1
    with out.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["Aces_1"] == "4"
    assert rows[0]["source_row"] == "2"
    assert "Aces_L5_1" not in rows[0]
    assert "Aces_A_1" not in rows[0]


def test_wrong_sha_and_existing_output_fail_closed(tmp_path):
    source, out = tmp_path / "wta.csv", tmp_path / "out.csv"
    make_source(source)
    with pytest.raises(ValueError, match="Pinned source"):
        normalize(source, out, expected_sha256="0" * 64)
    out.write_text("existing")
    with pytest.raises(ValueError, match="must be new"):
        normalize(source, out, expected_sha256=sha256(source))
    assert out.read_text() == "existing"


def test_pinned_drive_fetch_checks_entire_content_and_cleans_partial(tmp_path):
    data = b"small fake CSV"
    class Response:
        headers = {"Content-Length": str(len(data))}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size):
            yield data[:3]
            yield data[3:]
    class Session:
        def get(self, *args, **kwargs):
            assert kwargs["stream"] is True
            return Response()
    output = tmp_path / "wta.csv"
    assert fetch_pinned(output, session=Session(),
                        expected_sha256=hashlib.sha256(data).hexdigest()) == len(data)
    assert output.read_bytes() == data
    with pytest.raises(ValueError, match="overwrite"):
        fetch_pinned(output, session=Session(),
                     expected_sha256=hashlib.sha256(data).hexdigest())
    output.unlink()
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fetch_pinned(output, session=Session(), expected_sha256="0" * 64)
    assert not output.exists()
    assert not (tmp_path / "wta.csv.partial").exists()


def test_verified_reduced_snapshot_view_preserves_original(tmp_path):
    source, output = tmp_path / "source", tmp_path / "window"
    source.mkdir()
    asset_map = {}
    history = {"schema": 1, "years": {}}
    bundle = {"files": {}}
    for year in range(2016, 2021):
        name = f"history-{year}.parquet"
        (source / name).write_bytes(f"private snapshot {year}".encode())
        checksum = sha256(source / name)
        history["years"][str(year)] = {"asset": name, "sha256": checksum}
        bundle["files"][name] = {"sha256": checksum}
        asset_map[name] = {"name": name, "digest": "sha256:" + checksum}
    (source / "history_manifest.json").write_text(json.dumps(history))
    (source / "_tbt_bundle_manifest.json").write_text(json.dumps(bundle))
    for name in ("history_manifest.json", "_tbt_bundle_manifest.json"):
        asset_map[name] = {"name": name, "digest": "sha256:" + sha256(source / name)}
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"tag_name": "tbt-data-v1",
                                   "assets": list(asset_map.values())}))
    report = verified_window(source, release, output)
    assert report["production_mutated"] is False
    assert len(report["partitions"]) == 5
    assert len(json.loads((output / "history_manifest.json").read_text())["years"]) == 5
    assert (source / "history-2018.parquet").read_bytes() == (output / "history-2018.parquet").read_bytes()
    with pytest.raises(ValueError, match="must be empty"):
        verified_window(source, release, output)


def test_verified_view_rejects_partition_conflicts(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    history = {"years": {str(y): {"asset": f"history-{y}.parquet", "sha256": "0" * 64}
                         for y in range(2016, 2021)}}
    bundle = {"files": {f"history-{y}.parquet": {"sha256": "0" * 64}
                        for y in range(2016, 2021)}}
    for y in range(2016, 2021):
        (source / f"history-{y}.parquet").write_bytes(b"bad")
    (source / "history_manifest.json").write_text(json.dumps(history))
    (source / "_tbt_bundle_manifest.json").write_text(json.dumps(bundle))
    assets = [{"name": name, "digest": "sha256:" + sha256(source / name)}
              for name in ("history_manifest.json", "_tbt_bundle_manifest.json")]
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"tag_name": "tbt-data-v1", "assets": assets}))
    with pytest.raises(ValueError, match="checksum mismatch"):
        verified_window(source, release, tmp_path / "window")


def _jsonl(path, values):
    path.write_text("".join(json.dumps(row) + "\n" for row in values))


def test_strict_match_filter_is_additive_and_excludes_conflict(tmp_path):
    linker, out = tmp_path / "link", tmp_path / "stage"
    linker.mkdir()
    (linker / "report.json").write_text(json.dumps({
        "production_mutated": False, "api_requests": 0,
        "matching_strategy": "verified_ids", "source_rows": 4, "counts": {},
    }))
    def row(mid, evidence):
        return {"schema": 1, "match_id": mid, "import_ready": True,
                "canonical": {"tour": "wta", "scheduled_date_utc": "2018-06-03"},
                "incoming_stats": {"p1_aces": 2.0},
                "sources": [{"source": "kaggle-hwaitt:wta_matches_verified.csv",
                             "evidence": evidence}]}
    all_evidence = ["date_exact", "winner", "tournament_exact", "surface"]
    _jsonl(linker / "auto_linked.jsonl", [
        row("ok", all_evidence),
        row("quarantine", all_evidence),
        row("weak", ["date_exact", "winner", "tournament_exact"]),
    ])
    _jsonl(linker / "quarantine.jsonl", [{"match_id": "quarantine"}])
    result = filter_links(linker, out)
    assert result["eligible_matches"] == 1
    assert result["eligible_new_stat_fields"] == 1
    assert result["reasons"] == {"conflicted_canonical_stats": 1,
                                  "unconfirmed_source_identity": 1}
    assert [x["match_id"] for x in [json.loads(s) for s in (out / "eligible.jsonl").read_text().splitlines()]] == ["ok"]
    assert result["production_mutated"] is False
