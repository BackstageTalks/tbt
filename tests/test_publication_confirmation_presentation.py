from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = spec_from_file_location(
    "confirm_prediction_publication_test_module",
    SCRIPTS / "confirm_prediction_publication.py",
)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_publication_candidate_view_ignores_nested_member_presentation_fields():
    private = {
        "doubles_picks": [
            {
                "event_id": "evt-1",
                "player1": {
                    "id": "team-a",
                    "name": "Team A",
                    "members": [
                        {"id": "p1", "name": "One"},
                        {"id": "p2", "name": "Two"},
                    ],
                },
                "player2": {
                    "id": "team-b",
                    "name": "Team B",
                    "members": [
                        {"id": "p3", "name": "Three"},
                        {"id": "p4", "name": "Four"},
                    ],
                },
                "selection": "Team A",
            }
        ]
    }
    deployed = {
        "player_assets": {"available": True},
        "doubles_picks": [
            {
                "event_id": "evt-1",
                "player1": {
                    "id": "team-a",
                    "name": "Team A",
                    "rank": 10,
                    "members": [
                        {"id": "p1", "name": "One", "photo_url": "/p1.jpg", "country_code": "SK"},
                        {"id": "p2", "name": "Two", "best_rank": 22},
                    ],
                },
                "player2": {
                    "id": "team-b",
                    "name": "Team B",
                    "members": [
                        {"id": "p3", "name": "Three", "ranking_points": 500},
                        {"id": "p4", "name": "Four", "height_cm": 188},
                    ],
                },
                "selection": "Team A",
            }
        ],
    }

    assert module._publication_candidate_view(deployed) == module._publication_candidate_view(private)


def test_publication_candidate_view_still_detects_prediction_changes():
    left = {"top_daily_picks": [{"event_id": "evt", "player1": {"id": "1", "name": "A"}, "odds": 1.8}]}
    right = {"top_daily_picks": [{"event_id": "evt", "player1": {"id": "1", "name": "A"}, "odds": 1.9}]}
    assert module._publication_candidate_view(left) != module._publication_candidate_view(right)
