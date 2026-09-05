# Výmena tbt cez kláves bodka

Kláves `.` na stránke repozitára otvorí github.dev. Je to editor; sťahovanie a výpočty
spúšťaj cez GitHub Actions. Nevyžaduje otvorenie plateného Codespace.
Oficiálny návod: https://docs.github.com/en/codespaces/the-githubdev-web-based-editor

1. Stiahni ZIP aktuálneho `tbt` ako zálohu a zapíš si aktuálny commit.
2. Rozbaľ `tbt-v3-complete.zip` na počítači. Vnútri sú priamo `.github`, `api`, `scripts`,
   `tests`, `web`, `docs` a README. Nenahrávaj samotný ZIP ani nadradený priečinok navyše.
3. Otvor `BackstageTalks/tbt`, stlač `.`. V editore odstráň staré projektové súbory a nahraj
   rozbalený obsah do koreňa. Skontroluj aj skrytý priečinok `.github`.
   Staré workflow sa nesmú ponechať vedľa nových: v kompletnej verzii majú zostať len
   `.github/workflows/ci.yml` a `.github/workflows/data.yml`.
4. V Source Control skontroluj zmeny, Stage All a Commit & Push do `main`.
   Výmena súborov nemení GitHub Secrets ani druhý repozitár. Neodstraňuj samotný repozitár.
5. Otvor GitHub Actions a skontroluj **Test and deploy**. CI testy bežia automaticky;
   nasadenie z pushu je vypnuté, kým nenastavíš `TBT_DEPLOY_ENABLED=true`.
6. Nastav dva dátové Secrets podľa DNES_STIAHNUT_DATA.md a spusti históriu.

## Existujúci Azure a Supabase

Workflow používa existujúci deployment secret
`AZURE_STATIC_WEB_APPS_API_TOKEN_AGREEABLE_SKY_011A7FE10`.
Ak má tvoj platný token iný názov, zmeň odkaz v oboch workflow súboroch.

V Azure Static Web App Application settings nastav `SUPABASE_URL` a `SUPABASE_ANON_KEY`
existujúceho Supabase projektu. Nepoužívaj `service_role` ani secret key ako anon key.
Supabase Auth → URL Configuration: nastav produkčnú Site URL a povoľ callback
`https://TVOJA-DOMENA/follow-the-data/`. Zachovaj existujúci Supabase projekt: účty zostanú.
Potvrdenie emailov a odosielanie resetov závisí od nastavení a limitov Supabase mailu.

Po tréningu s úspešnou propagáciou spusti `refresh` (napr. max_requests 750).
Tento ručne spustený režim **nasadí web aj API** cez existujúci Azure token.
Následne over prihlásenie, odhlásenie, reset hesla, `/api/health` a chránený `/api/v1/feed`.
Bez tokenu musí feed vracať 401. Bez modelu web nezobrazuje vymyslené predikcie.

`TBT_AUTO_REFRESH=true` zapni až po úspešnom ručnom refreshi a overení rozpočtu.
`TBT_DEPLOY_ENABLED=true` zapína nasadenie pri ďalších pushoch do main.
Oba prepínače sú **Actions Variables**, nie Secrets. Voliteľná variable
`TBT_DATA_REPOSITORY` má predvolenú hodnotu `BackstageTalks/tbt-data`.

## Rozsah a návrat

Nový web má emailové prihlásenie/registráciu, obnovu hesla, predikcie, výsledky a reporty.
Pôvodné platby, Telegram autentifikácia a platené role sa neprenášajú ako hotové funkcie.
Vizuálne doladenie zostáva podľa zadania až po dátach a modeli.

Návrat k predchádzajúcemu kódu: revert migračného commitu. Dáta v `tbt-data` pritom
nemaž. Pred obnovou starých automatizácií over, kam zapisujú a koľko API požiadaviek čerpajú.
