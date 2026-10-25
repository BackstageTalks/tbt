# DIL – overenie aktuálneho binárneho zdroja CDB (25.10.2026)

Tento balík preverí, či existujúca autorizovaná CI infraštruktúra `BackstageTalks/tbt` dokáže bezpečne prečítať **všetkých 78 ročných častí** autoritatívnej CDB z privátneho `BackstageTalks/tbt-data`. Vykoná kontrolu SHA-256 každého súboru, oboch manifestov, inventára a porovná metadáta GitHub release pred sťahovaním, po ňom a po kontrole súborov. Ak sa release zmení, opakuje celý prenos maximálne trikrát. Pri pevnej chybe súboru končí blokáciou, nie predstieraným úspechom.

Pridaný workflow používa existujúci `TBT_DATA_GH_TOKEN` výhradne na `main` z dôveryhodného repozitára; nie pri PR. Nesprístupňuje súbory hráčov/zápasov verejným artefaktom. Pri chybe alebo dokončení vymaže dočasnú lokálnu kópiu.

Toto je **iba kontrola možnosti získať aktuálnu CDB**, nie zlúčenie alebo 100 % parita DIL. Na skutočný finálny import musí autorizované súkromné prostredie vykonať `refresh_dil_secondary.py` s overeným 5+ GB DIL snapshotom, predložiť výsledný nezávislý audit a až potom môže aktivovať *iba sekundárny DIL pointer*. Primárnu CDB, API, model ani produkciu tento balík nemení.

Obsah: `probe_dil_secondary_live_cdb.py`, `test_probe_dil_secondary_live_cdb.py`, `dil-secondary-cdb-source-preflight.yml`; lokálny kopírovaný `build_current_cdb_compare.py` slúži len na samostatné syntetické testovanie balíka. V BlinQ repozitári už existuje jeho kanonická verzia, neduplikovať ju.

Syntetické testy: `python -m unittest discover -q -s . -p 'test_probe_dil_secondary_live_cdb.py'` – **8/8 PASS**.