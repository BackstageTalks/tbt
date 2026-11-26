# Hotfix: morning offer crash "Top odds floor invariant failed" (2026-11-26)
Thin slate -> owner rule TOP 1.40-1.49 fill (#1804) added cards, final invariant still demanded >=1.50 -> pipeline crashed, no offer.
Invariant now exempts only selection_tier=low_odds_fill cards at/above the fill floor. Selection logic unchanged.
Revert: revert this PR.
