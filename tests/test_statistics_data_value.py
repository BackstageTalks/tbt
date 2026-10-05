from audit_statistics_inventory import statistics_value_change


def test_count_only_response_is_not_a_quality_gain_and_zero_is_observed():
    stats={'p1_aces':0,'p2_aces':3,'p1_double_faults':0,'p2_double_faults':2}
    delta=statistics_value_change({},stats)
    assert delta=={'new_statistic_values':4,'new_ace_df_values':4,'new_quality_ready_rows':0}
    assert statistics_value_change(stats,dict(stats))=={'new_statistic_values':0,'new_ace_df_values':0,'new_quality_ready_rows':0}


def test_full_two_player_quality_transition_is_counted_once():
    partial={'p1_service_points_won':.6,'p1_return_points_won':.4,'p2_service_points_won':.7}
    full={**partial,'p2_return_points_won':.3}
    assert statistics_value_change(partial,full)['new_quality_ready_rows']==1
    assert statistics_value_change(full,full)['new_quality_ready_rows']==0
    assert statistics_value_change({},partial)['new_quality_ready_rows']==0
