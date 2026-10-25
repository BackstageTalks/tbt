# BlinQ Admin — navigácia, vlastníctvo nastavení a UX audit (25. 10. 2026)

## Rozsah

Kontrola všetkých jedenástich sekcií v `web/app.js` a ich operácií z pohľadu rozdelenia zodpovedností, uloženia a rizika omylu. Zmeny UX v tomto PR používajú existujúce API aj existujúcu štruktúru `ui-config`; neprepisujú prístupy účtov, zdrojové športové dáta ani historické záznamy.

## Mapa zodpovedností a ukladania

| Sekcia | Čo vlastní | Ako sa potvrdí |
| --- | --- | --- |
| Účty | Používatelia, úrovne, stav, TG čistenie, prihlásenia a prevádzkový log | Vlastné uloženie účtu alebo konkrétnej operácie; nie globálne Publikovať |
| Členstvá | Názvy, texty, odkazy, pozvánky, platnosť plánu, politika neaktivity ROOKIE | Koncept UI → Publikovať |
| Zobrazenie | Jediný editor prístupu podľa levelu; denné kategórie, SHOW/BLUR/HIDE, počet a poradie riadkov | Koncept UI → Publikovať |
| Projektové skupiny | Projektové členstvo, žiadosti, skupinové INFO a výsledky | Samostatné API operácie |
| INFO & LIVE | Publikácia správ, publikum, LIVE radar, výsledky, retencia a mazanie histórie | Vlastné operácie; retencia a mazanie sa neukladajú globálnym Publikovať |
| Telegram skupiny | Externé odkazy, názvy, min. level | Koncept UI → Publikovať |
| Bannery | Hero, kreatíva, obrázky, pozadie | Koncept UI → Publikovať |
| Dashboard KPI | Tri hlavné ukazovatele | Koncept UI → Publikovať |
| Testovacie tipy | Manuálne označenie testovacích predikcií | Samostatná potvrdená operácia |
| Model Lab / Kalibrácia | Tréning, kandidáti, shadow, kontrolné výsledky | Riadené operácie; nie globálne Publikovať |
| Systém | Read-only prevádzkový stav, diagnostika a API rozpočet | Bez ukladania; obnovenie je čítacia operácia |

## Čo sa opravuje v tomto PR

1. **INFO & LIVE rozdelené podľa úlohy:** Správy / Publikum & radar / Vyhodnotenia / História & mazanie. Trvalé mazanie je v oddelenom pohľade a nie vedľa editora správy. Prepnutie je len zobrazenie/skrytie existujúcich DOM panelov, takže nestráca rozpísaný text a nevolá save.
2. **Zobrazenie rozdelené:** Prístupy a limity / Denná ponuka / Poradie kategórií. Výber levelu zostáva na každom pohľade spoločný, poradie je globálne, ostatné nastavenia patria zvolenému levelu.
3. **Mapa „Kde čo nastavím“:** 11 priamych odkazov usporiadaných do troch oblastí; každá položka popisuje aj spôsob uloženia.
4. **Spresnenie admin hlavičiek:** Účty, projektové skupiny a INFO & LIVE nesmú sľubovať „automatické okamžité uloženie“ pri samotnom prepise poľa. Majú vlastné akcie potvrdenia.
5. **Ochrana concept-vs-live:** žiadna zmena dátového modelu alebo backendovej politiky; špecifické tlačidlá zostávajú oddelené od globálneho Publikovať.

## Audit ďalších miest (nezmenené správanie, sledovať pri ďalšej úprave)

- **Členstvá:** politika neaktivity ROOKIE žije v Členstvách, hoci udalosti a e-maily sú v Účtoch. V tomto PR sa nepresúva, lebo je to súčasť publikovanej konfigurácie; premiestnenie do čisto API-editora Účty by bez zmeny transakčnej logiky mohlo zavádzať.
- **Projektové skupiny vs INFO & LIVE:** existujú dva samostatné druhy INFO — skupinové a globálne. V navigácii majú explicitne odlišné vlastníctvo; nezlučovať ich dáta ani mazanie.
- **Model Lab a Kalibrácia:** riadené tréningové operácie a read-only kontrola zdieľajú sekciu. Potenciálne rozdelenie do vlastných podzáložiek vyžaduje samostatné end-to-end testy tréningového workera; v tomto PR neprerábať.
- **Konfigurácia bannera:** „Uložiť koncept“ ostáva iba lokálny browser draft, „Publikovať“ sa overuje cez API a read-back; pri strate spojenia zostáva globálne publikovanie blokované.
- **Zostávajúce viaceré formy mazania:** existujú v Účtoch, Projektových skupinách, Testovacích tipoch a INFO & LIVE. Vyžadujú ich vlastné potvrdenia a nesmú sa prepájať na jedno generické delete tlačidlo.

## Bezpečnostné a testovacie hranice

Offline Chromium regresia v `tests/browser_admin_ux_audit_navigation.py` overuje prepínanie panelov, zachovanie rozpísaného nadpisu, navigačnú mapu a to, že tlačidlá trvalého mazania nie sú súčasťou bežného pohľadu Správy, pri 390 / 768 / 1280 / 1440 px. Nejde o autentifikovaný test skutočného mazania ani o dôkaz nasadenia. Finálny release vyžaduje zelené CI, úspešný Azure deploy a zhodu read-back SHA/assetov.
