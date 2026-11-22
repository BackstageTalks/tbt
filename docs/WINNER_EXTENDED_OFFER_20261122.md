# Match Winner expanded competitions — 22 November 2026

## Goal and approved policy
The owner explicitly requested immediate Match Winner processing for ATP Challenger
50/75/100/125/175, WTA 125 and Davis Cup/Billie Jean King Cup **singles**,
in addition to existing ATP/WTA 250+, without a shadow-only delay.

TOP: model p >= 0.65, real before-start winner odds >= 1.50, depth >= 0.50,
>= 5 surface matches per player, max 5/day and priority ATP/WTA 250+ before
new categories. Value: model p >= 0.60, odds > 1.80, 15% symmetric two-way
price difference, depth >= 0.50, >= 3 surface matches/player.
No forced picks, no fabricated prices, and no probability recalibration.

## Minimal scope
- Extend only `RapidTennisClient.matches_for_day` discovery with an explicit
  `is_match_winner_offer_scope` predicate and national cup tour mapping.
- Keep historical stats gapfill `match_is_250_plus`, doubles discovery and
  ESÁ/Viac Es 250+ restrictions unchanged.
- Allow these recognized categories through existing TOP qualification.
- Preserve top-first competition priority (ATP/WTA 250+, then lower tiers),
  and preserve ACCA's main tour restriction.
- Preserve VALUE selection priority, all source identity checks, time gates,
  published earlier days, champion weights and shared RapidAPI budget.

## Checks and gates
1. Exact-HEAD CI, market/provider/preflight/league regression tests.
2. Independent Git source read-back, CI results, then guarded main deployment.
3. Next authentic 06:00 Bratislava refresh: capture discovered per category,
   priced vs unpriced, rejected reasons and actual new TOP/Value receipts.
4. Check provider native event categories/names and that CUP entries are
   individual players, not national-team ties; quarantine ambiguous identities.
5. Verify date-stamped live feed and stable existing Results from Azure.

Do not claim newly issued picks, API gain, model performance, or CDB mutation
from code-only tests. Restore previous scope via reverting this isolated PR if
new provider categories introduce degraded identity, wrong market or quota strain.
