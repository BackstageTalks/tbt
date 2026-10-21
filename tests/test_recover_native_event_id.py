"""Adversarial, network-free controls for first-party native event-ID recovery."""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from scripts.recover_native_event_id import candidate_days, eligible, recover_day, identity_gap_inventory


@dataclass
class Match:
    match_id: str
    tour: str = "wta"
    player1_id: str = "111"
    player2_id: str = "222"
    winner_id: str = "111"
    round_name: str = "Quarterfinal"
    scheduled_at: datetime = datetime(2025, 4, 10, 13, tzinfo=timezone.utc)
    provider_payload: dict | None = None
    stats: dict | None = None
    surface: str = "hard"
    is_completed: bool = True

    def __post_init__(self):
        if self.provider_payload is None:
            self.provider_payload = {"_tbt_source_category_id": "456"}
        if self.stats is None:
            self.stats = {}


def native(e="900", **overrides):
    context = {
        "_tbt_source_category_id": "456", "_tbt_provider_event_id": e,
        "_tbt_event_identity": {
            "event_id": e, "home": "111", "away": "222", "status": "finished",
        },
    }
    context.update(overrides)
    return Match("native" + e, provider_payload=context)


def test_recover_unique_and_idempotent():
    m = Match("canonical")
    before_stats = dict(m.stats)
    changes, report = recover_day([m], [native()], day=date(2025, 4, 10))
    assert report["recovered"] == 1 and len(changes) == 1
    assert m.provider_payload["_tbt_provider_event_id"] == "900"
    assert m.stats == before_stats
    assert recover_day([m], [native()], day=date(2025, 4, 10))[1].get("recovered", 0) == 0


def test_wrong_provider_scope():
    m = Match("canonical", provider_payload={})
    assert not eligible(m)
    assert not recover_day([m], [native()], day=date(2025, 4, 10))[0]


def test_many_canonical_one_native_quarantined():
    a, b = Match("a"), Match("b")
    out, stats = recover_day([a, b], [native()], day=date(2025, 4, 10))
    assert not out and stats["quarantine_many_canonical_to_one_native"] == 2
    assert "_tbt_provider_event_id" not in a.provider_payload


def test_ambiguous_provider_events_quarantined():
    a = Match("a")
    out, stats = recover_day([a], [native("900"), native("901")], day=date(2025, 4, 10))
    assert not out and stats["unresolved_no_unique_native_event"] == 1


def test_reject_winner_round_surface_conflicts():
    a = Match("a")
    p = native()
    p.winner_id = "222"
    assert not recover_day([a], [p], day=date(2025, 4, 10))[0]
    p = native()
    p.round_name = "Final"
    assert not recover_day([a], [p], day=date(2025, 4, 10))[0]
    p = native()
    p.surface = "clay"
    assert not recover_day([a], [p], day=date(2025, 4, 10))[0]


def test_original_id_never_overwritten():
    a = Match("a", provider_payload={"_tbt_source_category_id": "456", "event_id": "901"})
    assert not eligible(a)
    out, _ = recover_day([a], [native("900")], day=date(2025, 4, 10))
    assert not out and a.provider_payload["event_id"] == "901"


def test_provider_id_already_claimed():
    a = Match("a")
    b = Match("b", provider_payload={
        "_tbt_source_category_id": "456", "_tbt_provider_event_id": "900"})
    out, report = recover_day([a, b], [native("900")], day=date(2025, 4, 10))
    assert not out and report["quarantine_provider_id_claimed_elsewhere"] == 1


def test_no_native_participant_witness():
    a, p = Match("a"), native()
    p.provider_payload.pop("_tbt_event_identity")
    assert not recover_day([a], [p], day=date(2025, 4, 10))[0]
    p = native()
    p.provider_payload["_tbt_event_identity"]["away"] = "999"
    assert not recover_day([a], [p], day=date(2025, 4, 10))[0]


def test_recent_first_and_negative_cooldown():
    rows = [
        Match("old", scheduled_at=datetime(2023, 3, 4, 13, tzinfo=timezone.utc)),
        Match("new", scheduled_at=datetime(2025, 4, 10, 13, tzinfo=timezone.utc)),
    ]
    days = candidate_days(rows, start=date(2023, 1, 1), end=date(2026, 10, 1))
    assert [str(x[0]) for x in days] == ["2025-04-10", "2023-03-04"]
    days = candidate_days(rows, start=date(2023, 1, 1), end=date(2026, 10, 1),
                          attempts={"2025-04-10": {"at": "2026-10-20", "recovered": 0}},
                          today=date(2026, 10, 21))
    assert str(days[0][0]) == "2023-03-04"


def test_inventory_distinguishes_missing_scope_conflicts_cooldown_and_day_cap():
    examples = [
        Match("no-cat", provider_payload={}),
        Match("same-person", player2_id="111"),
        Match("bad-winner", winner_id="333"),
        Match("bad-round", round_name=""),
        Match("foreign-claim", provider_payload={"_tbt_source_category_id": "456",
                                                  "event_id": "foreign-alpha"}),
        Match("eligible"),
        Match("cooldown", scheduled_at=datetime(2025, 4, 11, 13, tzinfo=timezone.utc)),
        Match("old", scheduled_at=datetime(2023, 4, 11, 13, tzinfo=timezone.utc)),
        Match("already-known", provider_payload={"_tbt_source_category_id": "456",
                                                  "_tbt_provider_event_id": "900"}),
    ]
    report = identity_gap_inventory(
        examples, start=date(2023, 1, 1), end=date(2026, 10, 21),
        attempts={"2025-04-11": {"at": "2026-10-20", "recovered": 0}},
        today=date(2026, 10, 21), max_days=1,
    )
    assert report["canonical_missing_or_conflicting_id_rows"] == 8
    assert report["primary_blockers"] == {
        "eligible_native_calendar": 3,
        "existing_unusable_or_conflicting_event_claims": 1,
        "missing_first_party_category": 1,
        "missing_or_colliding_player_ids": 1,
        "missing_round": 1,
        "winner_outside_pair": 1,
    }
    assert report["eligible_native_calendar_rows"] == 3
    assert report["cooldown_blocked_days"] == 1
    assert report["cooldown_blocked_rows"] == 1
    assert report["scheduled_days"] == 1
    assert report["scheduled_eligible_rows"] == 1
    assert report["eligible_rows_outside_top_day_limit"] == 1
    assert report["native_provider_requests"] == report["cdb_writes"] == 0
    assert all("_tbt_provider_event_id" not in m.provider_payload for m in examples[:8])
    assert report["identity_attested_by_audit"] is False


def test_inventory_rejects_corrupt_persisted_identity_cooldown():
    with __import__("pytest").raises(ValueError, match="Invalid persisted identity cooldown"):
        identity_gap_inventory(
            [Match("blocked")], start=date(2025, 1, 1), end=date(2026, 1, 1),
            attempts={"2025-04-10": {"at": "not-date", "recovered": "x"}},
            today=date(2026, 10, 21),
        )


def test_production_identity_mode_keeps_provider_reserve_and_header_attestation():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/data.yml").read_text(encoding="utf-8")
    clause = workflow.split('if [[ "$mode" == "identity" ]]; then', 1)[1]
    clause = clause.split("          fi", 1)[0]
    assert 'BLINQ_PROVIDER_REQUEST_RESERVE=500' in clause
    assert 'BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER=true' in clause
    assert 'python scripts/verify_native_event_ids.py' in workflow
