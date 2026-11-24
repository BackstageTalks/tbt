# Prompt pre GPT – Esá s reálnymi hranicami Prop-Line (priorita 1)

Pracuj podľa AGENTS.md v BackstageTalks/tbt, vetva z main po zlúčení PR #1766. Nič nezapínaj bez môjho OK. Lokálny kurzový fallback, KPI a stĺpec KURZ NEMENIŤ.

## Cieľ
Každý deň 3–5 predikcií Esá O/U na REÁLNEJ hranici z Prop-Line (alebo RapidAPI), úspešnosť ≥ 75 %.

## Úlohy
1. Pokrytie (najprv, graf): za posledných 14 dní pre ATP/WTA 250+ a Challenger: počet zápasov / zápasov s `player_aces` hranicou (Prop-Line live, večerný 23:00 archív, RapidAPI tennisapi1) / počet kancelárií na zápas. Zisti, prečo 18.–19.11. Prop-Line takmer nič nevrátil (kvóta? matching mien? board?). Oprav príčinu.
2. Line-first výber: pre KAŽDÝ zápas s hranicou vyhodnoť OBOCH hráčov (`ace_selection._projection`) proti VŠETKÝM hraniciam a kanceláriam (`other_books` z PR #1766; klasické kancelárie pred PrizePicks/Underdog). Pravdepodobnosť z `_player_ou_probability`. Vyber max. 1 hranicu na zápas: p ≥ 0,60 a EV ≥ 0, potom podľa p. Prepínač `TBT_ACES_LINE_FIRST` + `_OWNER_APPROVED`, default OFF, `selection_tier=line_first`. Lokálny fallback ostáva pre zápasy BEZ reálnej hranice.
3. Kalibrácia na histórii (graf): hranice z `tbt-data/research/propline_closeout` + `propline-evening-odds` spárované s výsledkami es z CDB. Kriviek: predikovaná p vs skutočnosť po 5 p.b.; úspešnosť pri p ≥ 0,60 / 0,65 / 0,70; n; ATP a WTA zvlášť; chronologický split. Ak treba, izotonická kalibrácia (fit len na train časti).
4. Odporúčanie prahu: najnižšie p, pri ktorom test ≥ 75 % a ≥ 3 predikcie denne. Zapíš do `Claude/README.md`.
5. Výstup pre mňa: 3 grafy (pokrytie, kalibrácia, úspešnosť vs prah) + 1 veta odporúčania. Žiadny dlhý text.
