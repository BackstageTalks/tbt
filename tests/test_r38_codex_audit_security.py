from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import confirm_prediction_publication as confirm
from tbt.services import auth as auth_service
from tbt.services import admin_accounts
from tbt.services.entitlements import (
    filter_feed_for_access,
    match_detail_entitlements,
    match_intelligence_row_authorized,
    redact_match_intelligence,
)

ROOT = Path(__file__).resolve().parents[1]


def _top_row(i: int, *, odds: float = 1.80):
    return {
        "event_id": f"e{i}",
        "custom_id": f"c{i}",
        "pick": f"P{i}",
        "scheduled_at": f"2026-09-21T{10 + (i % 8):02d}:00:00+00:00",
        "betting": {"odds": odds},
        "blinq_probability": 0.80 - i / 1000,
        "player1": {"id": str(1000 + i), "name": f"P{i}", "probability": 0.7},
        "player2": {"id": str(2000 + i), "name": f"Q{i}", "probability": 0.3},
    }


def _payload(n: int = 10):
    top = [_top_row(i) for i in range(n)]
    return {
        "top_daily_picks": top,
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
        "upcoming": deepcopy(top),
        "results": [],
        "performance": {"accuracy": 0.8},
        "betting_performance": {"roi": 0.2},
        "performance_windows": {"7": {"accuracy": 0.9}},
        "performance_window_summary": {"accuracy": 0.9},
        "performance_subgroups": {"tour": {"atp": {"accuracy": 0.75, "n": 80}}},
    }


class _FakeRecord:
    uid = "user-1"


class _FakeFirebaseAuth:
    def __init__(self):
        self.set_calls = []

    def get_user(self, uid, app=None):
        return _FakeRecord()

    def set_custom_user_claims(self, uid, claims, app=None):
        self.set_calls.append((uid, claims))
        raise AssertionError("profile/operational metadata must never write custom claims")


def test_b01_profile_and_operational_metadata_do_not_write_custom_claims(monkeypatch):
    fake_auth = _FakeFirebaseAuth()

    monkeypatch.setattr(auth_service, "_firebase_modules", lambda: (None, fake_auth, None))
    monkeypatch.setattr(auth_service, "firebase_app", lambda cfg: object())
    monkeypatch.setattr(auth_service, "firebase_user_to_dict", lambda record: {"id": record.uid})
    assert auth_service.mirror_profile_claims(object(), "user-1", {"telegram_nick": "@x"})["id"] == "user-1"

    monkeypatch.setattr(admin_accounts, "_firebase_modules", lambda: (None, fake_auth, None))
    monkeypatch.setattr(admin_accounts, "firebase_app", lambda cfg: object())
    monkeypatch.setattr(admin_accounts, "firebase_user_to_dict", lambda record: {"id": record.uid})
    assert admin_accounts.mirror_admin_metadata_claims(object(), "user-1", {"tg_private_member": True})["id"] == "user-1"
    assert fake_auth.set_calls == []


def test_b01_function_app_no_longer_calls_metadata_claim_mirrors():
    source = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    assert "mirror_profile_claims(" not in source
    assert "mirror_admin_metadata_claims(" not in source


def test_b02_daily_and_legacy_top_alias_are_the_same_authorized_set():
    cfg = {
        "dashboard": {
            "daily_hub": {
                "enabled": True,
                "tabs": {
                    "daily": {
                        "enabled": True,
                        "plans": {
                            "rookie": {
                                "visible_rows": 1,
                                "blur_remaining": True,
                                "tab_enabled": True,
                                "see_all": False,
                                "selection_mode": "stable_random",
                                "display_state": "active",
                            }
                        },
                    }
                },
            }
        }
    }
    data, manifest = filter_feed_for_access(_payload(), {"id": "rookie-1", "status": "active", "plan": "rookie"}, cfg)
    daily_ids = {row["event_id"] for row in data["daily_picks"]}
    legacy_ids = {row["event_id"] for row in data["top_daily_picks"]}
    assert len(daily_ids) == 1
    assert legacy_ids == daily_ids
    assert manifest["sections"]["top_daily"]["slot_states"] == manifest["sections"]["daily"]["slot_states"]


def test_b10_stats_subgroups_are_redacted_when_performance_is_locked():
    data, manifest = filter_feed_for_access(_payload(), {"id": "rookie-1", "status": "active", "plan": "rookie"})
    assert manifest["performance"] is False
    assert data["performance"] == {}
    assert data["betting_performance"] == {}
    assert data["performance_windows"] == {}
    assert data["performance_window_summary"] == {}
    assert data["performance_subgroups"] == {}


def test_b03_match_detail_plan_and_section_rules_are_server_resolved():
    cfg = {
        "dashboard": {
            "match_detail": {
                "plans": {"rookie": False, "pro": True, "elite": True, "legend": True, "goat": True},
                "sections": {"overview": "rookie", "statistics": "pro", "radar": "elite", "history": "legend"},
            }
        }
    }
    rookie = match_detail_entitlements({"status": "active", "plan": "rookie"}, cfg)
    assert rookie["allowed"] is False
    assert not any(rookie["sections"].values())

    pro = match_detail_entitlements({"status": "active", "plan": "pro"}, cfg)
    assert pro["allowed"] is True
    assert pro["sections"] == {"overview": True, "statistics": True, "radar": False, "history": False}

    legend = match_detail_entitlements({"status": "active", "plan": "legend"}, cfg)
    assert all(legend["sections"].values())


def test_b03_match_intelligence_only_accepts_authorized_offer_rows():
    filtered = {
        "daily_picks": [_top_row(1)],
        "prime_picks": [], "top_daily_picks": [_top_row(1)], "value_picks": [],
        "doubles_picks": [], "ace_picks": [], "sg_picks": [], "board_upcoming": [],
    }
    assert match_intelligence_row_authorized(filtered, "1001", "2001", event_id="e1", custom_id="c1")
    assert not match_intelligence_row_authorized(filtered, "1002", "2002", event_id="e2", custom_id="c2")
    assert not match_intelligence_row_authorized(filtered, "1001", "2001", event_id="other", custom_id="c1")


def test_b03_cached_or_fresh_match_intelligence_is_redacted_per_section():
    payload = {
        "source": "provider",
        "h2h": {"player1_wins": 3, "player2_wins": 1, "matches": 4},
        "player1": {
            "rank": 10,
            "presentation": {
                "recent_form": {"wins": 8, "losses": 2},
                "surface_form": {"wins": 6, "losses": 2},
                "history_matches": 35,
                "surface_history_matches": 20,
                "h2h_wins": 3,
                "h2h_losses": 1,
                "h2h_matches": 4,
            },
        },
        "player2": {
            "rank": 20,
            "presentation": {
                "recent_form": {"wins": 5, "losses": 5},
                "surface_form": {"wins": 3, "losses": 5},
                "history_matches": 35,
                "surface_history_matches": 20,
                "h2h_wins": 1,
                "h2h_losses": 3,
                "h2h_matches": 4,
            },
        },
    }
    pro_access = {"sections": {"overview": True, "statistics": True, "radar": False, "history": False}}
    pro = redact_match_intelligence(payload, pro_access)
    assert pro["player1"]["presentation"]["recent_form"]
    assert "h2h" not in pro
    assert "h2h_wins" not in pro["player1"]["presentation"]

    overview_only = {"sections": {"overview": True, "statistics": False, "radar": False, "history": False}}
    overview = redact_match_intelligence(payload, overview_only)
    assert overview["player1"]["rank"] == 10
    assert "recent_form" not in overview["player1"]["presentation"]
    assert "history_matches" not in overview["player1"]["presentation"]


def test_b03_handler_authorizes_before_cache_or_provider_use():
    source = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    start = source.index('def match_intelligence(req):')
    end = source.index('@app.route(route="v1/player-image/', start)
    block = source[start:end]
    guard = block.index('match_intelligence_row_authorized(')
    cache = block.index('_cached_match_intelligence(')
    provider = block.index('RapidTennisClient(settings)')
    assert guard < cache < provider


def test_b06_birth_date_enrichment_is_presentation_only_for_publication_confirmation():
    private = {"upcoming": [{"event_id": "e1", "player1": {"id": "1", "name": "A"}, "player2": {"id": "2", "name": "B"}}]}
    deployed = deepcopy(private)
    deployed["upcoming"][0]["player1"].update({"birth_date": "1995-04-03", "birth_timestamp": 796089600})
    assert confirm._publication_candidate_view(deployed) == confirm._publication_candidate_view(private)


def test_b07_expanded_daily_hub_uses_expanded_slot_limit():
    source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    start = source.index("function renderDailyHub")
    end = source.index("function renderPredictions", start)
    block = source[start:end]
    assert "slotStates.slice(0,limit).forEach" in block
    assert "slotStates.slice(0,preview).forEach" not in block


def test_b08_cross_tab_logout_clears_private_workspace_and_invalidates_async_commits():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    auth = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")

    assert "window.addEventListener('storage',handleSessionStorageEvent)" in app
    assert "sessionEpochKey" in auth
    assert "function clearPrivateWorkspaceState()" in app
    for sensitive_reset in (
        "state.feed={upcoming:[],results:[],performance:{},history:{},model:null}",
        "state.insights=[]",
        "state.adminUsers=null",
        "state.adminDiagnostics=null",
        "state.adminInsights=null",
        "state.userLiveRadarStatus=null",
        "state.route='predictions'",
    ):
        assert sensitive_reset in app

    # Async private loaders must reject stale responses after a cross-tab identity epoch change.
    for signature in (
        "async function loadInsights(force=false)",
        "async function loadUserLiveRadarStatus(force=false)",
        "async function loadAdminInsights(force=false)",
        "async function loadAdminDiagnostics(force=false)",
        "async function loadAdminUsers(force=false)",
    ):
        start = app.index(signature)
        next_function = app.find("\n  function ", start + 1)
        next_async = app.find("\n  async function ", start + 1)
        candidates = [pos for pos in (next_function, next_async) if pos != -1]
        end = min(candidates) if candidates else len(app)
        block = app[start:end]
        assert "const generation=feedGeneration" in block
        assert "generation!==feedGeneration" in block

    assert "if(generation===feedGeneration){feedLoading=false" in app
