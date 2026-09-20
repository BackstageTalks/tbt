import json
from copy import deepcopy
from pathlib import Path

from tbt.services.admin_storage import _normalize_membership_invariants
from tbt.services.entitlements import filter_feed_for_access

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
RESPONSIVE = (WEB / "responsive.js").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
TIERS = json.loads((WEB / "config" / "membership-tiers.json").read_text(encoding="utf-8"))
LINKS = json.loads((WEB / "membership-links.json").read_text(encoding="utf-8"))
SITE = json.loads((WEB / "config" / "site-content.json").read_text(encoding="utf-8"))


def _row(i, market="match_winner"):
    return {
        "event_id": f"e{i}",
        "market": market,
        "scheduled_at": f"2026-09-20T{10+i%10:02d}:00:00Z",
        "pick": f"A{i}",
        "player1": {"id": f"a{i}", "name": f"A{i}", "probability": .72},
        "player2": {"id": f"b{i}", "name": f"B{i}", "probability": .28},
    }


def _payload():
    top = [_row(i) for i in range(8)]
    prime = [_row(20+i) for i in range(8)]
    value = [_row(40+i) for i in range(8)]
    ace = [{**_row(60+i, "aces"), "selection_id": f"a{i}"} for i in range(4)]
    sg = [{**_row(80+i, "sets"), "selection_id": f"s{i}"} for i in range(4)]
    return {
        "top_daily_picks": top,
        "prime_picks": prime,
        "value_picks": value,
        "ace_picks": ace,
        "doubles_picks": [],
        "sg_picks": sg,
        "upcoming": top,
        "results": [],
    }


def test_final_rookie_and_pro_offer_contract_is_server_enforced_by_defaults():
    rookie, rm = filter_feed_for_access(_payload(), {"status": "active", "plan": "rookie", "id": "r"}, None)
    pro, pm = filter_feed_for_access(_payload(), {"status": "active", "plan": "pro", "id": "p"}, None)
    assert len(rookie["top_daily_picks"]) == 1
    assert len(rookie["prime_picks"]) == 1
    assert len(rookie["value_picks"]) == 1
    assert rookie["ace_picks"] == [] and rookie["sg_picks"] == []
    assert len(pro["top_daily_picks"]) == 3
    assert len(pro["prime_picks"]) == 3
    assert len(pro["value_picks"]) == 3
    assert pro["ace_picks"] == [] and pro["sg_picks"] == []
    assert rm["results"] is False and pm["results"] is False


def test_results_default_to_legend_plus_in_static_config():
    access = UI["elements"]["SIDEBAR_RESULTS"]["access"]
    assert access["rookie"] == access["pro"] == access["elite"] == "locked"
    assert access["legend"] == access["goat"] == "active"


def test_legacy_runtime_access_matrix_is_migrated_once():
    cfg = deepcopy(UI)
    cfg.pop("access_contract_revision", None)
    cfg["elements"]["SIDEBAR_RESULTS"]["access"].update({"rookie":"active","pro":"active","elite":"active"})
    cfg["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"]["rookie"]["visible_rows"] = 8
    cfg["dashboard"]["daily_hub"]["tabs"]["sets"]["plans"]["rookie"]["visible_rows"] = "ALL"
    cfg["notifications"]["live_min_level"] = "rookie"
    out = _normalize_membership_invariants(cfg)
    assert out["access_contract_revision"] == 1
    assert out["elements"]["SIDEBAR_RESULTS"]["access"]["rookie"] == "locked"
    assert out["elements"]["SIDEBAR_RESULTS"]["access"]["elite"] == "locked"
    assert out["elements"]["SIDEBAR_RESULTS"]["access"]["legend"] == "active"
    assert out["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"]["rookie"]["visible_rows"] == 1
    assert out["dashboard"]["daily_hub"]["tabs"]["value"]["plans"]["rookie"]["visible_rows"] == 1
    assert out["dashboard"]["daily_hub"]["tabs"]["sets"]["plans"]["rookie"]["visible_rows"] == 0
    assert out["notifications"]["live_min_level"] == "elite"


def test_player_photo_responsive_handler_no_longer_short_circuits_gender_fallback():
    assert "if (img.matches('[data-player-photo]')) return;" in RESPONSIVE
    assert "/assets/missing_foto_m.webp" in APP
    assert "/assets/missing_foto_w.webp" in APP
    assert "img.dataset.fallbackApplied='1'" in APP


def test_locked_live_header_does_not_show_cryptic_required_tier_as_status():
    assert "shortcutLabel.textContent=liveEligible?(confirmed?'CONFIRMED':watching?'WATCH':'RADAR'):'RADAR'" in APP
    assert "shortcutLabel.hidden=false" in APP
    assert "shortcut.title=lcopy(`Available from ${liveAccessLabel}`" in APP


def test_locked_daily_tabs_get_a_visible_lock_state():
    assert "locked?' is-locked':''" in APP
    assert "firstDailyHubUnlockPlan(tab,0,tab==='see_all')" in APP


def test_public_copy_has_no_known_sk_cz_cross_language_regressions():
    assert "'Pick':'Predikcia'" in APP
    assert "'Pick':'Predikce'" in APP  # Czech mutation remains Czech
    assert "'Telegram nick':'Telegram prezývka'" in APP
    assert "'Telegram nick':'Telegram přezdívka'" in APP
    assert "Telegram prezývka zatiaľ nie je nastavená" in APP
    assert all(not page.get("subtitle", "").endswith(".") for page in SITE["pages"]["sk"].values())
    assert all(not page.get("subtitle", "").endswith(".") for page in SITE["pages"]["cz"].values())


def test_membership_copy_matches_current_product_contract():
    rookie = TIERS["tiers"]["rookie"]
    assert rookie["features"][:3] == ["1 TOP pick denne", "1 Short Odds pick denne", "1 Value pick denne"]
    assert "Doživotný prístup" not in LINKS["plans"]["goat"]["description"]


def test_real_rookie_cannot_see_or_open_admin():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "blinq-app.css").read_text(encoding="utf-8")
    assert 'id="profileAdminLink"' in index and 'type="button" hidden' in index
    assert "profileAdmin.hidden=!isAdminAccount()" in APP
    assert "if(route==='admin'&&!isAdminAccount()) route='predictions'" in APP
    assert ".profile-menu button[hidden]{display:none!important}" in css
    assert 'id="profilePreviewContext"' not in index
