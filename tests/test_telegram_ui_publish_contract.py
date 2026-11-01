"""Read-only guards for the Telegram Admin publishing and footer contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_telegram_publishes_scoped_latest_server_config_with_readback():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    auth = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")
    start = js.index("async function publishTelegramConfig()")
    end = js.index("async function publishUiConfig()", start)
    publish = js[start:end]
    assert 'data-admin-action="tg-publish"' in js
    assert "const payload=clone(status.config);payload.telegram_groups=wanted;" in publish
    assert "JSON.stringify(published)!==JSON.stringify(state.telegramPublishedOriginal||{})" in publish
    assert "adminSaveUiConfig(payload,status.config_revision)" in publish
    assert "telegram_readback=" in publish
    assert "JSON.stringify(check.config?.telegram_groups||{})===JSON.stringify(wanted)" in publish
    assert "'X-BlinQ-UI-Revision': revision" in auth
    assert "Staň sa súčasťou" in js and "s denným FREE" in js


def test_footer_does_not_call_feed_generation_model_training():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    start = js.index("function renderSystemFooterStatus(){")
    end = js.index("function insightTypeLabel", start)
    footer = js[start:end]
    assert "Ponuka aktualizovaná" in footer
    assert "Posledný LIVE scan" in footer
    assert "Aktualizácia modelu" not in footer
    assert "heartbeat?.last_success_at" in footer
