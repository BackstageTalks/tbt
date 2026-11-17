# BlinQ — bezplatné zdroje reálnych tenisových kurzov ESÁ / VIAC ES

Dátum overenia: **2026-11-17**, predzápasové vzorky ATP.

## Cieľ a hranice

Len bezplatné riešenie; overiť **skutočne dostupné** individuálne ESÁ Over/Under a dvojcestné VIAC ES, nie všeobecné katalógové deklarácie. Žiadne platené trialy, CDB/produkčné zápisy, model, web, už vydané tipy ani API Pro. Existujúce PropLine `PROPL` tajomstvo sa používalo výhradne v pamäti runnera, nebolo logované; odpovede logovali len verejný event/market/bookmaker a zostávajúcu kvótu.

## Dôkazy (autentický free PropLine API read-only)

- [Prvý reálny overovací beh](https://github.com/BackstageTalks/tbt/actions/runs/44040989158) o 07:44 UTC: `/v1/sports/tennis/odds?markets=player_aces,total_aces`; 20 eventov; 89 skupín `player_aces`; 5 kompletných Over/Under párov iba od DFS/pick'em Dabble a Sleeper. Zostávajúca kvóta podľa odpovede 280.
- [Detailný kontraktový probe](https://github.com/BackstageTalks/tbt/actions/runs/44041255021) o 07:46 UTC: 19 eventov, znovu 89 skupín `player_aces`, 5 DFS párov; 78 skupín od bookmakerov (`napoleon`:26, `superbet_pl`:26, `superbet_ro`:26). Dva konkrétne ATP zápasy (Fils–Jodar, Zverev–Shelton) advertizujú `player_aces`, **neadvertizujú žiadny `most_aces`/winner/superiority market**. Príklady pravých predzápasových hráčskych trhov `dabble` a `sleeper` nemožno predávať ako sportsbook single-bet odds.
- [Kontrola skutočnej sportsbook štruktúry](https://github.com/BackstageTalks/tbt/actions/runs/44041456814) o 07:47 UTC: bookmaker `player_aces` sú **YES-only milníky** `2+ Aces`, `3+ Aces`, `4+ Aces`, `5+ Aces` s `point=null`, nie kompletné Over/Under. Príklad: Takuya Kumasaka `5+ Aces` u Napoleon pri americkom kurze +142 (desatinný 2,42), Yi Zhou `6+ Aces` +155 (2,55); rovnaké základné trhy Superbet PL/RO. Za správneho zápasu a pravidiel môže `N+ aces` matematicky zodpovedať výhradne **Over N-0.5**, nikdy Under, ale vyžaduje oddelenú kontraktovú validáciu pred využitím.
- [Jednorazový verejný web fetch](https://github.com/BackstageTalks/tbt/actions/runs/44041714635): Paddy Power ATP Finals Zverev–Shelton má verejný HTML obsah s hráčskymi ESÁ prahmi (napr. 11+, 13+), ako sa dá overiť [na stránke bookmakera](https://www.paddypower.com/tennis/atp-finals-turin-2026/a-zverev-v-be-shelton-36313125?tab=player). Neprihlásený štandardný HTTP zberač z GitHub runnera však dostal **HTTP 403**. Tento verejný web nie je preukázaný spoľahlivý automatizovaný zdroj.
- [OddsSafari – aktuálny ATP Finals Zverev/Shelton](https://www.oddssafari.gr/en/matches/tennis/atp-finals/zverev-a.-vs-shelton-b./22408157?MarketTypeID=301&ScopeID=301) zobrazuje prepínače `Player O/U Aces` a `Most Aces - 3way`; **žiadne ceny pre tie prepnuté trhy neboli v tejto kontrole overené**. Prípadný `3way` (s remízou) **nie je** zameniteľný za požadovaný dvojcestný VIAC ES kontrakt.
- PropLine verejné [API dokumenty](https://prop-line.com/docs) výslovne hovoria, že DFS ceny nie sú samostatné sportsbook stávky, a dokumentujú free 1 000 requests/deň. [RapidOddsAPI](https://rapidoddsapi.com/) má 250 celkových bezplatných kreditov (nie trvalý denný/monthly prísun). [MoviOdds](https://moviodds.com/bet365-tennis-odds-api/) má vo free len hlavné trhy, nie rozšírené ESÁ.

## Stav

**OVERENÉ:** Free PropLine skutočne poskytuje sportsbook `player_aces` **jednostranné milníkové** kurzy s identity/time/source, aj DFS dvojstranné multiplikátory. Bežný bookmaker **2-way player ESÁ O/U: 0 presných párov** v preverenom živom snímku. Presný **2-way VIAC ES: 0** v dvoch explicitne preverených ATP eventoch. To nie je dôkaz, že sa tieto trhy nikdy neobjavia.

**NEIMPLEMENTOVANÉ:** Automatické produkčné cenové použitie; žiadna zmena modelu, CDB, UI, cron ani morning reader. Na branch sa spustil **iba výskumný** read-only workflow. Po verifikácii bol jeho automatický `push` trigger odstránený.

## Nasledujúci bezpečný krok

Ak má BlinQ zmysel pokrývať aj **Over-only** tipy bez kupovania dát, oddeleným schváleným pravidlom validovať bookmakerovo `N+ Aces` proti *konkrétnej* modelovej hranici `N-0.5`, identite, event time, platnosti/trvaniu ponuky a kurzu; overiť presnú zhodu na nevydanom tipe, nefalšovať chýbajúce Under/VIAC ES a nikdy nemiešať DFS či rôznych bookmakerov. Dvojcestné VIAC ES naďalej používať len po skutočnom bookmaker preukázaní plného kontraktu. Žiadne nové automatické požiadavky bez kontroly zdieľanej free kvóty a rezervy.
