"""Offline regression suite for the isolated SK/CZ evening odds research collector."""
import html
import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import skcz_evening_fortuna as f

INDEX = '<a href="/stavkovanie/tenis/atp/tournament/first-second">event</a>'
URL = f.ORIGIN + '/stavkovanie/tenis/atp/tournament/first-second'
NOW = datetime(2026, 11, 9, 17, tzinfo=timezone.utc)


def outcome(selection, odds, market, key, state='OPEN'):
    obj = {'longName': selection, 'odds': odds, 'displayType': state,
           'marketId': market, 'id': key}
    return '<button data-outcome="' + html.escape(json.dumps(obj), quote=True) + '"></button>'


def page(market='Michelsen A.: počet es', a='- 6.5', b='+ 6.5', extra='',
         scheduled='10. 11. 2026 13:00'):
    return (
        '<div data-testing-selector="DetailPage" data-id="ufo:mtch:1xl-1gk">'
        '<span class="participants-panel__participant-label">Michelsen A.</span>'
        '<span class="participants-panel__participant-label">Cerundolo J.M.</span>'
        '<div data-testing-selector="PrematchStartDateTime"><span>17:00:00</span><span>'
        + scheduled + '</span></div>'
        '<div data-testing-selector="MatchDetailCard" aria-label="Víťaz zápasu">'
        + outcome('Michelsen A.', 1.31, 'winner', 'w1')
        + outcome('Cerundolo J.M.', 3.40, 'winner', 'w2')
        + '</div><div data-testing-selector="MatchDetailCard" aria-label="' + market + '">'
        + outcome(a, 1.90, 'aces', 'o1')
        + outcome(b, 1.80, 'aces', 'o2') + extra + '</div>'
    )


class EveningFortunaTests(unittest.TestCase):
    def detail(self, **kwargs):
        return f.parse_detail(page(**kwargs), URL, NOW)

    def test_exact_player_aces_line_and_price(self):
        result = self.detail()
        self.assertEqual(result['event_id'], 'ufo:mtch:1xl-1gk')
        self.assertEqual(result['market_groups_seen'], 2)
        self.assertEqual(result['aces_markets'][0]['verified_pairs'], [
            {'market_id': 'aces', 'player': 'Michelsen A.', 'line': 6.5,
             'over': 1.8, 'under': 1.9}
        ])

    def test_reject_wrong_line_or_three_way_selection(self):
        self.assertEqual(self.detail(b='+ 7.5')['aces_markets'][0]['verified_pairs'], [])
        third = outcome('draw', 3.0, 'aces', 'o3')
        self.assertEqual(self.detail(extra=third)['aces_markets'][0]['verified_pairs'], [])

    def test_more_aces_only_exact_match_pair(self):
        result = self.detail(market='Viac es v zápase',
                             a='Michelsen A.', b='Cerundolo J.M.')
        pairs = result['aces_markets'][0]['verified_pairs']
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]['settlement'], 'bookmaker_rules_not_yet_verified')

    def test_no_set_quote_used_for_full_match(self):
        result = self.detail(market='1. set: Viac es',
                             a='Michelsen A.', b='Cerundolo J.M.')
        self.assertEqual(result['aces_markets'][0]['kind'], 'aces_set_other')
        self.assertEqual(result['aces_markets'][0]['verified_pairs'], [])

    def test_reject_missing_bookmaker_event_date(self):
        with self.assertRaises(ValueError):
            self.detail(scheduled='13:00')

    def test_target_day_and_empty_aces_not_a_positive_quote(self):
        def get(url):
            return INDEX if url == f.INDEX else page(market='Počet gemov v zápase')
        data = f.collect(date(2026, 11, 10), max_events=2, sleep_seconds=0,
                         now=NOW, get=get)
        self.assertEqual(data['status'], 'no_exact_aces_market_available')
        self.assertEqual(data['probed_urls'], 1)
        self.assertEqual(data['exact_aces_pairs'], 0)
        self.assertEqual(len(data['events_in_target_window']), 1)
        self.assertEqual(data['cdb_writes'], 0)
        self.assertEqual(data['published_picks_changed'], 0)

    def test_refuse_stale_evening(self):
        with self.assertRaises(ValueError):
            f.collect(date(2026, 11, 8), now=NOW, get=lambda _: INDEX)

    def test_blocked_detail_page_is_not_a_quote(self):
        def get(url):
            if url == f.INDEX:
                return INDEX
            raise RuntimeError('blocked')
        result = f.collect(date(2026, 11, 10), max_events=2, sleep_seconds=0,
                           now=NOW, get=get)
        self.assertEqual(result['status'], 'source_unavailable')
        self.assertEqual(result['exact_aces_pairs'], 0)


if __name__ == '__main__':
    unittest.main()
