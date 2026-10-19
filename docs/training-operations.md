# Protected training in one command

## Administracia BlinQ (implementacia pripravena, vyzaduje nasadenie)

V **Administracia → Kalibracia modelu → Trening kandidatov** vyber profil a klikni **Natrenovat kandidata**. Panel zobrazuje posledne behy, aktualny krok a ulozene modely. **Obnovit stav** nacita aktualny vysledok. Trening pouziva hlavnu vetvu `main`; zmenu logiky najprv otestuj a zluc do nej. Nove data musia byt importovane do CDB. Produkcny model sa neaktivuje.

Server nepotrebuje novy GitHub token. Existujuci `BLINQ_LIVE_WORKER_TOKEN` overuje internu synchronizaciu. GitHub workflow `admin-training-worker.yml` cita stav cez existujuci `TBT_DATA_GH_TOKEN`; na dispatch pouziva kratkodoby `github.token` s Actions write. Kontrola nadvazuje na existujuci externe spustany Match Status worker (pozorovana kadencia 30 minut) a na dokoncenie treningu. Novy GitHub cron sa nepridava. Manualne **Run workflow** v admin-training-worker vynuti okamzitu synchronizaciu.

Admin POST vytvori atomicky trvaly zaznam vo fronte `model-training-queue` v existujucom admin ulozisku. Worker ho moze prevziat iba raz, znovu overi lock a aktivne treningy a az potom odosle dispatch. Pri vypadku po prevzati sa poziadavka automaticky neopakuje; operator overi runy a konkretny claim. Stav starsi ako 90 minut zakazuje nove spustenie. Treningove vstupy a produkcny model stale chrania existujuce workflow brany.

Po nasadeni treba overit synchronizaciu s nezavislym readbackom, GET/POST autorizaciu a skutocny trening. Samotny stav QUEUED znamena ulozenu poziadavku, nie hotovy model.

## Samostatne trenovanie kandidatov

Potrebujes Python a prihlaseny GitHub CLI (`gh auth login`) s pristupom do `BackstageTalks/tbt` a sukromneho `BackstageTalks/tbt-data`.

1. Nove data najprv nahraj existujucim importom do kanonickej CDB a nechaj import dokoncit. Subory len na notebooku trening neuvidi.
2. Zmeny logiky otestuj, commitni a pushni do vetvy. Trening nepouziva necommitnute lokalne zmeny. Na zachovanie presnej verzie pouzi nemenny Git tag.
3. Spusti `python scripts/train_candidate.py start --ref main --profile top-7.2.1`. Namiesto `main` mozes zadat svoju pushnutu vetvu alebo tag. Prikaz odmietne zivy/neovereny lock aj uz cakajuci trening. Samotny workflow este stale musi atomicky ziskat lock.
4. Stav: `python scripts/train_candidate.py status`. Pri viacerych behoch pripni konkretny run pomocou `--run ID` a over jeho skutocny commit.
5. Kandidati: `python scripts/train_candidate.py list`. Otvor vrateny sukromny odkaz pre model a training report. INCOMPLETE znamena, ze chyba model alebo povinne subory; samotny release tag nie je natrenovany kandidat. ASSETS_PRESENT_UNVERIFIED znamena iba pritomnost suborov, nie overenu kvalitu.

Bez terminalu otvor [protected training v GitHub Actions](https://github.com/BackstageTalks/tbt/actions/workflows/protected-frozen-cdb-candidate.yml), klikni **Run workflow**, vyber vetvu a profil `top-7.2.1`. Pouziva rovnake existujuce ochrany. Pri zostatkovom locku po pade runnera najprv treba overenu obnovu prevadzky.

Kazdy beh vytvara oddeleneho kandidata s ID runu a pokusu. Je to novy fit z aktualnych zmrazenych dat a vybraneho kodu, nie pokracovanie od vah lubovolneho stareho kandidata. Stareho kandidata mozes uchovat na porovnanie; opakovanie s novymi datami prirodzene nevytvori totozny model. Presna reprodukcia vyzaduje aj povodny snapshot vstupov, zavislosti a nastavenia a tento prikaz ju automaticky nezarucuje.

Trening nic neaktivuje v produkcii. Po uspechu zostava vyhodnotenie kvality a samostatne rozhodnutie o aktivacii.

## Read-only status details

Run `python scripts/training_status.py` from the repository with an authenticated GitHub CLI account that can read both repositories. It finds the newest protected training run, reads its current attempt and independently checks the annotated writer lock. Use `--run 39144726241` to pin a run, or `--json` for machine-readable output.

The command only reads GitHub. It does not restart training, change a lock, consume provider requests or activate a model. An inaccessible or missing private lock is reported as UNVERIFIED, never as permission to start another writer.

If EXECUTING, let the existing workflow continue. If BLOCKED, inspect the failed step before retrying; never delete an unverified lock. WORKFLOW_SUCCEEDED means the workflow finished, not that the model is ready to deploy.

Before release, independently read back the candidate and compare it with the pinned champion and 7.1.1. Require ATP/WTA metrics, calibration and stability, and TOP evidence at real pre-match odds >= 1.50 (sample size, hit rate, ROI and uncertainty). Production activation still requires explicit owner permission.
