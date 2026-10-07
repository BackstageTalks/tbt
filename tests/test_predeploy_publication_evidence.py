from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbt.services.publication import (
    confirm_publication,
    prepare_publication_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def prediction_row():
    now = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)
    return {
        "id": "match-predeploy",
        "event_id": "event-predeploy",
        "scheduled_at": (now + timedelta(days=1)).isoformat(),
        "model_version": "model-test",
        "created_at": now.isoformat(),
        "player1": {"id": "A", "name": "Alpha", "probability": .71, "rank": 12},
        "player2": {"id": "B", "name": "Beta", "probability": .29, "rank": 38},
        "winner_id": "A",
        "confidence": .71,
        "data_depth": .88,
        "stats_available": True,
        "quality": {
            "player1": {"matches": 40, "surface_matches": 12},
            "player2": {"matches": 37, "surface_matches": 10},
        },
        "issued_at": None,
        "publication_status": "pending",
    }


def test_prediction_prepare_does_not_issue_and_strict_confirm_requires_same_hash():
    row = prediction_row()
    prepared = prepare_publication_evidence(
        [deepcopy(row)],
        [deepcopy(row)],
        datetime(2026, 10, 7, 10, 5, tzinfo=timezone.utc),
        feed_generated_at="2026-10-07T10:04:00+00:00",
    )
    assert prepared[0]["issued_at"] is None
    assert prepared[0]["publication_status"] == "pending"
    evidence = prepared[0]["prepared_publication"]
    assert evidence["model_version"] == "model-test"
    assert evidence["players"]["player1"]["probability"] == pytest.approx(.71)
    assert len(evidence["commitment_sha256"]) == 64

    confirmed = confirm_publication(
        prepared,
        [deepcopy(row)],
        datetime(2026, 10, 7, 10, 10, tzinfo=timezone.utc),
        require_prepared=True,
    )
    assert confirmed[0]["issued_at"] is not None
    assert confirmed[0]["publication_status"] == "published"


def test_prediction_strict_confirm_rejects_unprepared_or_tampered_evidence():
    row = prediction_row()
    with pytest.raises(RuntimeError, match="lacks pre-deploy evidence"):
        confirm_publication(
            [deepcopy(row)],
            [deepcopy(row)],
            datetime(2026, 10, 7, 10, 10, tzinfo=timezone.utc),
            require_prepared=True,
        )

    prepared = prepare_publication_evidence(
        [deepcopy(row)],
        [deepcopy(row)],
        datetime(2026, 10, 7, 10, 5, tzinfo=timezone.utc),
    )
    prepared[0]["prepared_publication"]["commitment_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="does not match deployed commitment"):
        confirm_publication(
            prepared,
            [deepcopy(row)],
            datetime(2026, 10, 7, 10, 10, tzinfo=timezone.utc),
            require_prepared=True,
        )


def test_production_workflow_prepares_before_azure_and_requires_evidence_on_confirm():
    source = (ROOT / ".github" / "workflows" / "data.yml").read_text(encoding="utf-8")
    prepare = source.index("Freeze immutable issuance evidence before deploy")
    deploy = source.index("Deploy refreshed feed and application")
    confirm = source.index("Confirm exactly deployed prediction publication")
    assert prepare < deploy < confirm
    assert "scripts/prepare_prediction_publication.py" in source[prepare:deploy]
    assert "--require-prepared-evidence" in source[confirm:]


def test_failed_deploy_evidence_has_no_issuance_side_effect():
    row = prediction_row()
    prepared = prepare_publication_evidence(
        [deepcopy(row)],
        [deepcopy(row)],
        datetime(2026, 10, 7, 10, 5, tzinfo=timezone.utc),
    )
    # No confirmation call represents a failed public deploy.
    assert prepared[0]["issued_at"] is None
    assert prepared[0]["publication_status"] == "pending"
    assert "prepared_publication" in prepared[0]
