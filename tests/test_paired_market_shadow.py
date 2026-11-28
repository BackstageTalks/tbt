"""Common-cutoff receipts and read-only paired scoring."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import gzip
import json
from types import SimpleNamespace

import pytest

from paired_market_shadow import FIELD, build_capture, compare, verified_captures
from test_market_rank_shadow import DAY, HASH, NOW, src
from test_remaining_regressions import fake_release
from tbt.schemas import MatchRecord


CANDIDATE_HASH = "b" * 64


def fixture(*, event="a", p=.70, odds=1.6, opposite=2.4, tour="ATP"):
    champion = src(event, p=p, odds=odds, opponent=opposite)
    champion.update(tour=tour, blinq_probability=.5 + (max(p, 1 - p) - .5) * .9)
    champion["match_winner_market"]["captured_at"] = champion["betting"]["captured_at"]
    candidate = deepcopy(champion)
    candidate["model_version"] = "candidate"
    candidate["player1"]["probability"] = .77
    return champion, candidate


def capture(champion, candidate, *, history=None, sections=None, clock=NOW,
            candidate_hash=CANDIDATE_HASH):
    return build_capture(
        history or {"snapshots": []}, champion, candidate, sections or {},
        observed_at=clock, public_offer_day=DAY, champion_sha256=HASH,
        candidate_sha256=candidate_hash,
    )


def outcome(row, **changes):
    start = NOW + timedelta(hours=3)
    match = MatchRecord(
        match_id=row["id"], tour=row["tour"].lower(), scheduled_at=start,
        player1_id="p1", player1_name="Alpha", player2_id="p2", player2_name="Beta",
        winner_id="p1", status="finished",
    )
    return replace(match, **changes)


def test_capture_reads_both_models_and_raw_two_way_odds_without_mutating_inputs():
    champion, candidate = fixture()
    before = deepcopy((champion, candidate))
    receipt, counts = capture([champion], [candidate], sections={"top_daily_picks": [champion]})
    assert (champion, candidate) == before
    assert counts["new_priced_pairs"] == 1
    assert receipt["research_only"] is True
    assert receipt["champion_sha256"] == HASH
    assert receipt["candidate_sha256"] == CANDIDATE_HASH
    row, = receipt["rows"]
    assert row["market_p1"] == pytest.approx(.6)
    assert row["production_player1_probability"] == .70
    assert row["challenger_player1_probability"] == .77
    assert row["sections"] == {"top": "p1"}
    assert "winner_id" not in row and "target_player1_win" not in row


@pytest.mark.parametrize("issue", ["late", "late_quote", "market_timestamp_mismatch",
                                   "wrong_price", "wrong_selected_price", "unknown_book", "reordered",
                                   "duplicate", "candidate_time", "next_day"])
def test_ineligible_or_ambiguous_rows_do_not_create_a_receipt(issue):
    champion, candidate = fixture()
    pairs = [candidate]
    clock = NOW
    if issue == "late":
        clock += timedelta(hours=2, minutes=55)
    elif issue == "late_quote":
        captured = (NOW + timedelta(minutes=1)).isoformat()
        champion["match_winner_market"]["captured_at"] = captured
        champion["betting"]["captured_at"] = captured
    elif issue == "market_timestamp_mismatch":
        champion["match_winner_market"]["captured_at"] = NOW.isoformat()
    elif issue == "wrong_price":
        champion["match_winner_market"]["player2_odds"] = 1.22
    elif issue == "wrong_selected_price":
        champion["betting"]["odds"] = 1.22
    elif issue == "unknown_book":
        champion["match_winner_market"]["source_id_known"] = False
    elif issue == "reordered":
        candidate["player1"], candidate["player2"] = candidate["player2"], candidate["player1"]
    elif issue == "duplicate":
        pairs.append(candidate)
    elif issue == "candidate_time":
        candidate["created_at"] = NOW.isoformat()
    else:
        champion["scheduled_at"] = candidate["scheduled_at"] = "2026-09-08T12:00:00Z"
    receipt, counts = capture([champion], pairs, clock=clock)
    assert receipt is None and counts["new_priced_pairs"] == 0


def test_retries_preserve_first_prices_and_a_new_hash_starts_its_own_cohort():
    champion, candidate = fixture()
    first, _ = capture([champion], [candidate])
    history = {"snapshots": [{FIELD: first}]}
    next_receipt, counts = capture([champion], [candidate], history=history)
    assert next_receipt is None and counts["already_captured"] == 1
    new, _ = capture([champion], [candidate], history=history, candidate_hash="c" * 64)
    assert new["candidate_sha256"] != first["candidate_sha256"]
    assert list(verified_captures(history)) == [first]


def test_report_is_paired_void_safe_and_keeps_original_immutable_receipt():
    top, top_challenger = fixture()
    other, other_challenger = fixture(event="b", p=.25, odds=2.4, opposite=1.6, tour="WTA")
    missing, missing_candidate = fixture(event="c")
    receipt, _ = capture(
        [top, other, missing], [top_challenger, other_challenger, missing_candidate],
        sections={"top_daily_picks": [top, other], "prime_picks": [missing]},
    )
    history = {"snapshots": [{FIELD: receipt}]}
    before = deepcopy(history)
    clock = NOW + timedelta(hours=6)
    results = [
        outcome(top),
        outcome(other, status="finished", provider_payload={"_tbt_termination": {"reason": "retired"}}),
        outcome(missing, player2_id="different"),
    ]
    report = compare([history, history], results, asof=clock)
    assert report["automatic_promotion"] is False
    cohort, = report["cohorts"]
    assert cohort["outcomes"] == {"settled": 1, "void": 1, "pending": 1}
    assert cohort["all"]["n"] == cohort["issued_policy_cohorts"]["top"]["n"] == 1
    assert cohort["by_tour"]["WTA"]["n"] == 0
    assert cohort["top_veto_no_refill"]["0.6"]["kept"] == 1
    assert cohort["top_veto_no_refill"]["0.6"]["flat_stake_roi"] == pytest.approx(.6)
    assert cohort["minimum_400_met"] is False
    assert history == before
    json.dumps(report, allow_nan=False)

    receipt["rows"][0]["market_p1"] = .51
    with pytest.raises(ValueError, match="digest"):
        compare([history], results, asof=clock)


def test_refresh_uploads_and_independently_reads_private_capture_without_changing_feed(
    monkeypatch, tmp_path, capsys,
):
    import pipeline
    import prepare_feed

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(pipeline, "datetime", FrozenClock)
    monkeypatch.setattr(prepare_feed, "_read_confirmed_telegram_state",
                        lambda _: {"schema": 1, "attempts": {}})
    monkeypatch.setenv("TBT_OFFER_SHADOW_DISABLED", "true")
    monkeypatch.setenv("TBT_MARKET_RANK_SHADOW_ENABLED", "false")
    champion, candidate = fixture()
    upcoming = outcome(champion, winner_id=None, status="scheduled",
                       provider_payload={"id": champion["event_id"]})
    model = SimpleNamespace(version=champion["model_version"])
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"test candidate bytes")
    store, assets = fake_release(monkeypatch, tmp_path)
    def reader(repository, tag, directory):
        instance = object.__new__(type(store))
        instance.repository, instance.tag, instance.directory = repository, tag, directory
        return instance

    monkeypatch.setattr(pipeline, "ReleaseStore", reader)
    args = (store, [], [champion], [], model, {}, [upcoming])
    monkeypatch.delenv("TBT_PAIRED_MARKET_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("BLINQ_POINT_SG_SHADOW", raising=False)
    baseline = pipeline._publish_predictions(*args)
    baseline_bytes = bytes(assets["feed.json"])
    monkeypatch.setenv("BLINQ_POINT_SG_SHADOW", "true")
    monkeypatch.setenv("TBT_PAIRED_MARKET_SHADOW_ENABLED", "true")
    enabled = pipeline._publish_predictions(
        *args, champion_sha256=HASH, paired_candidate_predictions=[candidate],
        paired_candidate_path=artifact,
    )
    assert assets["feed.json"] == baseline_bytes
    assert enabled == baseline
    assert not any(FIELD in assets[name].decode() for name in ("feed.json", "ledger.json"))
    history = json.loads(gzip.decompress(assets["selection_candidates_2026-09.json.gz"]))
    receipt, = verified_captures(history)
    assert len(receipt["rows"]) == 1
    assert "PRIVATE_READBACK_VERIFIED" in capsys.readouterr().out
