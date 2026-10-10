"""No DB or network: strict research-only WTA doubles sidecar contract tests."""
from __future__ import annotations

import gzip
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from tbt.data.wta_doubles_rank_history import WTADoublesRankHistory

HEADER = "ranking_date,ranking_type,sackmann_player_id,rank,points\n"
ROWS = [
    f"2026-06-15,doubles,{pid},{rank},{points}\n"
    for pid, rank, points in (("101", 10, 2000), ("102", 20, 1800), ("103", 30, 1600), ("104", 40, 1400))
]


def source(tmp_path: Path, rows=ROWS):
    path = tmp_path / "official.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(HEADER + "".join(rows))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_historical_as_of_and_mapping_gate(tmp_path):
    path, digest = source(tmp_path)
    history = WTADoublesRankHistory.from_csv_gz(path, expected_sha256=digest)
    crosswalk = {f"c{i}": str(100 + i) for i in range(1, 5)}
    f = history.research_features(
        ["c1", "c2"], ["c3", "c4"],
        datetime(2026, 6, 16, tzinfo=timezone.utc),
        canonical_to_sackmann=crosswalk,
    )
    assert f == {
        "wta_doubles_rank_known_four": 1,
        "wta_doubles_rank_advantage": 20,
        "wta_doubles_points_advantage": 400,
    }
    same_day = history.research_features(
        ["c1", "c2"], ["c3", "c4"],
        datetime(2026, 6, 15, tzinfo=timezone.utc),
        canonical_to_sackmann=crosswalk,
    )
    assert same_day["wta_doubles_rank_known_four"] == 0
    assert same_day["wta_doubles_rank_advantage"] is None
    assert history.research_features(
        ["c1", "c2"], ["c3", "unknown"],
        datetime(2026, 6, 16, tzinfo=timezone.utc),
        canonical_to_sackmann=crosswalk,
    )["wta_doubles_rank_known_four"] == 0
    assert history.research_features(
        ["c1", "c1"], ["c3", "c4"],
        datetime(2026, 6, 16, tzinfo=timezone.utc),
        canonical_to_sackmann=crosswalk,
    )["wta_doubles_rank_known_four"] == 0


def test_sha_fails_closed(tmp_path):
    path, _ = source(tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        WTADoublesRankHistory.from_csv_gz(path)


def test_conflicting_snapshots_fail_closed(tmp_path):
    path, digest = source(tmp_path, ROWS + ["2026-06-15,doubles,101,11,2000\n"])
    with pytest.raises(ValueError, match="Conflicting"):
        WTADoublesRankHistory.from_csv_gz(path, expected_sha256=digest)


def test_older_or_other_tour_rejected(tmp_path):
    path, digest = source(tmp_path, ["2026-06-08,doubles,101,10,2000\n"])
    with pytest.raises(ValueError, match="may not replace"):
        WTADoublesRankHistory.from_csv_gz(path, expected_sha256=digest)
    path, digest = source(tmp_path, ["2026-06-15,singles,101,10,2000\n"])
    with pytest.raises(ValueError, match="Non-doubles"):
        WTADoublesRankHistory.from_csv_gz(path, expected_sha256=digest)


def test_reject_timezone_naive(tmp_path):
    path, digest = source(tmp_path)
    history = WTADoublesRankHistory.from_csv_gz(path, expected_sha256=digest)
    with pytest.raises(ValueError, match="timezone"):
        history.latest_prior("101", datetime(2026, 6, 20))
