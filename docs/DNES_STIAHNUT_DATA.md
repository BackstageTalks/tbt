# Spustiť reálnu históriu dnes

Pri 31 % z 15 000 zostáva približne 10 350 požiadaviek. Používateľ uviedol reset o 19:10
a čas 15:30. Tieto údaje sú manuálny stav, nie živé meranie. Pred hlavným behom skontroluj
RapidAPI dashboard znova. Nečerpá nič iné: plán je 100 na kontrolu a najviac 9 900 na hlavný beh.

## 1. Repozitáre a prístupy

`tbt-data` musí byť PRIVATE a mať aspoň jeden commit, napríklad README. Žiadne dátové
priečinky v ňom nevytváraj; sťahovač sám vytvorí Release a uloží súbory po rokoch.

V **tbt → Settings → Secrets and variables → Actions → Secrets** nastav:

- `RAPIDAPI_KEY`: existujúci kľúč pre TennisApi.
- `TBT_DATA_GH_TOKEN`: fine-grained GitHub token s prístupom iba k `BackstageTalks/tbt-data`,
  oprávnenie **Contents: Read and write**. Ak ho organizácia musí schváliť, počkaj na schválenie.

Kľúče nedávaj do súborov, chatu ani screenshotov. Bežný workflow `GITHUB_TOKEN` verejného
`tbt` nemá automaticky prístup do druhého súkromného repozitára.

## 2. Kód

Buď nahraj celý nový projekt podľa MIGRACIA.md, alebo na rýchly štart iba obsah balíka
`tbt-download-today.zip` do existujúceho `tbt`. Samostatný balík obsahuje `tools/tennis_download`
a `.github/workflows/download-tennis-history.yml`; existujúci web nemení.
Po neskoršej kompletnej výmene samostatný workflow odstráň. Oba balíky ukladajú dáta rovnako.

## 3. Kontrolný beh

V GitHub **Actions → Tennis data and predictions → Run workflow**:

- `mode`: `history`
- `start`: prázdne
- `lookback_days`: `1095` (alebo `365` pre posledný rok)
- `end`: prázdne, teda včerajšok UTC
- `max_requests`: `100`
- `promote`: `false`

Pri samostatnom balíku sa workflow volá **Download tennis history** a navyše vyplníš
`data_repository = BackstageTalks/tbt-data`.

Počkaj na výsledok. V logu skontroluj `stored_matches`, `completed_days`,
`requests_including_retries`. V **tbt-data → Releases → tbt-data-v1** musia byť
Parquet súbory, manifest a checkpoint. Samotný zelený beh bez zápasov nestačí na overenie
pokrytia. Pri HTTP 401/403 alebo nerozpoznanej odpovedi neopakuj veľký beh naslepo.

## 4. Hlavný beh

Po úspešnej kontrole zadaj rovnaké dátumy a `max_requests=9900`, pokiaľ dashboard stále
ukazuje dostatočný zostatok. Opakované dni sa preskočia. Sťahovanie ide od včerajška dozadu.
Beh sa zastaví pri limite požiadaviek, po troch hodinách alebo po dokončení rozsahu.
9 900 je strop, nie sľub, že sa všetky požiadavky stihnú či spotrebujú.

Ak sa história dokončí s menšou spotrebou, rezervácia zostane blokovaná; nepokúšaj sa ju
obísť zmenou release tagu. Pre dlhšiu históriu zväčši `lookback_days`, napríklad na 1825. Dátumy netreba meniť pri novom roku.

## 5. Štatistiky a večerný tréning

Najprv široká história výsledkov. Potom režim `statistics` pre už stiahnuté dátumy.
Na prvú kontrolu štatistík použi 20 požiadaviek v období, kde už sú uložené zápasy;
pokrytie konkrétnej ligy nie je zaručené. Štatistiky sa nedomýšľajú a chýbajúce hodnoty
sa nemenia na nulové výkony. Tréning môže fungovať aj pred týmto obohatením.

Pri nových dátach overená identita z kalendára ušetrí detail endpoint: zostáva jedna
požiadavka na štatistiky. Staršie dáta bez tejto identity potrebujú aj detail. Dostupné
historické štatistiky sa znova nesťahujú; nedostupné sa skúšajú najskôr po 30 dňoch.
To znižuje spotrebu, ale automaticky nezachytáva neskoré opravy už dostupných štatistík.

Keď je dosť histórie, spusti v kompletnom projekte `train`, potom `backtest`.
Tieto dve operácie spotrebujú **0 TennisApi requestov**. Reálnu úspešnosť nájdeš až
v reportoch. Nepoužívaj percentá z testovacích dát ako výsledok systému.
