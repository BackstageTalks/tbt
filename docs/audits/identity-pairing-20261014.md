# BlinQ — checkpoint pred auditom párovania (2026-10-14)

## Účel
Audit-only zlepšenie vyhľadávania identít v historických tenisových zdrojoch. Produkčná CDB a model sa nemenia. Žiadne automatické uvoľňovanie neistých zhôd.

## Pre-change recovery pointers
| Component | Exact immutable reference / recovery pointer |
| --- | --- |
| App repository `BackstageTalks/tbt` | `c7e2f189ca625b938c5c5f06fcb1465375d9e55b` |
| Data repository `BackstageTalks/tbt-data` | `c9cc2caa9e4e3337a3b5ebe54a4158b224eaa90e` |
| Research repository `BackstageTalks/tbt-pro` | `1645f37515bbb6fb4d5c79b82f8736d2381b06bb` |
| Frozen reference branches (all 3 repos) | `backup/pre-identity-audit-20261014` |
| Current canonical CDB release | Private `BackstageTalks/tbt-data` release `tbt-data-v1` (release ID 383147911) |
| Frozen CDB, champion/model and training inputs | Private release `blinq-full-training-backup-38486683787-1` (release ID 412206702, 99 assets) |
| Historical partitions | All 78 `history-*.parquet` asset SHA-256 digest strings compared equal between active `tbt-data-v1` and frozen snapshot by GitHub authenticated metadata lookup |
| Current CDB history manifest | `sha256:036be275bfb526761c9a06233036b5a272dc3e561328577959a2ff8898664493` |
| Frozen production model.joblib | `sha256:a96e61f1942a3ee9cd35f1e754b4981e420f26ba08049a66d65c00ae4f09c4a7` |

**Caveat:** Matching remote asset digest metadata is not equivalent to full byte download / independent restore drill. No backup of Azure web app settings, Azure Blob media, Firebase account/auth or private external secrets has been independently verified. Do not label this a complete disaster-recovery backup.

## Worklog
1. Read latest default-branch commit and private CDB lock. At checkpoint, the global writer lock was owned by frozen-model training run `BackstageTalks/tbt/actions/runs/38486683787/attempts/1`; do not force release.
2. Created three isolated backup branch references at pre-change main SHAs. No Git main branch was moved by these operations.
3. Compared 78 history asset digests to the existing frozen history snapshot. All 78 matched at that moment.
4. Inspected existing exact normalized Sackmann name-pair match in `scripts/audit_pbp_source_vs_current_cdb.py`. Observed it cannot propose abbreviated/full-name variants. Existing `scripts/link_offline_serve_return.py` already enforces independent, SHA-pinned source-ID evidence; do not weaken it.
5. Proposed optional `--alias-research` mode in an isolated PR. Exact baseline remains the default. Full-name/initial+surname matches become *unverified research candidates only*. Ambiguous same-initial family names, non-two-token names, duplicate canonical ID mappings, unverified winner orientation are excluded. Unchanged CDB write authorization: zero.
6. Added isolated synthetic regression tests, plus opt-in manual audit workflow parameter.
7. Scheduled 06:30 Europe/Bratislava post-morning-refresh preflight. Its 8,000 API calls are a total ceiling (including retries), **not** a target; no automatic use of unverified research candidates. Require current CDB checksum, own global writer lock, preserved model, protected backup, provider header/quota checks, max 6 req/s, CAS and independent remote readback.

## Invariants for future work
- Never trust only name/date/tournament/round/score as *independent* match/player ID attestation. Never promote shorthand research proposals to the CDB.
- Whole-match stats must have independent completeness corroboration; balanced partial point totals are insufficient.
- No auto writer on source-only candidates. Original raw source and SHA retained privately; respect per-source rights/license.
- No concurrent writers, no forced lock release, no unplanned deploy, no model promotion, no skip of tests.
- Evaluate baseline vs alias mode against the same frozen CDB and source bytes; report unique net new candidates, aliases, conflicts, collisions, false matches on adjudicated truth set, and change in NULL proposal counts. Do not claim an increase in *approved import* solely from alias matches.

## Rollback
This PR changes research audit code only. Before any main merge, reverting is closing the PR; production code and CDB remain unchanged. After merge, restore the previous audit by reverting the merge commit or resetting only the affected files to the saved app commit after verifying the current head and unrelated new changes. Never force-push main. For CDB restoration, use the verified private release and global writer/immutable restore procedure; never directly overwrite while another writer owns the lock.

## Open prerequisites
- CI must pass on the exact proposed head commit.
- Full-scale opt-in alias scan and independent false-positive assessment are *not yet performed*.
- Actual complete Azure/Firebase disaster-recovery backup and restore have *not been demonstrated*.
- Current morning workflow, CDB lock, API quota and trainer state must be rechecked before any provider-backed ingestion.
