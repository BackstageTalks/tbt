# TennisApi PRO – reálny bulk yield vs CDB (2026-11-07)

**Cieľ:** zistiť, koľko surových a jedinečných zápasov poskytujú viacriadkové TennisApi endpointy, koľko sa **presne a nezávisle** páruje s aktuálnou kanonickou CDB, koľko zostáva neprepojených alebo konfliktných a aké má hromadný denný endpoint pokrytie ID pri kurzoch. Nezamieňať HTTP 200 či 993 záznamov za 993 použiteľných kurzov.

**Autoritatívna CDB:** súkromný `BackstageTalks/tbt-data`, release `tbt-data-v1`. Read-only snapshot partition 2023 a 2026 sa SHA-256 validuje proti obom manifestom a release asset digests. Nezávislý release read-back po sonde musí potvrdiť zhodu všetkých štyroch položiek.

**Platené volania:** 10 plánovaných, maximálne 12 vrátane retry (retry=1). Zdrojový 2023 AO turnaj, kolo, stránka a dátum; zdrojovo overený 2026 event, turnajová stránka, dátum a mesiac hráča; denný kurzový register, víťazné a všetky kurzy konkrétneho eventu. Spoločný ETag/CAS budget, provider remaining header, rezerva 500, globálny limit 14 500 a 6/s, QA client 3/s. Pred sondou samostatné read-only GET spoločného ledgeru a kontrola času do resetu.

**Párovanie:** kanonické ID zostáva nezávislé od provider native event ID. `linked` vyžaduje presne jeden existujúci zdrojový ID claim, rovnaký UTC deň, tour, obidvoch hráčov a víťaza. Duplicity, protichodné claimy a iné identity sa nemôžu stať net-new. Zápasy bez presného claimu sú `unlinked_source_id`, **nie** nové overené záznamy.

**Kurzové dáta:** denná mapa je len objavovací index. Neznámy provider quote timestamp znamená **0 časovo overených historických kurzov**. Žiadne implicitné premapovanie bookmakerov. Nezapisovať do modelu, CDB ani lokálnej statistiky kurzov na esá.

**Príkaz (len v chránenom runneri po SHA-verifikácii):**

```bash
PYTHONPATH=api:scripts python scripts/audit_tennisapi_bulk_cdb_yield.py \
  --history-dir .cache/qa-yield/view --max-requests 12 \
  --output .cache/qa-yield/report/verified-overlap.json
```

**Publikovanie dôkazov:** iba agregované počty; žiadne hráčske identity, plné API odpovede, lokálna štatistika kurzov ani Parquet partition mimo privátneho runnera. Workflow sa spustí jednorazovým pushom `.github/tennisapi-bulk-yield-run-request.json` na `main`. Samotný merge kódu ho nespúšťa.

**Stav pred živým behom:** implementované výskumné skripty a workflow; žiadny import. „HOTOVO“ pre túto QA sondu až po CI, reálnom runs, autentickom reporte a nezávislom read-backu. Produkčné nasadenie nových ciest vyžaduje osobitnú validáciu source-ID, completeness, časovej platnosti a existujúceho provider-native importéra.
