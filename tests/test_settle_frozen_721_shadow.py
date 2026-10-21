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


@pytest.mark.parametrize("use_alias", [False, True])
def test_private_settlement_persists_only_verified_outcomes_and_no_provider_calls(
    tmp_path, monkeypatch, use_alias
):
    now, payload, match = fixture()
    if use_alias:
        from dataclasses import replace
        match = replace(match, match_id="canonical-changed-hash", provider_payload={
            "_tbt_provider_event_id": "event1", "_tbt_event_identity": {
                "event_id": "event1", "home": "a", "away": "b", "status": "finished"}})
        duplicate = {**payload["rows"][0], "match_id": "later-prediction",
                     "captured_at": (now - timedelta(hours=4)).isoformat()}
        payload["rows"].append(duplicate)
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
    if use_alias:
        assert first["counts"]["excluded"] == 1
        assert saved["rows"][0]["settlement_identity"]["canonical_match_id"] == "canonical-changed-hash"
        assert saved["rows"][1]["status"] == "excluded"
        assert saved["rows"][1]["primary_match_id"] == saved["rows"][0]["match_id"]
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


def test_pending_diagnostics_distinguishes_future_overdue_and_canonical_identity_drift():
    now, payload, match = fixture()
    # One fixture is already scheduled, and an otherwise identical canonically
    # completed match has a DIFFERENT ID: never treat that as a settled pair.
    altered = MatchRecord(
        match_id="canonical-foreign-id", tour=match.tour,
        scheduled_at=match.scheduled_at, player1_id=match.player1_id,
        player1_name=match.player1_name, player2_id=match.player2_id,
        player2_name=match.player2_name, winner_id=match.winner_id, status="finished",
    )
    future = dict(payload["rows"][0])
    future["match_id"] = "future-unknown"
    future["scheduled_at"] = (now + timedelta(hours=9)).isoformat()
    future["captured_at"] = (now - timedelta(hours=1)).isoformat()
    future["player1_id"] = "x"
    future["player2_id"] = "y"
    older = dict(payload["rows"][0])
    older["match_id"] = "very-old"
    older["scheduled_at"] = (now - timedelta(days=2)).isoformat()
    older["captured_at"] = (now - timedelta(days=3)).isoformat()
    older["player1_id"] = "z"
    older["player2_id"] = "w"
    rows = [payload["rows"][0], future, older]
    audit = service.pending_schedule_diagnostics(rows, [altered], now)
    assert audit["pending"] == 3
    assert audit["scheduled_not_started"] == 1
    assert audit["scheduled_at_or_before_now"] == 2
    assert audit["starts_next_24h"] == 1
    assert audit["at_least_24h_after_schedule"] == 1
    assert audit["exact_id_in_canonical"] == 0
    assert audit["alternate_id_same_players_day_diagnostic_only"] == 1
    assert audit["alternate_id_canonically_completed_diagnostic_only"] == 1
    assert audit["alternate_id_join_used_for_settlement"] is False
    assert audit["provider_requests"] == 0
    accepted, strict_audit = service.completed_matches_for_pending(rows, [altered], now)
    assert accepted == []
    assert strict_audit["matched_canonical_rows"] == 0


def test_pending_diagnostics_exact_identity_not_inflated_by_fuzzy_lookup():
    now, payload, match = fixture()
    actual = service.pending_schedule_diagnostics(payload["rows"], [match], now)
    assert actual["exact_id_in_canonical"] == 1
    assert actual["exact_id_canonically_completed"] == 1
    assert actual["alternate_id_same_players_day_diagnostic_only"] == 0
    assert actual["scheduled_at_or_before_now"] == 1
    assert actual["provider_requests"] == 0


def test_verified_provider_event_resolves_changed_hash_without_mutating_cdb():
    from dataclasses import replace
    now, payload, match = fixture()
    canonical = replace(match, match_id='changed-after-delay',
                        scheduled_at=match.scheduled_at + timedelta(minutes=30),
                        provider_payload={'_tbt_provider_event_id': 'event1',
                          '_tbt_event_identity': {'event_id': 'event1', 'home': 'a', 'away': 'b', 'status': 'finished'}})
    accepted, audit = service.completed_matches_for_pending(payload['rows'], [canonical], now)
    assert accepted[0].match_id == payload['rows'][0]['match_id']
    assert canonical.match_id == 'changed-after-delay'
    assert audit['verified_provider_event_aliases'] == 1
    assert audit['provider_alias_evidence'][accepted[0].match_id]['canonical_match_id'] == canonical.match_id
    # Reversing canonical orientation preserves the exact provider event and winner.
    reversed_match = canonical.swapped()
    accepted, _ = service.completed_matches_for_pending(payload['rows'], [reversed_match], now)
    assert accepted[0].winner_id == 'a'


@pytest.mark.parametrize('failure', ['missing_identity', 'different_event', 'different_players', 'ambiguous', 'early_start'])
def test_provider_alias_fails_closed(failure):
    from dataclasses import replace
    now, payload, match = fixture()
    raw = {'_tbt_provider_event_id': 'event1', '_tbt_event_identity':
           {'event_id': 'event1', 'home': 'a', 'away': 'b', 'status': 'finished'}}
    canonical = replace(match, match_id='changed', provider_payload=raw)
    matches = [canonical]
    if failure == 'missing_identity': raw.pop('_tbt_event_identity')
    if failure == 'different_event': raw['_tbt_event_identity']['event_id'] = 'other'
    if failure == 'different_players': raw['_tbt_event_identity']['away'] = 'other'
    if failure == 'ambiguous': matches.append(replace(canonical, match_id='another'))
    if failure == 'early_start': canonical.scheduled_at = now - timedelta(hours=8)
    accepted, _ = service.completed_matches_for_pending(payload['rows'], matches, now)
    assert accepted == []


def test_duplicate_provider_event_keeps_earliest_prediction_and_audit_rows():
    from copy import deepcopy
    now, payload, match = fixture()
    first = payload['rows'][0]
    later = {**deepcopy(first), 'match_id': 'new-internal-hash',
             'captured_at': (now - timedelta(hours=4)).isoformat(),
             'challenger_player1_probability': .99}
    originals = [later, first]
    result = service.exclude_repeated_events(originals)
    assert len(result) == 2
    assert result[0]['status'] == 'excluded'
    assert result[0]['primary_match_id'] == first['match_id']
    assert result[0]['challenger_player1_probability'] == .99
    assert result[1] == first
    assert originals[0]['status'] == 'pending'
    assert service.exclude_repeated_events(result) == result
    later['player2_id'] = 'different'
    with pytest.raises(ValueError, match='Conflicting provider event'):
        service.exclude_repeated_events(originals)
