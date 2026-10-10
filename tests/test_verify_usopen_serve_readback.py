"""US Open persisted CDB read-back must use the real dataclass snapshot schema."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tbt.schemas import MatchRecord
from scripts.verify_usopen_serve_readback import _dump, verify
from scripts.import_usopen_serve_metadata import MARKER_KEY


def match():
    return MatchRecord(
        match_id="usopen1", tour="atp",
        scheduled_at=datetime(2024, 8, 27, 12, tzinfo=timezone.utc),
        player1_id="p1", player1_name="Player One",
        player2_id="p2", player2_name="Player Two",
        tournament="US Open", stats={"p1_aces": 5.0},
        provider_payload={"_tbt_provider_event_id": "event-1"},
    )


def test_readback_round_trip_only_allows_expected_marker():
    before = match()
    after = deepcopy(before)
    marker = {"source": "pinned", "feature_policy": "post_match_only"}
    after.provider_payload[MARKER_KEY] = marker
    staged = [{"schema": 1, "import_ready": True,
               "match_id": before.match_id, "marker": marker}]
    assert _dump(before) == before.to_storage_dict()
    result = verify([before], [after], staged)
    assert result["enriched_matches"] == 1
    assert result["stats_overwrites"] == 0
    assert result["identity_changes"] == 0


def test_readback_fails_on_unstaged_stats_change():
    before = match()
    after = deepcopy(before)
    after.stats["p1_aces"] = 99.0
    with pytest.raises(ValueError, match="Unstaged"):
        verify([before], [after], [])


def test_readback_fails_on_other_changes_in_staged_match():
    before = match()
    after = deepcopy(before)
    marker = {"source": "pinned"}
    after.provider_payload[MARKER_KEY] = marker
    after.winner_id = "p2"
    with pytest.raises(ValueError, match="Non-provider"):
        verify([before], [after], [
            {"schema": 1, "import_ready": True,
             "match_id": before.match_id, "marker": marker}
        ])


def test_readback_rejects_noncanonical_unsupported_objects():
    with pytest.raises(TypeError, match="to_storage_dict"):
        _dump(object())
