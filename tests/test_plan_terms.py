from datetime import datetime, timezone
from tbt.services import plan_terms as t

NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
cfg = lambda **d: {"plans": {k: {"duration_days": v} for k, v in d.items()}}


def test_deltas_only_for_changed_valid_plans():
    assert t.term_deltas(cfg(legend=30, pro=30), cfg(legend=180, pro=30)) == {"legend": 150}
    assert t.term_deltas(cfg(legend=30), cfg()) == {}


def test_extend_adds_difference():
    # switched 1.11. with 30 days -> 1.12.; +150 -> 30.4. (= 1.11. + 180)
    assert t.shifted_expiry("2026-12-01T00:00:00Z", 150, NOW) == "2027-04-30T00:00:00Z"


def test_shorten_never_before_tomorrow():
    out = t.shifted_expiry("2026-12-01T00:00:00Z", -60, NOW)
    assert out == "2026-11-26T12:00:00Z"


def test_apply_updates_only_active_users_of_plan():
    users = [
        {"id": "a", "app_metadata": {"role": "user", "blinq_plan": "legend", "blinq_status": "active", "blinq_expires_at": "2026-12-01T00:00:00Z"}},
        {"id": "b", "app_metadata": {"role": "user", "blinq_plan": "pro", "blinq_status": "active", "blinq_expires_at": "2026-12-01T00:00:00Z"}},
        {"id": "c", "app_metadata": {"role": "user", "blinq_plan": "legend", "blinq_status": "expired", "blinq_expires_at": "2026-11-01T00:00:00Z"}},
    ]
    calls = []
    rep = t.apply_term_deltas(None, {"legend": 150}, now=NOW,
                              list_users=lambda cfg, page, per_page: users if page == 1 else [],
                              update_user_access=lambda cfg, uid, payload, **kw: calls.append((uid, payload["expires_at"])))
    assert calls == [("a", "2027-04-30T00:00:00Z")] and rep["updated"] == 1
