# BlinQ – responzívna verzia

Pripravené 10. 9. 2026 z tvojho archívu `tbt-main.zip`.

## Čo použiť

**`blinq-responsive-web-update.zip`** obsahuje iba päť súborov na aktualizáciu existujúceho webu. Toto je najjednoduchší spôsob vyskúšania.

**`blinq-responsive-full.zip`** obsahuje celý repozitár vrátane pôvodného backendu, assetov a GitHub workflowov. Pridaný je tento návod a opakovateľné funkčné kontroly v `docs/responsive-qa/`.

## Ako to ráno vyskúšať

1. Ponechaj si pôvodný ZIP ako zálohu.
2. Rozbaľ menší aktualizačný ZIP do koreňa existujúceho repozitára. Nahraď `web/index.html`, `web/styles.css`, `web/app.js` a pridaj `web/responsive.css`, `web/responsive.js`. Dôležité je nahrať všetkých päť súborov spolu.
3. Nasaď web doterajším spôsobom cez existujúci GitHub/Azure postup. Existujúca workflow „Test and deploy“ podporuje aj manuálne spustenie. Nemeň konfiguráciu Firebase, API ani uložené tajné premenné.
4. Otvor nasadený web a prihlás sa bežným účtom. Ak ostal starý vzhľad, obnov stránku bez cache.
5. Skús telefón na výšku aj na šírku, tablet a PC: menu, ďalšiu kartu, „See all“, Results, Account a odhlásenie. Skús aj účet s nižším členstvom, aby si videl zamknuté karty.

Samotné dvojkliknutie na `index.html` nie je funkčný náhľad: aplikácia potrebuje pôvodné API, Firebase a obsluhu ciest zo servera. Nič som nenasadil na produkciu ani na nový hosting.

## Čo sa zmenilo

- Zachované tmavé pozadie, logo, fialové/zelené akcenty a pôvodné obrázky.
- Čitateľnejšie texty, väčšie dotykové ovládacie prvky a flexibilné výšky kariet.
- Na telefónoch a menších tabletoch vysúvacie menu a spodná navigácia Dashboard / Results / Account; na PC bočná navigácia.
- Viditeľný názov stránky a stav aktualizácie namiesto opakovaných reklamných pruhov v hlavičke.
- Počet kariet podľa šírky obrazovky, dostupné šípky aj na mobile a voliteľné listovanie potiahnutím.
- Výsledky a zoznamy tipov na úzkej obrazovke ako záznamy s pomenovanými údajmi. Na PC zostávajú tabuľkami.
- Technické pravidlá výberu možno rozbaliť; pri prázdnom zozname je krátke vysvetlenie.
- Tri reklamné/promopozície, na mobile vložené medzi sekcie. Hlavička a bočný panel neduplikujú ďalšie reklamy.
- Lepšie správanie dialógov, ovládanie klávesnicou, viditeľný fokus a podpora obmedzenia animácií.
- Funkčné tlačidlo Späť pri prechode medzi stránkami aplikácie.

## Dáta bez ručného dopĺňania

Existujúci backend, zdroje dát a plánované GitHub workflowy zostali nezmenené. **Tipy ani výsledky nemusíš ručne vypĺňať**, pokiaľ tvoje pôvodné API, zber dát a naplánované publikovanie fungujú.

Otvorená prihlásená stránka sa pokúsi obnoviť dáta každých päť minút. Obnovu skúsi aj po návrate do viditeľnej karty, ak od posledného pokusu prešla minúta, a pri návrate internetového spojenia. Tým sa načíta najnovší publikovaný výstup; nevynucuje to nový výpočet modelu. Počas editácie administrácie, písania do formulára a otvorených dialógov sa automatická obnova nevykonáva. Pri chybe zostanú už zobrazené dáta a objaví sa stav s možnosťou opakovať načítanie. Obnova neresetuje práve zvolenú stranu kariet, pokiaľ stále existuje.

Prihlásenie a členské oprávnenia sa zachovali. Odpoveď rozbehnutej obnovy po odhlásení už nesmie znovu otvoriť dashboard.

Toto je responzívna webová aplikácia. Bez internetu po novom načítaní stránky neponúka offline dáta ani offline prihlásenie.

## Reklamy

Existujúce nastavenia kampaní, obrázkov, mobilných obrázkov, odkazov a merania zobrazení/kliknutí zostali. Aplikácia použije najviac tri kreatívy z povolených obsahových riadkov: najprv jednu z každého povoleného riadka a potom doplní voľné pozície z ďalších kreatív. Štandardné nastavenie zobrazí pôvodné tri BlinQ promo bannery. Pozície sa rozložia automaticky podľa zariadenia.

Ak chceš skutočnú reklamu partnera, raz nastav jeho kampaň/obrázok a odkaz v existujúcej administrácii. Žiadnu novú reklamnú sieť ani príjem z reklám táto úprava sama nezapája. Ak všetky obsahové riadky vypneš, reklamné pozície sa skryjú.

Administratívne nastavenie počtu kariet sa rešpektuje ako horný limit, fyzická šírka obrazovky má prednosť. Mapka reklám v administrácii označuje pôvodné zdrojové pozície; verejný web ich rozkladá do troch responzívnych pozícií.

## Overenie

- Kontrola syntaxe oboch upravovaných JavaScriptov.
- Oba pôvodné JavaScriptové testy Firebase/prihlasovania: úspešné.
- 45 pôvodných testov kontraktov rozhrania, assetov a autentifikácie: úspešných.
- Funkčné testy cez JSDOM: stránkovanie pre 14 šírok od 320 do 2560 px, navigácia, formulárové stavy, všetky verejné trasy, menu, zamknuté/prázdne karty, administrácia, tri bannery, chyba obnovy, návrat online a odhlásenie počas obnovy.
- Obe CSS sa dajú syntakticky spracovať a lokálne odkazy z HTML smerujú na existujúce súbory.

Testy šírok overujú logiku stránkovania, nie skutočné vykreslenie prehliadača. Vizuálne overenie na reálnych zariadeniach, živé Firebase/API a produkčné nasadenie neboli vykonané. Kompletná sada backendových testov sa nespúšťala, backend sa nemenil.

## Návrat k pôvodnej verzii

Obnov tri pôvodné súbory `index.html`, `styles.css` a `app.js` zo zálohy do `web/` a znovu ich nasaď. Pridané `responsive.css` a `responsive.js` môžeš ponechať alebo zmazať; pôvodná stránka ich nenačítava.
