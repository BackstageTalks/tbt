from datetime import datetime, timezone

from tbt.services.environment import (
    ENVIRONMENT_SCHEMA_VERSION,
    environment_payload,
    location_candidates,
)


class FakeClient:
    def geocode(self, query):
        return None


def test_known_tournament_aliases_replace_ambiguous_raw_labels():
    candidates = location_candidates({}, 'US Open, Men')
    assert candidates == ['New York, New York, US']
    # Raw tournament names are not geographic queries. Do not spend geocoder
    # requests on them after a high-confidence city alias has been resolved.
    assert 'US Open, Men' not in candidates

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


def test_itf_compact_labels_strip_draw_gender_and_recover_city():
    cases = {
        'ITF M25 Kutaisi Men': 'Kutaisi, GE',
        'ITF M15 Maringa Men': 'Maringá, BR',
        'ITF W15 Hurghada Women': 'Hurghada, EG',
        'ITF M15 Kursumlijska Banja 4 Men': 'Kuršumlijska Banja, RS',
    }
    for label, expected in cases.items():
        candidates = location_candidates({}, label)
        assert candidates[0] == expected, (label, candidates[:4])


def test_itf_provider_country_code_becomes_explicit_country_hint():
    candidates = location_candidates({}, 'Kursumlijska Banja, Singles Qualifying, M-ITF-SRB-01A')
    assert 'Kuršumlijska Banja, RS' == candidates[0]
    candidates = location_candidates({}, 'Tbilisi, Singles, M-ITF-GEO-02A')
    assert 'Tbilisi, GE' in candidates[:3]
