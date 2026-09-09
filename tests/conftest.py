from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tbt.schemas import MatchRecord


@pytest.fixture
def match_factory():
    def make(
        match_id: str,
        p1: str,
        p2: str,
        winner: str | None,
        day: int = 1,
        surface: str = "hard",
        tour: str = "atp",
    ) -> MatchRecord:
        return MatchRecord(
            match_id=match_id,
            tour=tour,
            scheduled_at=datetime(2025, 1, day, 12, tzinfo=timezone.utc),
            player1_id=p1,
            player1_name=p1,
            player2_id=p2,
            player2_name=p2,
            winner_id=winner,
            surface=surface,
            tournament="Test Open",
            tournament_level="ATP 250",
        )

    return make
