# BlinQ – Telegram 06:20 daily cron (externý plánovač)

## Stav a cieľ

Cron **zatiaľ nie je aktivovaný**. Tento súbor je príprava pre operátora. Produkčný
worker je [`telegram-daily-offer.yml`](../../.github/workflows/telegram-daily-offer.yml).
Schválená spoločná správa = všetky oprávnené TOP → VALUE → ACES **bez nadpisov**
a bez EV, predikcia/pick namiesto projekcie; samostatná FREE správa obsahuje
jeden deterministicky vybraný TOP tip. Každý riadok má jednoduché označenie kategórie (`T |`, `V |`, `A |`), samostatný tip má pôvodné Telegram emoji `🆓 FREE |`. Číselné prefixy a neexistujúce vlastné systémové emoji sa nepoužívajú.
Zachovaná je pätička a klikateľný odkaz na BlinQ Stat Engine.

Údaje na nastavenie cronu sú aj v
[`telegram-daily-offer-0620.json`](./cron/telegram-daily-offer-0620.json).

## Externý plánovač / cron-job.org

| Nastavenie | Hodnota |
| --- | --- |
| Názov | `BlinQ – denné TG predikcie` |
| Enabled | Zapne operátor po overení |
| Čas | **06:20 každý deň** |
| Cron | `20 6 * * *` |
| Timezone | `Europe/Bratislava` (letný/zimný čas automaticky) |
| Method | `POST` |
| URL | `https://api.github.com/repos/BackstageTalks/tbt/dispatches` |
| HTTP success | **204 No Content** = *GitHub prijal spúšťač*, nie doručenie Telegramu |
| Timeout | 30 s |
| External retries | 0 – opakovanie má na starosti interná fronta |
| Auth | GitHub **fine-grained PAT**, iba repo `BackstageTalks/tbt`, Contents **Read and write** |

Request headers:

```http
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
Authorization: Bearer <GITHUB_CRON_TOKEN>
```

Request body – **Raw JSON**:

```json
{"event_type":"telegram-daily-offer-tick"}
```

Token vlož len do **secret/authorization field externého plánovača**. Token,
súkromný snapshot, chat ID ani priame tipy sa neposielajú v JSON payload-e.

## Fronta a zdroje dát

1. `repository_dispatch` spustí `BlinQ Telegram complete daily offer (06:20 queue)`.
2. `queue` uloží denný zámer do súkromnej vetvy
   `BackstageTalks/tbt-data@telegram-bot-state` a vykoná read-back.
3. `wait-for-confirmed-offer` čaká na ukončenie relevantných workflow
   (`data.yml`, `morning-refresh.yml`, `prediction-release-recovery.yml`,
   `data-autofill.yml`, `data-hourly-quota-gapfill.yml`,
   `nightly-data-maintenance.yml`). Nezaberá pritom Telegram writer lock.
4. Po čakaní načíta **aktuálny** `daily_offer_snapshot.json` zo súkromného
   release `tbt-predictions-v1`. Kontroluje `confirmed_only`, betting day,
   `generated_at`, dĺžku dát a SHA-256 oproti
   `_tbt_bundle_manifest.json`. Predikcie odoberá výlučne zo schváleného
   publikovania; **nevolá tenisové API**, neposiela shadow ani staging.
5. Ak dáta ešte nie sú pripravené, opakuje kontrolu každých 60 s.
   Pred limitom GitHub behu odovzdá čakajúci zámer ďalšiemu workflow behu.
   **06:20 je začiatok čakania, nie expirácia odoslania.**
6. `deliver` znova otvorí súkromný ledger a pred `sendMessage` zapíše
   rezerváciu do globálneho `blinq-telegram-ledger` concurrency group;
   až po Telegram message ID z každého prijatého príspevku uloží
   `sent` a vykoná nezávislý git read-back.

**Doručenie nie je garantované samotným HTTP 204.** Hotovo znamená úspešný
`deliver` job, stav `sent` a uložené message ID. Ak Telegram alebo GitHub
zlyhá po rezervácii, nepripravuj automaticky duplicitnú náhradu – Telegram
nemá garantovaný idempotency key. Skontroluj kanál, logy a ledger, až potom
prípadne manuálny recovery postup. Po zmene dňa sa **staré predikcie neposielajú**.

Ak je ponuka väčšia než limit Telegramu 4096 UTF-16 jednotiek, publisher ju
rozdelí na viaceré premium správy po riadkoch, bez straty tipov.
Riadky sú mobilne kompaktné; presné zalomenie závisí od šírky klienta.

## Prevádzkové overenie

- Akcia: `https://github.com/BackstageTalks/tbt/actions/workflows/telegram-daily-offer.yml`.
- Release zdroj: `BackstageTalks/tbt-data`, tag `tbt-predictions-v1`.
- Evidencia príjmov: `BackstageTalks/tbt-data@telegram-bot-state:ops/telegram-bot-state.json`.
- Existujúce GitHub Actions secrets: `TGB`, `TGCH`, voliteľne `TGCH_FREE`,
  `TBT_DATA_GH_TOKEN`; tieto sa **nikdy nevkladajú** do externého cronu.
- Denné vyhodnotenie je samostatný workflow `telegram-results.yml`.
  Ak ho plánuješ externe, používa `07:00 Europe/Bratislava` a event
  `telegram-results-tick`. Toto nastavenie neaktivuje ani nemení ranné reporty.
- Úspešný manuálny formátovací resend z 31.10.2026 sa nepočíta ako ďalšie
  vydanie predikcií; obnovuje iba vizuál. Cron ho nesmie opakovať.

## Dôležité

Nerob ďalší denný manuálny send v ten istý betting day, keď už má ledger
`reserved` alebo `sent`. Fronta a starší Admin publisher teraz zdieľajú
spoločnú same-day ochranu proti duplicitám. Prevádzkový prefix
`repost:format-v2-no-ev` je iba jednorazový, nie cron.
