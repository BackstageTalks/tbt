# BlinQ 7.2.2 — samostatné spustenie výskumného shadowingu (2026-11-12)

**Stav:** samostatná administrátorská požiadavka, žiadny automatický model switch.

## Postup v existujúcom Admin → Model Lab

1. **Obnoviť celý stav:** musí byť dostupný aktuálny pracovník Model Lab,
   aktuálny SHA produkčného championa, aktívneho kandidáta a súpis
   nemenných kandidátskych releasov.
2. Na hlavnej obrazovke **Model Factory** otvor priamo viditeľnú kartu
   **Výskumný shadow · bez produkčného nasadenia** (netreba rozbaliť
   pokročilé ovládanie).
3. V poli **Nemenný kandidát** vyber presný
   `blinq-candidate-frozen-<run_id>-<attempt>`. V ponuke sa
   zobrazuje skrátené SHA; originál sa overuje na serveri.
4. Stlač **Spustiť výskumný shadow (prospective only)** a potvrď účel.
5. Model Lab uloží **jednorazovú** požiadavku. Existujúci externý cron
   a `admin-model-lab-worker.yml` následne použijú **len**
   `activate-shadow-candidate.yml` s týmito vstupmi:

   | Workflow input | Hodnota |
   |---|---|
   | `ref` | `main` |
   | `request_id` | automaticky vygenerované ID |
   | `source_tag` | presne vybraný nemenný release |
   | `expected_candidate_sha256` | aktuálny digest shadow slotu z overeného serverového snapshotu |
   | `prospective_only` | `true` |
   | `expected_source_sha256` | digest vybraného nemenného releasu z overeného serverového snapshotu |

   **Nepoužívaj predvolené hodnoty workflow.** Pre nové verzie sa digest
   nemá ručne prepisovať podľa starých poznámok.

6. Po úspešnom GitHub behu sa server musí znovu zosúladiť s nezávislým
   read-backom candidate release. Až potom Model Lab uvádza
   `WORKFLOW_VERIFIED`. `SHADOW_ACTIVE` je výlučne o kandidátskom
   shadow slote, nie o produkcii.
7. **Vyhodnotiť shadow výsledky** je oddelená read-only operácia.
   Predzápasové vydania a skutočne vyhodnotené zápasy musia mať zhodné
   identifikátory. V historickej ponuke sa nič spätne nemení.

## Súčasná pripravená výskumná verzia

- Frozen candidate release: `blinq-candidate-frozen-42284691497-1`.
- Model SHA-256: `131a4dd71994f082bf5c041c5f7a785d581421170a44ace39de9e27c61f1de3f`.
- Predchádzajúci pozorovaný active shadow model SHA:
  `aa0f0ab10f08ef76f1bb793e431e460448ff7c645fb8528ba452957700215da8`.
- Predchádzajúci pozorovaný production SHA:
  `c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91`.

Tieto hodnoty sú **historická referencia**. Server ich vždy pred zápisom
znovu načíta a skontroluje; nesmú slúžiť ako pevne zakódované konštanty.

## Bezpečnostný kontrakt

- Jediný existujúci Model Lab queue + claim, pred dispatchom nové čítanie,
  existujúci GitHub `workflow_dispatch`, globálny CDB writer lock,
  CAS na aktuálnom kandidatovi, SHA nemenného zdroja.
- Reuse pôvodného `activate_shadow_candidate.py --prospective-only`:
  nezávislá kontrola nemennej zálohy, pôvodného championa,
  oboch shadow/release uploadov a read-back; pri neočakávanej chybe
  kontrolovaný rollback.
- Research-only `UNVERIFIED_RESEARCH`: neobchádza modelové metriky,
  iba výslovne označuje ich zatiaľ nepotvrdenú kvalitu. Žiadne automatické
  povýšenie 7.2.2, zmena webových tipov, kurzov, CDB ani platené API volania.
- Neúspešná alebo nejednoznačná mutácia drží frontu uzamknutú
  do nezávislej rekonciliácie. Znova ju nespúšťaj naslepo.
- Bežná **Aktivovať iba shadow (manuálne)** zostáva naďalej zvlášť
  viazaná na overený offline holdout (pôvodný režim).


## Overený stav po jednorazovom spustení (12. 11. 2026, UTC)

- **IMPLEMENTOVANÉ / OTESTOVANÉ / MERGED / NASADENÉ (Admin tlačidlá):**
  PR [#1573](https://github.com/BackstageTalks/tbt/pull/1573);
  produkčný CI/deploy [#43193261050](https://github.com/BackstageTalks/tbt/actions/runs/43193261050).
  Live `app.js` nezávisle obsahoval `model-lab-research-shadow` aj `prospective_only`.
- **SHADOW AKTIVOVANÝ A OVERENÝ:** presný native
  [workflow #43198370104](https://github.com/BackstageTalks/tbt/actions/runs/43198370104)
  na [schválenom one-shot PR #1577](https://github.com/BackstageTalks/tbt/pull/1577);
  result `VERIFIED_ACTIVE_SHADOW_CANDIDATE`, `remote_readback=VERIFIED`.
- **SKUTOČNE zapísaný kandidát:** `tbt-model-candidate-v1` / `model.joblib`
  SHA `131a4dd71994f082bf5c041c5f7a785d581421170a44ace39de9e27c61f1de3f`,
  model `v7.2.2-v201-20261106T212948133645Z`;
  porovnané nezávisle s immutable source release.
- **PRODUKCIA ZACHOVANÁ:** `tbt-model-production-v1` stále model SHA
  `c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91`,
  model `v7.2.1-v201-20261022T134742452543Z`. Zero model promotion.
- **METRIKY VYKONANIA:** `provider_requests=0`,
  `production_mutated=false`, `captured=0`, `settled=0`,
  `pending=0`, `remote_readback=VERIFIED`; 7 aktivátorových testov
  prešlo; globálny lock `acquired` aj `released` v rovnakom native behu.
  `UNVERIFIED_RESEARCH` = iba prospektívna kvalita; úspešnosť zatiaľ
  **nemožno vypočítať**, nula zápasov nie je dôkaz lepšieho modelu.
- **Admin porovnanie:** bezprostredný best-effort publish odmietol
  readiness starší než 1 hodinu (`Readiness evidence is not current`).
  Ide o PREDCHÁDZAJÚCE fail-closed pravidlo, nie chybné modelové SHA;
  žiadne obídenie pravidla. Existujúci `model-calibration-monitor.yml`
  po cleanup merge vykoná nový read-only kanonický scan a podpísaný
  Azure Admin read-back. Dokončenie publikácie overiť v jeho samostatnom behu.
- **Dočasná infraštruktúra:** jednorazový push override vypnúť/obnoviť
  cez [cleanup PR #1580](https://github.com/BackstageTalks/tbt/pull/1580).
  Trvalá aktivácia budúcich kandidátov používa iba Admin → Model Lab
  a pôvodný `workflow_dispatch`.
- **Ďalší krok:** zbierať pravé predštartové paired same-event shadow dáta,
  vyhodnotiť ATP/WTA a konfidenčné pásma ≥65 %,
  zdrojovú PIT provenienciu; nie je schválené prepnutie championa.


- **ADMIN SYNC OVERENÝ (následné nezávislé čítanie):** existujúci
  [kalibračný monitor #43200497455](https://github.com/BackstageTalks/tbt/actions/runs/43200497455)
  skončil úspešne 12. 11. 2026. Čerstvý readiness report
  `generated_at_utc=2026-11-12T10:30:45.190067+00:00`;
  publish `stored=true`, `production_version=v7.2.1-v201-20261022T134742452543Z`,
  `candidate_version=v7.2.2-v201-20261106T212948133645Z`,
  `shadow_settled=0`, `provider_requests=0`, `model_promoted=false`.
  Publisher vykonal nezávislý Azure GET read-back s kontrolou podpisového
  fingerprintu, modelových verzií a cohort počtov. Scanner zaznamenal
  `new_unseen_rows=6336` ako existujúce dokončené kanonické zápasy pre
  ďalšie posúdenie, **nie** 6336 nových shadow tipov.
- **Záverečná bezpečnostná kontrola:** po monitori
  `tbt-model-candidate-v1` stále SHA `131a4dd7...f1de3f`,
  `tbt-model-production-v1` stále SHA `c1e761cc...d99e9`;
  globálny CDB writer lock nie je obsadený.


## Prospektívny stav k 13. 11. 2026

**Overené (UTC 09:21):** Ranný externý clock spustil
[supervisor #43364306931](https://github.com/BackstageTalks/tbt/actions/runs/43364306931)
a chránený skutočný
[refresh #43364326140](https://github.com/BackstageTalks/tbt/actions/runs/43364326140).
Jeho `pipeline` job #131685037823 publikoval presný pár
`v7.2.1-v201-20261022T134742452543Z` vs.
`v7.2.2-v201-20261106T212948133645Z` a hlásenie
`shadow_evaluation: captured=215, settled=0,
minimum_for_review=200, ready_for_promotion_review=false`.
Súkromný shadow release `tbt-model-shadow-v1` dostal nový manifest
13. 11. 2026 o 04:47:27 UTC (SHA-256 ledgeru
`7a8ecb8f561d6c6acdf67d4bcb2518bc52a742c616d999665fb5fb061fcdda51`);
modelové releasy sa nezmenili. Aktuálny
[Model Lab monitor #43377523359](https://github.com/BackstageTalks/tbt/actions/runs/43377523359)
úspešne zapísal správny modelový pár do Azure Admin (`stored=true`,
`shadow_settled=0`, `provider_requests=0`, `model_promoted=false`).

**Neuzavreté:** Žiadny výsledok z aktuálneho páru nie je nezávisle
vyhodnotený; `captured` ≠ `settled`. Na rozhodnutie treba minimálne
200 jednoznačne kanonicky vyhodnotených zápasov z minimálne 3 UTC dní,
paired pre-match identitu, Brier/log-loss/accuracy vs championa vrátane
ATP/WTA a 65%+ skupín, nezávislý rollback/promotion gate a nový
explicitný súhlas na produkčný switch. Nie je prípustné nahradiť túto
vzorku historickými `unseen` zápasmi (napr. 6684 riadkov readiness
nepredstavuje shadow výsledky).

**Kontinuálne overenie:** Zriadená separátna denná podmienená kontrola
`BlinQ 7.2.2 shadow výsledky` v ChatGPT automations
(od 14. 11. 2026, 10:30 Europe/Bratislava). Monitoruje reálne ranné
`shadow_evaluation` výsledky, stabilné SHA, správnosť Admin sync,
prípadnú stagnáciu a prah 200 settled / 3 dni; bez provider requestov,
bez zmeny cronu, CDB alebo produkčného modelu.
