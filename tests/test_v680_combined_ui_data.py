from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd

import build_player_master
import build_production_readiness_report
import build_production_training_table
import build_tournament_venue_master
from tbt.schemas import MatchRecord
from tbt.services.countries import normalize_country_code

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'web/index.html').read_text(encoding='utf-8')
APP = (ROOT / 'web/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web/redesign-680.css').read_text(encoding='utf-8')
UI = json.loads((ROOT / 'web/ui-config.json').read_text(encoding='utf-8'))
WORKFLOW = (ROOT / '.github/workflows/data.yml').read_text(encoding='utf-8')


def _match(mid: str, ts: datetime, country: str = 'GER', *, name='Player A', rank=120):
    return MatchRecord(
        match_id=mid, tour='atp', scheduled_at=ts,
        player1_id='11', player1_name=name, player1_rank=rank,
        player2_id='22', player2_name='Player B', player2_rank=90,
        winner_id='11', tournament='Test Open', tournament_id='77',
        tournament_level='ATP 250', surface='hard', indoor=False,
        provider_payload={
            'homeTeam': {'id': '11', 'name': name, 'country': {'alpha3': country}},
            'awayTeam': {'id': '22', 'name': 'Player B', 'country': {'alpha3': 'USA'}},
            'tournament': {'id': '77', 'name': 'Test Open', 'city': 'Berlin', 'country': {'alpha3': 'GER'}},
        },
    )


def test_v680_reference_layout_is_active_and_uses_player_hero():
    assert f"/redesign-680.css?v={UI['asset_revision']}" in INDEX
    assert UI['revision'] == UI['ui_revision'] == '6.8.5'
    assert UI['asset_revision'] == '6850'
    hero = UI['elements']['HERO_BANNER_1']['content']
    assert hero['image_url'] == '/assets/hero-player-v680.webp'
    assert (ROOT / 'web/assets/hero-player-v680.webp').is_file()
    assert '1900px' in CSS
    assert 'grid-template-columns:minmax(0,1fr) 330px!important' in CSS
    assert 'overflow-x:hidden!important' in CSS
    assert 'color:#f7faf9!important' in CSS


def test_v680_right_rail_uses_native_four_banner_carousel_and_inline_match_detail():
    assert 'function railPromoItems()' in APP
    assert "elementList('sidebar_promo','sidebar').slice(0,4)" in APP
    assert 'class="rail-native-carousel"' in APP
    assert 'data-rail-promo-dot' in APP
    assert 'selectMatchInRail(current,state.dailyHubTab)' in APP
    assert 'renderSidebarMatchDetail' in APP
    assert 'renderMotivationPanel(row)' in APP
    assert 'SIDEBAR_PROMO_4' in (ROOT / 'web/ui-config.json').read_text(encoding='utf-8')


def test_v680_sidebar_hidden_state_really_replaces_highlight_with_match_detail():
    # A previous CSS rule used display:grid!important and overrode HTML [hidden],
    # causing the detail to append below the highlight instead of replacing it.
    assert 'body#blinqPremium #dashboardSidebarDefault[hidden]' in CSS
    assert 'body#blinqPremium #dashboardSidebarMatch[hidden]{display:none!important}' in CSS
    assert 'defaultPanel.hidden=true' in APP
    assert 'matchPanel.hidden=false' in APP
    assert 'matchPanel.hidden=true' in APP
    assert 'defaultPanel.hidden=false' in APP


def test_country_normalization_covers_common_tennis_provider_aliases():
    expected = {'GER':'DE','NED':'NL','SUI':'CH','GRE':'GR','RSA':'ZA','POR':'PT','CRO':'HR','SLO':'SI','ROM':'RO','URU':'UY'}
    assert {key: normalize_country_code(key) for key in expected} == expected


def test_player_master_uses_history_country_consensus_then_profile_override():
    matches = [
        _match('m1', datetime(2025,1,1,tzinfo=timezone.utc), 'GER', name='A. Player', rank=130),
        _match('m2', datetime(2025,2,1,tzinfo=timezone.utc), 'GER', name='Player A', rank=120),
    ]
    rows, report = build_player_master.build(matches)
    p = next(row for row in rows if row['player_id'] == '11')
    assert p['country_code'] == 'DE' and p['country_source'] == 'history_consensus'
    assert p['latest_rank'] == 120 and p['rank_source'] == 'history_latest_observed'
    assert p['alias_count'] >= 1
    assert report['by_tour']['atp']['country_coverage'] == 1.0

    rows, report = build_player_master.build(matches, {('atp','11'):{'id':'11','tour':'atp','country_code':'CH','rank':88,'name':'Player A'}}, {})
    p = next(row for row in rows if row['player_id'] == '11')
    assert p['country_code'] == 'CH' and p['country_source'] == 'profile'
    assert p['latest_rank'] == 88 and p['rank_source'] == 'profile'


def test_tournament_master_reports_identity_conflicts_without_auto_merging():
    one = _match('m1', datetime(2025,1,1,tzinfo=timezone.utc), 'GER')
    two = _match('m2', datetime(2025,1,2,tzinfo=timezone.utc), 'GER')
    two.tournament_id = '88'
    two.provider_payload['tournament']['id'] = '88'
    tournaments, _, report = build_tournament_venue_master.build([one, two])
    assert len(tournaments) == 2
    diag = report['identity_diagnostics']
    assert diag['policy'] == 'report_only_never_auto_merge'
    assert diag['potential_duplicate_signature_groups'] == 1


def test_training_report_has_segmented_es_and_static_env_coverage_and_blocks_weather():
    frame = pd.DataFrame({
        'scheduled_at': pd.to_datetime(['2025-01-01T12:00:00Z','2025-01-02T12:00:00Z']),
        'tour':['atp','wta'], 'year':['2025','2025'], 'surface':['hard','clay'],
        'stats_known_both':[1.0,0.0], 'environment_known':[1.0,1.0],
        'travel_known':[1.0,0.0], 'altitude_change_known':[1.0,1.0],
        'indoor_known':[1.0,1.0], 'weather_known':[1.0,1.0],
        **{name:[0.0,0.0] for name in build_production_training_table.FEATURE_NAMES if name not in {'stats_known_both','environment_known','travel_known','altitude_change_known','weather_known'}},
    })
    report = build_production_training_table.build_report(frame, {}, {})
    assert report['coverage']['by_tour']['atp']['stats_known_both_rate'] == 1.0
    assert report['candidate_feature_groups']['static_environment']['eligible_for_candidate'] is True
    assert report['candidate_feature_groups']['event_statistics']['eligible_for_candidate'] is False
    assert report['candidate_feature_groups']['event_statistics']['has_observations'] is True
    assert report['candidate_feature_groups']['event_statistics']['min_coverage'] == 0.70
    assert report['candidate_feature_groups']['historical_weather']['eligible_for_candidate'] is False


def test_preflight_builds_combined_readiness_report_and_uploads_it():
    assert 'scripts/build_production_readiness_report.py' in WORKFLOW
    assert 'readiness_report.json' in WORKFLOW and 'readiness_report.md' in WORKFLOW
    report = build_production_readiness_report.build(
        {'players':10,'country_coverage':1.0,'latest_rank_coverage':1.0,'duplicate_name_groups':0},
        {'tournaments':2,'venues':2,'tournament_coverage':{'country':1.0,'city':1.0},'venue_coverage':{'coordinates':1.0,'elevation':1.0,'timezone':1.0},'identity_diagnostics':{}},
        {'rows':100,'event_statistics':{'stats_known_both_rate':0.9},'static_environment':{'venue_environment_known_rate':0.9}},
        {'status':'pass'},
    )
    assert report['status'] == 'ready'
    assert report['candidate_training']['historical_weather'] is False


def test_data_finalize_resolved_venue_backfills_geo_into_masters_when_provider_location_missing():
    m = _match('geo', datetime(2025,3,1,tzinfo=timezone.utc), 'GER')
    # Simulate compact history where provider tournament geography was absent but
    # the point-in-time environment resolver stored a validated locality.
    m.provider_payload = {
        'tournament': {'id':'77','name':'Test Open'},
        '_tbt_environment': {
            'venue_resolved': True,
            'venue': {
                'name':'Berlin','country':'Germany','latitude':52.52,'longitude':13.405,
                'elevation_m':34.0,'timezone':'Europe/Berlin',
            },
        },
    }
    tournaments, venues, report = build_tournament_venue_master.build([m])
    assert tournaments[0]['country_code'] == 'DE'
    assert tournaments[0]['city'] == 'Berlin'
    assert venues[0]['country_code'] == 'DE'
    assert venues[0]['city'] == 'Berlin'
    assert report['match_weighted_coverage']['country'] == 1.0
    assert report['match_weighted_coverage']['coordinates'] == 1.0


def test_data_finalize_training_does_not_claim_es_ready_when_quality_coverage_is_zero():
    frame = pd.DataFrame({
        'scheduled_at': pd.to_datetime(['2025-01-01T12:00:00Z']),
        'tour':['atp'], 'year':['2025'], 'surface':['hard'],
        'stats_known_both':[0.0], 'environment_known':[1.0],
        'travel_known':[1.0], 'altitude_change_known':[1.0],
        'indoor_known':[1.0], 'weather_known':[0.0],
        **{name:[0.0] for name in build_production_training_table.FEATURE_NAMES if name not in {'stats_known_both','environment_known','travel_known','altitude_change_known','weather_known'}},
    })
    report = build_production_training_table.build_report(frame, {'with_statistics':1}, {})
    assert report['event_statistics']['raw_statistics_match_rate'] == 1.0
    assert report['event_statistics']['ready_for_candidate_eval'] is False
    assert report['candidate_feature_groups']['event_statistics']['eligible_for_candidate'] is False
    assert report['candidate_feature_groups']['static_environment']['eligible_for_candidate'] is True


def test_data_finalize_readiness_uses_real_candidate_flags_not_hardcoded_es_true():
    report = build_production_readiness_report.build(
        {'players':10,'country_coverage':1.0,'latest_rank_coverage':1.0,'duplicate_name_groups':0},
        {'tournaments':2,'venues':2,'tournament_coverage':{'country':1.0,'city':1.0},'venue_coverage':{'coordinates':1.0,'elevation':1.0,'timezone':1.0},'match_weighted_coverage':{'country':1.0,'city':1.0,'coordinates':1.0,'elevation':1.0,'timezone':1.0},'identity_diagnostics':{}},
        {'rows':100,'event_statistics':{'stats_known_both_rate':0.0,'ready_for_candidate_eval':False,'raw_statistics_match_rate':0.2},'static_environment':{'venue_environment_known_rate':0.9,'ready_for_candidate_eval':True},'candidate_feature_groups':{'event_statistics':{'ready_for_candidate_eval':False},'static_environment':{'ready_for_candidate_eval':True}}},
        {'status':'pass'},
        {'any_stats_rate':0.2,'both_players_quality_ready_rate':0.0,'stat_key_counts':{'p1_aces':20}},
    )
    assert report['candidate_training']['event_statistics'] is False
    assert report['candidate_training']['static_environment'] is True
    assert 'event_statistics_not_ready_for_candidate_eval' in report['warnings']
    assert report['statistics_diagnostics']['top_stat_keys'][0] == ('p1_aces', 20)


def test_data_readiness_requires_meaningful_coverage_not_one_observation():
    frame = pd.DataFrame({
        'scheduled_at': pd.to_datetime([f'2025-01-{day:02d}T12:00:00Z' for day in range(1, 11)]),
        'tour':['atp']*10, 'year':['2025']*10, 'surface':['hard']*10,
        'stats_known_both':[1.0]+[0.0]*9,
        'environment_known':[1.0]*3+[0.0]*7,
        'travel_known':[1.0]*10, 'altitude_change_known':[1.0]*10,
        'indoor_known':[1.0]*10, 'weather_known':[0.0]*10,
        **{name:[0.0]*10 for name in build_production_training_table.FEATURE_NAMES if name not in {'stats_known_both','environment_known','travel_known','altitude_change_known','weather_known'}},
    })
    report = build_production_training_table.build_report(frame, {'with_statistics':1}, {})
    assert report['event_statistics']['has_observations'] is True
    assert report['event_statistics']['ready_for_candidate_eval'] is False
    assert report['static_environment']['has_observations'] is True
    assert report['static_environment']['ready_for_candidate_eval'] is False


def test_readiness_prefers_match_weighted_geo_over_historical_entity_tail():
    report = build_production_readiness_report.build(
        {'players':10,'country_coverage':1.0,'latest_rank_coverage':1.0,'duplicate_name_groups':0},
        {
            'tournaments':100,'venues':100,
            'tournament_coverage':{'country':0.10,'city':0.10},
            'venue_coverage':{'coordinates':0.10,'elevation':0.10,'timezone':0.10},
            'match_weighted_coverage':{'country':0.99,'city':0.99,'coordinates':0.95,'elevation':0.85,'timezone':0.95},
            'identity_diagnostics':{},
        },
        {
            'rows':1000,
            'event_statistics':{'stats_known_both_rate':0.75,'ready_for_candidate_eval':True,'readiness_min_coverage':0.70},
            'static_environment':{'venue_environment_known_rate':0.85,'ready_for_candidate_eval':True,'readiness_min_coverage':0.80},
        },
        {'status':'pass'},
        {'any_stats_rate':0.80,'quality_capable_rate':0.78,'both_players_quality_ready_rate':0.75},
    )
    assert 'match_weighted_tournament_country_coverage_below_95pct' not in report['warnings']
    assert 'match_weighted_venue_coordinate_coverage_below_90pct' not in report['warnings']
    assert 'match_weighted_venue_elevation_coverage_below_80pct' not in report['warnings']
    assert report['candidate_training'] == {
        'event_statistics': True, 'static_environment': True,
        'historical_weather': False,
        'historical_weather_reason': 'requires genuine point-in-time pre-match forecast snapshots',
    }
    assert report['recommended_sequence'] == ['train','backtest-ablation','promotion-gate']


def test_v680_visual_polish_loading_ads_and_account_selector_contract():
    blinq_css = (ROOT / 'web/blinq.css').read_text(encoding='utf-8')
    assert '/assets/blinq_loading_tennis_v2.webp' in INDEX
    assert (ROOT / 'web/assets/blinq_loading_tennis_v2.webp').is_file()
    polish_css = (ROOT / 'web/polish-681.css').read_text(encoding='utf-8')
    assert '@keyframes bq-loader-rally' in polish_css
    # The right rail is an advertising surface; no forced BlinQ lockup lives inside slides.
    rail_fn = APP[APP.index('function railPromoSlideHtml'):APP.index('function clearRailPromoRotation')]
    assert 'rail-native-brand' not in rail_fn
    assert 'data-avatar-variant="m"' in APP and 'data-avatar-variant="w"' in APP
    assert 'accountModalAvatarVariant' in APP
    assert '.avatar-sex-toggle' in blinq_css
    assert 'grid-template-columns:1fr!important' in blinq_css
