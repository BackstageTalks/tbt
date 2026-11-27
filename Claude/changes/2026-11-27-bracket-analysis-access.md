# Bracket: Analysis access per level + data quality label (owner 27.11, Codex report 32 part)
- Admin → Zobrazenie → Prístupy: new switch "Analýza v pavúku" per level (dashboard.bracket_analysis.plans). Without it, Comparator rules apply (old behaviour).
- Server: /v1/brackets returns analysis_allowed; /v1/comparator/compare?context=bracket checks bracket_analysis rules (403 bracket_analysis_access_required). Standalone Comparator unchanged.
- Comparator card: "Kvalita dát: vysoká/stredná/nízka · N1 / N2 zápasov · povrch S1 / S2" (was "Dobrá/Čiastočná/Obmedzená vzorka"). Same thresholds (25/10, 10/4).
Not yet: verified tour/surface/format auto-context, frozen pre-match bracket predictions and tournament hit rate (report 32 P1/P2) - follow-up PR.
Revert: revert this PR.
