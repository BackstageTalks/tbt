from datetime import datetime, timezone

from tbt.services.environment import (
    ENVIRONMENT_SCHEMA_VERSION,
    environment_payload,
    location_candidates,
)


class FakeClient:
    def geocode(self, query):
        return None


def test_known_tournament_aliases_are_added_before_ambiguous_raw_labels():
    candidates = location_candidates({}, 'US Open, Men')
    assert candidates[0] == 'New York, New York, US'
    assert 'US Open, Men' in candidates

    candidates = location_candidates({}, 'Kursumlijska Banja, Singles Qualifying, M-ITF-SRB-01A')
    assert candidates[0] == 'Kuršumlijska Banja, RS'


def test_environment_payload_stamps_schema_even_when_unresolved():
    payload = environment_payload(
        FakeClient(), {}, 'Unknown Event', datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    assert payload['schema_version'] == ENVIRONMENT_SCHEMA_VERSION == 2
    assert payload['venue_resolved'] is False
