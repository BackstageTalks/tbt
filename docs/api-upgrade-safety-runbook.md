# BlinQ: príprava bezpečného API upgradu

Stav balíka: PREPARED. Lokálne testy a ich presná verzia sú v priloženom report.json a junit.xml.
Balík neobsahuje príkaz na produkčný zápis, publikovanie modelu ani spustenie backfillu.
Existujúci CDB writer, lock a runtime API rozpočet zostávajú autoritou. Nové kontroly ich nenahrádzajú.

## Spustenie lokálnych kontrol

Použite pracovnú kópiu tbt s aplikovaným patchom a jej testovacie Python prostredie.
Z koreňa repozitára:

```powershell
python scripts/run_api_upgrade_checks.py --out .cache/api-upgrade-run-001
```

Výstupný adresár musí byť nový. Runner vykoná iba explicitný zoznam regresných testov; testy writerov pracujú na dočasných/syntetických dátach. Uloží log, JUnit a report s commitom a hashmi Python zdrojov. Nenahrádza test živého API, vzdialeného writer locku ani obnovy zo SSD/Drive. Zdrojový hash dokumentuje pracovnú kópiu vrátane necommitnutých zmien.

V tomto prostredí boli potrebné pytest, pydantic, pydantic-settings, pandas, numpy, httpx, pyarrow, azure-core, joblib a scikit-learn. Verzie použité pri úspešnom behu sú priložené v environment.txt. Testovanie backup kontraktu netrénuje model.

## Kontroly a požadované dôkazy

| Oblasť | Pripravený mechanizmus | Skutočný dôkaz potrebný pred nasadením |
|---|---|---|
| Obnova | test_immutable_training_backup.py; existujúci backup gate | Identifikácia aktuálneho rollbacku na SSD/Drive, checksum, skúšobné načítanie obnovenej CDB mimo produkcie a verzia chránených vstupov. Lokálny test nie je overenie vlastníkových záloh. |
| Jeden writer | cdb_global_writer_lock.py + jeho testy | Overenie vlastníctva locku pre konkrétny run, odmietnutie druhého writera, aktuálny stav všetkých jobov. Lock sa nesmie násilne prevziať. |
| Identita | existujúci verified-ID linker a importer | Provider→canonical crosswalk, event ID, hráči a ich orientácia, dátum, turnaj, singles/doubles. Nejednoznačné zhody do karantény. |
| NULL-only | offline_exact_cdb_write.py + testy | Porovnanie celých dotknutých partitions; žiadny prepis existujúcej hodnoty vrátane 0, žiadna zmena kontextu. |
| Deduplikácia/obnova behu | test_offline_linked_serve_return_importer.py | Dvakrát rovnaká pilotná dávka: druhý beh bez nových buniek; prerušenie a pokračovanie bez duplicitných záznamov. |
| Štatistiky | test_statistics.py + strict importer | ATP/WTA, viac povrchov, ukončené zápasy, skreč/walkover, set verzus ALL, úspešné≤celkové body, správna orientácia. |
| Sezónne profily | point-in-time kontrola nižšie | Skutočný kontrakt singles/doubles, player/team ID, surface a coverage_end; samostatná vrstva, bez prepisu match stats. |
| Kalendár | nový compare_calendars | Normalizované rovnaké časové okno z oboch metód, zoznamy ID a zmeny kontextu. Porovnať ATP/WTA, kvalifikáciu, doubles, odklady a prechod DST. |
| Kurzy | suspended/sourceId regresie + PIT kontrola | Skutočné odpovede, význam sourceId, bookmaker, čas ceny, dostupnosť oboch strán rovnakého trhu. observed_at nesmie nahradiť quote time. |
| Market 13 | zatiaľ výskumný kandidát, bez aktivácie | Konkrétna odpoveď s ID, názvami volieb a rozsahom match/set; pravidlá vyhodnotenia a samostatné testy. |
| PBP | existujúci štrukturálny inventár + PIT kontrola | Zhoda skóre, gemov, servisov, tie-breakov a agregátov; kompletnosť musí doložiť samostatný audit. |
| Publikovanie | existujúce market-selection regresie | End-to-end simulácia výpadku, prázdnej ponuky, retry, zastaraných cien a duplicitného spustenia. Automatická obnova sa ešte neimplementovala. |
| API limit | shared_api_budget + probe kontrakt testy | Reálne spoločné účtovanie všetkých jobov/retry, limit 14 500, rezerva 500, 6/s, reset 17:09 UTC, cutoff 17:07 UTC, history 12 000/run. |
| Read-back | verify_cdb_enrichment.py + exact writer verifier | Nové nezávislé načítanie persisted partitions; súlad staged buniek, úplný rozdiel pred/po, nulové vedľajšie zmeny. |

## Pracovný postup a stop podmienky

1. Zaznamenať aktuálny commit, verziu CDB a čas auditu. Overiť existujúci rollback; netvoriť ďalšie GitHub archívne duplikáty.
2. Spustiť lokálne regresie. Ak zlyhajú alebo chýbajú závislosti, riešiť príčinu; neoznačiť krok ako úspešný.
3. Stiahnuť malú reprezentatívnu vzorku API cez existujúceho klienta so shared-budget ochranou. Uložiť raw odpovede mimo CDB. Nepridávať odhady dostupnosti podľa samotného HTTP 200.
4. Overiť identitu a dátové kontrakty. Neznáme mapovania, konflikty a neúplné záznamy ponechať v karanténe.
5. Na izolovanej kópii CDB pripraviť staging a spustiť existujúci importer bez --write-partitions. Zaznamenať počty raw, linked, net-new, enriched, karanténu a doplnené bunky. Tento pilot dopĺňa existujúce zápasy: net-new musí byť 0.
6. Overiť dry-run, potom samostatne otestovať lokálny zápis, opakovanie a obnovu po prerušení. Lokálny exact writer môže meniť zadaný history-dir; musí to byť výhradne skúšobná kópia.
7. Produkčný pilot až po splnení runtime podmienok, pod globálnym lockom a s opätovným overením, že CDB od stagingu nezmenila verziu. Pri zmene baseline staging prepočítať, nie vynucovať starý plán.
8. Read-back vykonať nezávisle od objektov použitých na zápis. Rozširovať dávku iba po preukázanom súlade. Release upload nie je dôkaz persisted výsledku.
9. Nové profily/PBP/streak dáta zapájať do modelu až po chronologickom holdoute, testoch leakage a samostatnom modelovom gate. Tento balík model nemení.

## Pripravené príkazy bez produkčného zápisu

Po vytvorení stagingu existujúcim provider-native adaptérom a overení jeho kompatibility:

```powershell
python scripts/import_offline_linked_serve_return.py --stage PILOT/link/auto_linked.jsonl --history-dir PILOT/backup --out-dir PILOT/dry-run --exact-stats-only
python scripts/verify_cdb_enrichment.py --phase dry --root PILOT
```

PILOT je absolútny adresár oddelenej pracovnej dávky. `link/report.json` musí byť skutočný výstup linkera; nevyrábať ho ručne len na splnenie gate. Ak provider-native schéma nezodpovedá tomuto importeru, použiť existujúcu provider-native cestu a jej verifier, nie násilnú konverziu. Generic verifier akceptuje iba svoju explicitnú stats-only schému.

Po samostatnom riadenom zápise a nezávislom read-backu očakáva verifier tieto podadresáre: backup/, link/, dry-run/, write/, verify/. Posledný obsahuje nanovo načítané persisted partitions.

```powershell
python scripts/verify_cdb_enrichment.py --phase readback --root PILOT
```

Príprava živej sondy, až keď je nastavený existujúci shared-budget klient a zvolené overené event ID:

```powershell
python scripts/probe_tennisapi_extended_contract.py --event-id EVENT_ID --phase quality --max-requests 8 --out PILOT/probe-quality.json
```

Tento príkaz spotrebúva API rozpočet, ale nezapisuje CDB. V rámci prípravy balíka nebol spustený. EVENT_ID nie je náhodný predvolený zápas; zvoliť ho z auditovanej vzorky.

## Nové offline kontroly

Kalendár prijíma normalizovaný JSON `{"events": [...]}`. Každý záznam musí mať id, home_id, away_id, scheduled_at s timezone, discipline (singles/doubles), tour (ATP/WTA). Normalizácia musí zachovať provider ID a nesmie odfiltrovať nezhody pred porovnaním. Dve prázdne množiny nie sú úspech. Nové zápasy sa označia na preskúmanie, nie automaticky ako lepšie pokrytie.

```powershell
python scripts/api_upgrade_preflight.py calendar --input baseline.json --candidate candidate.json
python scripts/api_upgrade_preflight.py point-in-time --input observations.json
```

Časový vstup: `{"observations": [...]}`. Spoločné polia: kind, entity_id, source_ref, available_at, prediction_at. kind je season/match_stats/pbp/odds. Všetky časy sú ISO s timezone.

- season: coverage_end = koniec skutočne zahrnutých výsledkov, nie dátum stiahnutia.
- match_stats/pbp: coverage_end, source_match_id, target_match_id, match_finished=true. PBP navyše completeness_verified=true podložené samostatným auditom.
- odds: provider_quote_at, target_match_start, source_id, suspended=false. Čas predikcie aj ceny musia byť pred začiatkom zápasu.

Nástroj kontroluje logiku dodaných tvrdení, nie pravdivosť ručne vyplnených časov či identity. source_ref musí smerovať na preskúmateľný dôkaz. Výstup obsahuje SHA-256 vstupných súborov, návratový kód 0/2 a vždy production_write_authorized=false. JSON výsledok ide iba na stdout; žiadny vstup sa neprepisuje.

## Zostávajúce rozhodnutia podľa dôkazov

Pozastavené ponuky a nejasné sourceId už majú lokálny patch. Live kompatibilitu treba ešte overiť. API dokumentácia sama nepotvrdzuje päťdňové dávkovanie, singles sezónne profily, presný market 13 ani historické quote timestamps. Tieto časti zostávajú mimo produkcie, kým konkrétne odpovede a validácia nepreukážu ich význam.

Zelený lokálny report znamená iba úspešné lokálne regresie. Neoprávňuje obísť writer lock, backup/restore kontrolu, provenance, rozpočet alebo nezávislý read-back.
