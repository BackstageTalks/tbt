# BlinQ Telegram publisher — Admin configuration

## What was implemented

Admin → **Telegram bot** (separate from the existing Telegram group/link management):
- TOP, Value, Esá switches and optional **one random TOP FREE** selection.
- One combined message or one per premium category, maximum 1–10 picks each.
- Bratislava local time, weekdays, automatic switch, probability/available odds, legacy BackstageTalks header/footer and one-line rows.
- **Publish** saves settings to the existing authenticated UI configuration; **Zaradiť jednorazové odoslanie** persists a one-shot request. The button queues, not confirms Telegram delivery.
- Fully disabled by default on release.

## Secrets

Already supplied:
- **TGB**: Telegram bot token
- **TGCH**: Telegram channel/chat ID

Optional **TGCH_FREE**: distinct FREE-channel chat ID. Without it the FREE one-pick message goes to TGCH. Bot must be admin/member with posting rights in the destination(s).

The publisher also needs the existing **TBT_DATA_GH_TOKEN** to read the private `BackstageTalks/tbt-data` prediction release (`tbt-predictions-v1`).

The secrets are never written into the frontend, API response, Azure UI configuration or job logs. Do **not** enter them into Admin.

## Schedule and manual sending

GitHub Actions workflow: `BlinQ Telegram offer`. Triggers:
- Existing external hourly tick commit `.github/hourly-api-gapfill-tick.json`, branch `main`.
- Optional external `repository_dispatch` event `telegram-offer-tick` for finer (for example 10-minute) resolution.
- Manual GitHub Actions `workflow_dispatch`.

The Admin clock does not itself create a cron job. The workflow checks the configured local time and a 90-minute catch-up interval; depending on when the external tick runs, dispatch can be delayed. There is **no background polling inside the API** and no native GitHub cron in this repository. A one-shot Admin request likewise waits for the next workflow tick or a manual Actions run and expires after 90 minutes.

## Source of truth

Only the checksum-verified `daily_offer_snapshot.json` from the private release, with `confirmed_only: true`, today's correct betting day and current generation timestamp, is eligible. The TOP candidates use the public canonical TOP selection logic (`_daily_rows`), which excludes Value duplicates. Value uses `value_picks`. Esá uses `ace_picks` filtered to `market=aces` (not double faults).

If no eligible rows exist, it does **not** send a placeholder. Already started rows are excluded by default; the Admin can explicitly include them. No paid tennis API calls, model training, CDB writes, or unconfirmed-prediction fallbacks occur.

The FREE selection is a stable hash-based pseudo-random pick from today's eligible official TOP. Once a FREE send has been reserved in the durable ledger, later runs that day cannot send another FREE message. This is **at-most-once**, prioritizing no duplicate posts: if Telegram times out after accepting a message, the workflow will not blindly retry it. Inspect the Actions run and target channel manually to resolve ambiguous delivery.

## Duplicate protection

The workflow uses a separate persistent branch `telegram-bot-state`. It records an attempt and confirms the remote commit before calling Telegram. Only one workflow job runs at a time. Normal premium scheduled sends have one reservation per betting day; each manually requested resend has a different reservation ID. No unrelated `main` changes are made to log delivery state.

## Tests and rollout

Offline contract tests: `tests/test_telegram_offer_publisher.py`.

After merge and a verified successful frontend deployment, configure Admin → Telegram bot → enable the publisher, select categories, save via Publish. Use **Zaradiť jednorazové odoslanie** and (if the next hourly tick is too far away) manually run the `BlinQ Telegram offer` workflow from Actions. Confirm a Telegram `message_id` in Actions AND the message in the destination channel before enabling automatic sends.

**Do not mistake a successful dispatch, saved configuration, or HTTP 200 response for verified Telegram delivery.**

## Ranné Results — výsledky predchádzajúceho betting day

Samostatný read-only workflow `.github/workflows/telegram-results.yml` a formátovač `scripts/telegram_result_publisher.py`:
- Predvolený čas **07:00 Europe/Bratislava**; 06:00 je hranica betting day. Napríklad 31.10. o 07:00 patrí report za 30.10. V Admin → Telegram bot samostatne zapni **Odosielať výsledky** a nastav `Čas reportu`.
- Trigger: externý GitHub `repository_dispatch` typu **`telegram-results-tick`** podľa tvojho cronu (približne 07:00 Bratislava vrátane letného času). Zároveň funguje už existujúci externý hourly tick alebo ručné `workflow_dispatch`; prijať sa môže len 90-minútové okno od nastaveného času.
- Dáta sa **nevypočítavajú nanovo**. Interný read-only endpoint `GET /api/v1/internal/telegram-results` vyžaduje už používaný `BLINQ_LIVE_WORKER_TOKEN`. Číta presne aktuálne serverové Results a ich overený archív, používa existujúci zoznam testovacích vylúčení. Nevolá platené športové API, nemení výsledky ani ich nepersistuje.
- Pre TOP, Value a Esá formát **Data Betting by BackstageTalks → 📊 Results → 📅 → 1️⃣ ✅ / ❌ / ➖ / ⏳ → súhrn units + ROI**. Finančné metriky zobrazí iba pri skutočne ocenených, vydaných a overených výsledkoch.
- Report zahŕňa len **zaznamenané** Results v archíve. Po 07:00 nemusia byť všetky zápasy doriešené, preto sa nikdy netvári ako úplné vyhodnotenie celej vydanej ponuky. Pri prázdnom overenom výsledkovom zdroji sa nič neodosiela, namiesto nepravdivého „0 výhier“.
- Ak predchádzajúci FREE výber z TOP existuje v dennej rezervácii a má zodpovedajúci oficiálny výsledok, bot vie vytvoriť aj 📊 Results | FREE. `TGCH_FREE` ho smeruje do FREE kanála, inak používa `TGCH`.
- Spoločné idempotentné rezervácie na `telegram-bot-state`: **maximálne jeden ranný report za predchádzajúci betting day**. Pri chybnom/neurčitom odoslaní sa neskúša slepá automatická oprava.
- Offline testy: `tests/test_telegram_results.py`. Nevyžaduje sa žiadny nový secret okrem existujúcich `TGB`, `TGCH`, `BLINQ_LIVE_WORKER_TOKEN` a čítacieho `TBT_DATA_GH_TOKEN` pre tipy.

**Vynucovaný limit:** PR je iba používateľské zobrazenie, read-only endpoint a Telegram automatizácia. Nepíše do CDB, nemení schému ani výpočty modelu, nevytvára settlement a nevolá provider API.
