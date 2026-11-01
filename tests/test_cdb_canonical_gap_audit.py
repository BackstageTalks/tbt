"""Coverage audit must never export match identities, values or inferred fills."""
from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest

from scripts.cdb_canonical_gap_audit import FIELDS, coverage


def _match(mid, year, tour, stats):
    return SimpleNamespace(
        match_id=mid, tour=tour,
        scheduled_at=datetime(year, 6, 2, tzinfo=timezone.utc),
        stats=stats,
    )


def test_aggregate_only_tracks_exact_missing_cells():
    rows = [
        _match("secret-one", 2018, "wta", {
            "p1_service_points_won": 0.4, "p2_service_points_won": 0.5,
            "p1_return_points_won": 0.2, "p2_return_points_won": 0.3,
            "p1_aces": 0, "p2_aces": None,
        }),
        _match("secret-two", 2018, "wta", {}),
        _match("private-atp", 2020, "atp", {
            "p1_service_points_won": 0.8,
        }),
    ]
    result = coverage(rows)
    assert result["canonical_rows"] == 3
    assert result["production_mutated"] is False
    assert result["api_requests"] == 0
    wta = next(x for x in result["year_tour"] if x["tour"] == "wta")
    assert wta["matches"] == 2
    assert wta["core_complete_matches"] == 1
    assert wta["core_fully_missing_matches"] == 1
    assert wta["fields"]["aces"]["present_cells"] == 1
    assert wta["fields"]["aces"]["missing_cells"] == 3
    assert wta["fields"]["aces"]["both_missing_matches"] == 1
    assert len(wta["fields"]) == len(FIELDS)
    dump = json.dumps(result)
    for forbidden in ("secret-one", "secret-two", "private-atp", "0.8", "0.4"):
        assert forbidden not in dump


def test_fail_closed_on_duplicate_id_and_bad_data():
    with pytest.raises(ValueError, match="duplicate"):
        coverage([_match("x", 2020, "atp", {}), _match("x", 2021, "atp", {})])
    with pytest.raises(ValueError, match="stats"):
        coverage([_match("x", 2020, "atp", ["bad"])])
    with pytest.raises(ValueError, match="year or tour"):
        coverage([_match("x", 2011, "wta", {})])


def _mock_identity_snapshot(monkeypatch, *, safe_rows, quarantine_count=6, malformed=False):
    """Synthetic only: raw rows are never exported by the census."""
    import tbt.data.history_snapshot as snap
    import tbt.data.history_safety as safety_module
    raw_rows = list(safe_rows) + [
        _match(f"opaque-collision-{n}", 2026, "atp", {}) for n in range(quarantine_count)
    ]
    safety = {
        "input_rows": len(raw_rows),
        "output_rows": len(safe_rows),
        "quarantined_rows": quarantine_count,
        "merged_rows_removed": 0,
        "duplicate_match_ids": [],
        "duplicate_provider_event_ids": ["opaque-provider"],
        "quarantine": [
            {"reason": "other_conflict" if malformed else "ambiguous_duplicate_identity",
             "provider_event_id": "opaque-provider",
             "match_id": f"opaque-collision-{n}"}
            for n in range(quarantine_count)
        ],
        "changed": True,
        "affected_years": [2026],
    }
    monkeypatch.setattr(snap, "load_partitions", lambda _: raw_rows)
    monkeypatch.setattr(safety_module, "sanitize_history_identities", lambda rows: (safe_rows, safety))


def test_pinned_six_collisions_aggregate_only_no_cdb_writes(tmp_path, monkeypatch):
    from scripts.cdb_canonical_gap_audit import run

    safe_rows = [_match("private-safe-a", 2025, "wta", {}),
                 _match("private-safe-b", 2024, "atp", {})]
    _mock_identity_snapshot(monkeypatch, safe_rows=safe_rows)
    path = tmp_path / "aggregate.json"
    result = run(tmp_path, path, expected_provider_quarantine=6)
    assert result["canonical_rows"] == 2
    assert result["canonical_raw_rows"] == 8
    assert result["excluded_ambiguous_provider_rows"] == 6
    assert sum(row["matches"] for row in result["year_tour"]) == 2
    assert not result["production_mutated"] and result["api_requests"] == 0
    payload = path.read_text()
    assert "opaque-collision" not in payload and "private-safe" not in payload
    assert json.loads(payload) == result


@pytest.mark.parametrize("expected,malformed", [(0,False), (5,False), (7,False), (6,True)])
def test_readonly_census_rejects_changed_quarantine(tmp_path, monkeypatch, expected, malformed):
    from scripts.cdb_canonical_gap_audit import run

    _mock_identity_snapshot(monkeypatch, safe_rows=[_match("safe", 2024, "wta", {})],
                            malformed=malformed)
    path = tmp_path / "aggregate.json"
    with pytest.raises(ValueError, match="quarantine"):
        run(tmp_path, path, expected_provider_quarantine=expected)
    assert not path.exists()


def test_readonly_census_rejects_disappeared_expected_quarantine(tmp_path, monkeypatch):
    from scripts.cdb_canonical_gap_audit import run
    import tbt.data.history_snapshot as snap
    import tbt.data.history_safety as safety_module

    safe = [_match("safe", 2024, "wta", {})]
    monkeypatch.setattr(snap, "load_partitions", lambda _: safe)
    monkeypatch.setattr(safety_module, "sanitize_history_identities", lambda _: (
        safe, {"quarantined_rows": 0, "changed": False}))
    path = tmp_path / "aggregate.json"
    with pytest.raises(ValueError, match="disappeared"):
        run(tmp_path, path, expected_provider_quarantine=6)
    assert not path.exists()
