# BlinQ TOP rank-three morning selector — decision and runbook (2026-11-08)

## Goal and accepted product boundaries
Replace the inaccurate 80/78/75/70% count-based morning selector with one
deterministic ranking of the **whole existing priced Match Winner board**.
The output remains ONLY `top_daily_picks` in the existing TOP section.
TOP1/TOP3 are ranking positions, not new categories, tabs, public feed fields,
price contracts or Telegram offers. Aim for 3 real picks per betting day;
do not invent picks if fewer than 3 authentic qualified prices exist.

- Keep real decimal odds >=1.50, **no upper odds limit**.
- VALUE **unchanged**, with exclusive assignment priority before TOP,
  odds >=1.80 and symmetric two-way price difference <=15%.
- PRIME, ACES/DF (including local random ACES odds 1.6–1.8), S/G,
  doubles, LIVE, model/champion and CDB are unchanged.
- Do not reprice, backdate or regrade any existing issued bet or freeze.
- No extra provider passes, new writer, cron, job, budget or UI element.

## Implementation
- Existing morning-refresh workflow dispatches data.yml mode=refresh, which
  runs scripts/pipeline.py, which already invokes the shared
  `select_market_sections` in both `annotate_market_publication_candidates`
  and `attach_market_sections_to_feed`. This change lives in that selector.
- Pre-price discovery must include the new TOP floor (BlinQ-adjusted p>=0.60)
  and uses the **existing** quota guard and fallback. No extra API consumer.
- Core TOP requires p>=.60 (the evidence-adjusted BlinQ display p),
  depth>=.80, at least 5 point-in-time surface matches for **each** player,
  and authentic pre-start Match Winner odds>=1.50.
- Rank by harmonic agreement of BlinQ's adjusted probability with original
  same-source, two-way de-vigged bookmaker probability; depth/samples only
  break ties. This deterministic heuristic is **NOT** proven calibration.
- Pick **3 highest-ranked** candidates; if fewer than 3 core picks exist,
  top up only from independently qualified p>=.60, depth>=.75, surface>=3.
  Never bypass pre-start, event/selection identity or price-integrity guards.
  A genuinely unpriced/unsupported slate may yield fewer than 3 and records
  a `top_daily_shortfall`; no fabricated bet or invalid public offer.
- Exclude all VALUE-qualified identities first. No proposed upper odds cap.
  Existing section assignment and immutable publication lifecycle remain.

## Evidence (frozen candidates, NOT public issued bets)
Read-only Actions: https://github.com/BackstageTalks/tbt/actions/runs/42424176800
On 12 available historical 7.2.1 betting days:
- Original snapshot TOP: 43 candidates, 33 settled; 16W/17L,
  hypothetical 1u ROI -20.47%.
- Ranked TOP1 internal: 12 candidates, 9 settled; 7W/2L,
  hypothetical ROI +20.63% (very small cohort).
- Ranked TOP3: 36 candidates (3/day), 26 settled; 14W/12L,
  hypothetical ROI -16.05%; 10 not settled or unmatched.
- Ranked TOP5 research ONLY: 60 candidates, 42 settled; 17W/25L,
  hypothetical ROI -36.71%; consequently do **not** publish five.
- Caution: source daily snapshot quote discovery had >=.65 discovery floor,
  so the historic TOP3 replay has different offer coverage from the new
  >=.60 morning price discovery. This is a **descriptive, unequal-denominator
  historical test, not proof of prospective better hit rate or ROI**.

## Acceptance / rollback
1. Relevant full CI and read-only replay succeed at exact head SHA;
   validate no new public offer categories, VALUE/ACES unchanged, valid
   quote timestamps, morning feed/pending publication identity consistency.
2. Merge into main only after CI; ensure morning job picks up the main SHA;
   no separate paid refresh dispatch to "test" a selector.
3. Independently read the exact next real deployed morning feed and immutable
   issued TOP records. Verify TOP1/3 identity, same betting day, no duplicate,
   odds>=1.50, source timestamps pre-start, no missing VALUE/ACES,
   compare to morning pipeline counts and snapshot CAS.
4. If actual output violates identity, price, published-snapshot stability,
   exclusivity, or breaks morning refresh, halt further mutation and revert
   only this change without overriding concurrent legitimate main work.
5. Monitoring success metrics: daily TOP eligible/input/published, number
   of real quotes, invalid/rejected counts, settled W/L/void,
   average odds, hypothetical ROI vs actual issued ROI, comparison with
   prior production on matched dates. Any outperformance claim requires a
   later independent sample; green CI alone is not that proof.

## Status
Implementation on isolated production-target branch via PR #1454:
https://github.com/BackstageTalks/tbt/pull/1454
Draft research-only PR #1452 is **not** the route to production.
No CDB mutation and no fabricated public bets. Merge, deployment and next
morning read-back must have separate evidence before marked complete.
