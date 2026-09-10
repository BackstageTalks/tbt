import pandas as pd
from tbt.services.prediction_quality import subgroup_report, coverage
from tbt.models.feature_builder import FeatureBuilder


def test_small_subgroups_keep_counts_and_do_not_claim_reliability():
    frame = pd.DataFrame({'target': [1, 0, 1], 'surface': ['hard', 'clay', 'hard'],
                          'competition': ['ATP', 'WTA', 'ATP'], 'history_band': ['30+', '0–9', '30+']})
    report = subgroup_report(frame, [.8, .2, .6])
    assert report['surface']['hard']['n'] == 2
    assert report['surface']['hard']['small_sample'] is True
    assert report['surface']['hard']['coverage'] == 2 / 3
    assert report['surface']['hard']['accuracy_ci95_wilson'][0] < .5


def test_coverage_is_based_only_on_replayed_history(match_factory):
    builder = FeatureBuilder()
    previous = match_factory('old', 'A', 'B', 'A')
    fixture = match_factory('next', 'A', 'B', None, day=2, surface='clay')
    builder.replay([previous])
    quality = coverage(builder, fixture)
    assert quality['player1']['matches'] == 1
    assert quality['player1']['surface_matches'] == 0
    assert quality['history_band'] == '0–9'
