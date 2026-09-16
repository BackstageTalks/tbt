from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/"web/app.js").read_text(encoding="utf-8")
INDEX=(ROOT/"web/index.html").read_text(encoding="utf-8")
CSS=(ROOT/"web/admin-polish-687.css").read_text(encoding="utf-8")

def test_admin_starts_with_task_overview_and_grouped_navigation():
    assert "adminTab:'overview'" in APP
    assert "function renderAdminOverview()" in APP
    assert "['START',['overview']]" in APP
    assert "['PREVÁDZKA',['accounts','support']]" in APP
    assert "['OBSAH',['layout','banners','insights','plans','campaigns','pages']]" in APP
    assert "['KONTROLA',['analytics','system','performance']]" in APP

def test_daily_offer_is_guided_and_matrix_based():
    assert 'admin-daily-settings-v687' in APP
    assert 'admin-daily-matrix-row' in APP
    assert 'data-admin-daily-preset="full"' in APP
    assert 'Zamknúť zvyšok' in APP
    assert 'Až tlačidlo Publikovať prenesie konfiguráciu na live web' in APP

def test_nav_hotfix_and_auth_polish_are_still_combined():
    assert "const modelRoutes=new Set(['model_data','methodology','how_blinq_works'])" in APP
    assert '/auth-polish-686.css?v=6864' in INDEX
    assert '/admin-polish-687.css?v=6864' in INDEX
    assert '/app.js?v=6864' in INDEX

def test_admin_uses_green_first_visual_language():
    assert '--bq-admin-accent:#2df2ad' in CSS
    assert 'admin-tabs-v685 button.active' in CSS
    assert 'admin-overview-v687' in CSS
