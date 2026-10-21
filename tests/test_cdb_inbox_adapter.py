"""Contract tests for private Drive inbox source normalization and safe link filtering."""
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.cdb_inbox_adapter import run as normalize, normalize as normalize_row, read_rows, pieces
from scripts.cdb_inbox_stage import run as stage


def sample(**kw):
    row = {
        "tour": "ATP", "match_date": "2026-10-17",
        "tournament": "Vienna", "winner": "Alpha One", "loser": "Beta Two",
        "round": "QF", "surface": "Hard",
        "w_svpt": "70", "w_1stIn": "40", "w_1stWon": "30", "w_2ndWon": "14",
        "l_svpt": "60", "l_1stIn": "35", "l_1stWon": "25", "l_2ndWon": "11",
    }
    row.update(kw)
    return row


def test_normalize_csv_uses_approved_source_columns(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    with (src / "tennis.csv").open("w", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=sample())
        writer.writeheader()
        writer.writerow(sample())
        writer.writerow(sample(tour="unknown"))
    result = normalize(src, out)
    assert result["production_mutated"] is False
    assert result["counts"]["normalized_rows"] == 1
    assert result["counts"]["rejected_rows"] == 1
    output = Path(result["normalized"][0]["path"])
    rows = list(csv.DictReader(output.open()))
    assert rows[0]["tourney_date"] == "20261017"
    assert rows[0]["tourney_name"] == "Vienna"
    assert rows[0]["w_svpt"] == "70"


def test_json_zip_and_identical_duplicate_bytes(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    raw = json.dumps({"matches": [sample(tour="WTA")]}).encode()
    (src / "one.json").write_bytes(raw)
    (src / "two.json").write_bytes(raw)
    with zipfile.ZipFile(src / "bundle.zip", "w") as archive:
        archive.writestr("wta_match.jsonl", json.dumps(sample(tour="WTA")))
    report = normalize(src, out)
    assert report["counts"]["duplicate_source_files"] == 1
    assert report["counts"]["normalized_rows"] == 2
    assert all(x["tour"] == "wta" for x in report["normalized"])


def test_bad_file_refuses_false_import_ready(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (src / "bad.jsonl").write_text(json.dumps({"tour": "ATP", "winner": "A"}) + "\n")
    result = normalize(src, out)
    assert result["normalized"] == []
    assert result["counts"]["rejected_rows"] == 1


def test_zip_oversize_rejected_without_unbounded_extraction(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    with zipfile.ZipFile(src / "too-large.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("records.csv", b"x" * (33 * 1024 * 1024))
    result = normalize(src, out)
    assert not result["normalized"]
    assert result["counts"].get("invalid_archives", 0) == 1


def test_stage_requires_exact_day_tournament_winner_and_extra_evidence(tmp_path, monkeypatch):
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    sample_file = normalized / "atp_0123456789abcdef_0.csv"
    sample_file.write_text("league\natp\n")
    manifest = tmp_path / "report.json"
    manifest.write_text(json.dumps({"normalized": [{"path": str(sample_file)}]}))

    def fake_link(command, **kw):
        link_dir = Path(command[command.index("--out-dir") + 1])
        link_dir.mkdir(parents=True)
        (link_dir / "report.json").write_text(json.dumps({"production_mutated": False,
            "api_requests": 0, "counts": {"identity_linked": 3}, "source_rows": 3}))
        def row(mid, proof):
            return {"schema": 1, "import_ready": True, "match_id": mid,
                    "canonical": {"tour": "atp", "scheduled_date_utc": "2026-10-17"},
                    "incoming_stats": {"p1_aces": 7},
                    "sources": [{"source": "sackmann:" + sample_file.name, "evidence": proof}]}
        rows = [
            row("good", ["date_exact", "winner", "tournament_exact", "round"]),
            row("weak", ["date_tournament_window", "winner", "tournament_exact", "round"]),
            row("conflict", ["date_exact", "winner", "tournament_exact", "surface"]),
        ]
        (link_dir / "auto_linked.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
        (link_dir / "quarantine.jsonl").write_text(json.dumps({"match_id": "conflict"}) + "\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.cdb_inbox_stage.subprocess.run", fake_link)
    result = stage(manifest, tmp_path / "history", tmp_path / "stage")
    assert result["eligible_matches"] == 1
    assert result["eligible_new_values"] == 1
    assert result["filtered_matches"] == 2
    assert result["conflict_matches"] == 1
    assert result["filter_reasons"]["date_not_exact"] == 1
    assert result["filter_reasons"]["canonical_stat_conflict"] == 1
    assert json.loads((tmp_path / "stage/eligible.jsonl").read_text())["match_id"] == "good"


def test_preserve_untrusted_player_ids_without_claiming_verified_identity(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    row = sample(winner_id="atp-100", loser_id="atp-200")
    with (src / "atp_matches.csv").open("w", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    report = normalize(src, out)
    normalized = list(csv.DictReader(Path(report["normalized"][0]["path"]).open()))
    assert normalized[0]["source_winner_id"] == "atp-100"
    assert normalized[0]["source_loser_id"] == "atp-200"
    assert "winner_id" not in normalized[0]
    assert "loser_id" not in normalized[0]
    assert report["state"] == "SOURCE_ONLY"
    assert report["production_mutated"] is False


def test_unambiguous_pandas_date_literal_and_per_file_audit(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    good = sample(match_date="20261017.0")
    bad = sample(match_date="10/17/2026")
    with (src / "atp_test.csv").open("w", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=good)
        writer.writeheader()
        writer.writerow(good)
        writer.writerow(bad)
    report = normalize(src, out)
    assert report["counts"]["normalized_rows"] == 1
    assert report["counts"]["reason_date_missing_or_invalid"] == 1
    assert report["source_diagnostics"][0]["raw_rows"] == 2
    assert report["source_diagnostics"][0]["rejected_by_reason"] == {
        "date_missing_or_invalid": 1
    }
    row = next(csv.DictReader(Path(report["normalized"][0]["path"]).open()))
    assert row["tourney_date"] == "20261017"


def test_real_utc_start_overrides_tournament_start_only_within_window():
    row, reason = normalize_row(
        sample(tourney_date="20261018", match_date="", start_time_utc="2026-10-21T13:05:00Z"),
        "atp_matches_2026.csv", 1,
    )
    # The input's match_date column is blank; use tournament start then an
    # independently supplied UTC timestamp, never a canonical inferred date.
    assert reason == ""
    assert row["tourney_date"] == "20261021"


def test_utc_start_does_not_rescue_disagreeing_davis_cup_season_date():
    row, reason = normalize_row(
        sample(match_date="", tourney_date="20260206",
               start_time_utc="2026-09-18T14:20:00Z"),
        "atp_matches_2026.csv", 1,
    )
    assert row is None
    assert reason == "start_time_outside_tournament_window"


def test_utc_start_invalid_or_conflicting_exact_match_date_fails_closed():
    row, reason = normalize_row(
        sample(start_time_utc="2026-10-21 13:05:00", match_date="2026-10-21"),
        "atp_matches_2026.csv", 1,
    )
    assert row is None and reason == "start_time_utc_invalid"
    row, reason = normalize_row(
        sample(start_time_utc="2026-10-21T13:05:00Z", match_date="2026-10-20"),
        "atp_matches_2026.csv", 1,
    )
    assert row is None and reason == "match_date_start_time_conflict"


def test_missing_precise_start_keeps_existing_tournament_date_behavior():
    row, reason = normalize_row(
        sample(match_date="", tourney_date="20261018", start_time_utc=""),
        "wta_matches_2026.csv", 1,
    )
    assert reason == ""
    assert row["tourney_date"] == "20261018"

def _drive_context_manifest(tmp_path, source, source_path, source_sha=None):
    manifest = tmp_path / "drive_manifest.json"
    manifest.write_text(json.dumps({
        "schema": 2, "state": "DRIVE_SOURCE_FETCH_ONLY",
        "production_mutated": False,
        "files": [{"status": "fetched", "local_file": str(source),
                   "sha256": source_sha or hashlib.sha256(source.read_bytes()).hexdigest(),
                   "source_path": source_path}],
    }))
    return manifest


def test_ambiguous_filename_recovers_tour_only_from_sha_verified_drive_folder(tmp_path):
    incoming = tmp_path / "input"
    incoming.mkdir()
    source = incoming / "bbbbbbbbbbbbbbbb__X_99.csv"
    data = sample(tour="")
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=data)
        writer.writeheader()
        writer.writerow(data)
    manifest = _drive_context_manifest(
        tmp_path, source, "/10_POVODNE_ZDROJE_ARCHIVY/ATP/X (99).csv"
    )
    report = normalize(incoming, tmp_path / "out", drive_manifest_path=manifest)
    assert report["state"] == "SOURCE_ONLY"
    assert report["production_mutated"] is False
    assert report["api_requests"] == 0
    assert report["counts"]["normalized_rows"] == 1
    assert report["counts"]["rows_rescued_by_sha_verified_drive_folder_tour"] == 1
    written = list(csv.DictReader(Path(report["normalized"][0]["path"]).open()))
    assert written[0]["league"] == "atp"
    assert written[0]["source_winner_id"] == ""
    assert "import_ready" not in written[0]


def test_folder_tour_conflict_and_ambiguous_parent_are_quarantined(tmp_path):
    incoming = tmp_path / "input"
    incoming.mkdir()
    source = incoming / "bbbbbbbbbbbbbbbb__X_99.csv"
    row = sample(tour="WTA")
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    manifest = _drive_context_manifest(
        tmp_path, source, "/10_POVODNE_ZDROJE_ARCHIVY/ATP/X (99).csv"
    )
    result = normalize(incoming, tmp_path / "conflict", drive_manifest_path=manifest)
    assert result["counts"].get("normalized_rows", 0) == 0
    assert result["counts"]["reason_tour_provenance_conflict"] == 1

    row["tour"] = ""
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    manifest = _drive_context_manifest(
        tmp_path, source, "/10_POVODNE_ZDROJE_ARCHIVY/WTA/ATP/X (99).csv"
    )
    result = normalize(incoming, tmp_path / "ambiguous", drive_manifest_path=manifest)
    assert result["counts"].get("normalized_rows", 0) == 0
    assert result["counts"]["reason_tour_missing_or_unsupported"] == 1


def test_drive_path_hint_never_bypasses_source_sha_or_zip_member_tour(tmp_path):
    incoming = tmp_path / "input"
    incoming.mkdir()
    source = incoming / "bbbbbbbbbbbbbbbb__X_99.csv"
    data = sample(tour="")
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=data)
        writer.writeheader()
        writer.writerow(data)
    manifest = _drive_context_manifest(
        tmp_path, source, "/10_POVODNE_ZDROJE_ARCHIVY/ATP/X (99).csv",
        source_sha="0" * 64,
    )
    with pytest.raises(ValueError, match="provenance SHA"):
        normalize(incoming, tmp_path / "invalid-sha", drive_manifest_path=manifest)
    source.unlink()
    archive = incoming / "bbbbbbbbbbbbbbbb__mixed.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        body = io.StringIO()
        writer = csv.DictWriter(body, fieldnames=data)
        writer.writeheader()
        writer.writerow(data)
        handle.writestr("unknown.csv", body.getvalue())
    manifest = _drive_context_manifest(
        tmp_path, archive, "/10_POVODNE_ZDROJE_ARCHIVY/ATP/mixed.zip"
    )
    result = normalize(incoming, tmp_path / "mixed-tour", drive_manifest_path=manifest)
    assert result["counts"].get("normalized_rows", 0) == 0
    assert result["counts"]["reason_tour_missing_or_unsupported"] == 1


def test_sackmann_ids_are_namespaced_and_not_promoted(tmp_path):
    from scripts.link_offline_serve_return import _sackmann_rows, _verified_ids

    raw = sample(winner_id="atp-100", loser_id="atp-200")
    incoming = tmp_path / "raw"
    incoming.mkdir()
    with (incoming / "atp_matches.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw))
        writer.writeheader()
        writer.writerow(raw)
    report = normalize(incoming, tmp_path / "normalized")
    normalized_path = Path(report["normalized"][0]["path"])
    match = list(_sackmann_rows([str(normalized_path)]))[0]
    assert (match.source_player_a_id, match.source_player_b_id) == ("atp-100", "atp-200")
    assert match.source_id_namespace == "drive-unverified"
    assert (match.player_a, match.player_b) == ("Alpha One", "Beta Two")
    # Even a real, independently verified Sackmann crosswalk may NOT bind an
    # unrelated Drive provider namespace merely because the IDs look alike.
    known = {
        ("sackmann", "atp", "atp-100"): "canonical-alpha",
        ("sackmann", "atp", "atp-200"): "canonical-beta",
    }
    assert _verified_ids(match, known) == (None, None)

    # Direct native Sackmann exports retain their own ID namespace and are
    # eligible for the crosswalk after independent SHA-pinned verification.
    native = tmp_path / "atp_matches_2026.csv"
    cols = ["league", "tourney_date", "tourney_name", "winner_name",
            "loser_name", "winner_id", "loser_id", "w_svpt", "w_1stIn",
            "w_1stWon", "w_2ndWon", "l_svpt", "l_1stIn",
            "l_1stWon", "l_2ndWon"]
    with native.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        writer.writerow({
            "league": "atp", "tourney_date": "20261012",
            "tourney_name": "Vienna", "winner_name": "Alpha One",
            "loser_name": "Beta Two", "winner_id": "atp-100",
            "loser_id": "atp-200", "w_svpt": 70, "w_1stIn": 40,
            "w_1stWon": 30, "w_2ndWon": 14, "l_svpt": 60,
            "l_1stIn": 35, "l_1stWon": 25, "l_2ndWon": 11,
        })
    direct = list(_sackmann_rows([str(native)]))[0]
    assert direct.source_id_namespace == "sackmann"
    assert _verified_ids(direct, known) == (("canonical-alpha", "canonical-beta"), None)


@pytest.mark.parametrize(("proof", "eligible"), [
    (["date_exact", "winner", "tournament_exact", "round"], True),
    (["date_tournament_window", "winner", "tournament_exact",
      "round", "surface", "best_of"], True),
    (["date_tournament_window", "winner", "tournament_exact",
      "round", "surface"], False),
    (["date_tournament_window", "winner", "tournament_tokens",
      "round", "surface", "best_of"], False),
    (["date_tournament_window", "winner", "tournament_exact",
      "round", "surface", "best_of", "round_conflict"], False),
    (["date_plusminus_1", "winner", "tournament_exact",
      "round", "surface", "best_of"], False),
])
def test_window_requires_complete_independent_metadata(proof, eligible):
    from scripts.cdb_inbox_stage import _strict_source_evidence

    assert _strict_source_evidence({"evidence": proof}) is eligible
