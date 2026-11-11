# TOP production policy and morning runbook

Active policy: `priority_tours_top_v19`. Supersedes v18 and the earlier stepped-probability proposal.

VERIFIED deployment: PR #1459, commit `f4e0eda72dd5c6a5065c0df93a3428250b8c5ed6`,
[successful checks and deployment](https://github.com/BackstageTalks/tbt/actions/runs/42480094670).
Independent production deployment.json and ui-config.json readback matched this commit and policy on 2026-11-08.

The owner's latest instruction is to aim for at least three TOP picks and allow
probabilities to fall to approximately 70%. This supersedes the earlier proposal
of a fixed 80% floor with no daily target. The existing three-slot output is
retained; there is no new TOP1/TOP3 product.

- Within ATP/WTA, rank by descending probability with a fixed 70% floor.
- Then use Challenger/WTA125, and finally ITF, with the same 70% floor and probability ordering.
  Tour names alone cannot identify competition: ATP also contains male ITF/UTR.
- Use the existing model/bookmaker agreement ranking only to break probability ties.
  This score is a ranking heuristic, never a displayed calibrated probability.
- No drop below 70%, depth 80%, or five prior surface matches for either player.
  Remove v18's 60% floor and .75-depth/three-surface-match backup.
- TOP decimal odds >=1.50, with no upper price limit.
- VALUE has priority at odds strictly >1.80 and symmetric gap <=15%, with its
  existing probability/data-quality gates. Exactly 1.80 belongs to TOP.
- Require exact event/selection identity, model/quote pre-start timestamps and
  internally consistent probabilities. Preserve price-integrity guards.
- Freeze competition, original prediction time, round, model-time ranks,
  rejection reasons and policy version for future auditing.
- ACES/DF, including existing random ACES prices 1.6-1.8, are unchanged.
  No CDB writes, model fitting, extra provider passes, new cron, or sent messages.

Three valid picks is the target, not permission to fabricate a quote or inflate
a probability. The full ordinary prediction slate remains intact. Repeated
shortfalls are diagnostics for data delivery, quote coverage and model quality,
not a successful product outcome.

## Evidence and rollout

`audit_top_direction.py` checks private input hashes and joins outcomes by exact
event/player identity. Historical snapshots lack explicit competition/created_at.
The capacity screen labels current category joins and snapshot-time upper bounds
as surrogates; it is NOT an exact blind test or proof of profitability. Its day
anchor is the first snapshot at/after 06:00 Bratislava, >=15 minutes pre-start.

Existing v18 historical ranking and raw/depth experiments now import frozen
research policy modules so this production change cannot silently rewrite their
baseline. No private data or performance report belongs in this public repo.

## Morning execution and verification

The existing external morning dispatch invokes `morning-refresh.yml`; its child
is `data.yml --ref main --mode refresh --morning_refresh true`, with betting-day
start 06:00 Europe/Bratislava. `data.yml` checks out the dispatched main revision.
`pipeline.py` calls `attach_market_sections_to_feed`, which calls the current
`select_market_sections`; frozen v18 research modules are not used for issuance.
No scheduler change or additional paid refresh is needed for this policy.

Before refresh/current-refresh, `verify_top_morning_policy.py` checks the active
backend metadata, UI contract, competition priority, probability ordering and
70% floor without provider calls. A mismatch stops the job before data work.

After the first new morning run, inspect the child run, saved candidate snapshot,
feed and publication receipts. Require policy `priority_tours_top_v19`, floor .70,
three picks or explicit shortfall, unique events, category priority, descending
probability within each category group, VALUE exclusivity, and pre-start evidence.
Check unchanged ACES/DF contracts. Do not rewrite already-issued picks to make
an older feed match the new policy. A shortfall is diagnostic, never permission
to relax the evidence requirements or invent odds/probabilities.

The next intended morning is 2026-11-09. The external dispatcher was observed on
2026-11-08 at 05:15 Bratislava; its future enabled state was not independently
read from the scheduler. Native GitHub scheduled runs are gated and were skipped.
The Nov 8 wrapper failed after a stale-code deployment handoff and publication
candidate mismatch (child 42450099227). Later deployment 42480094670 passed the
publication/readback checks. Do not claim the next scheduled run succeeded until
its actual feed and receipts have been checked.

Rollback: existing immutable `blinq-full-training-backup-42294330038-1` was reused;
serving model bytes and isolated restored predictions matched (difference zero).
No training, model promotion, CDB mutation, extra backups or provider calls were
performed for this policy rollout. A code rollback must preserve newer unrelated
changes and must not retroactively alter published betting contracts.


## 2026-11-11 — M15/M25 TOP evidence incident and scoped hold

Observed concern: published ITF M15/M25 Match Winner picks showed about 71%
BlinQ-adjusted probability despite long bookmaker odds. A single lost bet
is not evidence of model miscalibration; the active `data_depth` definition
was independently inspected and is **only** `min(player1.matches,
player2.matches, 50) / 50`. At 50 matches per player it becomes 100%,
even when pre-match serve/return, surface serve/return and rank information
is unavailable. It must not be described as broad data completeness
or empirically calibrated reliability.

Safety action for *future* selection only: ITF M15 and M25 tournaments
are held out of new TOP Match Winner issuance pending independent
point-in-time and settled-outcome calibration. Other ITF levels,
ATP/WTA, Challenger/WTA125 and the existing VALUE/PRIME/ACES
contracts are unchanged. TOP may contain fewer than three picks;
no replacement is fabricated and no original issued selection or result
is rewritten. The model, public probability formula and frozen trained
feature semantics stay unchanged.

Observability action: snapshot pre-match availability of paired serve/return,
surface serve/return, rank values and the historical match-count depth as
distinct fields, without claiming a new calibrated aggregate score.

**Remaining gate**: measure M15/M25 and ATP/WTA source availability,
pre-match field coverage and held-out reliability by probability band
(including 70–75%) against original quoted bookmaker implied probabilities.
Reassess re-entry only with enough independent settled observations.
Check relevant CI then first fresh real morning TOP snapshot and
publication read-back; a code merge is not deployment proof.
