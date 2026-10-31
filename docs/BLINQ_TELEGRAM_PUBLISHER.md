# BlinQ Telegram publisher — Admin and GitHub Actions

## Use

Admin -> **Telegram bot** is independent of the existing **Telegram skupiny** page. On that page set:

- Publisher ON / OFF.
- TOP, VALUE, ESÁ categories independently.
- Free preview: one deterministic random confirmed TOP bet per BlinQ betting day (defaults ON).
- Scheduled dispatch time in **Europe/Bratislava**, weekdays, on/off.
- Combined vs per-category message, number of picks, include already-started matches, probability/odds fields, classic footer.

Click **Publikovať** to store the configuration in the existing durable Azure Admin UI store. The default is OFF. Clicking **Zaradiť jednorazové odoslanie** saves the current draft along with a unique request ID; the existing externally scheduled hourly tick processes fresh requests, within 90 minutes. An external 10-minute repository dispatch can improve precision. The button does not mean that Telegram confirmed delivery.

## Secrets

Add these in **BackstageTalks/tbt → Settings → Secrets and variables → Actions**:

| Key | Purpose |
| --- | --- |
| `TGB` | Telegram bot token (required) |
| `TGCH` | Telegram channel chat ID (required, bot must be allowed to post) |
| `TGCH_FREE` | Optional second FREE channel ID. Without it FREE goes to the same `TGCH` channel |
| `TBT_DATA_GH_TOKEN` | Existing GitHub token with read access to private `BackstageTalks/tbt-data` release assets |

The last token is already used by existing BlinQ data workflows and must not be replaced with the Telegram bot token.

Never place Telegram credentials, channel IDs, or private release credentials in UI JSON, source code or frontend configuration.

## Source of truth

Uses the **confirmed_only** `daily_offer_snapshot.json` from the existing private `tbt-predictions-v1` release. It validates the SHA-256 and exact byte length against the release manifest before rendering. It calls `tbt.services.entitlements._daily_rows` to match TOP selection (Value precedence, odds quality floor, probability fallback).

- No tennis RapidAPI calls.
- Never publishes shadow, pending, stale or unconfirmed predictions.
- ESÁ projection-only offers never receive fabricated prices.
- FREE chooses exactly one confirmed eligible TOP row; deterministic hashed rank. The chosen event ID is persisted so later runs for that day use the same event.

Historical style retained:
```
Data Betting by BackstageTalks

🎾 TOP Picks | BlinQ
📅 31.10.2026

1️⃣ Player A vs Player B | 12:30 | 72.4% | 1.75
...
ℹ️ Analytical preview only
🧠 by BackstageTalks Data Engine
```

## Delivery guarantees

Workflow: `.github/workflows/telegram-offer.yml`; no native GitHub cron (prohibited by the app release contract). The existing external hourly API tick triggers the publisher on `.github/hourly-api-gapfill-tick.json` updates. To tighten delivery to 10-minute resolution, configure an external scheduler to call `repository_dispatch` with `event_type=telegram-offer-tick` every 10 minutes. The send window is the selected time plus 90 minutes. If no external ticks occur, automatic sending will not run.

Before any Telegram request, the workflow writes a durable send reservation to the separate `telegram-bot-state` branch and performs a GitHub read-back. Reservation keys are betting day + schedule/manual request ID. Only a successfully reserved batch is sent; retries do **not** automatically resend a batch because Telegram does not support an idempotency key. If a send fails or GH status is uncertain, inspect GitHub Actions and the Telegram channel before manually creating a new request.

A FREE message uses `TGCH_FREE` when configured, otherwise `TGCH`. With both channels pointing to the same chat, FREE will be a separate post in that channel.

## Offline tests

`python -m pytest tests/test_telegram_offer_publisher.py`

The test suite checks classic formatting, deterministic/free-only selection, confirmed snapshot integrity, stale date rejection, schedule/manual request windows, and free routing.

## Operational rollout

1. Merge code through green CI; verify production backend/frontend deployment.
2. Confirm `TGB`, `TGCH` and existing `TBT_DATA_GH_TOKEN` secrets.
3. In Admin -> Telegram bot enable publisher; keep scheduled sending OFF during initial smoke test.
4. Click **Zaradiť jednorazové odoslanie** with an appropriate confirmed daily offer. It will be picked up at the next external tick or by manually running `BlinQ Telegram offer` from GitHub Actions.
5. Inspect workflow logs and the actual Telegram channel. Only then enable the desired daily schedule.

Do not enable automatic sending until you have independently verified the target chat and test delivery.
