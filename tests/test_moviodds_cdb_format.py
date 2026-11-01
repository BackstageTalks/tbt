"""MoviOdds CDB-source archive contract and mismatch safety, no CDB write."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from moviodds_cdb_format import (
    ARCHIVE_FORMAT, _digest, format_cdb_archive, verify_cdb_archive,
)


def record(*, home="Alex De Minaur", away="Carlos Alcaraz",
           league="ATP Paris", fixture="203859194", kickoff="",
           aces_home=4, aces_away=7, percent_home=82):
    payload = {
        "schema": 1, "source": "moviodds", "fixture_id": fixture,
        "home": home, "away": away, "league": league, "status": "finished",
        "finished_at": "2026-10-31T18:31:00+00:00",
        "observed_at": "2026-10-31T18:30:35+00:00",
        "kickoff_utc": kickoff, "final_score": "6-3,6-4",
        "periods": [{"name": "Set 1", "score": "6-3"}, {"name": "Set 2", "score": "6-4"}],
        "stats": {
            "sport": "tennis", "format": "best_of_3", "surface": "Hard",
            "updated_at": "2026-10-31T18:30:35Z",
            "home": {"aces": aces_home, "double_faults": 3,
                     "first_serve_win_pct": percent_home,
                     "break_point_conversion_pct": 40, "sets": [6, 6]},
            "away": {"aces": aces_away, "double_faults": 1,
                     "first_serve_win_pct": 70,
                     "break_point_conversion_pct": 55, "sets": [3, 4]},
        },
    }
    return {"payload": payload, "sha256": _digest(payload)}


def archive(*rows):
    return {"schema": 1, "source": "moviodds", "verified": True,
            "days": ["2026-10-31"], "count": len(rows), "records": list(rows)}


def test_source_cdb_counts_preserve_raw_and_do_not_forge_canonical_match():
    source = record()
    converted = format_cdb_archive(archive(source))
    assert converted["schema"] == 2
    assert converted["format"] == ARCHIVE_FORMAT
    assert converted["count"] == 1
    assert converted["cdb_import_ready"] is False
    assert converted["cdb_write_performed"] is False
    assert converted["records"][0]["payload"] == source["payload"]
    assert converted["records"][0]["sha256"] == source["sha256"]
    c = converted["records"][0]["cdb_candidate"]
    assert c["source_fixture_id"] == "203859194"
    assert c["source_side_counts"] == {
        "home": {"aces": 4, "double_faults": 3},
        "away": {"aces": 7, "double_faults": 1},
    }
    assert c["match"]["tour_hint"] == "atp"
    assert c["match"]["event_type"] == "singles_unconfirmed"
    assert c["match"]["scheduled_at_utc"] is None
    assert c["match"]["finished_at_utc"] == "2026-10-31T18:31:00+00:00"
    assert c["cdb_link"]["match_id"] is None
    assert c["cdb_link"]["incoming_stats"] is None
    assert c["cdb_link"]["import_ready"] is False
    assert "kickoff_utc_missing" in c["cdb_link"]["review_reasons"]
    assert converted["summary"]["source_atp_wta_singles"] == 1
    assert converted["summary"]["cdb_imported"] == 0
    verify_cdb_archive(converted)
    assert format_cdb_archive(archive(source)) == converted


def test_source_percentages_not_automatically_mapped_as_cdb_fractions():
    c = format_cdb_archive(archive(record(percent_home=82)))["records"][0]["cdb_candidate"]
    assert c["unmapped_source_percentages"]["home"] == {
        "first_serve_win_pct": 82.0,
        "break_point_conversion_pct": 40.0,
    }
    assert "first_serve_win" not in c["source_side_counts"]["home"]
    assert c["cdb_link"]["incoming_stats"] is None
    assert c["cdb_link"]["canonical_player1_id"] is None


def test_doubles_and_non_primary_tour_are_not_promoted():
    source = record(home="Team One/Team Two", away="Team Three/Team Four",
                    league="WTA Tokyo WD")
    other = record(league="UTR Pro Knoxville", fixture="203859195")
    out = format_cdb_archive(archive(source, other))
    c1, c2 = [r["cdb_candidate"] for r in out["records"]]
    assert "doubles_not_in_scope" in c1["cdb_link"]["review_reasons"]
    assert c1["match"]["event_type"] == "doubles"
    assert "canonical_tour_unconfirmed" in c2["cdb_link"]["review_reasons"]
    assert c2["match"]["tour_hint"] is None
    assert out["summary"]["doubles_excluded"] == 1
    assert out["summary"]["other_tour_review"] == 1
    assert out["summary"]["source_atp_wta_singles"] == 0
    verify_cdb_archive(out)


def test_raw_tamper_and_candidate_tamper_fail_closed():
    source = record()
    bad_source = json.loads(json.dumps(source))
    bad_source["payload"]["stats"]["home"]["aces"] = 50
    with pytest.raises(ValueError, match="checksum mismatch"):
        format_cdb_archive(archive(bad_source))
    converted = format_cdb_archive(archive(source))
    converted["records"][0]["cdb_candidate"]["source_side_counts"]["home"]["aces"] = 5
    with pytest.raises(ValueError, match="changed or does not match"):
        verify_cdb_archive(converted)


@pytest.mark.parametrize("override", [
    {"status": "live"}, {"fixture_id": "dangerous ID"},
    {"finished_at": ""}, {"final_score": ""},
    {"stats": {"sport": "tennis", "home": {"aces": -1}, "away": {}}},
])
def test_bad_source_row_rejected_before_upload(override):
    r = record()
    r["payload"].update(override)
    r["sha256"] = _digest(r["payload"])
    with pytest.raises(ValueError):
        format_cdb_archive(archive(r))


def test_duplicate_provider_id_rejected_even_with_different_names():
    a = record()
    b = record(home="Someone Else", away="Someone Other")
    with pytest.raises(ValueError, match="Duplicate provider fixture"):
        format_cdb_archive(archive(a, b))


def test_archive_does_not_depend_on_source_candidate_identity_guess():
    # Source kickoff can be populated later. Date is not guessed from
    # finished_at, and no p1/p2 orientations are assigned.
    r = record(kickoff="2026-10-31T16:00:00Z")
    c = format_cdb_archive(archive(r))["records"][0]["cdb_candidate"]
    assert c["match"]["scheduled_at_utc"] == "2026-10-31T16:00:00Z"
    assert "kickoff_utc_missing" not in c["cdb_link"]["review_reasons"]
    assert c["cdb_link"]["import_ready"] is False
    assert c["cdb_link"]["match_id"] is None


def test_cdb_format_rejects_false_empty_verification():
    # A source scan receipt is required by the API export before this stage.
    # Conversion cannot promote a source without its verified=true flag.
    with pytest.raises(ValueError, match="not independently verified"):
        format_cdb_archive({
            "schema": 1, "source": "moviodds", "verified": False,
            "days": ["2026-10-31"], "count": 0, "records": [],
        })
