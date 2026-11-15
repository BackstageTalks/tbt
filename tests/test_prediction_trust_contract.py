from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from test_top_priority_policy import pick, ids
from tbt.services.market_selection import select_market_sections, build_selection_candidate_snapshot
from tbt.services.sports_prediction_audit import sports_prediction_audit
from tbt.services.prediction_quality import coverage


def test_unlimited_top_and_no_forced_fill():
    rows = [pick(str(i), .80-i*.001) for i in range(12)]
    rows.append(pick('weak', .60))
    out = select_market_sections(rows)
    assert len(ids(out)) == 12 and 'weak' not in ids(out)
    assert out['market_selection']['selection_counts']['top_daily_shortfall'] == 0
    assert len(ids(select_market_sections(rows, top_limit=5))) == 5
    assert select_market_sections([pick('weak', .60)])['top_daily_picks'] == []


def test_top_tie_order_does_not_depend_on_odds():
    rows = [pick('a', .8, odds=1.6, other=2.8), pick('b', .8, odds=1.7, other=2.5)]
    before = ids(select_market_sections(rows))
    changed = deepcopy(rows)
    changed[0]['betting']['odds'], changed[1]['betting']['odds'] = 1.7, 1.6
    assert ids(select_market_sections(changed)) == before


def test_sports_audit_without_price_and_no_outcome_leakage():
    now = datetime(2026,9,7,8,tzinfo=timezone.utc)
    a = pick('a', .8)
    a.pop('betting')
    a['result'] = {'correct': True}
    saved = sports_prediction_audit([a], now)[0]
    assert saved['sports_rank'] == 1 and saved['status'] == 'predicted'
    assert 'result' not in saved and 'odds' not in saved
    assert saved['reliability_status'] == 'cohort_validation_required'
    snap = build_selection_candidate_snapshot([a], generated_at=now)
    assert snap['sports_prediction_audit'][0]['sports_rank'] == 1


def test_history_count_is_not_probability_reliability():
    out = select_market_sections([pick('a', .8)])['top_daily_picks'][0]
    assert out['historical_count_depth'] == 1.0
    assert out['probability_reliability'] is None


def test_statistics_evidence_counts_actual_past_rows_only(match_factory):
    match = match_factory('m', 'a', 'b', None, day=10)
    def obs(day, serve, returns):
        return SimpleNamespace(played_at=datetime(2025,1,day,12,tzinfo=timezone.utc),
                               surface='hard', serve_quality=serve, return_quality=returns)
    state = SimpleNamespace(matches=50, surface_matches={'hard':20},
                            recent=[obs(1,.6,.4),obs(2,None,None),obs(10,.8,.6),obs(11,.9,.9)])
    builder = SimpleNamespace(_state=lambda match, side: state)
    result = coverage(builder, match)['player1']['statistics_evidence']
    assert result['overall']['observed_matches'] == 2
    assert result['overall']['paired_serve_return_matches'] == 1
    assert result['overall']['paired_coverage'] == .5
    assert result['future_or_same_time_rows_excluded'] == 2


def test_invalid_and_duplicate_sports_predictions_do_not_gain_rank():
    now = datetime(2026,9,7,8,tzinfo=timezone.utc)
    bad = pick('bad', .8)
    bad['created_at'] = '2026-09-07T09:00:00Z'
    audit = sports_prediction_audit([bad, pick('a', .8), pick('a', .8)], now)
    assert audit[0]['status'] == 'unavailable'
    assert sum('sports_rank' in r for r in audit) == 1


def test_malformed_optional_evidence_is_flagged_without_crashing_daily_audit():
    now = datetime(2026, 9, 7, 8, tzinfo=timezone.utc)
    malformed = pick('bad', .8)
    malformed['player1'] = 'untrusted-invalid-player'
    malformed['quality'] = 'invalid evidence'
    malformed['scheduled_at'] = None
    audit = sports_prediction_audit([malformed, pick('good', .8)], now)
    assert audit[0]['status'] == 'unavailable'
    assert 'invalid_identity' in audit[0]['reasons']
    assert 'missing_prematch_model_evidence' in audit[0]['reasons']
    assert audit[1]['status'] == 'predicted'
    assert audit[1]['sports_rank'] == 1
