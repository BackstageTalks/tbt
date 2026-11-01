"""Contract for the one authorized 2016 provider-native push request.

The existing data.yml writer remains the only publisher. No direct CDB
mutation, extra data writer, model activation, or unbudgeted API calls.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_2016_history_request_is_explicit_and_bounded():
    request = json.loads((ROOT / ".github/data-operation-request.json").read_text())
    # Future approved modes legitimately replace this short-lived request.
    if request.get("mode") != "history":
        return
    assert request["source"] == "tennisapi1"
    assert request["source_event_id"] == "7115726"
    assert request["source_event_date"] == "2016-07-09"
    assert request["start"] == "2016-07-09"
    assert request["end"] == "2016-07-10"
    assert request["max_requests"] == 40
    assert request["cdb_writes_allowed"] is True
    assert request["model_changes"] is False
    assert request["promote"] is False


def test_only_fixed_source_window_can_be_triggered_by_push_request():
    workflow = (ROOT / ".github/workflows/data.yml").read_text()
    for invariant in (
        'if [[ "$mode" == "history" ]]; then',
        '"$start_date" == "2016-07-09"',
        '"$end_date" == "2016-07-10"',
        '10#$max_requests <= 40',
        '.source_event_id // empty',
        '"7115726"',
        '.cdb_writes_allowed // empty',
        'BLINQ_SHARED_API_BUDGET_PURPOSE=history',
        'python scripts/cdb_global_writer_lock.py acquire',
        'python scripts/download_tennis_history.py',
    ):
        assert invariant in workflow
    assert "BLINQ_PROVIDER_REQUEST_RESERVE: '500'" in workflow
    assert "github.event_name == 'push'" in workflow
