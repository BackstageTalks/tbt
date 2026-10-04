from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_training_leakage as leakage


def test_leakage_audit_detects_unverified_rank_even_if_stripping_report_claims_success(monkeypatch, match_factory):
    match = match_factory('rank-leak', 'A', 'B', 'A')
    match.player1_rank = 10
    match.player2_rank = 20
    monkeypatch.setattr(leakage, 'load_partitions', lambda directory: [match])
    monkeypatch.setattr(leakage, '_enforce_rank_provenance', lambda rows: (rows, {'stripped_values': 2}))
    report = leakage.audit(Path('unused'))
    assert report['status'] == 'fail'
    assert 'unverified_historical_ranks_stripped_before_features' in report['failed_checks']
    assert report['retained_unverified_rank_match_ids'] == ['rank-leak']


def test_leakage_audit_passes_after_unverified_ranks_are_actually_removed(monkeypatch, match_factory):
    match = match_factory('rank-clean', 'A', 'B', 'A')
    match.player1_rank = 10
    match.player2_rank = 20
    monkeypatch.setattr(leakage, 'load_partitions', lambda directory: [match])
    report = leakage.audit(Path('unused'))
    assert report['status'] == 'pass'
    assert report['rank_provenance']['stripped_values'] == 2
    assert report['retained_unverified_rank_match_ids'] == []
