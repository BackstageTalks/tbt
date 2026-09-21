from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"web"
APP=(WEB/"app.js").read_text(encoding="utf-8")
CSS=(WEB/"blinq-app.css").read_text(encoding="utf-8")
UI=json.loads((WEB/"ui-config.json").read_text(encoding="utf-8"))

def test_r27_short_odds_is_public_and_admin_managed():
    assert UI["ui_patch"] == "736-r45"
    prime=UI["dashboard"]["daily_hub"]["tabs"]["prime"]
    assert prime["enabled"] is True
    assert prime["label"] == "Short Odds"
    assert prime["plans"]["rookie"]["visible_rows"] == 1
    assert "const tabs=['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'];" in APP
    assert "if(tab==='prime')return marketRows('prime').filter(offerSurfaceEligible);" in APP
    assert "const rows=['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'].map" in APP

def test_r27_see_all_uses_same_controls_as_other_categories():
    assert "admin-see-all-rule-note" not in APP
    assert "if(tab==='see_all')return previewDailyHubEntitlement(tab);" in APP
    assert "tab==='see_all'&&!ent.see_all" not in APP
    assert 'data-admin-hub-field="visible_rows"' in APP
    assert 'data-admin-hub-field="selection_mode"' in APP
    assert 'data-admin-hub-field="blur_remaining"' in APP
    assert 'data-admin-hub-row-state=' in APP

def test_r27_copy_from_level_tool_is_removed():
    for legacy in ("Kopírovať nastavenie z iného levelu","adminCopyFrom","copy-plan","Skopírovať všetky pravidlá"):
        assert legacy not in APP

def test_r27_admin_telegram_icon_is_clean_filled_glyph():
    assert 'stroke:none;fill:#36aeea' in CSS
    assert 'padding-left:36px' in CSS
