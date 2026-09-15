from datetime import datetime, timedelta, timezone

import audit_statistics_inventory
from tbt.schemas import MatchRecord


def _m(mid, day, stats):
    return MatchRecord(
        match_id=mid, tour='atp', scheduled_at=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=day),
        player1_id='1', player1_name='A', player2_id='2', player2_name='B', winner_id='1',
        tournament='X', surface='hard', stats=stats,
    )


def test_statistics_inventory_separates_raw_counts_from_es_quality_readiness():
    counts = _m('counts', 0, {'p1_aces':8.0,'p2_aces':4.0,'p1_double_faults':2.0,'p2_double_faults':3.0})
    rates = _m('rates', 1, {
        'p1_service_points_won':0.64,'p1_return_points_won':0.37,
        'p2_service_points_won':0.63,'p2_return_points_won':0.36,
    })
    report = audit_statistics_inventory.build([counts, rates])
    assert report['any_stats_matches'] == 2
    assert report['both_players_quality_ready'] == 1
    assert report['both_players_quality_ready_rate'] == 0.5
    assert report['stat_key_counts']['p1_aces'] == 1
    assert report['interpretation']['raw_stats_are_not_es'] is True
