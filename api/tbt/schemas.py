from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any


@dataclass
class MatchRecord:
    match_id: str
    tour: str
    scheduled_at: datetime
    player1_id: str
    player1_name: str
    player2_id: str
    player2_name: str
    surface: str = "unknown"
    tournament: str = ""
    tournament_id: str = ""
    tournament_level: str = ""
    round_name: str = ""
    player1_rank: int | None = None
    player2_rank: int | None = None
    winner_id: str | None = None
    status: str = "upcoming"
    best_of: int | None = None
    indoor: bool | None = None
    stats: dict[str, float | None] = field(default_factory=dict)
    provider_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def event_date(self):
        return self.scheduled_at.date()

    @property
    def is_completed(self) -> bool:
        return self.winner_id in {self.player1_id, self.player2_id}

    def swapped(self) -> "MatchRecord":
        swapped_stats: dict[str, float | None] = {}
        for key, value in self.stats.items():
            if key.startswith("p1_"):
                swapped_stats["p2_" + key[3:]] = value
            elif key.startswith("p2_"):
                swapped_stats["p1_" + key[3:]] = value
            else:
                swapped_stats[key] = value
        return replace(
            self,
            player1_id=self.player2_id,
            player1_name=self.player2_name,
            player2_id=self.player1_id,
            player2_name=self.player1_name,
            player1_rank=self.player2_rank,
            player2_rank=self.player1_rank,
            stats=swapped_stats,
        )

    def to_storage_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scheduled_at"] = self.scheduled_at.astimezone(timezone.utc).isoformat()
        return data


@dataclass
class PredictionRecord:
    match_id: str
    model_version: str
    generated_at: datetime
    player1_probability: float
    player2_probability: float
    predicted_winner_id: str
    predicted_winner_name: str
    confidence_pct: float
    confidence_band: str
    features: dict[str, float]
    signals: list[dict[str, Any]]
    fixture: MatchRecord

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "model_version": self.model_version,
            "generated_at": self.generated_at.astimezone(timezone.utc).isoformat(),
            "scheduled_at": self.fixture.scheduled_at.astimezone(timezone.utc).isoformat(),
            "tour": self.fixture.tour,
            "tournament": self.fixture.tournament,
            "surface": self.fixture.surface,
            "round_name": self.fixture.round_name,
            "player1_id": self.fixture.player1_id,
            "player1_name": self.fixture.player1_name,
            "player1_rank": self.fixture.player1_rank,
            "player2_id": self.fixture.player2_id,
            "player2_name": self.fixture.player2_name,
            "player2_rank": self.fixture.player2_rank,
            "player1_probability": self.player1_probability,
            "player2_probability": self.player2_probability,
            "predicted_winner_id": self.predicted_winner_id,
            "predicted_winner_name": self.predicted_winner_name,
            "confidence_pct": self.confidence_pct,
            "confidence_band": self.confidence_band,
            "features": self.features,
            "signals": self.signals,
            "result_winner_id": None,
            "is_correct": None,
        }
