# Počasie a automatické roky

Starý environment-enrichment.yml zapisoval nedávne počasie do Supabase. Nová verzia to
nerobí. Voliteľný režim `environment` uloží iba výskumný archív do súkromného Release
`tbt-environment-v1` v `tbt-data`, súbory `enviro-YYYY.json.gz`. História zápasov zostáva
v `tbt-data-v1` ako `history-YYYY.parquet`. Priečinky ani roky nevytváraj ručne.

Počasie pochádza z Open-Meteo, teda spotrebuje **0 TennisApi požiadaviek**. Free API je
určené na nekomerčné použitie/evaluáciu; komerčný API prístup má samostatné podmienky.
Preto sa v produkcii automaticky nezapína a nepridáva sa platené predplatné.
Zdroj: https://open-meteo.com/en/pricing . Dáta vyžadujú atribúciu Open-Meteo (CC BY 4.0).

Ak chceš výskumný download, nastav Actions variable `TBT_WEATHER_RESEARCH=true`, potom
spusti `mode=environment`, `max_requests=100`, `lookback_days=1095` (alebo 365).
Režim environment používa iba lookback, nie voliteľné start/end ostatných režimov.
Limit je 1..500 weather HTTP požiadaviek na beh a najviac 500 rezervovaných za 28 hodín.

Jedna odpoveď počasia poskytuje celý UTC deň pre mesto a opakovane slúži všetkým zápasom
na danom mieste. Súradnice mesta sa tiež uchovávajú. Identita miesta vyžaduje explicitné
mesto a dvojpísmenový kód krajiny v dátach. Nejednoznačné lokality sa preskočia; názov
turnaja sa nepoužíva ako domyslená adresa. Ide o presnosť mesta, nie konkrétneho kurtu.
Prvých 7 dní dozadu sa vynechá kvôli oneskoreniu archívnych dát. Indoor zápasy sa vynechajú.

Ide o reanalýzu skutočných podmienok, nie o predpoveď známu pred zápasom. Archív je
oddelený od tréningu a live model počasie zatiaľ nepoužíva. Pre budúce zapojenie treba
ukladať predpovede s časom vydania pred zápasom a overiť prínos na novom období.
Zdroj: https://open-meteo.com/en/docs/historical-weather-api .

`history` má predvolený pohyblivý rozsah posledných 1095 dokončených dní; číslom 365
si vyberieš posledný rok. Už stiahnuté dni sa preskočia a staršie súbory sa nemažú.
Po prvom ručnom overení nastav `TBT_AUTO_HISTORY=true`: denne automaticky dopĺňa
históriu s alokáciou najviac 4000 TennisApi požiadaviek. Roky a priestupné dni vypočíta Python.
`TBT_AUTO_REFRESH=true` je osobitný prepínač aktualizácie predikcií. Tréning/propagácia
a výskumné počasie sú zámerne ručné; úspešný model sa nevymieňa bez vyhodnotenia.

Automatizácia neznamená záruku nulovej údržby: expirované tokeny, zmeny API schémy,
výpadky a limity vyžadujú zásah. Pri chybe sa výpočty nesnažia nahradiť chýbajúce dáta výmyslami.
