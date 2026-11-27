# ACES/DF: stop counting never-settleable rows as pending; reconcile older ready bets (27.11)
Codex report 30: of 8 "ready but unsettled", 7 are projection-only rows without O/U contract (unknown_price_contract) and 1 issued after start. Engine already excludes them (not in KPI); they were only inflating the pending count.
- Pending list skips terminal exclusions (unknown_price_contract, issued_after_actual_start, invalid_*).
- current_only settlement also reconciles pending ACES/DF bets 14-30 days old, only exact unique completed ready matches.
KPI math unchanged. Revert: revert this PR.
