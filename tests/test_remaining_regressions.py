from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json

import httpx
import numpy as np
import pandas as pd
import pytest

import pipeline
import release_store
from tbt.data.history_snapshot import merge_matches, _merge_record, write_snapshot, load_snapshot, load_partitions
from tbt.data.provider_context import minimize_provider_payload, merge_provider_context
from tbt.models.feature_builder import FeatureBuilder
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services import backtest_service, training
from tbt.services.engine import predict, reconcile_ledger, confirm_publication


def test_conflicting_provider_events_never_collapse(match_factory):
    a = replace(match_factory('a', 'A', 'B', 'A'), provider_payload={'id': 1})
    b = replace(a, match_id='b', provider_payload={'id': 2})
    c = replace(b, tournament='Other Open', scheduled_at=b.scheduled_at + timedelta(hours=3))
    for right in (b, c, replace(b, match_id=a.match_id)):
        for order in permutations([a, right]):
            assert len(merge_matches(order)) == 2


def test_synthetic_match_id_never_overrides_time_or_tournament_conflict(match_factory):
    base = match_factory('collision', 'A', 'B', 'A')
    other = replace(base, tournament='Other Open',
                    scheduled_at=base.scheduled_at + timedelta(hours=3),
                    provider_payload={})
    assert len(merge_matches([base, other])) == 2
    known = replace(other, provider_payload={'id': 222})
    assert len(merge_matches([base, known])) == 2


def test_fallback_requires_time_tournament_and_unique_match(match_factory):
    a = match_factory('a', 'A', 'B', 'A')
    assert len(merge_matches([a, replace(a, match_id='b')])) == 1
    for changes in ({'tournament': ''}, {'tournament': 'Other'},
                    {'scheduled_at': a.scheduled_at + timedelta(minutes=1)}):
        assert len(merge_matches([a, replace(a, match_id='b', **changes)])) == 2
    known1 = replace(a, match_id='known1', provider_payload={'id': 1})
    known2 = replace(a, match_id='known2', provider_payload={'id': 2})
    for order in permutations([a, known1, known2]):
        assert len(merge_matches(order)) == 3


@pytest.mark.parametrize('incoming_richer', [False, True])
def test_reversed_merge_keeps_statistics_and_ranks_with_player(match_factory, incoming_richer):
    a = replace(match_factory('a', 'A', 'B', 'A'), player1_rank=10, player2_rank=80,
                stats={'p1_aces': 10, 'p2_aces': 2, 'p1_double_faults': 3})
    b = replace(a.swapped(), player1_rank=None, player2_rank=None, stats={})
    if incoming_richer:
        b.provider_payload = {'_tbt_environment': {'venue_resolved': True}}
    result = _merge_record(a, b)
    assert result.player1_id == ('B' if incoming_richer else 'A')
    rank_by_player = {result.player1_id: result.player1_rank, result.player2_id: result.player2_rank}
    aces_by_player = {result.player1_id: result.stats['p1_aces'], result.player2_id: result.stats['p2_aces']}
    assert rank_by_player == {'A': 10, 'B': 80}
    assert aces_by_player == {'A': 10, 'B': 2}
    assert a.stats['p1_aces'] == 10
    with pytest.raises(ValueError, match='incompatible'):
        _merge_record(a, replace(b, player2_id='C'))


def test_rank_provenance_survives_parquet_and_does_not_certify_other_ranks(match_factory, tmp_path):
    marker = {'point_in_time': True, 'source': 'historical', 'as_of': '2024-12-30T00:00:00+00:00'}
    a = replace(match_factory('a', 'A', 'B', 'A'), player1_rank=10, player2_rank=80,
                provider_payload={'_tbt_rank_provenance': marker, 'large_raw_response': [1, 2, 3]})
    path = tmp_path / 'history.parquet'
    write_snapshot([a], path)
    restored = load_snapshot(path)[0]
    assert restored.provider_payload['_tbt_rank_provenance'] == marker
    assert 'large_raw_response' not in restored.provider_payload
    cleaned, report = training._enforce_rank_provenance([restored])
    assert report['verified_rows'] == 1 and cleaned[0].player1_rank == 10
    b = replace(a, player1_rank=99, player2_rank=None,
                provider_payload={'_tbt_environment': {'venue_resolved': True}})
    merged = _merge_record(a, b)
    assert '_tbt_rank_provenance' not in merged.provider_payload
    assert training._enforce_rank_provenance([merged])[0][0].player1_rank is None
    merged_context = merge_provider_context(a.provider_payload, {'_tbt_rank_provenance': {'source': 'current'}})
    assert merged_context['_tbt_rank_provenance'] == {'source': 'current'}


def test_training_replay_order_and_whole_utc_day_snapshots(match_factory):
    early = replace(match_factory('z', 'A', 'B', 'A'), scheduled_at=datetime(2025, 1, 1, 8, tzinfo=timezone.utc))
    late = replace(match_factory('a', 'A', 'B', 'B'), scheduled_at=early.scheduled_at + timedelta(hours=10))
    # A different timezone must not split the same UTC day.
    late.scheduled_at = late.scheduled_at.astimezone(timezone(timedelta(hours=8)))
    training_builder, replay_builder = FeatureBuilder(), FeatureBuilder()
    frame = training_builder.build_training_frame([late, early])
    replay_builder.replay([late, early])
    assert list(frame.match_id) == ['z', 'a']
    assert (frame.data_depth == 0).all()
    future = match_factory('future', 'A', 'B', None, day=3)
    assert training_builder.snapshot(future) == replay_builder.snapshot(future)


def test_backtest_rejects_duplicate_event_before_features(match_factory):
    a = replace(match_factory('a', 'A', 'B', 'A'), provider_payload={'id': 1})
    with pytest.raises(ValueError, match='Duplicate'):
        backtest_service.walk_forward_backtest([a, replace(a, match_id='b')])


def test_backtest_enforces_training_eligibility_and_rank_policy(monkeypatch, match_factory):
    a = replace(match_factory('a', 'A', 'B', 'A'), player1_rank=10, player2_rank=80)
    b = replace(a, match_id='invalid', stats={'p1_aces': 'bad'})
    c = replace(a, match_id='future', scheduled_at=datetime.now(timezone.utc) + timedelta(days=1))
    expected = training._enforce_rank_provenance(training.audit_history([a, b, c])[0])[0]
    def capture(self, matches):
        assert matches == expected
        assert matches[0].player1_rank is None
        raise RuntimeError('policy_checked')
    monkeypatch.setattr(FeatureBuilder, 'build_training_frame', capture)
    with pytest.raises(RuntimeError, match='policy_checked'):
        backtest_service.walk_forward_backtest([a, b, c])


def test_prediction_requires_post_deploy_confirmation(match_factory):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    soon = replace(match_factory('soon', 'A', 'B', None), scheduled_at=start + timedelta(seconds=5))
    later = replace(soon, match_id='later', scheduled_at=start + timedelta(hours=1))
    model = SimpleNamespace(version='test', predict_proba=lambda frame: np.full(len(frame), .7))
    drafts = predict(model, [], [soon, later], start)
    records = reconcile_ledger([], drafts, [], start)
    assert all(row['issued_at'] is None for row in records)
    publication = start + timedelta(seconds=10)
    confirmed = confirm_publication(records, {'soon', 'later'}, publication)
    by_id = {row['id']: row for row in confirmed}
    assert by_id['soon']['issued_at'] is None
    assert by_id['soon']['excluded_reason'] == 'not_confirmed_before_start'
    assert by_id['later']['issued_at'] == publication.isoformat()
    again = confirm_publication(confirmed, {'later'}, publication + timedelta(seconds=5))
    assert next(row for row in again if row['id'] == 'later')['issued_at'] == publication.isoformat()


def test_refresh_checkpoints_before_next_day_failure(match_factory, tmp_path):
    calls, published = [], []
    def fetch(tour, day, historical):
        calls.append((tour, day))
        if day.day == 2:
            assert len(published) == 2
            raise RuntimeError('later day failed')
        return [match_factory(tour, 'A', 'B', 'A', tour=tour)]
    def upload(paths):
        published.append({p.name: p.read_bytes() for p in paths})
    with pytest.raises(RuntimeError, match='later day failed'):
        pipeline._refresh_history(SimpleNamespace(matches_for_day=fetch), [], tmp_path,
                                  SimpleNamespace(upload_bundle=upload),
                                  datetime(2025, 1, 1).date(), datetime(2025, 1, 2).date())
    assert len(load_partitions(tmp_path)) == 2
    assert 'history_manifest.json' in published[-1]


def fake_release(monkeypatch, tmp_path):
    assets = {}
    def gh(*args):
        if args[:2] == ('release', 'view'):
            return json.dumps({'assets': [{'name': name} for name in assets]})
        if args[:2] == ('release', 'download'):
            name = args[args.index('--pattern') + 1]
            destination = Path(args[args.index('--dir') + 1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / name).write_bytes(assets[name])
        elif args[:2] == ('release', 'upload'):
            for path in args[3:args.index('--repo')]:
                path = Path(path)
                assets[path.name] = path.read_bytes()
        else:
            raise AssertionError(args)
        return ''
    monkeypatch.setattr(release_store, 'gh', gh)
    store = object.__new__(release_store.ReleaseStore)
    store.directory, store.repository, store.tag = tmp_path, 'test/private', 'test-v1'
    return store, assets


def test_partial_bundle_preserves_remote_checksums_and_required_download(monkeypatch, tmp_path):
    store, assets = fake_release(monkeypatch, tmp_path)
    model, ledger = tmp_path / 'model.joblib', tmp_path / 'ledger.json'
    model.write_bytes(b'model')
    ledger.write_bytes(b'ledger')
    store.upload_bundle([model])
    # A stale local manifest must never overwrite another release's entries.
    (tmp_path / store.BUNDLE_MANIFEST).write_text('{"files": {"alien": {}}}')
    store.upload_bundle([ledger])
    manifest = json.loads(assets[store.BUNDLE_MANIFEST])
    assert set(manifest['files']) == {'model.joblib', 'ledger.json'}
    model.unlink()
    store.download(required_names=('model.joblib',))
    assert model.read_bytes() == b'model'
    assets['model.joblib'] = b'corrupt'
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        store.download(required_names=('model.joblib',))


@pytest.mark.parametrize('manifest', [None, {'files': {}}, {'files': {'model.joblib': {'sha256': ''}}}])
def test_required_assets_require_checksum_coverage(monkeypatch, tmp_path, manifest):
    store, assets = fake_release(monkeypatch, tmp_path)
    assets['model.joblib'] = b'model'
    if manifest is not None:
        assets[store.BUNDLE_MANIFEST] = json.dumps(manifest).encode()
    with pytest.raises((RuntimeError, FileNotFoundError), match='manifest|checksum coverage'):
        store.download(required_names=('model.joblib',))


@pytest.mark.parametrize('delay', ['120', '75.5'])
def test_retry_after_full_delay_precedes_retry(monkeypatch, delay):
    elapsed, requests = [], []
    def transport(request):
        requests.append(sum(elapsed))
        if len(requests) == 1:
            return httpx.Response(429, headers={'Retry-After': delay})
        assert sum(elapsed) >= float(delay)
        return httpx.Response(200, json={'ok': True})
    provider = RapidTennisClient(replace(pipeline.settings, rapidapi_key='test'))
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(provider, '_throttle', lambda: None)
    monkeypatch.setattr('tbt.providers.rapidapi.time.sleep', elapsed.append)
    try:
        assert provider._get('/test') == {'ok': True}
        assert requests == [0, float(delay)]
    finally:
        provider.client.close()


def gate_report():
    return {'holdout': {'n': 250},
            'delta_vs_elo': {'accuracy': .01, 'log_loss': -.02, 'brier_score': -.01, 'ece_10': -.01},
            'production_holdout': {'n': 250},
            'delta_vs_production': {'accuracy': 0, 'log_loss': -.01, 'brier_score': 0, 'ece_10': 0},
            'evaluation_governance': {'production_present': True}}


def test_gate_blocks_worse_than_champion_even_when_better_than_elo():
    report = gate_report()
    assert pipeline._promotion_metric_gate(report)[0]
    report['delta_vs_production']['log_loss'] = .01
    ok, reasons = pipeline._promotion_metric_gate(report)
    assert not ok and 'log_loss_worse_than_production' in reasons
    report['production_holdout']['n'] = 249
    assert 'production_evaluation_set_mismatch' in pipeline._promotion_metric_gate(report)[1]


def test_evaluation_excludes_champion_seen_days_and_overlapping_decisions():
    frame = pd.DataFrame({'match_id': ['a', 'b', 'c'], 'scheduled_at': pd.to_datetime(
        ['2025-01-01T20:00Z', '2025-01-02T20:00Z', '2025-01-03T20:00Z'])})
    champion = SimpleNamespace(metadata={'history_end': '2025-01-01T12:00Z'})
    previous = [{'holdout_fingerprint': 'different', 'holdout_period': {'end': '2025-01-02T12:00Z'}}]
    eligible, reason = training._eligible_evaluation(frame, champion, previous)
    assert list(eligible.match_id) == ['c'] and reason is None
    assert training._eligible_evaluation(frame, SimpleNamespace(metadata={}))[0].empty
    assert training._eligible_evaluation(frame, champion, [{}])[0].empty


@pytest.mark.parametrize('promote,passing', [(False, False), (True, False), (False, True), (True, True)])
def test_all_holdout_decisions_persist_before_promotion(monkeypatch, tmp_path, promote, passing):
    published = []
    class Store:
        def __init__(self, repository, tag, directory):
            self.tag, self.directory = tag, directory
            directory.mkdir(parents=True, exist_ok=True)
        def _asset_names(self):
            return set()
        def download(self, *args, **kwargs):
            pass
        def upload_bundle(self, paths):
            history = json.loads(next(p for p in paths if p.name == 'promotion_history.json').read_text())
            published.append((self.tag, history))
    report = gate_report()
    report['evaluation_governance'].update(holdout_fingerprint='fingerprint', production_present=False)
    report['periods'] = {'holdout': {'start': '2025-01-01T00:00Z', 'end': '2025-02-01T00:00Z'}}
    if not passing:
        report['delta_vs_elo']['log_loss'] = .1
    monkeypatch.setattr(pipeline, 'ROOT', tmp_path)
    monkeypatch.setattr(pipeline, 'ReleaseStore', Store)
    monkeypatch.setattr(pipeline, 'load_partitions', lambda path: [])
    monkeypatch.setattr(pipeline, 'train_from_matches', lambda *args, **kwargs:
                        SimpleNamespace(model=SimpleNamespace(version='candidate'), report=report))
    monkeypatch.setattr(pipeline, 'save_model', lambda model, path: Path(path).write_bytes(b'model'))
    monkeypatch.setattr('sys.argv', ['pipeline', 'train'] + (['--promote'] if promote else []))
    if promote and not passing:
        with pytest.raises(SystemExit, match='refused'):
            pipeline.main()
    else:
        pipeline.main()
    assert published[0][0] == 'tbt-model-candidate-v1'
    decision = published[0][1][0]
    assert decision['eligible'] is passing
    assert pipeline._holdout_already_used(published[0][1], 'fingerprint')
    assert len(published) == (2 if promote and passing else 1)


def test_release_upload_does_not_backdate_issuance(monkeypatch, tmp_path, match_factory):
    start = datetime.now(timezone.utc)
    later = replace(match_factory('later', 'A', 'B', None), scheduled_at=start + timedelta(hours=1))
    model = SimpleNamespace(version='test', predict_proba=lambda frame: np.full(len(frame), .7))
    drafts = predict(model, [], [later], start)
    store, assets = fake_release(monkeypatch, tmp_path)
    feed = pipeline._publish_predictions(store, [], drafts, [], model, {}, [later])
    records = json.loads(assets['ledger.json'])
    assert records[0]['issued_at'] is None
    assert records[0]['publication_status'] == 'pending'
    assert feed['upcoming'][0]['issued_at'] is None


def test_candidate_and_production_score_identical_unseen_rows_without_refit(monkeypatch, match_factory):
    fits, scored, candidates = [], {}, []
    class Candidate:
        version = 'candidate'
        blend_weight = .5
        calibrator = SimpleNamespace(kind='identity')
        def __init__(self):
            self.metadata = {}
            candidates.append(self)
        def fit(self, train, calibration):
            fits.append((train.copy(), calibration.copy()))
            return self
        def predict_proba(self, frame):
            scored['candidate'] = frame.copy()
            return np.full(len(frame), .6)
    class Champion:
        version = 'production'
        metadata = {'history_end': '2024-09-20T00:00:00Z'}
        def predict_proba(self, frame):
            scored['production'] = frame.copy()
            return np.full(len(frame), .55)
    monkeypatch.setattr(training, 'TennisEnsemble', Candidate)
    matches = [replace(match_factory(str(i), 'A', 'B', 'A' if i % 2 else 'B'),
                       scheduled_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4))
               for i in range(1200)]
    result = training.train_from_matches(matches, min_matches=1000, production_model=Champion())
    assert len(candidates) == len(fits) == 1
    assert result.model is candidates[0]
    pd.testing.assert_frame_equal(scored['candidate'], scored['production'])
    evaluated = scored['candidate']
    assert len(evaluated) > 0
    assert evaluated.scheduled_at.min() > pd.Timestamp(Champion.metadata['history_end'])
    assert fits[0][1].scheduled_at.max() < evaluated.scheduled_at.min()
    assert not set(evaluated.match_id) & (set(fits[0][0].match_id) | set(fits[0][1].match_id))
    assert pd.Timestamp(result.model.metadata['history_end']) == fits[0][1].scheduled_at.max()


def test_no_unseen_rows_refuses_promotion_without_scoring_champion(monkeypatch, match_factory):
    class Candidate:
        version = 'candidate'
        blend_weight = .5
        calibrator = SimpleNamespace(kind='identity')
        metadata = {}
        def fit(self, train, calibration):
            return self
        def predict_proba(self, frame):
            assert frame.empty
            return np.array([])
    class Champion:
        version = 'production'
        metadata = {'history_end': '2025-01-01T00:00:00Z'}
        def predict_proba(self, frame):
            raise AssertionError('Seen data must not be scored')
    monkeypatch.setattr(training, 'TennisEnsemble', Candidate)
    matches = [replace(match_factory(str(i), 'A', 'B', 'A' if i % 2 else 'B'),
                       scheduled_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4))
               for i in range(1200)]
    result = training.train_from_matches(matches, min_matches=1000, production_model=Champion())
    assert result.report['holdout'] == {}
    assert not pipeline._promotion_metric_gate(result.report)[0]


def test_history_rejects_missing_match_identity(match_factory):
    broken = replace(match_factory('x', 'A', 'B', 'A'), match_id='')
    with pytest.raises(ValueError, match='match identity'):
        training.audit_history([broken])



def test_provider_daily_dedupe_preserves_conflicting_provider_events(monkeypatch, match_factory):
    client = RapidTennisClient.__new__(RapidTennisClient)
    client.calendar_categories = lambda day: [{"id": 3, "name": "ATP"}]
    client._category_id = lambda category: 3
    client._category_tour = lambda category: "atp"
    client.category_events = lambda category_id, day: [
        {"id": 101, "homeTeam": {"id": "A", "name": "A"}, "awayTeam": {"id": "B", "name": "B"}},
        {"id": 202, "homeTeam": {"id": "A", "name": "A"}, "awayTeam": {"id": "B", "name": "B"}},
    ]
    client._is_singles_event = lambda raw: True
    client._event_tour = lambda raw, category_id, category_name: "atp"
    base = match_factory("collision", "A", "B", "A")

    def normalize(raw, tour, historical):
        provider_id = str(raw["_tbt_provider_event_id"])
        return replace(
            base,
            tournament="One" if provider_id == "101" else "Two",
            scheduled_at=base.scheduled_at + (timedelta(hours=0) if provider_id == "101" else timedelta(hours=3)),
            provider_payload={"_tbt_provider_event_id": provider_id},
        )

    client.normalize_match = normalize
    rows = client.matches_for_day("atp", base.scheduled_at.date(), historical=True)
    assert len(rows) == 2
    assert {row.provider_payload["_tbt_provider_event_id"] for row in rows} == {"101", "202"}


def test_release_download_fails_when_history_manifest_partition_is_missing(monkeypatch, tmp_path):
    store, assets = fake_release(monkeypatch, tmp_path)
    history_manifest = {
        "years": {
            "2024": {"asset": "history-2024.parquet"},
            "2025": {"asset": "history-2025.parquet"},
        }
    }
    assets["history_manifest.json"] = json.dumps(history_manifest).encode()
    assets["history-2024.parquet"] = b"present"
    bundle_manifest = {
        "files": {
            "history_manifest.json": {"sha256": hashlib.sha256(assets["history_manifest.json"]).hexdigest()},
            "history-2024.parquet": {"sha256": hashlib.sha256(assets["history-2024.parquet"]).hexdigest()},
        }
    }
    assets[store.BUNDLE_MANIFEST] = json.dumps(bundle_manifest).encode()
    with pytest.raises(FileNotFoundError, match="history-2025.parquet"):
        store.download()


def test_load_partitions_fails_closed_when_manifest_requires_missing_year(tmp_path):
    (tmp_path / "history_manifest.json").write_text(json.dumps({
        "years": {"2024": {"asset": "history-2024.parquet"}, "2025": {"asset": "history-2025.parquet"}}
    }))
    with pytest.raises(FileNotFoundError, match="history-2024.parquet"):
        load_partitions(tmp_path)


def test_live_prediction_rejects_duplicate_provider_event_history(match_factory):
    start = datetime(2025, 1, 3, 12, tzinfo=timezone.utc)
    historical = replace(
        match_factory("a", "A", "B", "A", day=1),
        provider_payload={"id": 77},
    )
    duplicate = replace(historical, match_id="b")
    future = replace(match_factory("future", "A", "B", None, day=4), scheduled_at=start + timedelta(hours=1))
    model = SimpleNamespace(version="test", predict_proba=lambda frame: np.full(len(frame), .7))
    with pytest.raises(ValueError, match="Duplicate"):
        predict(model, [historical, duplicate], [future], start)


def test_empty_first_history_download_publishes_progress_without_missing_bundle(monkeypatch, tmp_path):
    uploaded = []

    class Store:
        def __init__(self, *args):
            pass
        def download(self):
            pass
        def upload_bundle(self, paths):
            paths = list(paths)
            assert all(path.is_file() for path in paths)
            uploaded.append([path.name for path in paths])

    class Provider:
        def __init__(self, request_budget):
            assert request_budget is None
            self.request_count = 0
            self.request_limit = None
            self.client = SimpleNamespace(close=lambda: None)
        def matches_for_day(self, tour, day, historical):
            self.request_count += 1
            return []

    import download_tennis_history as downloader
    monkeypatch.setattr(downloader, "ReleaseStore", Store)
    monkeypatch.setattr(downloader, "RapidTennisClient", Provider)
    monkeypatch.setattr(downloader, "settings", replace(downloader.settings, rapidapi_key="test"))
    monkeypatch.setattr("sys.argv", ["download", "--start", "2025-01-01", "--end", "2025-01-01",
        "--history-dir", str(tmp_path), "--max-requests", "10", "--publish", "--data-repository", "test/private"])
    downloader.main()
    assert uploaded
    assert all("history-2025.parquet" not in batch for batch in uploaded)
    assert all("history_manifest.json" not in batch for batch in uploaded)
    assert "download_progress.json" in uploaded[-1]


def test_workflows_confirm_publication_and_share_deploy_lock():
    root = Path(__file__).resolve().parents[1]
    data = (root / ".github/workflows/data.yml").read_text()
    ci = (root / ".github/workflows/ci.yml").read_text()
    assert "download_environment.py" not in data
    assert "backfill_venue_context.py" not in data
    assert data.count("group: tbt-history-data-writer") >= 1
    assert ci.count("group: tbt-history-data-writer") >= 1
    assert "confirm_prediction_publication.py" in data
    assert "confirm_prediction_publication.py" in ci
    assert "--deployed-feed api/data/feed.json" in data
    assert "--deployed-feed api/data/feed.json" in ci
