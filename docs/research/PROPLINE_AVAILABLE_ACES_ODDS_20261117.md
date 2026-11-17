# PropLine — bezplatné aktuálne ceny tenisových ESÁ (17. 11. 2026)

## Cieľ / rozsah
Jednorazovo prečítať bezplatné predzápasové PropLine kurzy a vyhodnotiť ich proti piatim dnes potvrdeným Over ESÁ BlinQ. Nezmeniť výber modelu, vydané tipy, web, Telegram, API Pro, CDB ani cron. Oddeliť športové single-bookmaker milníky `N+ Aces` od DFS/pick'em cien `Over/Under`. Všetky sumy v tabuľkách sú desatinné kurzy prepočítané z amerického formátu.

## Dôkazy
- [Živý jednorazový prvý zber](https://github.com/BackstageTalks/tbt/actions/runs/44070937891), **2026-11-17 11:06:20 UTC**: jeden API request do `https://api.prop-line.com/v1/sports/tennis/odds?markets=player_aces,total_aces`, 22 eventov v odpovedi, 19 budúcich eventov, 103 skupín `player_aces`, 414 **bookmaker milestone** cien + 7 dvojcestných DFS/pick'em párov, rate-limit header `X-Daily-Remaining=405` po volaní; výstup uvádza prvých 250 surových riadkov pre dôkaz, nie celý súbor (žiadna zámena s počtom overených tipov).
- [Kompaktný read-back všetkých zápasov](https://github.com/BackstageTalks/tbt/actions/runs/44071219580), **11:08:11 UTC**: 31 reprezentatívnych tenisových hráčov s bookmaker milestone kurzy a všetkých 7 DFS párov (2 z nich až na 18. november). Jeden príklad z dnešnej ponuky: Rodionov – Nagal, Napoleon `Jurij Rodionov 8+ Aces` za 1,629, ale vydaný BlinQ tip je **Over 3,5**, takže nejde o zhodný kontrakt.
- [Presná kontrola piatich dnes publikovaných kontraktov](https://github.com/BackstageTalks/tbt/actions/runs/44071360818), **11:09:03 UTC**:
  - Borna Gojo Over 7,5 vs Kimmer Coppejans: bez presného bookmaker `8+ Aces` kurzu v tomto feede.
  - Otto Virtanen Over 7,5 vs Moez Echargui: bez presného bookmaker `8+ Aces`.
  - Jurij Rodionov Over 3,5 vs Sumit Nagal: dostupné sú iba `5+ Aces` a vyššie, nie `4+ Aces`.
  - Thiago Seyboth Wild Over 3,5 vs Nicolas Kicker: bez presného bookmaker `4+ Aces`.
  - **Niels Visker Over 6,5 vs Samir Banerjee**: presný bookmaker milník `7+ Aces` za **1,09** v Napoleon, Superbet PL a Superbet RO. **Nie je vydavateľný** pri súčasnej spodnej hranici **1,50** a jeho sportsbook settlement podmienky neboli nezávisle preverované.
- DFS (nejde o single bookmaker stávku, nezamieňať za 2-way ESÁ): Fils – Jodar, Arthur Fils 6,0 Dabble 2,00/2,00; Fils 6,5 Sleeper 2,11/1,529. Zverev – Shelton, Alexander Zverev 10,5 Dabble 2,00/2,00 alebo Sleeper 1,80/1,758; Ben Shelton 12,0 Dabble 2,00/2,00. Zvyšné dva páry z `underdog` sú pre Cobolli – Tiafoe na 18. november a nepatria k dnešku.
- Pôvodný [dnešný podpísaný feed a parity webu](https://github.com/BackstageTalks/tbt/actions/runs/44059390414) a [audit 5+27 zvyšných tipov](https://github.com/BackstageTalks/tbt/actions/runs/44059750084) zachytáva stav o 09:51 až 09:54 UTC.

## Verdikt / integrita
- Zaznamenané: **414 bookmaker cenových míľnikov** neznamená 414 použiteľných bookmaker O/U kontraktov ani 414 rôznych zápasov.
- Pre dnešných päť Over tipov: **1 presná hranica, 0 zodpovedajúcich kurzov >=1,50**. Na kompletný O/U bookmaker kontrakt (Over aj Under na tej istej hranici) **0**. VIAC ES dvojcestný trh nebol pri tomto zbere preukázaný (predchádzajúci živý audit: 0/8 testovaných zodpovedajúcich zápasov).
- Športové predikcie **nemeníme** spätne na zápasy s dostupným bookmaker kurzom. Kurzy môžu byť až následný filter pre budúce nevydané modelové tipy.
- Zber prebehol len ako izolovaný audit na branchi `audit/propline-available-odds-table-20261117`, workflow po auditovaní vypnutý z automatického `push` spúšťania (ponechaný iba manuálny `workflow_dispatch`). **0 CDB zápisov, 0 zmenených publikovaných tipov, 0 paid API požiadaviek.** Doterajší produkčný systém a cron nezmenené.
