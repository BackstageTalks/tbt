from collections import Counter
from types import SimpleNamespace
from datetime import datetime, timezone

from scripts.link_slam_pointbypoint_serve_return import (
    _canonical_index,
    _rates,
    _source_pair,
)


def test_rates_use_explicit_server_and_winner_counts():
    data = {
        1: Counter(service_points=10, service_won=7, return_points=8, return_won=3),
        2: Counter(service_points=8, service_won=5, return_points=10, return_won=3),
    }
    rates = _rates(data)
    assert rates[1]["service_points_won"] == 0.7
    assert rates[1]["return_points_won"] == 0.375
    assert rates[2]["service_points_won"] == 0.625
    assert rates[2]["return_points_won"] == 0.3


def test_canonical_index_requires_major_identity_and_exact_pair():
    match = SimpleNamespace(
        scheduled_at=datetime(2024, 7, 1, tzinfo=timezone.utc),
        player1_name="Jannik Sinner",
        player2_name="Yannick Hanfmann",
        tournament="Wimbledon",
    )
    index = _canonical_index([match])
    key = (2024, "wimbledon", _source_pair("Jannik Sinner", "Yannick Hanfmann"))
    assert index[key] == [match]
    wrong = (2024, "usopen", _source_pair("Jannik Sinner", "Yannick Hanfmann"))
    assert wrong not in index
