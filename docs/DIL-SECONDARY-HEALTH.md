# Sekundárna DIL: nezávislý health-check, aktuálnosť a rollback

**Základná zásada:** CDB je stále jediná primárna a autoritatívna databáza. DIL je iba sekundárna izolovaná kópia. Nástroj nemení CDB, produkčné API, modely, predikcie ani importy.

Po úspešnom súkromnom behu `scripts/refresh_dil_secondary.py --activate-secondary` overiť sekundárnu verziu:

```bash
python scripts/check_dil_secondary_health.py \
  --secondary-dir /private/dil-secondary-releases
```

Pre **aktuálnosť oproti živému primárnemu release** je nevyhnutný autorizovaný prístup `gh` k `BackstageTalks/tbt-data`:

```bash
python scripts/check_dil_secondary_health.py \
  --secondary-dir /private/dil-secondary-releases \
  --verify-live-cdb
```

Health-check nezávisle prečíta `current-secondary.json`, priradený nemenný `.sqlite`, importný aj paritný audit, porovná celé SHA-256 binárneho súboru s importným receiptom a získa skutočný počet zápasov z SQLite. Odmietne chýbajúce či pozmenené receipty, konflikt identity alebo štatistík, neúplný integrity/FK audit, cestu mimo sekundárneho úložiska a akýkoľvek dôkaz o zásahu do produkcie. Živé overenie vykoná dve nezávislé čítania metadát GitHub release a vyžaduje 78 unikátnych SHA-označených ročných súborov. Neprenáša súkromné zápasové riadky.

Možné stavy:

- `PINNED_SECONDARY_VERIFIED_FRESHNESS_UNCHECKED`: súbor a audity sú v poriadku, **aktuálnosť oproti CDB nie je overená**.
- `SECONDARY_CURRENT_RELEASE_MATCH_VERIFIED`: overená sekundárna verzia pochádza z release manifestu, ktorý stále zodpovedá aktuálnej CDB (stav v okamihu kontroly).
- `SECONDARY_LAGGING_BEHIND_PRIMARY`: CDB má novší manifest, treba spustiť nový súkromný `refresh_dil_secondary.py`. Exit kód 3.
- `SECONDARY_HEALTH_BLOCKED`: neúplné či chybné doklady/súbor, prerušenie alebo nedostupné oprávnenia. Exit kód 2; nezapínať nové výstupy.

Pre **výslovne autorizovaný návrat** k predchádzajúcej lokálnej sekundárnej verzii, ak existujú platné receipty oboch súborov:

```bash
python scripts/check_dil_secondary_health.py \
  --secondary-dir /private/dil-secondary-releases \
  --rollback-to-previous \
  --expect-active-filename DIL_SECONDARY_<presny_aktualny_nazov>.sqlite
```

Rollback má single-writer lock a compare-and-swap podmienku. Mení iba lokálne súbory `current-secondary.json` / `previous-secondary.json`; nikdy zdrojovú CDB, nasadenie ani tréning. Staršia sekundárna verzia môže byť voči súčasnej CDB neaktuálna.

## Čo ešte nemožno označiť ako 100 % pripravené

1. Skutočný `78/78` binárny export **aktuálnej** CDB v autorizovanom súkromnom prostredí (nestačia metadáta).
2. Dokončený import a **0** chýbajúcich CDB zápasov, metadát, štatistických buniek, konfliktov a chybných DIL-only metrík podľa `audit_dil_cdb_secondary_parity.py --full-integrity`.
3. Fyzicky uložený a aktívny (iba sekundárny) vydaný SQLite súbor s presným hashom, read-backom a zachovanou predchádzajúcou verziou.
4. Overená periodická súkromná synchronizácia a alert pri zaostávaní / chýbajúcej kapacite; každá aktualizácia CDB môže sekundárnu DIL dočasne zostariť.
5. Samostatné modelové/prevádzkové kontrakty a prípadná paralelná skúška aplikácie. **Žiadne automatické preklopenie produkčného čítania ani modelového tréningu.**

**Repozitárové syntetické testy nie sú dôkaz aktuálnej parity**, ani úspech GitHub CI nie je dôkaz fyzického nasadenia sekundárnej DIL.