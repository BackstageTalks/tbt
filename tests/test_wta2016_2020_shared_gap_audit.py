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


class _MatchCohort:
    def __init__(self, count):
        self.count = count

    def __len__(self):
        return self.count


def _full_manifest(count=994101):
    return {"years": {str(year): {"rows": count if year == 2020 else 0}
                       for year in range(1943, 2021)}}


def _identity_safety(input_rows=994101, output_rows=994101, quarantine=0, merged=0):
    return {"input_rows": input_rows, "output_rows": output_rows,
            "rows_after_proven_merges": input_rows - merged,
            "merged_rows_removed": merged, "quarantined_rows": quarantine,
            "affected_years": []}


def test_verified_manifest_and_safe_canonical_pass():
    result = a.verify_full_canonical_identity(
        _MatchCohort(994101), _identity_safety(), _full_manifest())
    assert result["manifest_expected_rows"] == 994101
    assert result["manifest_partition_count"] == 78
    assert result["quarantined_rows"] == 0


def test_reject_truncated_raw_snapshot_even_without_identity_collision():
    with pytest.raises(ValueError, match="manifest vs loaded"):
        a.verify_full_canonical_identity(
            _MatchCohort(994100), _identity_safety(input_rows=994100, output_rows=994100),
            _full_manifest())


def test_reject_identity_quarantine_with_exact_manifest_count():
    with pytest.raises(ValueError, match="identity unsafe"):
        a.verify_full_canonical_identity(
            _MatchCohort(994099),
            _identity_safety(output_rows=994099, quarantine=2),
            _full_manifest())


def test_reject_missing_manifest_rows_or_partition():
    short = _full_manifest()
    short["years"].pop("1943")
    with pytest.raises(ValueError, match="year inventory"):
        a.verify_full_canonical_identity(_MatchCohort(994101), _identity_safety(), short)
    invalid = _full_manifest()
    invalid["years"]["2020"].pop("rows")
    with pytest.raises(ValueError, match="missing row counts"):
        a.verify_full_canonical_identity(_MatchCohort(994101), _identity_safety(), invalid)
