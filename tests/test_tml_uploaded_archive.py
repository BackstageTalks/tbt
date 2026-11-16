"""Safety regressions for the owner's uploaded nested TML archive (source-only)."""
from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from scripts.tml_uploaded_archive import (
    expected_sources, source_members, is_approved_member, member_year,
)
from scripts.cdb_inbox_adapter import normalize, _pinned_tml_safety_reason
from scripts.prepare_tml_atp_cdb import complete_winner_score


def _zip(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    return out.getvalue()


def _fixture(*, missing=None, mutate_name=False):
    csv_bytes = (
        "tourney_id,tourney_name,tourney_date,match_num,"
        "winner_id,loser_id,winner_name,loser_name,surface,round,best_of,"
        "score,w_ace,l_ace,w_svpt,l_svpt\n"
        "2016-1049,Auckland,20160104,1,201648,201421,"
        "Naomi Broady,Ana Ivanovic,Hard,R32,3,7-5 6-4,14,4,63,73\n"
    ).encode()
    sources = expected_sources()
    named = {
        ("unexpected.csv" if mutate_name and key == "2016_wta.csv" else key): csv_bytes
        for key in sources if key != missing
    }
    nested = _zip(named)
    outer = _zip({"tml-data.zip": nested, "irrelevant-leaderboard.csv": b"summary"})
    return outer, nested, csv_bytes


def test_exact_only_44_observed_match_sources_and_canonical_tours():
    paths = expected_sources()
    assert len(paths) == 44
    assert len({safe for safe, _, _ in paths.values()}) == 44
    assert paths["2016_wta.csv"] == ("wta-2016.csv", "wta", 2016)
    assert paths["2026_challenger.csv"] == ("atp-challenger-2026.csv", "atp", 2026)
    assert paths["atp_quali/2026_atp_quali.csv"] == ("atp-qualifying-2026.csv", "atp", 2026)
    assert is_approved_member("wta-2016.csv")
    assert member_year("atp-qualifying-2026.csv") == 2026
    assert not is_approved_member("wta-2015.csv")
    assert not is_approved_member("ATP_Database.csv")
    with pytest.raises(ValueError):
        member_year("2026-wta-straight-sets-won.csv")


def test_nested_archive_sha_exact_byte_gate_and_no_leaderboards():
    outer, nested, original = _fixture()
    result = source_members(
        outer,
        expected_outer_sha=hashlib.sha256(outer).hexdigest(),
        expected_nested_sha=hashlib.sha256(nested).hexdigest(),
    )
    assert len(result) == 44
    assert len({name for name, _ in result}) == 44
    assert all(raw == original for _, raw in result)
    assert not any("irrelevant" in name for name, _ in result)
    assert source_members.__defaults__ is None


def test_wrong_outer_and_nested_sha_are_rejected():
    outer, nested, _ = _fixture()
    with pytest.raises(ValueError, match="archive SHA mismatch"):
        source_members(outer, expected_outer_sha="0" * 64,
                       expected_nested_sha=hashlib.sha256(nested).hexdigest())
    with pytest.raises(ValueError, match="Nested TML archive SHA mismatch"):
        source_members(outer, expected_outer_sha=hashlib.sha256(outer).hexdigest(),
                       expected_nested_sha="0" * 64)


def test_missing_or_renamed_source_fails_closed():
    for missing, mutate in [("2016_wta.csv", False), (None, True)]:
        outer, nested, _ = _fixture(missing=missing, mutate_name=mutate)
        with pytest.raises(ValueError, match="Missing pinned TML source years"):
            source_members(outer, expected_outer_sha=hashlib.sha256(outer).hexdigest(),
                           expected_nested_sha=hashlib.sha256(nested).hexdigest())


def test_tml_source_start_not_transformed_into_exact_match_date():
    sample = {
        "tourney_id": "2016-1049", "tourney_name": "Auckland",
        "tourney_date": "20160104", "match_num": "1",
        "winner_id": "201648", "loser_id": "201421",
        "winner_name": "Naomi Broady", "loser_name": "Ana Ivanovic",
        "surface": "Hard", "round": "R32", "best_of": "3",
        "score": "7-5 6-4", "w_ace": "14", "l_ace": "4",
        "w_svpt": "63", "l_svpt": "73",
    }
    row, reason = normalize(sample, "wta-2016.csv", 1)
    assert reason == ""
    assert row["league"] == "wta"
    assert row["source_date_kind"] == "tournament_start"
    assert row["source_winner_id"] == "201648"
    assert row["source_loser_id"] == "201421"
    assert row["winner_name"] == "Naomi Broady"
    assert complete_winner_score(sample["score"], sample["best_of"])
    assert not complete_winner_score("7-5 6-4 RET", "3")
    assert not complete_winner_score("6-3 4-6", "3")


def test_native_quality_rejects_empty_and_conflicting_source():
    assert _pinned_tml_safety_reason({
        "winner_id": "", "loser_id": "2", "score": "6-1 6-2"
    }) == "tml_native_identity_missing_or_equal"
    assert _pinned_tml_safety_reason({
        "winner_id": "1", "loser_id": "2", "score": "RET"
    }) == "tml_noncompleted_or_missing_score"
