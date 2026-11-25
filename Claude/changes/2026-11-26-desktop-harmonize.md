# Desktop home harmonization (2026-11-26)
New final layer web/blinq-desktop.css (media min-width:901px, not admin), linked last in index.html.
- KPI cards + Daily Hub panel: green glass (same as Telegram panel), was bluish-grey gradient #0b181e/#08151a.
- Type floor: table th 11px (was 6.1-10px), td 12px (was 9.3-11.8px), meta labels 11px (PREDIKCIA/KURZ was 6.6px, tournament meta 8.5px).
- Time cell: time over date (was truncated "28.0..."); tournament meta one line with ellipsis.
No existing rule edited; full original values in Codex report 20. KPI math and day switching untouched.
Revert: delete web/blinq-desktop.css and its <link> in index.html.
