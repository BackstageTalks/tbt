from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/nightly-data-maintenance.yml").read_text(encoding="utf-8")


def test_nightly_maintenance_is_zero_tennisapi_and_bratislava_dst_safe():
    assert "RAPIDAPI_KEY" not in WORKFLOW
    assert "RapidTennis" not in WORKFLOW
    assert "Europe/Bratislava" in WORKFLOW
    assert "30 22 * * *" in WORKFLOW
    assert "30 23 * * *" in WORKFLOW
    assert "offset_hours" in WORKFLOW
    assert "time(4, 0)" in WORKFLOW
    assert "time(5, 0)" in WORKFLOW


def test_nightly_maintenance_prefers_offline_cache_then_positive_geocoding():
    assert "--cache-only" in WORKFLOW
    assert "--unique-geocode" in WORKFLOW
    assert "--static-only" in WORKFLOW
    assert "--complete-static" in WORKFLOW
    assert "--yield-guard-after-requests 200" in WORKFLOW
    assert "--min-geocoder-success-rate 0.005" in WORKFLOW
    assert "open_meteo_max_requests" in WORKFLOW
    assert 'default: "1200"' in WORKFLOW


def test_nightly_maintenance_rebuilds_derived_quality_reports():
    for script in (
        "audit_environment_release.py",
        "audit_statistics_inventory.py",
        "audit_feature_v3_coverage.py",
        "build_player_master.py",
        "build_tournament_venue_master.py",
        "build_production_training_table.py",
        "audit_training_leakage.py",
        "build_production_readiness_report.py",
    ):
        assert script in WORKFLOW
    assert "audit/nightly-data-maintenance-latest.json" in WORKFLOW
    assert "derived/nightly/player_master.json" in WORKFLOW
    assert "group: tbt-history-data-writer" in WORKFLOW
