# ACES/DF settlement finds matches again (2026-11-26)
Morning logs 24-25.11: 34-35 pending ace/DF events "missing_match", 0 stats calls.
Cause (Codex report 23): ledger key is the provider event id, lookup used internal match_id only.
Fix in scripts/pipeline.py _enrich_pending_ace_df_settlement_stats: index by engine.event_id (same key as reconcile_ledger) + match_id; require same player pair; >1 candidate = ambiguous_match (never guessed).
Tests: tests/test_ace_settlement_event_id_20261126.py. Revert: revert this PR.
