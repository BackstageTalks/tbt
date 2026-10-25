# BlinQ DIL ↔ kanonická CDB: bezpečná parita dát

Stav: `ISOLATED_DIL_QUALITY_VERIFIED / CURRENT_CDB_PARITY_BLOCKED` (25. 10. 2026).

## Čo bolo skutočne overené

- Plný read-only priechod obnovenou izolovanou DIL: 998 732 kanonických zápasov, 998 732 čitateľných štatistických JSON objektov, 9 969 891 nenulových (nie SQL NULL) štatistických polí. Po oprave presných časových jednotiek: **0** anomálií medzi kontrolovanými základnými identitnými a časovými pravidlami; nie je to absolútny dôkaz úplnej kvality.
- Kompletná kontrola SQLite `PRAGMA quick_check`: `ok` (samostatný audit, 25. októbra 2026). Testované FK tréningových linkov a review: 0 porušení. **Nejde o plný `PRAGMA integrity_check` ani všetky FK tabuľky.**
- 931 nedokončených zápasov v izolovanej DIL (705 retired, 172 walkover, 45 canceled, 9 interrupted). Môžu byť kanonické výsledkové fakty, nesmú sa bez samostatného rozhodnutia propagovať ako dokončené výsledky alebo tréningové príklady.
- 531 historických kandidátov CDB-only z 24. 10. 2026 (281 ATP, 250 WTA) už bolo uložených ako **nekanonická kontrolná fronta**. Dnešná CDB má iný SHA-256; tieto kandidáty sa nesmú importovať na základe starého auditu.
- 10 syntetických testov importéra a 4 testy exportéra úspešné. **Neboli vykonané nad aktuálnymi 78 Parquet časťami CDB; práve toto je blokácia.**

## Spustenie úplnej parity (iba v autorizovanom súkromnom prostredí)

Potrebujete existujúci checkout `BackstageTalks/tbt` s jeho Python závislosťami, `gh` prihlásený s prístupom k `BackstageTalks/tbt-data`, dostatočný súkromný disk a obnovenej izolovanej DIL `DIL_MERGED_TRAINING_REVIEW_STAGING_20261024.sqlite` (nemeniť originál). **Neposielajte originálne CDB zápasy do verejných Actions artefaktov.**

```bash
set -euo pipefail
mkdir -p /private/dil-work/cdb
# Metadáta nezávisle pred a po preberaní všetkých 78 častí.
gh api repos/BackstageTalks/tbt-data/releases/tags/tbt-data-v1 \
    > /private/dil-work/release-before.json
gh release download tbt-data-v1 -R BackstageTalks/tbt-data \
    -p 'history-*.parquet' -p 'history_manifest.json' \
    -p '_tbt_bundle_manifest.json' -D /private/dil-work/cdb
gh api repos/BackstageTalks/tbt-data/releases/tags/tbt-data-v1 \
    > /private/dil-work/release-after.json

python scripts/build_current_cdb_compare.py \
    --history-dir /private/dil-work/cdb \
    --release-before /private/dil-work/release-before.json \
    --release-after /private/dil-work/release-after.json \
    --out /private/dil-work/CDB_PINNED_COMPARE.sqlite
```

Z `CDB_PINNED_COMPARE.sqlite.receipt.json` vezmite presné polia `export_sqlite_sha256` a `source_release_manifest_sha256`:

```bash
python scripts/finalize_dil_from_cdb_v2.py \
    --dil /private/dil-work/DIL_MERGED_TRAINING_REVIEW_STAGING_20261024.sqlite \
    --cdb /private/dil-work/CDB_PINNED_COMPARE.sqlite \
    --export-receipt /private/dil-work/CDB_PINNED_COMPARE.sqlite.receipt.json \
    --out /private/dil-work/DIL_CDB_RECONCILED.sqlite \
    --expected-cdb-sha256 "${VERIFIED_CDB_SQLITE_SHA256}" \
    --release-manifest-sha256 "${VERIFIED_MANIFEST_SHA256}"
```

**Bez aktuálneho úplného exportu a jeho SHA-256 sa žiadny import nespúšťa.** Vzniká výlučne nová izolovaná kópia. Spúšťanie z CLI vyžaduje verifikovaný exportný receipt.

## Kontroly pred akýmkoľvek nasadením

- Nový CDB release SHA-256 ihneď pred nasadením musí byť identický s pripnutým manifestom; ak sa posunul, opakovať celý export a porovnanie, nepoužiť starý výsledok.
- `data_gate == ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION`, bez aktuálnych CDB-only/DIL-only identít, konfliktných buniek a nevyriešených kandidátov. Žiadny historický review záznam sa nesmie tváriť ako práve potvrdený kanonický import.
- Všetky nové `NULL-only` hodnoty musia byť čitateľné späť, s provenienciou; bez prepisu existujúcej DIL/CDB. Nejednoznačný čas, side orientation, alternatívne zápasové ID alebo existujúca štatistika s odlišnou hodnotou ide do review.
- Oddelená kontrola úniku výsledkov do pre-match features a schválenie konkrétnej serving/training cesty. Importér sám **nedáva povolenie na tréning ani produkčný deploy**.
- Plný SQLite read-back, konzistencia kanonického počtu, minimum `PRAGMA quick_check` a relevantných FK. CDB je výlučne read-only; jediný autoritatívny CDB writer sa nemení.

## Čo automaticky neznamená dokončenie

Lokálny úspešný audit 998 732 DIL zápasov nie je dôkaz rovnakého aktuálneho počtu alebo kvality proti CDB. Aktuálna CDB bola opakovane aktualizovaná; dostupný GitHub connector vracia metadata release, nie jeho úplný binárny obsah. Preto v tomto behu **nebolo fyzicky doplnené nič z aktuálnej CDB**: nové kanonické zápasy 0, nové štatistické bunky 0, produkčné nasadenie nie.