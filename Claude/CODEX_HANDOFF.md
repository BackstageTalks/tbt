# Spolupráca Claude ↔ Codex

Cieľ: nebiť sa v práci, nič nerobiť dvakrát.

## Roly
- **Codex** – čítanie, audit, merania, reporty. Žiadne PR, žiadne zápisy do CDB, žiadne volania providerov.
  Výstup: `outputs/NN-nazov.md` (číslovanie pokračuje), každý nález s `cesta:riadok`.
- **Claude** – implementácia, PR, testy, nasadenie. Číta reporty z `outputs/`, opravy robí po malých PR overených testami a `tools/visual_baseline.py`.
- **Vlastník** – schvaľuje zlúčenie (`ok <číslo PR>`) a väčšie zmeny. Princíp výpočtov BlinQ % a KPI sa nemení bez dohody.

## Pravidlá
1. Codex nemení súbory, na ktorých práve beží otvorený PR od Claude (zoznam: `gh pr list --author @me`).
2. Report uvádza revíziu (commit SHA), z ktorej vychádza; Claude pred opravou overí, či sa medzitým nezmenila.
3. Každý report končí sekciou **Navrhované kroky** zoradenou podľa priority (P1–P3), aby sa dali priamo zmeniť na PR.
4. Hotové reporty Claude označí v tomto súbore v sekcii Stav.

## Stav
| Report | Téma | Stav |
|---|---|---|
| 01 | Audit adminu | spracované: PR #1834, #1840; zvyšok v zjednotení adminu |
| 02 | Pamäť ranného behu | spracované: PR #1839 |
| 03 | Mŕtve CSS (69 kB) | čaká – po zjednotení adminu |
| 04 | Mapa adminu pre zjednotenie | zadané 25.11. |
| 05 | Písmo a kontrast v admine | zadané 25.11. |
| 06 | Spoľahlivosť denných behov | zadané 25.11. |
