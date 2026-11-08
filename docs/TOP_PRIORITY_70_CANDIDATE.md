# TOP priority / 70% floor candidate

PREPARED, not deployed. Based on main `958019b1ebcc739487ba4a39a632978c6cafc3ff`
after PR #1454; do not overwrite concurrent ACES, Telegram or admin work.

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
- ACES/DF, including existing random ACES prices 1.6–1.8, are unchanged.
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

Before promotion: review same-period availability and results, pass CI at the
exact commit, verify the applicable rollback under AGENTS.md, then independently
read the new morning feed and publication receipts. Check three-pick/shortfall
counts, tier order, VALUE exclusivity, actual timestamps and unchanged ACES.
Do not describe a green test, commit or merge as a verified deployment.
