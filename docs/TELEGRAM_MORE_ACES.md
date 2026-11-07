# Telegram VIAC ES — exact website ball marker

## Contract

The new message is a **separate daily Telegram feed** following the confirmed
06:20 daily offer. It uses the same premium Telegram destination, existing
bot credentials, branded header, date, compact per-player row and footer.
It does not replace the regular TOP/VALUE/ACES daily feed.

**Selection source:** the current SHA/size-verified private
`daily_offer_snapshot.json` — the same generation as the authenticated
production `/api/v1/internal/serving-readback` (ready, nonstale, same betting
day, sufficient visible ACES rows). The tennis-ball mark follows exactly the
`web/app.js::aceLeaderHintHtml` contract:
`aces_superiority_hint` / `projection_subject` and the corresponding
player ID, rather than the separate O/U `selection_id`. Resolve to exactly
one of the two fixture participants. Conflicting player identity fails closed.

Only future, current local-date, same-betting-day fixture rows are eligible.
Existing O/U line, selected player, odds, provider price and bankroll stats
are **never** copied into the Most Aces message: these describe another bet.

Example, intentionally illustrative (not live picks):

```text
🎾 BlinQ | Tennis Intelligence

📅 08.11.2026

🎾 VIAC ES

🎾 | Smith | 16:00 | viac ES | 78.0%

ℹ️ Analytical preview by BlinQ Stat Engine
```

## Sending and identity

- Workflow: `.github/workflows/telegram-more-aces.yml`.
- Normal dispatch is a separate GitHub `workflow_dispatch` after successful
  `telegram-daily-offer.yml` deliver.
- No independent native cron, provider call, CDB write or model change.
- Share the existing global `blinq-telegram-ledger` concurrency group and
  private `tbt-data@telegram-bot-state` ledger.
- One immutable idempotency slot per betting day:
  `attempts["more-aces:YYYY-MM-DD"]`, distinct from bet/result receipts.
- Require original `YYYY-MM-DD:daily:0620` state `sent` with confirmed
  message IDs before preparing any More Aces message.
- Write reservation + independent Git readback **before** Telegram; use
  existing `telegram_offer_publisher.py send` / `mark-sent` and read back
  confirmed Telegram message ID.
- A reserved, sent or uncertain outcome is never automatically replayed.
  Empty/unavailable/expired selections do not emit empty messages.

## Acceptance and tests

`python -m pytest tests/test_telegram_more_aces.py
tests/test_telegram_offer_publisher.py
tests/test_telegram_daily_cron_contract.py`

Production completion requires an actual next-daily delivery
message ID in the new private ledger slot. Until then the code is merged/
deployed but **delivery remains unverified**. At present this is a Telegram
offer feature; it does not itself add a new website/Admin/stats category.
