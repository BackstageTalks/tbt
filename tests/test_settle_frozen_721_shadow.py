"""Regression tests for private frozen 7.2.1 settlement from canonical outcomes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

import settle_frozen_721_shadow as service
from tbt.schemas import MatchRecord
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256,
)

CHAMPION = "v201-20260925T204608601094Z"


def fixture(now=None):
    now = now or datetime(2026, 10, 20, 20, tzinfo=timezone.utc)
    kickoff = now - timedelta(hours=3)
    row = {
        "schema": 1, "match_id": "fixture-721-1",
        "event_id": "event1", "tour": "ATP", "surface": "hard",
        "scheduled_at": kickoff.isoformat(),
        "captured_at": (kickoff - timedelta(hours=4)).isoformat(),
        "player1_id": "a", "player2_id": "b",
        "production_model_version": CHAMPION,
        "challenger_model_version": FROZEN_721_VERSION,
        "production_player1_probability": 0.60,
        "challenger_player1_probability": 0.71,
        "status": "pending", "result_winner_id": None,
    }
    payload = {"schema": 1, "source": {
        "candidate_tag": FROZEN_721_TAG,
        "candidate_version": FROZEN_721_VERSION,
        "candidate_model_sha256": FROZEN_721_MODEL_SHA256,
        "production_version": CHAMPION,
        "provider_requests": 0,
    }, "rows": [row]}
    match = MatchRecord(
        match_id=row["match_id"], tour="atp", scheduled_at=kickoff,
        player1_id="a", player1_name="A",
        player2_id="b", player2_name="B",
        winner_id="a", status="finished",
    )
    return now, payload, match


def test_settles_only_identical_completed_pre_match_fixture():
    now, payload, match = fixture()
    rows = payload["rows"]
    accepted, audit = service.completed_matches_for_pending(rows, [match], now)
    assert len(accepted) == 1
    assert audit["identity_mismatch"] == 0

    foreign = MatchRecord(
        match_id=match.match_id, tour="atp", scheduled_at=match.scheduled_at,
        player1_id="a", player1_name="A", player2_id="different", player2_name="C",
        winner_id="a", status="finished",
    )
    accepted, audit = service.completed_matches_for_pending(rows, [foreign], now)
    assert accepted == [] and audit["identity_mismatch"] == 1

    accepted, audit = service.completed_matches_for_pending(
        rows, [match], match.scheduled_at - timedelta(seconds=1)
    )
    assert accepted == [] and audit["not_yet_played"] == 1


def test_preliminary_metric_is_descriptive_and_reports_uncertainty():
    now, payload, match = fixture()
    from tbt.services.shadow_evaluation import update_shadow_ledger
    prior = json.loads(json.dumps(payload["rows"]))
    updated = update_shadow_ledger(prior, completed_matches=[match], now=now)
    result = service.preliminary_scoreboard(updated)
    assert result["automatic_promotion"] is False
    assert result["status"] == "PRELIMINARY_SCORES_ONLY_NOT_PROMOTION"
    assert result["groups"]["overall"]["n"] == 1
    assert result["groups"]["ATP"]["n"] == 1
    assert result["groups"]["WTA"]["n"] == 0
    assert result["groups"]["overall"]["champion"]["accuracy_ci95_wilson"] is not None
    assert result["groups"]["overall"]["champion"]["roc_auc"] is None
    json.dumps(result, allow_nan=False)


def test_private_settlement_persists_only_verified_outcomes_and_no_provider_calls(
    tmp_path, monkeypatch
):
    now, payload, match = fixture()
    remote_assets = {
        service.LEDGER_ASSET: (json.dumps(payload, sort_keys=True)+"\n").encode(),
        service.REPORT_ASSET: b'{"initial":true}\n',
    }
    calls = []
    class FakeReleaseStore:
        def __init__(self, repository, tag, directory):
            assert tag == service.SHADOW_TAG
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)

        def download(self, **kwargs):
            for name, data in remote_assets.items():
                (self.directory / name).write_bytes(data)

        def upload_bundle(self, paths):
            calls.append("uploaded_private_shadow_only")
            remote_assets.update({path.name: path.read_bytes() for path in paths})

    monkeypatch.setattr(service, "ReleaseStore", FakeReleaseStore)
    monkeypatch.setattr(service, "gh", lambda *args: "{}")
    monkeypatch.setattr(service, "download_verified_years",
                        lambda repo, directory, years: ([match], {
                            "source_release": "tbt-data-v1", "verified_partition_sha256": {
                                "2026": "0"*64
                            }, "provider_requests": 0
                        }))
    monkeypatch.setattr(service, "acquire",
                        lambda repo, path, **kw: calls.append("lock_acquired"))
    monkeypatch.setattr(service, "release",
                        lambda repo, path, **kw: calls.append("lock_released"))

    first = service.settle(workdir=tmp_path, now=now)
    assert first["status"] == "VERIFIED_SETTLEMENT_PUBLISHED"
    assert first["remote_readback"] == "VERIFIED"
    assert first["counts"]["settled"] == 1
    assert first["new_settled"] == 1
    assert first["provider_requests"] == 0
    assert first["production_mutated"] is False
    assert calls == ["lock_acquired", "uploaded_private_shadow_only", "lock_released"]
    saved = json.loads(remote_assets[service.LEDGER_ASSET])
    assert saved["rows"][0]["production_player1_probability"] == 0.60
    assert saved["rows"][0]["challenger_player1_probability"] == 0.71
    assert saved["rows"][0]["captured_at"] == payload["rows"][0]["captured_at"]
    assert saved["rows"][0]["status"] == "settled"
    report = json.loads(remote_assets[service.REPORT_ASSET])
    assert report["preliminary"]["groups"]["ATP"]["n"] == 1
    assert report["automatic_promotion"] is False
    second = service.settle(workdir=tmp_path / "second", now=now)
    assert second["status"] == "NO_PENDING_SHADOW_MATCHES"
    assert len(calls) == 3


def test_history_download_is_bound_to_both_private_release_hashes(tmp_path, monkeypatch):
    artifact = b"synthetic partition file"
    import hashlib
    canonical = {name: data for name, data in {
        "history-2026.parquet": artifact,
        "history_manifest.json": json.dumps({
            "years": {"2026": {"asset": "history-2026.parquet"}}
        }).encode(),
    }.items()}
    inventory = {name: {"sha256": hashlib.sha256(data).hexdigest()}
                 for name, data in canonical.items()}
    canonical["_tbt_bundle_manifest.json"] = json.dumps({
        "files": inventory
    }).encode()
    digest = {name: {"name": name, "digest": "sha256:"+hashlib.sha256(data).hexdigest()}
              for name, data in canonical.items()}

    def fake_gh(*args):
        if args[:2] == ("api", f"repos/{service.DATA_REPO}/releases/tags/{service.HISTORY_TAG}"):
            return json.dumps({"assets": list(digest.values())})
        assert args[:3] == ("release", "download", service.HISTORY_TAG)
        root = tmp_path
        for name, data in canonical.items():
            (root / name).write_bytes(data)
        return ""

    monkeypatch.setattr(service, "gh", fake_gh)
    monkeypatch.setattr(service, "load_snapshot", lambda path: [fixture()[2]])
    matches, provenance = service.download_verified_years(service.DATA_REPO, tmp_path, {2026})
    assert len(matches) == 1
    assert provenance["provider_requests"] == 0
    digest["history-2026.parquet"]["digest"] = "sha256:" + "a"*64
    with pytest.raises(ValueError, match="release asset checksum mismatch"):
        service.download_verified_years(service.DATA_REPO, tmp_path, {2026})
