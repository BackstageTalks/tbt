# TOP production policy and morning runbook

Pending deployment policy: `priority_tours_top_v20` — ATP/WTA >=65%, then
Challenger >=65%, and only ITF women W35+ with point-in-time paired S/R and
surface S/R available, model probability strictly >65%, and odds <=1.70;
all male ITF and unknown-level ITF excluded.
Earlier v19 was the 70%-all-groups policy.

VERIFIED deployment: PR #1459, commit `f4e0eda72dd5c6a5065c0df93a3428250b8c5ed6`,
[successful checks and deployment](https://github.com/BackstageTalks/tbt/actions/runs/42480094670).
Independent production deployment.json and ui-config.json readback matched this commit and policy on 2026-11-08.

Updated 2026-11-11 per owner: aim for three TOP selections with ATP/WTA >=65%
first. Fallback to Challenger >=65%, then women ITF W35+ strictly >65%
and decimal odds <=1.70 **only** when both players have verified pre-match
overall and surface serve/return.
This is a selection-tier policy, NOT new probability calibration. The existing
three-slot output remains; there is no new TOP1/TOP3 product.

- Within ATP/WTA, rank all candidates >=65% by probability; model/market
  agreement only breaks ties, never certifies the public confidence.
- If fewer than 3, next Challenger >=65%, then ITF women W35+ strictly >65%
  at verified odds <=1.70, with point-in-time serve/return AND surface
  serve/return known for both.
  All men's ITF (including M15/M25/M50/M100), W15/W25, ambiguous ITF,
  WTA125, UTR, unknown and unsupported competitions do not enter TOP.
- Existing M15/M25 and extreme ITF model/market outsider guards remain.
- Never drop any approved competition below 65%; maintain depth >=80%,
  at least five prior surface matches per player, exact paired pre-match quotes
  and coherent probability evidence. No backup can bypass these gates.
- Model/market agreement is a ranking heuristic, NOT a calibrated hit-rate claim.
- TOP decimal odds >=1.50 for ATP/WTA and Challenger, no new upper limit;
  ITF TOP is restricted to inclusive decimal odds 1.50–1.70.
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

Before refresh/current-refresh, `verify_top_morning_policy.py` checks active
backend/UI v20, ATP/WTA >=65%, Challenger >=65%, then verified W35+ >65%
with decimal odds <=1.70,
price/quality thresholds and target three without any provider call.
A mismatch stops the job before data work.

After the first new morning run, inspect child run, saved candidate snapshot,
feed and publication receipts. Require policy `priority_tours_top_v20`, ATP/WTA
>=65%, Challenger >=65%, and ITF W35+ >65% at odds <=1.70 only with
verified S/R, three picks
or explicit shortfall,
unique events, category priority, probability ordering within each tier,
VALUE exclusivity, and exact pre-start evidence.
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


## 2026-11-11 — final conservative TOP fallback scope

Owner requested ATP/WTA >=65% first with cautious lower-tier fallback, and
raised an explicit concern that men's ITF M-level data cannot be independently
validated. Decision implemented in PR #1564: Challenger >=65% second; only
women's ITF W35/W50/W60/W75/W80/W100 strictly >65% last, with
verified decimal odds <=1.70, requiring BOTH paired
pre-match overall and surface serve/return evidence flags. Absence of a flag,
false or ambiguous grade fails closed. All male ITF (not only M15/M25) and
women ITF W15/W25 remain out of TOP; other products and issued results remain.

This is an evidence *availability* gate, not empirical calibration. v7.2.1
model probability is unchanged; count-only depth cannot establish real hit rate.
Read-only exact-issued model audit of 2026-11-11 had 43 settled TOP bets,
27 wins, 62.8% hit rate vs 76.6% mean declared probability; 51/51 historical
issued TOP had unverified PIT S/R feature flags. See
https://github.com/BackstageTalks/tbt/actions/runs/43093112425 .
These historical data do not prove that the 65% policy is calibrated or
profitable. Reassessment requires disjoint future point-in-time samples.

Rollout gate: full CI including browser, merge, deploy + SHA read-back, then
first actual next morning issuer ledger/serving comparison. Preserve external
cron, old immutable picks and all other GitHub collaborators' commits.


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


## 2026-11-11 — final ITF price boundary clarification

Owner clarified the **third and final fallback**, used only when ATP/WTA
and then Challenger supply fewer than three qualifying TOP matches:
ITF only with **verified decimal winner odds <=1.70 (inclusive)** and
**published model probability strictly >65%**. The original ITF fail-closed
pre-match evidence gates (only women W35+ with both serve/return feature
flags), men's ITF exclusions, M15/M25 holds, price-integrity check,
minimum overall odds 1.50, depth >=0.80 and 5 surface matches per player
remain active. ATP/WTA and Challenger may still enter TOP at exactly 65%
and retain their original upper-odds policy. No forced fill, no backdated
Results/ledger updates and no CDB/champion/cron change. Current confidence
is not automatically re-calibrated by this selection change.

Regression tests explicitly cover ITF odds=1.70 eligible, >1.70 rejected,
probability 65% excluded and >65% eligible, main-tour/Challenger unaffected,
and the morning zero-paid-request preflight checks the same boundaries.
