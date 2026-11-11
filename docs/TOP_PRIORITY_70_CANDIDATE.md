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


## 2026-11-11 — severe market-outsider TOP safeguard (follow-up)

The same-day immutable 2026-11-11 issued TOP contained ITF M15/M25
long-shot selections (e.g. 71.8% public BlinQ vs decimal 2.50/2.70).
The earlier M15/M25 TOP-only hold was merged after the morning publication;
do not rewrite that publication or its Results.

This incremental **ITF TOP-only** precaution holds a *new* selection when
the bookmaker's verified two-way, no-vig implied probability for that player
is < 50%, while the displayed model probability is over 25 percentage
points higher. This is an explicitly provisional review threshold,
**not** independently calibrated, an automatic loser prediction, an
odds ceiling, or a revision of public model probabilities. An odds-2.20
pick remains eligible if the opposing price indicates the same player is
the bookmaker favorite. For example, 71.8% vs a no-vig 37–40% is held;
71.8% vs a no-vig 62% is not.

ATP/WTA, Challenger/WTA 125 market-selection eligibility is unchanged by this
ITF-specific hold. The full original ATP/WTA high-priced TOP contract remains.

No change to absolute TOP floor (70%), 3-pick target (unfilled slots
are permitted), tier priority, VALUE assignment, PRIME, ACES, CDB,
trained champion, historical ledger, published forecasts, or pricing.
The existing reason/audit system records the rejection reason
`top_unverified_market_outsider_conflict`. Reconsider this hold only after
an independent forward/held-out, point-in-time, price-banded calibration
with meaningful sample sizes; a single day's outcomes are insufficient.

Independent replay run
https://github.com/BackstageTalks/tbt/actions/runs/43080096941
reported **historical frozen selector simulations** for an older/newer
model: original snapshot TOP hit rates 25/56 (44.64%) and 22/46
(47.83%), respectively, on settled matched candidates. These are
**not current-v19 issued bets**, are not an outcome-matched post-change
counterfactual, and do not establish a 25pp cutoff's effectiveness.
The same replay states pre-match serve/return/rank freshness was not
available in older frozen snapshot schema.

Deployment gate: run relevant tests plus main CI, then verify the first
new morning `data.yml` run, generated candidate rejection counts,
immutable issuance and live serving read-back. This change cannot be
claimed deployed merely because a PR or merge succeeded.


## 2026-11-11 — match-count semantics and exact-issuance audit completion

Evidence: `data_depth` is a capped historical match-count factor, not
a quality-completeness or observed success probability. Existing public
winner detail calls high match counts "High data coverage" despite possibly
missing paired serve/return. This patch does **not** change the champion,
its probability, the TOP >=70% threshold, issued tip identities or CDB.
It relabels that existing display slot to actual historical match counts
and presents paired serve/return status only if feature evidence is
explicitly saved. Unknown legacy snapshots remain **unverified**.

Read-only issued TOP/VALUE audit now reports separately:
- genuine ITF M15/M25/W35/etc grade vs main tours (no male ATP alias);
- pre-match paired serve/return existence, with a separate unverified cohort;
- a >25-percentage-point model-market outsider difference using the exact
  confirmed two-way pre-issuance bookmaker quote;
- published 70–75% confidence cohort for the currently serving model.

Audit outputs are subgroup aggregates; no per-person/selection leakage.
A model-version-only matched issued audit is **not** model recalibration:
low cohort sizes, old archived rows without provenance, censoring and
the new-day forward check still limit conclusions. The production model
must not be retrained, re-calibrated or promoted from historic summary alone.

Pre-existing M15/M25 TOP hold and ITF extreme market disagreement guard
stay active. Next gate: first 2026-11-12 normal morning release,
candidate read-back and actual issued/success cohort including point-in-time
serve/return coverage. Only then revisit a further quality gate based on
measured capacity; never backfill published records.

Rollback: revert only descriptive display and read-only audit code, not
ongoing external data runs or historical offer decisions.
