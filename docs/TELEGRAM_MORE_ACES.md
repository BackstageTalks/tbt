# Telegram VIAC ES — exact website ball marker

## Contract

The separate VIAC ES workflow is now **manual-only**. It is not dispatched
by the 06:20 daily offer; the approved automatic morning delivery has exactly
the complete offer and one two-row FREE post. It uses the same premium Telegram destination, existing
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

🎾 | Smith | 16:00 | viac ES | 78.0% | BlinQ štat. kurz 1.59

ℹ️ Analytical preview by BlinQ Stat Engine
```

## VIAC ES — owner-approved local price (8 Nov 2026 onward)

The project owner approved the **1.50–1.70** range for his own statistical
Most Aces prices when no independently verified exact API Pro Most Aces quote
exists. The value is a bounded, monotonic presentation mapping of the existing
frozen, CDB-derived calibrated `projection_confidence`: 60% maps to 1.70 and
93% to 1.50, rounded to cents. Source provenance:
`blinq_user_most_aces_confidence_band_v1`. This is **not** a bookmaker quote,
a conversion of the unrelated Aces player Over/Under line, or a proven
per-event fair probability including draw/push semantics.

The API decorates only currently visible, qualified `most_aces` rows with
`statistical_more_aces_odds` and `statistical_more_aces_price_basis`, keeping
`odds=None`, immutable issuance, CDB and Results/ROI untouched. Website
desktop/mobile labels the value **BlinQ štat. kurz**. Telegram uses the
same validated website ball identity, even if the original O/U selection
points to the opponent, and labels it **BlinQ štat. kurz**. An authenticated,
contract-specific API Pro price takes priority when present; this local
fallback does not masquerade as such an API quote. Do not retroactively
reprice historical Results or confirmed Telegram messages.

## Sending and identity

- Workflow: `.github/workflows/telegram-more-aces.yml`.
- Dispatch is manual-only (`workflow_dispatch`); it is no longer triggered
  by `telegram-daily-offer.yml`, and no `repository_dispatch` is accepted.
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
deployed but **delivery remains unverified**. The independent website/Admin/Results/STATS VIAC ES category is implemented
separately. This Telegram extension never changes that category's frozen
betting economics.
