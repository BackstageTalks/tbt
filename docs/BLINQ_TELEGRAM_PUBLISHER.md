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
| `TBT_DATA_GH_TOKEN` | Existing GitHub token with **read access to private release assets and Contents write permission to the isolated `telegram-bot-state` branch** in `BackstageTalks/tbt-data` |

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

Before any Telegram request, the workflow writes a durable send reservation to the **private `BackstageTalks/tbt-data` / `telegram-bot-state` branch** and performs a GitHub read-back. Reservation keys are betting day + schedule/manual request ID. Only a successfully reserved batch is sent; retries do **not** automatically resend a batch because Telegram does not support an idempotency key. If a send fails or GH status is uncertain, inspect GitHub Actions and the Telegram channel before manually creating a new request.

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


## Daily settlement reports — previous betting day (NEW)

The previous-day evaluation uses the **exact picks with Telegram-confirmed message IDs** from the isolated **private `BackstageTalks/tbt-data` / `telegram-bot-state` branch**. The opening betting day is `Europe/Bratislava 06:00` until the next 06:00. At ~07:00 on 1 November the report covers 31 October, even if a tennis match crossed midnight.

- Enable **Telegram bot → Denné vyhodnotenie** in Admin and click **Publikovať**. Defaults OFF. The existing publishing toggle must also be ON.
- Job: `.github/workflows/telegram-results.yml` (**BlinQ Telegram daily results**).
- Configure your external scheduler for **07:00 Europe/Bratislava** with DST-aware timezone; invoke `repository_dispatch` with `event_type=telegram-results-tick`. GitHub native cron is forbidden by the existing project contract. Manual `workflow_dispatch` remains available.
- The GitHub secret `BLINQ_LIVE_WORKER_TOKEN` (already used by other BlinQ workers) authenticates a **read-only** call to `/api/v1/internal/telegram/settled-results?day=YYYY-MM-DD`. This endpoint returns only settled issued TOP / Value / Esá publications with verified match-status archive evidence. No new provider calls, no settlement side effects.
- Report sections **TOP / Value / Esá / FREE** keep the classic `📊 Results`, row-by-row `✅ ❌ ➖ ⏳` and `unit / ROI` layout.
- Missing settlements show **Pending**. Projection-only aces may show a verified outcome but **do not contribute invented stake, yield or ROI**. Priced ROI divides genuine one-unit graded stakes only. Reports with pending picks are explicitly marked *priebežné*.
- Report `results:YYYY-MM-DD` is reserved before any Telegram request. A successfully delivered report is saved back with individual message IDs; an uncertain send never triggers automatic duplicate retries.

Example external scheduler HTTP action (provide its GitHub auth token securely):
```http
POST https://api.github.com/repos/BackstageTalks/tbt/dispatches
Authorization: Bearer <external-scheduler-GitHub-token>
Accept: application/vnd.github+json
Content-Type: application/json

{"event_type":"telegram-results-tick"}
```
For convenient local timezone scheduling use `TZ=Europe/Bratislava` (or your scheduler's equivalent); do not hardcode UTC 06:00 throughout the year because DST changes.

## Data impact

The Telegram PR never modifies CDB, the existing verified-results archive, provider quotas, models or prediction issuance. It **does** update the existing Admin UI-config storage when the operator publishes settings, writes a **private `tbt-data` branch** ledger of Telegram reservations/receipts/immutable sent-row identifiers, and sends Telegram messages. The settlement API is read-only.

### Security isolation of Telegram state

The application repository `BackstageTalks/tbt` is **public**. Never commit issued paid picks, recipient IDs, price data or Telegram message receipts to any public branch of this repo. Both Telegram workflows check out the **private** `BackstageTalks/tbt-data` branch `telegram-bot-state` with sparse `ops/` checkout. The existing `TBT_DATA_GH_TOKEN` must be allowed to read that private repository and push to this isolated branch; if it cannot push, the workflow fails **before sending**. No CDB branch, asset or release is written by either workflow.

## Complete daily offer and combined daily Results

- Admin **Celá publikovaná ponuka** (default ON) sends all eligible confirmed TOP → Value → Aces picks instead of the previous limit of 7 per category. Switching it OFF restores the optional per-category limit (1–10). The existing include-started setting remains effective. Longer Telegram posts are split into lossless ordered pages.
- Daily Results at around 07:00 Europe/Bratislava use the previous completed 06:00–06:00 betting day. Premium sections are consolidated into one Results report (or automatically paginated), FREE remains separately addressed.
- The tbt-pro TG_SENT_SNAPSHOT_V12 and TG_RESULTS_COMPLETENESS_V11 principle is retained: only exact, Telegram-receipt-confirmed sent rows are expected; verified settled Results are paired by immutable identity and absent outcomes stay PENDING.
- WIN, LOSS, VOID percentages each use all settled outcomes as denominator (WIN + LOSS + VOID). **Hit rate = WIN / (WIN + LOSS)**, excluding VOID/PENDING.
- **Profit units** = sum of settled priced 1u picks (WIN: odds − 1; LOSS: −1; VOID: 0), **daily ROI** = profit / number of settled priced 1u picks × 100. Projection-only Aces may have an outcome but no invented money performance.
- No new tennis API calls, CDB updates, model recalculation, or settlement writes. The publisher writes only its separate Telegram delivery ledger.
