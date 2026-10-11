"""2016-2020 read-only stage never proposes half-complete ranking overwrites."""
from copy import deepcopy

import pytest
import audit_wta_2016_2020_shared_gap_audit as a


def test_two_null_stage_filter_discards_partial_existing_rank():
    good={"add_only_null_fields":{"player1_rank":7,"player2_rank":9},
          "expected_player1_rank":None,"expected_player2_rank":None}
    partial={"add_only_null_fields":{"player2_rank":9},
             "expected_player1_rank":7,"expected_player2_rank":None}
    report={"counts":{"candidate_matches":2,"candidate_rank_cells":3},
            "quarantined":{}}
    eligible=a.two_null_only(report,[deepcopy(good),deepcopy(partial)])
    assert eligible==[good]
    assert report["counts"]["candidate_matches"]==1
    assert report["counts"]["candidate_rank_cells"]==2
    assert report["counts"]["unfiltered_audit_candidate_matches"]==2
    assert report["quarantined"]["partial_null_not_stageable_by_strict_writer"]==1
    assert a.YEARS==(2016,2017,2018,2019,2020)


class _FakeVerifiedRelease:
    def __init__(self, failures):
        self.failures = failures
        self.attempts = 0

    def download(self, *, require_bundle_manifest):
        assert require_bundle_manifest is True
        self.attempts += 1
        if self.attempts <= len(self.failures):
            raise RuntimeError(self.failures[self.attempts - 1])
        return ["all-partitions-sha-verified"]


def test_snapshot_partition_race_retries_complete_verification_once():
    store = _FakeVerifiedRelease(["Release bundle checksum mismatch for history-2026.parquet"])
    assert a.download_consistent_history(store) == ["all-partitions-sha-verified"]
    assert store.attempts == 2


def test_snapshot_partition_race_still_fails_closed_if_persistent():
    store = _FakeVerifiedRelease(["Release bundle checksum mismatch for history-2026.parquet"] * 2)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        a.download_consistent_history(store)
    assert store.attempts == 2


@pytest.mark.parametrize("error", [
    "Release bundle checksum mismatch for history_manifest.json",
    "Required assets lack checksum coverage: history-2026.parquet",
    "Release bundle checksum mismatch for history-2026.parquet.untrusted",
])
def test_snapshot_other_integrity_failures_are_never_retried(error):
    store = _FakeVerifiedRelease([error])
    with pytest.raises(RuntimeError, match="checksum|coverage"):
        a.download_consistent_history(store)
    assert store.attempts == 1
