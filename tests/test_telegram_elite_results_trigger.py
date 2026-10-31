"""Do not lose ELITE results after the final match; no duplicate writes/cron."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_match_status_dispatches_results_after_successful_reconciliation():
    text=(ROOT/".github/workflows/match-status.yml").read_text()
    assert "Dispatch completed Telegram ELITE results check after settlement" in text
    assert "if: success() && github.event_name == 'workflow_dispatch'" in text
    assert "gh workflow run telegram-results.yml" in text


def test_results_worker_checks_on_every_tick_and_uses_single_configured_channel():
    workflow=(ROOT/".github/workflows/telegram-results.yml").read_text()
    assert "prepare --elite-auto --api-url" in workflow
    assert "BLINQ_LIVE_WORKER_TOKEN" in workflow
    assert "TGB: ${{ secrets.TGB }}" in workflow
    assert "TGCH: ${{ secrets.TGCH }}" in workflow
    assert "TGCH_ELITE" not in workflow
    assert "TGCH_FREE" not in workflow
    assert "group: blinq-telegram-ledger" in workflow
    assert "mark-sent" in workflow and "ls-remote origin refs/heads/telegram-bot-state" in workflow
    assert "\nschedule:" not in workflow
    source=(ROOT/"scripts/telegram_offer_publisher.py").read_text()
    assert 'item.get("audience") not in ("free","premium","elite")' in source
    assert 'destination=chat' in source
    assert "TGCH_ELITE" not in source
    assert "TGCH_FREE" not in source


def test_verified_archive_api_can_read_current_betting_day_but_not_future():
    source=(ROOT/"api/function_app.py").read_text()
    assert "current_betting_day = local.date() if local.hour >= 6" in source
    assert "target <= current_betting_day" in source
    assert 'if not _live_worker_token_ok(req):' in source
    report=(ROOT/"scripts/telegram_daily_results.py").read_text()
    assert "target_day=unreported_day(state,now)" in report
    assert '"issued_picks_not_all_settled"' in report
    assert 'post["audience"]="elite"' in report
    assert "outside_07_local_window" not in report
