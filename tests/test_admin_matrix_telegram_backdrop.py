"""Regression: predictable responsive Daily Picks controls and a single Telegram backdrop."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "web"


def test_admin_daily_matrix_has_seven_headers_and_seven_columns():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "blinq-app.css").read_text(encoding="utf-8")
    assert '<span>Zvyšok</span><span>Celá ponuka</span></div>' in app
    assert 'Seven real columns:' in css
    assert 'minmax(94px,.8fr)!important' in css
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))!important' in css
    assert 'grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr))!important' in css
    assert 'admin-daily-matrix-row>.admin-row-advanced{grid-column:1/-1!important}' in css


def test_telegram_background_is_once_on_section_not_on_each_card():
    css = (ROOT / "blinq-app.css").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    addition = css.split("/* 2026-10-25: One artwork-backed Telegram shell",1)[1]
    assert 'body#blinqPremium.blinq-home .telegram-groups-panel' in addition
    assert 'url("/assets/blinq_page_background.webp")' in addition
    assert 'background:rgba(2,18,18,.92)!important' in addition
    assert 'grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))!important' in addition
    assert "tg-artwork=1" in html


def test_admin_navigation_supports_saved_order_and_default_reset():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "blinq-app.css").read_text(encoding="utf-8")
    assert 'data-admin-nav-reset' in app
    assert 'localStorage.removeItem(ADMIN_TAB_ORDER_KEY)' in app
    assert 'admin-nav-toolbar{flex-wrap:wrap!important}' in css
