# BlinQ Drive/CDB audit on a bounded public GitHub runner

**State: PREPARED; no LIVE audit or CDB import is claimed until real-run verification.**

The workflow `.github/workflows/blinq-private-drive-cdb-audit-bridge.yml` runs on the public software repository `BackstageTalks/tbt` to avoid exhausted PRIVATE-repo GitHub Actions minutes. It reads the **private Google Drive** BlinQ folder (ID `17UChTTWLpC-7tZIbvTXKA4_2eqooV44A`) and **private canonical CDB** in `BackstageTalks/tbt-data`. Both data and results stay private. The Drive folder is backed up from `Computers / My laptop`; bytes already synchronized are available when the computer is off.

## One-time operator checks before the first live run

1. In **BackstageTalks/tbt → Settings → Secrets and variables → Actions**, create the secret `BLINQ_DRIVE_READER_JSON` containing the existing Drive reader service-account JSON. **Do not** publish the credentials in a public repo, pull request, chat or log. The secret with the same name in `tbt-data` is NOT automatically available to `tbt`. If necessary, obtain the key securely from the Google Cloud project; do not copy a screenshot of its contents.
2. Verify that `TBT_DATA_GH_TOKEN` exists in **public tbt Actions secrets**, is restricted to private repository `BackstageTalks/tbt-data`, and has access sufficient for private release asset reads/writes. Do not print or transmit this token.
3. Drive metadata verified the existing reader `blinq-drive-reader@blinq-drive-audit.iam.gserviceaccount.com` has **Viewer** permission on the nested `BlinQ` folder. No need to share or publicize parent `BlinQ_data`.
4. Verify current GitHub billing is configured without extra spending. This is intended for standard public-repository `ubuntu-latest` only, not larger paid runners or heavy scraping.

## Manual pilot

After the workflow is merged into `tbt/main` and the prerequisites are confirmed, use the GitHub **Actions** tab, open **BlinQ private Drive CDB audit - bounded free public runner**, press **Run workflow** with `batch_files=10`.

Alternatively, from already-authenticated GitHub CLI:

```powershell
gh workflow run blinq-private-drive-cdb-audit-bridge.yml --repo BackstageTalks/tbt --ref main -f batch_files=10
```

**Dispatch does not mean success.** Verify the actual job conclusion, a private audit report release `blinq-drive-cdb-audit-<run>-<attempt>`, its independent SHA-256 read-back, and (only if successful) a private SHA-256-verified cache in `blinq-drive-cdb-audit-cache-v1`.

## Hard boundaries

- **No new scraping, no sports API requests, no model training and no write to canonical CDB.** Only the current CDB is read with a required bundle manifest.
- On public PRs the only job is synthetic safety tests, which receive no private token. Full private Drive access is gated to a manual run on trusted `tbt/main`.
- Private-source Python audit is pinned to commit `5166c9695269fa3c570e5a42f6e2f7a8133b554a`, not an uncontrolled branch head.
- Bounded source parsing: 10/25/50 changed files and **256 MiB** per run. Read-only SQLite checkpoints are reused only when both script SHA-256 and folder identity match.
- **No public cache, no public upload-artifact and no raw private diagnostic logs.** Evidence and result files are uploaded only to `tbt-data` *private* Releases and downloaded again for checksum validation. Do not publicly share the report download URLs or file contents.
- The audit output has `approved_fields=0`, `cdb_writes=0`, `all_data_importability_assessed=false`. Each candidate must be `import_ready=false`. The current parser supports CSV/TSV/JSONL/ZIP and certain canonical stats only. Excel, SQLite, JSON, Parquet and unlinked matches require reviewed adapters.
- This is deliberately not a 24/7 bulk web scraping infrastructure. `on.schedule` is absent; no external cron is activated in this PR. First verify a real **10-file** pilot, then discuss tightly bounded unattended scheduling compliant with repo contracts and GitHub terms.
- A future CDB importer is a **separate** workflow requiring confirmed identities, licences, provenance, point-in-time gates, global writer lock, immutable backup, current manifest CAS and full read-back.

If a prerequisite is missing, the pilot must fail CLOSED, without enabling paid GitHub services.
