# ACES/DF: retry older matches, VOID after 7 days (owner 27.11)
- Pending ACES/DF bets whose match is missing from history: morning run re-reads that bet's own day (max 10 days, last 21 days, ATP+WTA, in-memory, canonical history read-only).
- Still not found 7 days after start -> VOID "match_not_found_7d"; found but Aces/DF stats still unavailable after 7 days -> VOID "stats_unavailable_7d". VOID = 0 units, same shape as existing engine voids.
- Diagnostic: ready-but-excluded bets log their excluded_reason (8 seen 26-27.11).
Revert: revert this PR (voids already written stay in ledger; re-settle possible if the match appears).
