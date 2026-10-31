# DIL → CDB: source-only Sackmann intake / bezpečná príprava

## Stav a hranica

DIL prijíma raw Sackmann-formátové zdroje, ale CDB zostáva autoritatívna. `prepare_dil_sackmann_cdb_intake.py` je **read-only pre CDB a DIL** a z existujúcej 31.10.2026 source-extension SQLite pripraví *len vstup* pre už existujúci kanonický linker. Nepripravuje `import_ready` záznamy bez oddelene overených identít a aktuálneho CDB NULL auditu.

Zdroj: privátny Google Drive `DIL_SACKMANN_SOURCE_EXTENSION_20261031.sqlite.zst` s SHA-256 `732f99854e70d297f1d14242775768605c733dd140662c0a08091992ef148b36`, po rozbalení SQLite SHA-256 `25f536eb83c999513217268897533e144be9effbe28a714e2b0fdc640724b654`. Kontrakt obsahuje `dil_sackmann_*` tabuľky: raw source observations, source hashes, provenance, decisions, verified already-present links a receipts. Zdrojové pozorovania **nie sú** kanonické CDB zápasy.

## Použitie v izolovanom, neverejnom prostredí

```bash
zstd -d DIL_SACKMANN_SOURCE_EXTENSION_20261031.sqlite.zst -o /private/sackmann-source.sqlite
python scripts/prepare_dil_sackmann_cdb_intake.py \
  --source-extension /private/sackmann-source.sqlite \
  --expected-source-sha256 25f536eb83c999513217268897533e144be9effbe28a714e2b0fdc640724b654 \
  --out-dir /private/bridge-intake-unique-20261031
```

Výstup `report.json` je agregovaný, `linker_inputs/` obsahuje súkromné per-source CSV **iba ak** sú v raw riadku prítomné pôvodné native winner/loser/event ID, DIL označí ich kompletnosť ako `NATIVE_IDS_COMPLETE` a vstupné serve štatistiky prejdú syntaktickou validáciou. Ani tieto CSV **nie sú autorizovaný import**. Neplatné/retired súbory ostávajú v DIL; script ich nemaže.

## Ďalšie povinné brány (bez nového CDB writeru)

1. Načítaj najnovšiu CDB (78/78 Parquet) s overeným SHA-256 manifestom, plným read-only auditom a kontrolou release drift.
2. Získaj *nezávisle* overený SHA-pinned player crosswalk v správnom provider namespace, plus potvrdenie turnajovej/event identity a víťaznej orientácie; nespoliehaj sa iba na meno ani na `tourney_date` (je to začiatok turnaja). Neoverené asociácie nechaj v review/quarantine.
3. Spusti existujúci `link_offline_serve_return.py` na `linker_inputs/*.csv` s `--matching-strategy verified_ids --require-verified-identities` a so správnym `--verified-player-crosswalk ... --verified-player-crosswalk-sha256 ...`. Bez crosswalku musí vzniknúť **0 importovateľných** kandidátov.
4. `import_offline_linked_serve_return.py` najprv **bez** `--write-partitions`, potom jeho `verify_cdb_enrichment.py` podľa link/dryrun reportov. Pri konflikte štatistiky, neistej identite, inom winnerovi, časovom drifte alebo zdrojovej neistote nemožno pokračovať.
5. Len potvrdené `NULL-only` hodnoty s dôkazom precedence/pôvodu cez *existujúci* CDB single-writer (globálny lock, immutable backup, CAS, DRY-RUN, WRITE, nezávislé remote READ-BACK a integrita). Skontroluj, či daily CDB run už nebeží. Nezapisovať do existujúcich kvalitných buniek; nič meniť na serving/modeloch.
6. Report vždy oddeľuje **raw / linked / net-new canonical / enriched values / conflicts / review**. Tréningové pre-match features nesmú čítať štatistiky vlastného zápasu ani výsledky pred časom dostupnosti.

## Reálne zistenie na archivovanom DIL zdroji

Read-only spustenie na nekomprimovanom zdrojovom rozšírení 31.10.2026: 139 016 source-only riadkov, z toho 69 062 v rokoch 2016–2026. Po vylúčení 2 569 neistých/nedokončených skóre a 3 564 neúplných/neplatných serve dvojíc má 62 929 riadkov platné obojstranné serve počty (z toho 62 927 s úplnými validnými break point count údajmi). **Všetkým 62 929** však chýbajú pôvodné winner/loser/event ID: `linker_input_rows_pending_independent_crosswalk=0`, `cdb_null_only_import_ready=0`. Všetkých 139 016 raw/provenance riadkov zostáva zachovaných v zdrojovom rozšírení DIL. Opätovne skontrolovaných 663 prepojení / 9 282 štatistík je už v baseline, takže to nie je nový zápis.

### Dôležité

`source_files.sha256` je konvertorom uložený hash zdrojového CSV, nie úplný dôkaz jeho aktuálneho pôvodného súboru, ak originál nie je k dispozícii na opakovaný prepočet. Toto rozšírenie nepreukazuje join `provenance.match_key -> source_observations`. Tool preto explicitne uvádza `dil_provenance_join_attested=false` a nikdy nepovoľuje CDB import. Na nový import treba samostatne potvrdené ID a aktuálne CDB NULL rozdiely. Nepublikovať raw CSV/ID na verejnom GitHube ani v Actions logoch.
