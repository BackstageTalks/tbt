# Oprava nasadenia – market feed/ledger mismatch

## Nasadenie

Ak už máš responzívnu verziu v repozitári, rozbaľ `blinq-publication-fix.zip` do koreňa repozitára `BackstageTalks/tbt`, nahraď súbory a commitni zmeny. Potom spusti workflow **Test and deploy** znova ako nový beh z aktuálneho `main` (manuálne Run workflow), nie opakovanie starého behu zo starého commitu.

Alternatíva: `blinq-responsive-full-fixed.zip` je kompletný upravený repozitár s responzívnym webom aj touto opravou. Nemusíš používať oba ZIP-y.

`feed.json` ani `ledger.json` v privátnom release ručne neprepisuj. Existujúci bundle manifest a história zostávajú zachované. Obnovenie publikovaných hodnôt vykoná opravený kód pri príprave feedu; následné potvrdenie nasadenia používa rovnaký postup na privátnom kandidátovi a stále vyžaduje presnú zhodu so skutočne nasadeným feedom.

## Príčina

Pri Top Bets event `16983980` bol kurz v oboch súboroch rovnaký. Novší výpočet vo feede mal pravdepodobnosť `0.7127801010001384`, ale už publikovaná hodnota v ledgeri bola `0.7128064800368561`. Odlišovali sa aj edge a EV. Pôvodný pipeline zachovával publikovanú históriu, ale do feedu vkladal nový výpočet tej istej ponuky a pred uložením ho neoveril proti market ledgeri.

## Správanie opravy

- Pre tú istú kombináciu zápasu, sekcie, trhu, hráča a stávkového dňa sa môže použiť iba jednoznačný už publikovaný záznam.
- Zosúladia sa hodnoty ponuky vo feede; pôvodný ledger sa neprepisuje a nevymýšľajú sa nové kurzy ani výsledky.
- Chýbajúce, nejednoznačné alebo iba pending záznamy s rozdielnymi hodnotami stále spôsobia chybu. Kontrola nie je vypnutá ani zjemnená toleranciou desatinných čísel.
- Príprava nasadenia, kontrola existujúceho kandidáta pri ďalšom výpočte a potvrdenie po nasadení používajú zhodnú normalizáciu privátneho kandidáta. Skutočne nasadený feed sa pri porovnaní spätne neopravuje.
- Pipeline navyše pred uložením ďalšieho kandidáta validuje feed proti ledgeri.

Zdrojové súbory: `api/tbt/services/publication.py`, `scripts/prepare_feed.py`, `scripts/confirm_prediction_publication.py`, `scripts/pipeline.py`. Priložené sú aj regresné testy.

## Overenie a hranice

Na dodaných dátach prešlo všetkých päť market záznamov po oprave; zmenil sa iba Top Bets `16983980`. Ostatné sekcie feedu a pôvodné vstupné súbory zostali nezmenené. Prešlo 19 testov obnovy snapshotu a nasadzovacieho procesu vrátane odmietnutia nesprávneho nasadeného feedu. Produkčný GitHub/Azure beh tu nebol spustený a celý výpočtový pipeline s externými zdrojmi sa lokálne nevykonával.

Pôvodný návod k vizuálnej úprave opisuje predchádzajúcu verziu bez backendových zmien. Táto verzia navyše mení vyššie uvedené štyri publikačné súbory; model, tréningové pravidlá ani Firebase autentifikácia sa nemenia.
