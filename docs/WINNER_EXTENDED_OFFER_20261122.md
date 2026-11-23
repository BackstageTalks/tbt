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

## ITF M15+/W15+ seasonal extension (owner request 2026-11-22)
- Allow source-native ITF Men (785) and ITF Women (213) **prospective singles** discovery.
- At the event gate require explicit, gender-consistent M15+ / W15+ grade; unknown, under-15, junior, doubles, UTR and contradictory grade labels fail closed.
- Preserve the exact verified grade on the normalized prospective Match Winner fixture so the TOP selector can classify it, even when the provider's general tournament rank says only ITF.
- ITF is third priority **after** existing ATP/WTA main tour and Challenger/WTA125/team cups, with standard TOP probability, data-depth, surface and real pre-start odds checks. VALUE uses its existing standard gates and exclusive priority. No forced picks, special ITF odds ceiling, dedicated ITF probability floor, or changes to ACCA.
- Keep historical Tennis API data downloads, CDB gapfills, doubles, ESÁ/Viac Es, champion, API budget, provider safety and already issued receipts unchanged.
- Current baseline is 60% public probability and 30% minimum data depth. The opt-in candidate TBT_ITF_TOP_DEPTH_MODE=sqrt_v1 changes only the graded ITF TOP depth adjustment. It retains sqrt(depth) of the raw advantage over 0.5. At depth 0.30 the raw requirement for 0.60 becomes 68.26%. Candidate scoring is experimental pending independent chronological evaluation. Unset the variable to restore linear scoring. No model promotion.
- Read-only PR replay uses the first archived snapshot after 06:00 Bratislava for each day, independently timed quotes and exact player/event joins. Report sample size and unresolved outcomes before interpreting hit rate.
- An interrupted admission to the Admin training or Lab queue leaves its durable admission row for inspection. Recover only after verifying the owning request has ended and reconciling its durable queue row. Routine completion releases it.
