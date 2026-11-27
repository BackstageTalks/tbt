# Bracket: verified match context + frozen predictions + 🎯 tournament stats (Codex patches 39+40)
- analysis_context (tour/surface/best_of) only from exact event ID + player pair + edition match; else old fallback.
- Results worker freezes one pre-start winner prediction per bracket match in the bracket snapshot (not CDB); hit rate counts only pre-start, decided matches (walkover/unfinished/changed pair excluded).
- tournament_stats = extensible server sections; 🎯 badge bottom-right of tournament card, green-glass popup (×, outside click, Esc; mobile bottom sheet). Access via dashboard.bracket_analysis. 0 new API calls.
Revert: revert this PR.
