# ACES/DF settlement: ignore conflicts in unrelated stats (2026-11-26)
26.11 rerun: 9 pending bets errored "Conflicting whole-match statistic: p*_service_points_won".
- parse_statistics(only_fields=...) settlement mode: conflict outside the needed fields drops that field; conflict in aces/DF still fails closed. Default behaviour (only_fields=None) unchanged.
- pipeline settlement uses only_fields={aces/DF}; logs first 5 missing_match with history vs ledger player ids (12 left on 26.11).
Revert: revert this PR.
