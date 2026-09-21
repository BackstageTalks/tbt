from tbt.match_format import exact_best_of_from_score_stats, infer_best_of


def test_explicit_best_of_wins():
    assert infer_best_of(explicit=3, tour="atp", tournament="US Open")[0] == 3
    assert infer_best_of(explicit=5, tour="wta", tournament="Test")[0] == 5


def test_structured_four_set_minimum_proves_bo5_for_pre_match_helper():
    value, source = infer_best_of(tour="atp", tournament="Test", total_sets=4)
    assert value == 5
    assert source == "structured_score_minimum"


def test_finished_score_proves_best_of_exactly():
    assert exact_best_of_from_score_stats({"p1_sets_won": 2, "p2_sets_won": 1, "total_sets": 3}) == (3, "structured_finished_score")
    assert exact_best_of_from_score_stats({"p1_sets_won": 1, "p2_sets_won": 3, "total_sets": 4}) == (5, "structured_finished_score")


def test_finished_score_rejects_inconsistent_rows():
    assert exact_best_of_from_score_stats({"p1_sets_won": 2, "p2_sets_won": 0, "total_sets": 3})[0] is None


def test_atp_slam_main_draw_and_qualifying_are_distinguished():
    assert infer_best_of(tour="ATP", tournament="Roland Garros", round_name="Quarterfinal")[0] == 5
    assert infer_best_of(tour="ATP", tournament="Roland Garros", round_name="Qualifying R2")[0] == 3


def test_wta_slam_stays_bo3():
    assert infer_best_of(tour="WTA", tournament="Australian Open", round_name="Final")[0] == 3


def test_nonstandard_next_gen_fails_closed_for_sg():
    assert infer_best_of(tour="ATP", tournament="Next Gen ATP Finals") == (None, "unsupported_format")


def test_unknown_tour_fails_closed():
    assert infer_best_of(tour="mystery", tournament="Some Open") == (None, "unknown")
