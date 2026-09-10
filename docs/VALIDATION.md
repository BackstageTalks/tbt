# Overenie odovzdaného balíka

- 46 offline pytest testov prešlo v Python 3.12.
- Testy zahŕňajú chronologické rozdelenie, symetriu modelu a uloženého artefaktu,
  tréning na syntetickej histórii, priradenie štatistík, Parquet roundtrip, počítanie
  retry požiadaviek, rezerváciu pred API volaním, resume, odmietnutie verejného dátového
  repozitára, nemennosť predikcie, Supabase auth failure a dátumy cez Nový rok/priestupný deň.
- Python compileall pre API a scripts prešiel.
- Node syntax check pre web/app.js a web/auth.js prešiel.
- Workflow YAML a statické JSON konfigurácie sa parsujú. CLI --help funguje.
- ZIP obsahuje koreňové projektové súbory, bez API kľúčov, cache, reálnych dát a modelov.

Živé volania TennisApi/Open-Meteo, reálne GitHub Actions, Azure deploy a Supabase login/email
neboli vykonané. Offline mock odpovede neoverujú aktuálny kontrakt poskytovateľa.
Prvý beh s 100 requestmi je preto nutnou prevádzkovou kontrolou.
Nie je deklarovaná nameraná reálna predikčná úspešnosť. Vizuálne QA webu bolo podľa zadania
odložené; webová implementácia a auth musia byť overené na tvojej doméne.
V ZIP-e nie sú staré priložené workflow, ktoré zapisovali športové dáta do Supabase.
