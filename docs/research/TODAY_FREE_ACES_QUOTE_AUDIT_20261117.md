# BlinQ — today's free bookmaker ESÁ / VIAC ES exact-price verification

Date **2026-11-17**, Bratislava.

## Authorized scope / invariants
Read-only research of already published website contracts, no web/model/TG/CDB/cron mutation, no paid API Pro calls, no synthetic substitutions. Compare event+opponents+start+player+market+exact line to free PropLine markets, enforcing same-book completeness. Ignore starts before the observation. A completed request is not sufficient proof of a usable price.

## Source parity
- [Independent current signed feed / website readback #44059390414](https://github.com/BackstageTalks/tbt/actions/runs/44059390414), 09:51:33 UTC. `confirmed_only=true`, betting day `2026-11-17`. The private signed `daily_offer_snapshot.json` from `tbt-data` and the production `/api/v1/internal/serving-readback` both identify exactly the same source generation `2026-11-17T05:01:00.000201Z`.
- **6** published player-ESÁ O/U cards (5 future at that moment), **30** published `most_aces` cards (27 future). All 6 O/U rows have `on_website_ace_keys=true`; the separate most-aces rows share the website-authority key list. The 5 future O/U cards were: Borna Gojo O7.5 (vs Kimmer Coppejans), Otto Virtanen O7.5 (vs Moez Echargui), Jurij Rodionov O3.5 (vs Sumit Nagal), Thiago Seyboth Wild O3.5 (vs Nicolas Kicker), Niels Visker O6.5 (vs Samir Banerjee). The early Isomura–Gorzny card was already started, excluded from price comparison.

## Actual no-cost provider audit
- [Live signed-offer-to-PropLine read-only comparison #44059750084](https://github.com/BackstageTalks/tbt/actions/runs/44059750084), 09:54:00 UTC.
- 1 bulk authenticated FREE `PropLine` `player_aces,total_aces` response + 8 market-list requests, **9 provider requests total**, `X-Daily-Remaining=406` at end. No other provider calls, no CDB/TG writes.
- Provider returned **24** event objects, **133** `player_aces` market groups (many unrelated to today's BlinQ contracts). Only **8** distinct today-offered BlinQ match identities linked uniquely to future events on the provider board (7 full names, 1 abbreviated; no ambiguous matches).
- ESÁ O/U: **1 of 5** selected future cards had a uniquely matched PropLine fixture: Rodionov–Nagal `Jurij Rodionov Over 3.5`, provider event `830329`; no same bookmaker complete O/U or `4+ Aces` standalone milestone with identical player and line in the bulk response. Four other current ESÁ fixtures not on the bulk provider board. **0 of 5** usable free bookmaker quotes.
- VIAC ES: **8 of 27** selected future cards had uniquely matched provider fixtures. All **8** had market-list verification; **none** advertised an unambiguous whole-match two-way `most_aces`/winner/superiority market. **0** verified VIAC ES quotes among the tested matches. The other **19** offered selections were not linked to provider events, so do *not* infer bookmaker absence there.
- Historical research had revealed sportsbook `N+ Aces` milestones in PropLine but on other events, and DFS `Over/Under` multipliers that are not ordinary standalone bookmaker odds. Their existence is **not** a price match for the published BlinQ offers.

## Status and next action
- **TESTED**, not a usable provider integration. Price attached to published picks: **0**; CDB rows written: **0**; TG edits: **0**.
- No automatic publishing or retroactive repricing. Reassess free sources on newly issued future ESÁ offers and prioritize bookmaker milestones only if the player/event/exact half-ace threshold and settlement semantics align. A three-way most-aces market is not BlinQ's two-way contract.
- One-time branch `audit/today-aces-free-quotes-20261117` holds the audit script; it was not merged or deployed.
