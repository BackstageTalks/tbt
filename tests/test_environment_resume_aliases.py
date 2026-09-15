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


def test_major_unresolved_tournament_hubs_get_canonical_city_aliases():
    cases = {
        'Miami': 'Miami, Florida, US',
        'Indian Wells, USA': 'Indian Wells, California, US',
        'US Open, Women': 'New York, New York, US',
        'Wimbledon, Men': 'London, England, GB',
        'Cincinnati': 'Mason, Ohio, US',
        'Iasi, Romania': 'Iași, RO',
        'Dubai': 'Dubai, AE',
        'Toronto, Canada': 'Toronto, Ontario, CA',
        'Shanghai, China': 'Shanghai, CN',
        'Bogota, Colombia': 'Bogotá, CO',
        'Nottingham, Great Britain': 'Nottingham, England, GB',
    }
    for label, expected in cases.items():
        candidates = location_candidates({}, label)
        assert candidates[0] == expected, (label, candidates[:3])


def test_itf_draw_suffixes_do_not_hide_known_city_alias():
    candidates = location_candidates({}, 'Kursumlijska Banja, Singles Qualifying, M-ITF-SRB-01A')
    assert candidates[0] == 'Kuršumlijska Banja, RS'
    candidates = location_candidates({}, 'Bogota, Women, W-ITF-COL-03A')
    assert candidates[0] == 'Bogotá, CO'
