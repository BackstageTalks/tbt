"""Static guardrails for the operator-scheduled 06:20 Telegram publishing pipeline."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REQUEST=ROOT/"docs/cron/telegram-daily-offer-0620.json"
WORKFLOW=ROOT/".github/workflows/telegram-daily-offer.yml"


def test_cron_dispatch_contract_is_daylight_saving_aware_and_data_free():
    config=json.loads(REQUEST.read_text(encoding="utf-8"))
    assert config["enabled_in_external_scheduler"] is False
    assert config["schedule"]=={
        "cron":"20 6 * * *","timezone":"Europe/Bratislava","dst_aware":True}
    request=config["request"]
    assert request["method"]=="POST"
    assert request["url"]=="https://api.github.com/repos/BackstageTalks/tbt/dispatches"
    assert request["json_body"]=={"event_type":"telegram-daily-offer-tick"}
    assert request["success_http_status"]==204
    assert request["headers"]["Authorization"]=="Bearer <EXTERNAL_CRON_GITHUB_TOKEN>"
    assert "daily_offer_snapshot" not in json.dumps(request)
    assert "TGB" not in json.dumps(request)
    assert "TGCH" not in json.dumps(request)


def test_daily_workflow_waits_for_data_writers_and_verifies_telegram_receipts():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "types: [telegram-daily-offer-tick]" in text
    assert "cancel-in-progress: false" in text
    assert "group: blinq-telegram-ledger" in text
    assert 'queue-daily --state .private-telegram/ops/telegram-bot-state.json' in text
    assert 'prepare --daily --config-url' in text
    assert "python scripts/telegram_offer_publisher.py send" in text
    assert "python scripts/telegram_offer_publisher.py mark-sent" in text
    assert "ls-remote origin refs/heads/telegram-bot-state" in text
    # Site readiness supersedes waiting for unrelated background data writers.
    assert "api/v1/internal/serving-readback" in text
    assert "verified_website_morning_parity" in text
    assert "data pipeline busy" not in text
    assert "BLINQ_LIVE_WORKER_TOKEN" in text
    assert 'sleep 60' in text
    assert "gh workflow run telegram-daily-offer.yml" in text
    assert "\nschedule:" not in text  # external cron is operator-owned
