"""Negative-control and true-price tests for the read-only full Results auditor."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_settled_archive_reconciled as audit

ISSUED = '2026-10-10T08:00:00Z'
START = '2026-10-10T14:00:00Z'


def pick(event, section='top_daily', market='match_winner', selection='p1', *,
         odds=1.60, correct=True, issued=ISSUED, **extra):
    pub = dict(section=section, market=market, selection_id=selection,
               issued_at=issued, odds=odds, result={'correct': correct})
    pub.update(extra)
    return {'event_id': event, 'scheduled_at': START, 'tour': 'WTA', 'surface': 'Hard',
            'market_publications': [pub]}


def archive(row):
    row = deepcopy(row)
    row.update(runtime_result_overlay=True, archive_source='verified_match_status_snapshot')
    return row


class FullReconciliationTests(unittest.TestCase):
    def test_archive_overlay_closes_ledger_pending_without_double_count(self):
        ledger = [pick('evt1', correct=None)]
        snap = [archive(pick('evt1', correct=True))]
        report = audit.reconcile(ledger, {'results': [deepcopy(ledger[0])]}, snap)
        self.assertEqual(report['total']['wins'], 1)
        self.assertEqual(report['total']['issued_unique'], 1)
        self.assertEqual(report['total']['priced_settled'], 1)
        self.assertEqual(report['total']['roi_flat_stake'], 0.6)
        self.assertEqual(report['input_counters']['archive_joined_to_ledger'], 1)

    def test_ou_lines_are_not_silently_deduplicated(self):
        a = pick('evt2', section='ace', market='aces', selection='p1',
                 publication_key='O4.5', correct=True)
        b = pick('evt2', section='ace', market='aces', selection='p1',
                 publication_key='U5.5', correct=False)
        report = audit.reconcile([a, b], {'results': []}, [])
        self.assertEqual(report['total']['issued_unique'], 2)
        self.assertEqual(report['total']['distinct_events'], 1)
        self.assertEqual(report['sections']['ace']['wins'], 1)
        self.assertEqual(report['sections']['ace']['losses'], 1)

    def test_conflicting_outcomes_quarantined(self):
        report = audit.reconcile([pick('evt3', correct=True)],
                                 {'results': []}, [archive(pick('evt3', correct=False))])
        self.assertEqual(report['total']['issued_unique'], 0)
        self.assertEqual(report['input_counters']['settlement_conflicts_quarantined'], 1)

    def test_odds_conflict_only_removes_roi(self):
        report = audit.reconcile([pick('evt4', odds=1.6)],
                                 {'results': []}, [archive(pick('evt4', odds=1.7))])
        self.assertEqual(report['total']['wins'], 1)
        self.assertIsNone(report['total']['roi_flat_stake'])
        self.assertEqual(report['input_counters']['odds_conflicts_excluded_from_roi'], 1)

    def test_late_issued_and_missing_issued_are_excluded(self):
        late = pick('late', issued='2026-10-10T15:00:00Z')
        missing = archive(pick('unknown', issued=None))
        report = audit.reconcile([late], {'results': []}, [missing])
        self.assertEqual(report['total']['issued_unique'], 0)
        self.assertEqual(report['input_counters']['missing_immutable_issued_at'], 1)
        self.assertEqual(report['input_counters']['not_verifiably_pre_match'], 1)

    def test_missing_ou_contract_is_quarantined(self):
        report = audit.reconcile([pick('evt5', section='ace', market='aces')],
                                 {'results': []}, [])
        self.assertEqual(report['total']['issued_unique'], 0)
        self.assertEqual(report['input_counters']['invalid_identity_or_ou_contract'], 1)

    def test_archive_without_verified_origin_is_rejected(self):
        report = audit.reconcile([], {'results': []}, [pick('evt6')])
        self.assertEqual(report['total']['issued_unique'], 0)
        self.assertEqual(report['input_counters']['archive_unverified_origin'], 1)

    def test_no_source_mutations_and_cli_produces_report(self):
        ledger = [pick('evt7')]
        feed = {'results': []}
        original = deepcopy(ledger)
        audit.reconcile(ledger, feed, [])
        self.assertEqual(ledger, original)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name, value in [('ledger', ledger), ('feed', feed), ('archive', [])]:
                (folder / f'{name}.json').write_text(json.dumps(value), encoding='utf-8')
            dest = folder / 'report.json'
            p = subprocess.run([sys.executable, str(Path(audit.__file__)),
                '--ledger', str(folder/'ledger.json'), '--feed', str(folder/'feed.json'),
                '--archive', str(folder/'archive.json'), '--out', str(dest)],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            r = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(r['total']['wins'], 1)
            self.assertIn('archive', r['sources']['sha256'])
            self.assertEqual(r['confirmed_strategies'], 0)


if __name__ == '__main__':
    unittest.main()