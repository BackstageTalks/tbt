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

    def test_real_fortuna_match_prefixed_player_aces_label(self):
        result = self.detail(market='Zápas: Michelsen A. počet es')
        self.assertEqual(result['aces_markets'][0]['kind'], 'player_aces_ou')
        self.assertEqual(len(result['aces_markets'][0]['verified_pairs']), 1)

    def test_three_way_more_aces_cannot_be_used_as_two_way_price(self):
        draw = outcome('Remíza', 4.2, 'aces', 'draw')
        result = self.detail(market='Zápas: viac es',
                             a='Michelsen A.', b='Cerundolo J.M.', extra=draw)
        self.assertEqual(result['aces_markets'][0]['kind'], 'most_aces_match')
        self.assertEqual(result['aces_markets'][0]['verified_pairs'], [])

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

    def test_unrendered_client_side_shell_is_source_unavailable(self):
        # A plain HTTP 200 page may have a tennis heading but no fixtures:
        # this MUST NOT be counted as a real scan of missing ace prices.
        html_shell = '<html><a href="/stavkovanie/tenis/atp">ATP</a></html>'
        result = f.collect(date(2026, 11, 10), max_events=2, sleep_seconds=0,
                           now=NOW, get=lambda _: html_shell)
        self.assertEqual(result['status'], 'source_unavailable')
        self.assertEqual(result['candidate_urls'], 0)
        self.assertEqual(result['exact_aces_pairs'], 0)


    def test_round_robin_tournaments_with_first_index_full_of_one_tournament(self):
        a = f.ORIGIN + "/stavkovanie/tenis/atp/m-stockholm/one-two"
        b = f.ORIGIN + "/stavkovanie/tenis/atp/m-stockholm/three-four"
        w = f.ORIGIN + "/stavkovanie/tenis/wta/m-wta-finals/five-six"
        self.assertEqual(f.select_diverse_urls([a, b, w], 2), [a, w])
        self.assertEqual(f.select_diverse_urls([a, b, w], 3), [a, w, b])

    def test_follow_publicly_linked_tournament_category_to_other_matches(self):
        wta = f.ORIGIN + "/stavkovanie/tenis/wta/m-wta-finals"
        atp = f.ORIGIN + "/stavkovanie/tenis/atp/m-atp-stockholm/one-two"
        womens = f.ORIGIN + "/stavkovanie/tenis/wta/m-wta-finals/five-six"
        index = (
            '<a href="/stavkovanie/tenis/atp/m-atp-stockholm/one-two">ATP</a>'
            '<a href="/stavkovanie/tenis/wta/m-wta-finals">WTA draw</a>'
        )
        def get(url):
            if url == f.INDEX:
                return index
            if url == wta:
                return '<a href="/stavkovanie/tenis/wta/m-wta-finals/five-six">WTA</a>'
            if url in (atp, womens):
                return page(market='Počet gemov v zápase')
            raise AssertionError("Unexpected network request: " + url)
        report = f.collect(date(2026, 11, 10), max_events=10, sleep_seconds=0,
                           now=NOW, get=get)
        self.assertEqual(report["candidate_urls"], 2)
        self.assertEqual(report["probed_urls"], 2)
        self.assertEqual(report["candidate_tournaments"], 2)
        self.assertEqual(report["probed_tournaments"], 2)
        self.assertEqual(report["catalog_pages_scanned"], 1)
        self.assertEqual(report["exact_aces_pairs"], 0)

    def test_audit_preserves_public_market_names_without_faking_aces(self):
        row = self.detail(market='Počet gemov v zápase')
        self.assertEqual(row['aces_markets'], [])
        self.assertIn('Počet gemov v zápase', row['market_group_titles_sample'])
        self.assertIn('Víťaz zápasu', row['market_group_titles_sample'])

    def test_out_of_window_public_market_names_are_diagnostics_only(self):
        def get(url):
            return INDEX if url == f.INDEX else page(market='Počet gemov v zápase')
        report = f.collect(date(2026, 11, 11), max_events=3,
                           sleep_seconds=0, now=NOW, get=get)
        self.assertEqual(len(report['events_in_target_window']), 0)
        self.assertEqual(report['out_of_target_window_events'], 1)
        self.assertIn('Počet gemov v zápase',
                      report['market_labels_observed_sample'])
        self.assertEqual(report['prematch_aces_market_diagnostics'], [])
        self.assertEqual(report['exact_aces_pairs'], 0)

    def test_out_of_window_genuine_prematch_aces_are_diagnostic_not_imported(self):
        def get(url):
            return INDEX if url == f.INDEX else page()
        report = f.collect(date(2026, 11, 11), max_events=3,
                           sleep_seconds=0, now=NOW, get=get)
        self.assertEqual(report['exact_aces_pairs'], 0)
        self.assertEqual(len(report['events_in_target_window']), 0)
        groups = report['prematch_aces_market_diagnostics']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['kind'], 'player_aces_ou')
        self.assertEqual(groups[0]['verified_pairs'][0]['line'], 6.5)
        self.assertEqual(groups[0]['verified_pairs'][0]['over'], 1.8)

    def test_verified_out_of_window_quotes_persist_in_full_archival_ledger(self):
        # Evening capture for 11 Nov sees a valid 10 Nov pre-start quote.
        # It must be archived as 10 Nov evidence, never as a 11 Nov pick.
        def get(url):
            return INDEX if url == f.INDEX else page()
        report = f.collect(date(2026, 11, 11), max_events=2,
                           sleep_seconds=0, now=NOW, get=get)
        self.assertEqual(report['exact_aces_pairs'], 0)
        self.assertEqual(report['events_in_target_window'], [])
        self.assertEqual(report['observed_prematch_priced_pairs'], 1)
        self.assertEqual(report['observed_priced_pairs_outside_target'], 1)
        stored = report['observed_prematch_priced_events']
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]['event_betting_day'], '2026-11-10')
        self.assertEqual(stored[0]['captured_at'], NOW.isoformat())
        self.assertEqual(stored[0]['event_id'], 'ufo:mtch:1xl-1gk')
        self.assertEqual(stored[0]['source_url'], URL)
        self.assertEqual(len(stored[0]['source_sha256']), 64)
        self.assertEqual(stored[0]['aces_markets'][0]['verified_pairs'][0]['over'], 1.8)

    def test_target_day_quotes_saved_for_publisher_and_independent_ledger(self):
        def get(url):
            return INDEX if url == f.INDEX else page()
        report = f.collect(date(2026, 11, 10), max_events=2,
                           sleep_seconds=0, now=NOW, get=get)
        self.assertEqual(report['exact_aces_pairs'], 1)
        self.assertEqual(report['observed_prematch_priced_pairs'], 1)
        self.assertEqual(report['observed_priced_pairs_outside_target'], 0)
        self.assertEqual(len(report['events_in_target_window']), 1)
        self.assertEqual(len(report['observed_prematch_priced_events']), 1)

    def test_archive_preserves_all_exact_lines_not_just_diagnostic_first_three(self):
        extra = ''.join(
            outcome(f'- {line}', 1.65, f'aces-{i}', f'under-{i}') +
            outcome(f'+ {line}', 1.90, f'aces-{i}', f'over-{i}')
            for i, line in enumerate((7.5, 8.5, 9.5), 1))
        def get(url):
            return INDEX if url == f.INDEX else page(extra=extra)
        report = f.collect(date(2026, 11, 11), max_events=2,
                           sleep_seconds=0, now=NOW, get=get)
        self.assertEqual(report['observed_prematch_priced_pairs'], 4)
        quoted = report['observed_prematch_priced_events'][0]['aces_markets'][0]
        self.assertEqual(len(quoted['verified_pairs']), 4)
        self.assertEqual([p['line'] for p in quoted['verified_pairs']],
                         [6.5, 7.5, 8.5, 9.5])
        self.assertEqual(len(report['prematch_aces_market_diagnostics'][0]['verified_pairs']), 3)

    def test_no_post_start_quote_or_three_way_market_enter_full_price_archive(self):
        three_way = outcome('Remíza', 3.8, 'aces', 'third')
        def get(url):
            return INDEX if url == f.INDEX else page(
                market='Zápas: viac es', a='Michelsen A.', b='Cerundolo J.M.',
                extra=three_way)
        report = f.collect(date(2026, 11, 11), max_events=2,
                           sleep_seconds=0, now=NOW, get=get)
        self.assertEqual(report['observed_prematch_priced_pairs'], 0)
        self.assertEqual(report['observed_prematch_priced_events'], [])
        def old_get(url):
            return INDEX if url == f.INDEX else page()
        # Now after event start, with a future target day.
        late_now = datetime(2026, 11, 10, 16, tzinfo=timezone.utc)
        report = f.collect(date(2026, 11, 11), max_events=2,
                           sleep_seconds=0, now=late_now, get=old_get)
        self.assertEqual(report['observed_prematch_priced_pairs'], 0)

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
