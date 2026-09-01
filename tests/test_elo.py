from tbt.models.elo import elo_expected, update_elo


def test_elo_expected_is_symmetric():
    a = elo_expected(1640, 1510)
    b = elo_expected(1510, 1640)
    assert abs((a + b) - 1.0) < 1e-12


def test_elo_update_is_zero_sum_for_equal_k():
    a, b = update_elo(1500, 1500, 1.0, 0, 0)
    assert a > 1500
    assert b < 1500
    assert abs((a - 1500) + (b - 1500)) < 1e-9
