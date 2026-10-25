# DIL ako 100 % overená **sekundárna** databáza – prevádzkový postup

**Primárna autorita zostáva CDB.** Nič v tejto implementácii neprepína produkčné API/predikcie/tréning na DIL ani nezapisuje do CDB.

## Aktuálny stav a neprekročiteľné hranice

- Izolovaná DIL z 24. 10. 2026: 998 732 kanonických zápasov, kontrola `quick_check` OK; ďalších 993 018 overených tréningových prepojení a 931 riadkov vyžadujúcich kontrolu. Tieto prepojenia **nie sú** nové kanonické zápasy.
- DIL obsahuje historické obohatenia, ktoré nezahadzujeme; pravidlo zápisu je **NULL-only**.
- Starých 531 chýbajúcich zápasov je len historická nekanonická kontrolná fronta. Neaplikovať ako aktuálny import.
- **Dátová parita k dnešnému CDB release ešte nie je overená**, preto nehovoríme o 100 % aktuálnej kvalite. Binárne súbory privátneho release neboli dostupné v ChatGPT runtime. Žiadny živý end-to-end import v tejto zmene neprebehol.
- Kód a syntetické testy prechádzajú, ale nenahrádzajú integráciu na súkromných dátach.

## Nové bezpečnostné časti

1. `build_current_cdb_compare.py`: overený 78-part export z autoritatívnej CDB, s manifestom a SHA-256, do izolovaného `cdb-compare.sqlite`.
2. `finalize_dil_from_cdb_v2.py`: fyzická **kópia** DIL; presné ID/čas/tour/surface/status, doplnenie chýbajúcich polí, karanténa konfliktov, proveniencia, idempotencia. Zdrojové databázy sa nemenia.
3. `audit_dil_cdb_secondary_parity.py`: nezávislé porovnanie *každého* kanonického zápasu a vyplnenej štatistickej bunky CDB oproti DIL vrátane obohatených overlay hodnôt. Kontrola plného SQLite integrity a FK je **povinná** na schválenie sekundárneho vydania. Výnimky, konflikty alebo neoverený zdroj znamenajú fail-closed.
4. `refresh_dil_secondary.py`: jeden kontrolovaný `CDB → DIL` import v oprávnenom privátnom Linux prostredí, bez verejných artefaktov. Pred/po prečíta GitHub Release metadata, stiahne všetkých 78 Parquet súborov, skontroluje SHA, vyrobí novú verziu a nezávisle overí paritu. Vytvorí novú nemennú sekundárnu verziu; starú nikdy neprepíše.
5. `--activate-secondary` zmení **iba lokálny sekundárny JSON pointer** `current-secondary.json`, nie nastavenie produkčnej služby. `previous-secondary.json` zachová posledný sekundárny odkaz. Bez parametra vznikne len overená nezapnutá kandidátna sekundárna verzia. Nejde o zálohu do iného fyzického umiestnenia.

## Prvé obnovenie sekundárnej DIL

Na autorizovanom súkromnom **Linux/WSL** stroji s prístupom `gh` ku `BackstageTalks/tbt-data`, nainštalovanými závislosťami `BackstageTalks/tbt` (`pandas`, `pyarrow`...) a dostatočným úložiskom pre 78 Parquet, CDB SQLite, 5+ GB DIL a pracovné súbory:

```bash
python scripts/refresh_dil_secondary.py \
  --base-dil /private/isolated/DIL_MERGED_TRAINING_REVIEW_STAGING_20261024.sqlite \
  --work-dir /private/scratch/dil-unique-run-001 \
  --secondary-dir /private/dil-secondary-releases \
  --activate-secondary
```

Každý opakovaný beh použije aktuálne označenú sekundárnu DIL, bez potreby `--base-dil`:

```bash
python scripts/refresh_dil_secondary.py \
  --work-dir /private/scratch/dil-unique-run-002 \
  --secondary-dir /private/dil-secondary-releases \
  --activate-secondary
```

Nespúšťajte viacero príkazov súčasne na rovnaký sekundárny adresár. Lock blokuje druhého zapisovateľa. `--work-dir` musí byť nový adresár, aby nedošlo k zámene starých dát. Nepracujte s verejne dostupnými CI artefaktmi ani necommitujte binárne súkromné zápasy do `BackstageTalks/tbt`.

## Kritériá schválenia 100 % dátovej parity

- Nemenný release `tbt-data-v1`: 78/78 Parquet častí fyzicky dostupných a ich SHA-256 zhodné s metadátami release, ročným i bundle manifestom, pred/po rovnaké release metadáta.
- CDB 100 % obsahu porovnávaného exportu; počty sú v súlade s jeho podpísaným a znovu prečítaným receiptom.
- CDB-only ID v DIL = **0**; DIL-only kanonické ID = **0**; konflikty jadrových polí = **0**.
- Každá neprázdna CDB štatistika má vo výslednej DIL rovnakú efektívnu hodnotu vrátane overlay: chýbajúce hodnoty = **0**, konflikty = **0**.
- `PRAGMA integrity_check` pre oba vstupy = `ok`; úplný `PRAGMA foreign_key_check` = **0**; neoverený full-integrity stav nikdy nie je schválený.
- Importný audit má `ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION`; následný nezávislý audit má `VERIFIED_CURRENT_CDB_PARITY`; metadata release sa nezmenili ani do konca behu.
- Tréningové targety, neoverené review zápasy, budúce post-match štatistiky a prevádzkové rozhodnutia nesmú preniknúť do pre-match použitia.
- Zdrojová CDB, pôvodná DIL, nasadené modely a API nastavenia sú bez zmeny.

**100 % dátová parita v jednom okamihu nie je 100 % nepretržitá aktuálnosť.** Pri ďalšej CDB aktualizácii je DIL sekundárna a môže dočasne zaostávať; pravidelné spúšťanie sa rieši na existujúcom privátnom runneri. Chýbajúce binárne prístupy / uloženie novej 5+ GB sekundárnej DIL na trvalom privátnom disku musia byť reálne preukázané pred výrokom „100 % pripravená“.

## Rollback

Pri nesúlade zostane posledné `current-secondary.json` nezmenené. Ak sa chyba objaví po prepnutí sekundárneho pointera, prečítať `previous-secondary.json`, overiť že cieľový immutable `.sqlite` existuje a s prevádzkovou autorizáciou atómovo vrátiť predchádzajúci pointer. Produkčná CDB je tým úplne nedotknutá.