"""Morning publication checks. All times use the Bratislava business calendar."""
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
from urllib.request import Request, urlopen

ZONE = ZoneInfo("Europe/Bratislava")


def visible_offer(readback, day):
    counts = readback.get("visible_counts") or {}
    return (readback.get("betting_day") == day and readback.get("stale") is False
            and any(type(counts.get(k)) is int and counts[k] > 0
                    for k in ("top_daily_picks", "value_picks")))


def alarm():
    day = datetime.now(ZONE).date().isoformat()
    try:
        req = Request(os.environ["PUBLIC_BASE"].rstrip("/") + "/api/v1/internal/serving-readback",
                      headers={"X-Blinq-Worker-Token": os.environ["WORKER_TOKEN"], "Cache-Control": "no-cache"})
        with urlopen(req, timeout=15) as result:
            readback = json.load(result)
            authority = readback.get('offer_authority_keys') or {}
            if visible_offer(readback, day) and any(authority.get(k) for k in ('top', 'value')):
                return
        reason = "chýba aktuálny publikovaný TOP alebo Value tip"
    except (OSError, ValueError, TypeError, AttributeError):
        reason = "publikovaný feed sa nepodarilo overiť"
    token, chat = os.environ.get("TGB"), os.environ.get("TG_ADMIN_CHAT_ID")
    if not token or not chat:
        raise SystemExit("Admin Telegram destination or bot not configured")
    body = json.dumps({"chat_id": chat, "text": f"BlinQ 06:30 — {day}: {reason}."}).encode()
    try:
        with urlopen(Request("https://api.telegram.org/bot" + token + "/sendMessage",
                             data=body, headers={"Content-Type": "application/json"}), timeout=15) as result:
            if not json.load(result).get("ok"):
                raise ValueError()
    except Exception:
        raise SystemExit("Telegram admin delivery not confirmed") from None


if __name__ == "__main__":
    alarm()
