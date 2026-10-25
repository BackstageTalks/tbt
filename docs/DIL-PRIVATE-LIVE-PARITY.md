# DIL sekundárna DB: spoločný privátny CDB ↔ DIL audit

**CDB ostáva jediná autorita. Tento workflow nemení produkčné API, model, CDB ani trvalú sekundárnu DIL.**

## Cieľ

V dôveryhodnom GitHub Actions behu na verejnom repo `BackstageTalks/tbt` (iba `main`, nikdy PR event) načítať:
- 33 SHA-pinned častí izolovanej DIL z privátneho Drive foldera `1crwy2Z0AoG-bApBOhZ8SKvK_gJ9T7Ypg`.
- Aktuálnych 78 častí CDB z privátneho `BackstageTalks/tbt-data` release `tbt-data-v1`.

Drive prístup je iba read-only cez secret `BLINQ_DRIVE_READER_JSON`. CDB číta existujúci `TBT_DATA_GH_TOKEN`. Pri chýbajúcich oprávneniach workflow skončí **BLOCKED**. Tokeny nikdy nezapisovať do logov, výstupných artefaktov alebo checkout credentials.

Archivovaná izolovaná DIL je pevne viazaná na nezávisle potvrdené hodnoty:
- zstd SHA-256: `3bb17d3fe4a1b18aa324afd3d833e5743ddfe16a054511393c42c85f28289ede`
- SQLite SHA-256: `b39f489e321f346c729bd150c871ee0cd54a70db2b0ebe0f8333892da840c816`

## Brány

Restore každej časti -> SHA a celkový digest -> SQLite plný `integrity_check` -> najnovšie privátne CDB manifesty a 78 Parquet -> `refresh_dil_secondary.py` (oddelená kopia, NULL-only) -> nezávislý každý-ID/každá-štatistika audit -> read-back hash, snapshot, lokálny sekundárny pointer a aktuálnosť CDB.

Konflikty identít, metadata, štatistiky, DIL-only kanonické ID, porušené FK alebo posun release znamenajú **BLOCKED**. Žiadne záznamy sa nemažú či neprepisujú. V workflow ide o jeden skutočný synchronizačný cyklus; identické znovu spustené dáta sa nepovažujú za novú verziu iba preto, aby vznikol iný hash.

Na verejnej GitHub stránke sa zobrazujú len allowlistované agregačné počty; súkromné zápasy/ID, raw zdroje, CDB porovnávacia DB ani 5+ GB DIL sa nepublikujú ako artefakt. `always()` vymaže ephemeral scratch, aj keď je audit zablokovaný.

## Čo úspešný beh NEZNAMENÁ

Úspešný beh preukáže dočasnú, fyzickú paritu aktuálneho CDB snapshotu voči izolovanej výslednej sekundárnej DIL **na runneri**, nie trvalé uloženie na SSD/Drive, produkčné nasadenie alebo nepretržitú paritu pri budúcich zápisoch do CDB. Trvalá verzia musí byť súkromne uložená, spätne prečítaná a atomicky zapnutá osobitne. Bez autentického PASS nereportovať 100 %.

Nový `history_manifest.json` po predchádzajúcom behu preflightu (2026-10-25 22:05 UTC, SHA-256 `92159042d96dc28418a96b90c6e6ad547cf2c4e7aff9786f3d06cb6cf495b6b7`) znamená, že staré preflight digesty už nie sú dôkazom aktuálnosti. Tento workflow vždy číta najnovší release.
