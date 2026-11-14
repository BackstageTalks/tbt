"""Adversarial, network-free controls for first-party native event-ID recovery."""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from scripts.recover_native_event_id import (candidate_days, eligible, recover_day,
                                             identity_gap_inventory, identity_calendar_prefetch_groups)


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


def test_claim_diagnostics_do_not_promote_or_hide_metadata_gaps():
    rows = [
        Match("unscoped", provider_payload={"event_id": "foreign-alpha"}),
        Match("native-claim", provider_payload={"_tbt_provider_event_id": "native-alpha",
                                               "_tbt_source_category_id": "456"},
              player2_id="111"),
        Match("conflict", provider_payload={"event_id": "901", "provider_event_id": "902",
                                            "_tbt_source_category_id": "456"},
              round_name=""),
    ]
    report = identity_gap_inventory(
        rows, start=date(2025, 1, 1), end=date(2025, 12, 31),
        today=date(2026, 10, 21))
    assert report["primary_blockers"]["existing_unusable_or_conflicting_event_claims"] == 3
    assert report["existing_claim_diagnostics"]["unscoped_event_claim"] == 2
    assert report["existing_claim_diagnostics"]["explicit_native_provider_claim"] == 1
    assert report["existing_claim_diagnostics"]["multiple_distinct_claim_values"] == 1
    assert report["existing_claim_diagnostics"]["non_positive_or_nonnumeric_claim"] == 2
    assert report["existing_claim_secondary_blockers"]["missing_first_party_category"] == 1
    assert report["existing_claim_secondary_blockers"]["missing_or_colliding_player_ids"] == 1
    assert report["existing_claim_secondary_blockers"]["missing_round"] == 1
    assert report["scheduled_days"] == 0
    assert report["cdb_writes"] == report["native_provider_requests"] == 0
    assert all(not eligible(m) for m in rows)

def test_grand_slam_negative_100_exact_provider_category_is_recoverable():
    for category in (-100, "-100"):
        canonical = Match("slam", provider_payload={"_tbt_source_category_id": category})
        source = native()
        source.provider_payload["_tbt_source_category_id"] = category
        assert eligible(canonical)
        updates, evidence = recover_day([canonical], [source], day=date(2025, 4, 10))
        assert evidence["recovered"] == 1
        assert updates["slam"]["category_id"] == "-100"
        assert canonical.provider_payload["_tbt_provider_event_id"] == "900"
        assert canonical.stats == {}


def test_negative_category_mismatch_and_unverified_claims_remain_blocked():
    for invalid in (-101, "-1", "-100.0", " -100", True):
        canonical = Match("invalid", provider_payload={"_tbt_source_category_id": invalid})
        assert not eligible(canonical)
        assert not recover_day([canonical], [native()], day=date(2025, 4, 10))[0]
    canonical = Match("slam", provider_payload={"_tbt_source_category_id": -100})
    assert not recover_day([canonical], [native()], day=date(2025, 4, 10))[0]


def test_native_identity_batches_only_selected_days_in_same_month():
    planned = [
        (date(2025, 4, d), ("atp",), 1)
        for d in (3, 9, 12, 18, 25, 26)
    ] + [
        (date(2026, 5, 1), ("wta",), 1),
        (date(2025, 4, 30), ("wta",), 1),
        (date(2026, 5, 8), ("wta",), 1),
        (date(2026, 6, 1), ("atp",), 1),
    ]
    groups = identity_calendar_prefetch_groups(planned)
    assert groups == {
        date(2025, 4, 3): tuple(date(2025, 4, d)
                                for d in (3, 9, 12, 18, 25)),
        date(2025, 4, 26): (date(2025, 4, 26), date(2025, 4, 30)),
        date(2026, 5, 1): (date(2026, 5, 1), date(2026, 5, 8)),
    }
    assert all(2 <= len(chunk) <= 5 for chunk in groups.values())
    assert date(2026, 6, 1) not in groups  # Lone day uses normal daily route.
    assert len({d for v in groups.values() for d in v}) == 9


def test_native_identity_batch_planner_rejects_duplicate_or_invalid_days():
    import pytest
    for planned in [
        [(date(2025, 1, 1), (), 0), (date(2025, 1, 1), (), 0)],
        [(datetime(2025, 1, 1, tzinfo=timezone.utc), (), 0)],
        [(None, (), 0)],
    ]:
        with pytest.raises(ValueError, match="native identity calendar date"):
            identity_calendar_prefetch_groups(planned)


def test_existing_native_identity_prefetch_cache_records_paid_batch_not_matches():
    from collections import Counter
    from scripts.download_tennis_history import _prefetch_native_identity_calendar

    class Provider:
        request_count = 0
        calls = []
        def prefetch_calendar_categories(self, days):
            self.calls.append(tuple(days))
            self.request_count += 1
            return len(days)

    provider, report = Provider(), Counter()
    days = (date(2025, 4, 4), date(2025, 4, 12))
    _prefetch_native_identity_calendar(provider, days, report)
    assert provider.calls == [days]
    assert report["identity_monthly_calendar_paid_requests"] == 1
    assert report["identity_monthly_calendar_cached_days"] == 2
    assert report["identity_recovered"] == 0


def test_native_identity_invalid_batch_falls_back_without_changing_id_gate():
    from collections import Counter
    from tbt.errors import ProviderError
    from scripts.download_tennis_history import _prefetch_native_identity_calendar
    class Provider:
        request_count = 0
        def prefetch_calendar_categories(self, days):
            self.request_count += 1
            raise ProviderError("optional monthly route unavailable")
    provider, report = Provider(), Counter()
    _prefetch_native_identity_calendar(provider, (date(2025, 4, 4),
                                                  date(2025, 4, 12)), report)
    assert report["identity_monthly_calendar_paid_requests"] == 1
    assert report["identity_monthly_calendar_fallbacks"] == 1
    assert report["identity_recovered"] == 0


def test_native_identity_shared_quota_stop_never_becomes_daily_fallback():
    import pytest
    from collections import Counter
    from tbt.providers.budget import RequestBudgetExceeded
    from scripts.download_tennis_history import _prefetch_native_identity_calendar
    class Provider:
        request_count = 0
        def prefetch_calendar_categories(self, days):
            self.request_count += 1
            raise RequestBudgetExceeded("shared quota already exhausted")
    provider, report = Provider(), Counter()
    with pytest.raises(RequestBudgetExceeded, match="shared quota"):
        _prefetch_native_identity_calendar(provider, (date(2025, 4, 4),
                                                      date(2025, 4, 12)), report)
    assert report["identity_monthly_calendar_paid_requests"] == 1
    assert report["identity_recovered"] == 0


def test_native_identity_production_run_uses_only_existing_provider_and_writer():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] /
           "scripts/download_tennis_history.py").read_text()
    assert "calendar_batches = identity_calendar_prefetch_groups(planned)" in src
    assert "_prefetch_native_identity_calendar(provider, batch_days, report)" in src
    assert "source_rows.extend(provider.matches_for_day(tour, day, historical=True))" in src
    assert "updates, outcomes = recover_day(matches, source_rows, day=day)" in src
