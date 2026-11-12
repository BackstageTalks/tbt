# BlinQ 7.2.2 — samostatné spustenie výskumného shadowingu (2026-11-12)

**Stav:** samostatná administrátorská požiadavka, žiadny automatický model switch.

## Postup v existujúcom Admin → Model Lab

1. **Obnoviť celý stav:** musí byť dostupný aktuálny pracovník Model Lab,
   aktuálny SHA produkčného championa, aktívneho kandidáta a súpis
   nemenných kandidátskych releasov.
2. V časti **2 · Natrénovať a aktivovať kandidáta** nájdi
   **Výskumný shadow · bez produkčného nasadenia**.
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
