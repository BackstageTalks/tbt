from copy import deepcopy
from datetime import date

import pytest

from aces_line_first import choose_line, price_contract, select_candidate
from stage_aces_offer_cdb import stage
from test_propline_evening_quotes import card, source, report, DAY, MORNING, CAPTURE
from propline_evening_odds import collect


def fixture(mean=5, line=3.5):
    data = source()
    # Existing parser fixture: first sportsbook prices Ben Shelton.
    for book in data["events"][0]["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                if "point" in outcome:
                    outcome["point"] = line
    row = card()
    row["projection"] = mean
    row["opponent_projection"] = None
    return row, report(data)


@pytest.mark.parametrize("mean,line,side", [(5, 3.5, "over"), (10.5, 12.5, "under")])
def test_required_examples(mean, line, side):
    row, archive = fixture(mean, line)
    result = select_candidate([row], archive, now=MORNING, betting_day=DAY)
    pick, = result["picks"]
    assert (pick["projection"], pick["ou_side"], pick["market_line"]) == (mean, side, line)
    assert 0.5 < pick["probability"] < 1
    assert pick["odds_source"] == "propline"


def test_no_offer_excluded_top_value_and_input_unchanged():
    row = card()
    top, value = {"market": "top", "odds": 1.7}, {"market": "value", "odds": 2.1}
    rows = [row, top, value]
    before = deepcopy(rows)
    result = select_candidate(rows, None, now=MORNING, betting_day=DAY)
    assert result["picks"] == [top, value]
    assert result["diagnostics"][0]["status"] == "bez ponuky"
    assert rows == before


def test_over_preference_and_nearest_real_cushion():
    offers = [{"line": line, "side": side} for line, side in
              [(1.5, "over"), (3.5, "over"), (7.5, "under"), (4.5, "over")]]
    assert choose_line(5, offers)["line"] == 3.5
    assert choose_line(5, [{"line": 4.5, "side": "over"}]) is None


@pytest.mark.parametrize("line", [float("nan"), float("inf"), True, -1, 3])
def test_invalid_or_push_lines_rejected(line):
    assert choose_line(5, [{"line": line, "side": "over"}]) is None


def test_prices_exact_contract_and_local_fallback(monkeypatch):
    row = card()
    offer = {"line": 3.5, "side": "over", "odds": 1.8}
    monkeypatch.setattr("aces_line_first.extract_player_total_ou", lambda *a, **k:
        [{"line": 4.5, "over": 3.0}, {"line": 3.5, "over": 2.0}])
    assert price_contract(row, 2, offer, {}) == (2.0, "rapidapi")
    monkeypatch.setattr("aces_line_first.extract_player_total_ou", lambda *a, **k:
        [{"line": 4.5, "over": 3.0}])
    assert price_contract(row, 2, offer, {}) == (1.8, "propline")
    offer["odds"] = None
    price, kind = price_contract(row, 2, offer, {})
    assert 1.6 <= price <= 1.8
    assert kind == "local_aces_statistical_v1"


def test_opponent_projection_can_win():
    row, archive = fixture()
    row.update(selection_id="p1", projection=0, opponent_projection=5)
    result = select_candidate([row], archive, now=MORNING, betting_day=DAY)
    assert result["picks"][0]["selection_id"] == "p2"
    assert result["picks"][0]["projection"] == 5


def test_duplicate_fixture_detail_requested_once_and_candidate_never_calls(monkeypatch):
    data = source()
    data["events"].append(deepcopy(data["events"][0]))
    calls = []
    def detail(event_id):
        calls.append(event_id)
        return data["events"][0], 400
    archive = collect(date.fromisoformat(DAY), now=CAPTURE,
                      get=lambda: (data, 420), get_event=detail)
    assert len(calls) == 1
    assert archive["duplicate_event_rows_skipped"] == 1
    def forbidden(*a, **k):
        raise AssertionError("Candidate must reuse stored data, including on reruns")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    for _ in range(2):
        result = select_candidate([card()], archive, now=MORNING, betting_day=DAY)
        assert result["incremental_provider_requests"] == 0
    assert len(calls) == 1


def test_conflicting_identity_never_requested():
    data = source()
    other = deepcopy(data["events"][0])
    other["home_team"] = "Different Person"
    data["events"].append(other)
    archive = collect(date.fromisoformat(DAY), now=CAPTURE, get=lambda: (data, 420),
                      get_event=lambda _: pytest.fail("ambiguous fixture requested"))
    assert archive["conflicting_event_ids_skipped"] == 1


def test_cdb_stage_verified_evidence_and_immutable_inputs():
    archive = report()
    before = deepcopy(archive)
    payload = stage(archive, day=DAY, now=MORNING)
    assert payload["events"] and payload["incremental_provider_requests"] == 0
    assert archive == before
    broken = deepcopy(archive)
    broken["coverage_truncated"] = True
    with pytest.raises(ValueError):
        stage(broken, day=DAY, now=MORNING)


def test_ambiguous_duplicate_cards_and_stale_evidence_rejected():
    row, archive = fixture()
    assert not select_candidate([row, row], archive, now=MORNING, betting_day=DAY)["picks"]
    archive["events_in_target_window"][0]["source_sha256"] = "bad"
    assert not select_candidate([row], archive, now=MORNING, betting_day=DAY)["picks"]


def test_native_line_without_price_uses_local_statistic():
    data = source()
    for book in data["events"][0]["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                outcome["point"] = 3.5
                outcome["price"] = None
    row = card()
    row.update(projection=5, opponent_projection=None)
    result = select_candidate([row], report(data), now=MORNING, betting_day=DAY)
    pick, = result["picks"]
    assert pick["market_line"] == 3.5
    assert pick["odds_source"] == "local_aces_statistical_v1"
    assert 1.6 <= pick["odds"] <= 1.8


def test_projection_universe_does_not_require_superiority_gap(monkeypatch):
    from aces_line_first import project_candidates
    monkeypatch.setattr("tbt.services.ace_selection.ace_eligibility_reason", lambda r: "eligible")
    monkeypatch.setattr("tbt.services.ace_selection._history_index", lambda h, c: ({}, {"aces": 5}, {}))
    monkeypatch.setattr("tbt.services.ace_selection._projection", lambda *a, **k: {"estimate": 5})
    row = card()
    before = deepcopy(row)
    projected, = project_candidates([], [row], now=MORNING)
    assert projected["projection"] == projected["opponent_projection"] == 5
    assert row == before


def test_cdb_writer_idempotency_and_readback(tmp_path, monkeypatch):
    from stage_aces_offer_cdb import persist
    remote, actions = {}, []
    class Store:
        def __init__(self, repo, tag, directory):
            self.directory = directory
            directory.mkdir(parents=True, exist_ok=True)
        def _asset_names(self):
            return set(remote)
        def _download_asset(self, name):
            (self.directory / name).write_bytes(remote[name])
        def upload_bundle(self, paths):
            actions.append("upload")
            for path in paths:
                remote[path.name] = path.read_bytes()
    monkeypatch.setattr("release_store.ReleaseStore", Store)
    monkeypatch.setattr("cdb_global_writer_lock.acquire", lambda *a, **k: actions.append("lock"))
    monkeypatch.setattr("cdb_global_writer_lock.release", lambda *a, **k: actions.append("unlock"))
    path = tmp_path / "aces-offers-2026-11-18.json"
    path.write_text('{"events": []}')
    assert persist(path, work=tmp_path) == persist(path, work=tmp_path)
    assert actions == ["lock", "upload", "unlock", "lock", "unlock"]
    path.write_text('{"events": [1]}')
    with pytest.raises(RuntimeError, match="refusing overwrite"):
        persist(path, work=tmp_path)
    assert actions[-1] == "unlock"
