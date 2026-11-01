# MoviOdds tennis statistics archive — operating contract

The source archive is separate from the canonical CDB. The operator-selected
Google Drive folder **MoviOdds** is
https://drive.google.com/drive/folders/13kDDxOaQ0L1Jr5ZjbSNjbDFJiNSz9uwx
(folder ID \`13kDDxOaQ0L1Jr5ZjbSNjbDFJiNSz9uwx\`).

## Capture

- LIVE workflow collects \`/odds?sport=tennis&in_play=1&groups=67&stats=1\`
  into \`BlinQMoviOddsStats\` (existing Azure Table Storage) using source
  \`stats.updated_at\` as an immutable observation identity.
- Match-status workflow collects finished \`/results?stats=1\` for today
  and yesterday UTC, storing complete final records under a separate key.
- Both collectors use the *existing* external clocks and worker token, require
  persisted SHA-256 readback, and cost **zero Tennis API Pro requests**.
  Provider outage is isolated from the existing LIVE/match-status workflow.
- A corrected final record with an existing different hash is flagged as a
  conflict; the source value does not silently overwrite the first final.
  Live snapshots are not eligible for CDB import.
- All records preserve provider fixture ID, full names, source timestamp,
  raw statistics, score, provenance, and final status. Missing values stay
  missing; percentages are never confused with point-count statistics.

## Drive

- The \`moviodds-drive-archive.yml\` workflow exports a verified UTC date via
  \`/api/v1/internal/moviodds-stats-worker?date=YYYY-MM-DD\`.
- The archived JSON contains finalized source records **only**. The Azure
  journal retains denser intermediate live observations.
- Filename is \`moviodds-tennis-final-YYYY-MM-DD-SHA16.json\`.
  Identical bytes are idempotent; a changed dataset gets an additional version.
  Upload is verified by independent Drive binary download and exact SHA-256.
- Automatic daily dispatch uses the existing external Match Status clock
  at 04:00 UTC (exporting the previous UTC date). No extra cron or switch.
- The archive job can reuse existing `BLINQ_DRIVE_READER_JSON` credentials,
  requesting write scope ONLY within its own archive script. The other
  importers retain their existing read-only scope.
- **One-time operator setup:** change the permission on the linked MoviOdds
  folder for `blinq-drive-reader@blinq-drive-audit.iam.gserviceaccount.com`
  from Viewer to Editor. Do not modify any parent or CDB folder permission.
  A separate `BLINQ_DRIVE_WRITER_JSON` remains supported if desired.
- As checked on 2026-11-01, the existing service account has reader access
  only. The daily Drive export will fail until folder Editor access is granted;
  no successful upload is claimed.
- The archive job also retains 14-day troubleshooting artifacts, without
  publishing private source JSON into the public repository.

## CDB-ready JSON source contract (version 2)

Each daily file (still named \`moviodds-tennis-final-YYYY-MM-DD-SHA16.json\`)
uses \`schema: 2\`, \`format: blinq.moviodds.tennis-final.cdb-source.v1\`,
and has \`records[]\` sorted by the verified source API export order.

- \`records[].payload\`: **unchanged** complete source-native finalized stats,
  full score/sets, provider fixture ID, players, league and original timestamps.
- \`records[].sha256\`: SHA-256 of the original canonical JSON source payload.
  Each source row is independently verified BEFORE being normalized.
- \`records[].cdb_candidate.match\`: home/away names, verified source event ID,
  full original competition, ATP/WTA tour **hint** when explicitly present,
  match type, actual source kickoff if present, source finish timestamp,
  final score, set breakdown, surface and best-of. An absent kickoff stays null.
- \`records[].cdb_candidate.source_side_counts\`: home/away **aces and
  double_faults**, integers or null, ready for later CDB player orientation.
  Home/Away is NEVER preemptively mapped to canonical p1/p2.
- \`records[].cdb_candidate.unmapped_source_percentages\`: source percent
  values 0..100 for first-serve won and break-point conversion, explicitly
  not canonical 0..1 rates; no invented denominators.
- \`records[].cdb_candidate.provenance\`: unmodified provider digest, fixture
  ID, timestamp and finished-match evidence.
- \`records[].cdb_candidate.cdb_link\`: \`status=unlinked\`,
  \`match_id=null\`, \`canonical_signature=null\`, \`incoming_stats=null\`,
  \`import_ready=false\`, and explicit reasons requiring review. Provider
  fixture IDs are NEVER treated as canonical CDB IDs.
- \`summary\`: source rows, ATP/WTA singles hints, doubles excluded,
  other-tour review, availability of ace/DF counts, and **0** actual imports.

Only *finished* source statistics enter the archive; live observations stay in
the Azure journal. Doubles/ITF/UTR/Challenger rows are preserved as raw evidence
for research, not silently relabelled as ATP/WTA canonical candidates.

For a future offline, read-only linkage batch:

\`\`\`bash
python scripts/moviodds_cdb_extract.py \
  --archive moviodds-tennis-final-YYYY-MM-DD-SHA16.json \
  --out-dir work/moviodds-cdb-link
\`\`\`

This independently validates the archive and emits \`link_candidates.jsonl\`,
\`review.jsonl\` and \`report.json\`. **These files are not import-ready stages.**
A later dedicated provider-native CDB linker must establish unique
canonical identity (including source home/away orientation), independently
confirm full set scores, apply quality precedence and produce the existing
guarded \`import_offline_linked_serve_return.py\` stage contract. The existing
single-writer, global lock, backup, CAS and remote read-back are mandatory.
The source JSON itself never writes the CDB.

## CDB (not scheduled)

No automatic daily canonical import is configured. A periodic import requires
an explicit separate guarded batch:

1. Read immutable final JSON snapshots and source digests.
2. Map only exact ATP/WTA matches against the authoritative CDB with verified
   player pair, date/time, final **set score**, and non-ambiguous source ID.
3. Treat raw count-valued aces / double faults as potential CDB candidates.
   First-serve win percentages and break-point conversion percentages are
   provider-native raw measurements, **not** automatic canonical rate/count
   mappings until their denominators and definitions are validated.
4. Quarantine identity collisions and value conflicts; accept only supported
   NULL-only verified fields; never replace higher-quality canonical values.
5. Use the EXISTING single-writer CDB importer, immutable backup, lock, CAS,
   dry-run, remote readback and full affected-year partition integrity check.
6. Report raw / linked / newly-enriched / rejected and independently
   confirmed numbers. A saved JSON is **not** a successful CDB import.

Neither collection nor Drive archive triggers model training or a canonical
writer.

## Autonómna príprava importných dávok (bez zápisu do CDB)

\`moviodds-cdb-stage.yml\` sa automaticky spúšťa o **05:00 UTC**
prostredníctvom existujúceho externého plánovača \`match-status.yml\`;
nie je potrebné vytvárať ďalší cron. Každý deň spracuje posledné **tri
dokončené UTC dni** z chráneného MoviOdds Azure DB exportu, aj keď Google
Drive export zlyhá alebo je dočasne nedostupný.

1. Overí source export + normalizovaný JSON v2 vrátane SHA-256 a vnútornej
   súdržnosti súboru.
2. Z privátneho autoritatívneho \`BackstageTalks/tbt-data\` stiahne celý
   manifest a všetky požadované CDB ročné partition súbory. Overí každé
   SHA-256 proti súkromnej release manifest a asset digest.
3. Linkuje plné mená hráčov bez skrátených aliasov, ATP/WTA tour, presnú
   súťaž alebo celú súvislú source frázu, zhodný povrch, jedinečný zápas,
   datum dokončenia (48h) a víťaza z CDB. Zdrojové setové skóre musí
   korešpondovať s kompletnými číselnými setmi oboch strán.
4. Zachová **home/away → canonical p1/p2**, pôvodné source IDs,
   source/archive SHA-256, UTC časové pečiatky a originálny source score.
   Konflikty s už vyplnenými CDB hodnotami sú quarantine, kvalitné
   existujúce hodnoty sa nikdy neprepisujú.
5. Zapíše \`eligible.jsonl\` **v presnom stage kontrakte existujúceho
   \`import_offline_linked_serve_return.py\`**, \`review.jsonl\` pre
   neisté identity/konflikty a \`report.json\` s raw/linked/kandidátmi
   doplnených polí a nulovým počtom zápisov do CDB.
6. Existujúci CDB importer sa automaticky vykoná v **dry-run režime**
   (bez \`--write-partitions\`). Očakávaný počet riadkov a doplnených
   polí sa musí presne zhodovať s nezávislým linkovaním.
7. Pred uložením artefaktu prebehne kontrola nemennosti privátneho CDB
   release (CAS). Výstup import-ready prejde GitHub Actions artefaktom
   s retenciou 7 dní; trvalá evidencia zostáva v Azure DB a denných
   MoviOdds JSON archívoch, takže dávka sa dá znova vygenerovať.

**Samotný finálny CDB zápis ostáva v existujúcom single-writer importéri**,
ktorý pri následnom schválenom importe opäť nezávisle porovná aktuálny
kanonický podpis, spustí globálny lock, CAS, backup a read-back. Denné
staging workflow ani Drive collector **nikdy nepoužívajú CDB writer**.

Zdrojový set score nie je plne nezávisle reprodukovaný v samotnej CDB,
pretože jej kanonický snapshot ho historicky nemá ako samostatnú povinnú
položku. Predpísaný automatický gate potvrdzuje internú súdržnosť
setov MoviOdds a **nezávisle potvrdzuje víťaza v CDB**. Oboje je osobitne
zaznamenané v \`provenance\`. Ak budú dostupné ďalšie nezávislé finálne
skóre, môže sa pridať prísnejší full-score gate bez zmeny writeru.


## Automatický guarded import MoviOdds do CDB

**Žiadny nový externý cron.** Existujúci Match Status job (každých 30 minút
pod externým cron plánovačom) raz týždenne, **v nedeľu o 06:00 UTC**,
dispatchuje \`cdb-drive-inbox.yml\` s
\`source_mode=moviodds\`, \`moviodds_days_back=14\`,
\`request_id=moviodds-YYYY-MM-DD\`. GitHub run-name kontrola zabráni
druhému dispatchu toho istého týždňa.

MoviOdds používa presne **existujúci** CDB single-writer z Drive Inbox:
- chránený Azure FINAL export; samostatne označené nedostupné (503) dni,
  žiadne tiché nahradenie nulovým úspechom; iné HTTP chyby sú fatálne;
- SHA-256 overený source CDB JSON v2, striktné priradenie ATP/WTA
  hráčov, súťaže, skóre a orientácie p1/p2, konflikty v karanténe;
- iba nové **NULL-only** bunky v \`eligible.jsonl\`, bez prepisu;
- ten istý súkromný kanonický snapshot/manifest audit, guarded importer
  v dry-run, CDB global lock, CAS, immutable backup s readback,
  \`import_offline_linked_serve_return.py --exact-stats-only\`,
  celé lokálne partition overenie, release store s CAS a nezávislý
  vzdialený readback každého zmeneného riadku;
- keď je delta prázdna, žiadny lock, publish ani CDB mutation;
- pri obsadenom zámku sa MoviOdds dávka na CDB **nezapisuje**; source
  zostáva v durable Azure a je znovu spracovateľný pri ďalšom behu.

Denný read-only \`moviodds-cdb-stage.yml\` o 05:00 UTC zostáva nezmenený.
Google Drive archivácia a pôvodný Drive Inbox režim zostávajú oddelené.
MoviOdds import je aktívny iba keď sa explicitly dispatchuje
\`cdb-drive-inbox.yml\` s \`source_mode=moviodds\`; implicitný režim je
vždy \`drive\`. Žiadne nové tenisové API quota čerpanie.
