"""Synthetic read-only identity probe contracts. No credentials or CDB needed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import diagnose_frozen_721_settlement as probe
from tbt.schemas import MatchRecord


def test_read_only_probe_classifies_mismatched_player_namespace_without_any_write(
    tmp_path, monkeypatch,
):
    now = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)
    kickoff = now - timedelta(days=1)
    row = {
        "status": "pending",
        "match_id": "immutable-prediction",
        "event_id": "provider-event-1",
        "tour": "ATP",
        "scheduled_at": kickoff.isoformat(),
        "captured_at": (kickoff - timedelta(hours=4)).isoformat(),
        "player1_id": "provider-id-a", "player2_id": "foreign-id-b",
    }
    payload = {"source": {"production_version": "champion"}, "rows": [row]}
    original = json.dumps(payload, sort_keys=True)
    canonical = MatchRecord(
        match_id="canonical-id", tour="atp", scheduled_at=kickoff,
        player1_id="provider-id-a", player1_name="A",
        player2_id="provider-id-b", player2_name="B",
        winner_id="provider-id-a", status="finished",
        provider_payload={
            "_tbt_provider_event_id": "provider-event-1",
            "_tbt_event_identity": {
                "event_id": "provider-event-1",
                "home": "provider-id-a", "away": "provider-id-b",
                "status": "finished",
            },
        },
    )

    class ReadOnlyStore:
        def __init__(self, repo, tag, directory):
            assert repo == probe.DATA_REPO and tag == probe.SHADOW_TAG
            self.directory = directory

        def download(self, **kwargs):
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / probe.LEDGER_ASSET).write_text(original)
            (self.directory / probe.REPORT_ASSET).write_text("{}")

        def upload_bundle(self, *args, **kwargs):
            raise AssertionError("A read-only probe must never upload")

    monkeypatch.setattr(probe, "ReleaseStore", ReadOnlyStore)
    monkeypatch.setattr(
        probe, "validate_frozen_evidence",
        lambda source, production_version: (source["rows"], {"pending": 1, "settled": 0}),
    )
    monkeypatch.setattr(probe, "exclude_repeated_events", lambda rows: rows)
    monkeypatch.setattr(
        probe, "download_verified_years",
        lambda repo, directory, years: (
            [canonical], {"provider_requests": 0, "verified_partition_sha256": {"2026": "a" * 64}},
        ),
    )
    report = probe.diagnose(now=now, workdir=tmp_path)
    assert report["ledger_pending"] == 1
    assert report["eligible_for_separate_strict_settlement"] == 0
    assert report["canonical_matching"]["identity_mismatch"] == 1
    assert report["canonical_matching"]["alias_identity_categories"] == {
        "captured_canonical_player_id_conflict": 1
    }
    assert report["provider_requests"] == 0
    assert report["CDB_mutated"] is False
    assert report["shadow_mutated"] is False
    assert report["production_mutated"] is False
    assert json.dumps(payload, sort_keys=True) == original
    assert "foreign-id-b" not in json.dumps(report)
    assert "provider-event-1" not in json.dumps(report)


def test_read_only_probe_rejects_unexpected_repository_or_naive_timestamp(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="canonical"):
        probe.diagnose(repo="different/private", workdir=tmp_path)
    with pytest.raises(ValueError, match="timezone"):
        probe.diagnose(now=datetime(2026, 10, 28), workdir=tmp_path)
