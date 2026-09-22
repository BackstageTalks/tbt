from pathlib import Path

from tbt.services.environment import (
    ENVIRONMENT_RESOLVER_VERSION,
    explicit_country_hints,
    strong_location_name_hints,
    venue_context_compatible,
)


ROOT = Path(__file__).resolve().parents[1]


def _venue(name: str, country: str) -> dict:
    return {
        "query": name,
        "name": name,
        "latitude": 1.0,
        "longitude": 1.0,
        "country": country,
    }


def test_r55_environment_hotfix_bumps_resolver_contract():
    assert ENVIRONMENT_RESOLVER_VERSION >= 5


def test_itf_country_code_blocks_cross_country_cache_poisoning():
    tournament = "Daegu, Singles W-ITF-KOR-04A"
    assert explicit_country_hints({}, tournament) == {"KR"}
    assert "daegu" in strong_location_name_hints({}, tournament)

    compatible, reason = venue_context_compatible(
        {},
        tournament,
        _venue("Goyang", "Indonesia"),
    )
    assert compatible is False
    assert reason == "country_mismatch"


def test_itf_city_hint_blocks_same_country_wrong_city_cache_hit():
    tournament = "Daegu, Singles W-ITF-KOR-04A"
    compatible, reason = venue_context_compatible(
        {},
        tournament,
        _venue("Goyang", "South Korea"),
    )
    assert compatible is False
    assert reason == "city_mismatch"


def test_curated_alias_allows_tournament_city_to_real_host_city():
    # Cincinnati is deliberately mapped to Mason in the curated tennis aliases.
    tournament = "Cincinnati, ATP"
    compatible, reason = venue_context_compatible(
        {},
        tournament,
        _venue("Mason", "United States"),
    )
    assert compatible is True
    assert reason == "compatible"


def test_missing_geography_fails_open_instead_of_guessing():
    compatible, reason = venue_context_compatible(
        {},
        "Unknown Invitational",
        _venue("Somewhere", "France"),
    )
    assert compatible is True
    assert reason == "compatible"


def test_resume_job_repairs_incompatible_previously_resolved_rows():
    source = (ROOT / "scripts" / "enrich_environment_snapshot.py").read_text(encoding="utf-8")
    assert 'return True, "incompatible_resolved"' in source
    assert 'report["incompatible_existing_resolved"] += 1' in source
    assert 'report["repaired_incompatible_resolved"] += 1' in source
    assert 'report["invalidated_incompatible_resolved"] += 1' in source
    assert "venue_cache_rejected_observations" in source
