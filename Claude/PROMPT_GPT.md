# Prompt pre GPT/Codex – BlinQ (stav 22.11.2026)

> **Novšie záväzné rozhodnutie majiteľa (22.11.2026):** celý podbod 5 týkajúci sa ROI/yieldu, premenovania `KURZ` a pevného 30-dňového KPI obdobia je ZRUŠENÝ; zachovať pôvodný stav. Oprava horizontálneho mobilného posunu zostáva v rozsahu. Nižší pôvodný text je historický, nie pokyn na realizáciu týchto troch zmien.

Pracuj v BackstageTalks/tbt podľa AGENTS.md. Nič nezapínaj v produkcii bez môjho OK. Každý krok: test, PR, stav podľa AGENTS.md (PREPARED/VERIFIED…).

## 1. Zlúčenie PR #1766 (Claude) – PRVÉ
- Over CI na PR #1766 (fix/blinq-audit-opravy). Ak zelené, pripravím merge ja.
- Po merge over: CI „Test and deploy“ na main zelené, watchdog „production UI revision“ prestane padať, issue #1765 uzavri až po read-back servovaného UI (app.js/index.html hash = main).

## 2. Esá: hranice z Prop-Line → model ich vyhodnotí (priorita)
Cieľ: každá ponúknutá hranica es (player_aces O/U) dostane modelovú pravdepodobnosť; publikujeme len p ≥ 0,60 a EV ≥ 0; nikdy nevymyslená hranica, ak reálna existuje.
a) „Line-first“: dnes sa hranica hľadá len pre hráča vybraného ako „Viac es“ (gap ≥ 0,85). Uprav `ace_selection.select_ace_picks` + `projection_odds.enrich_projection_odds` tak, aby sa pre KAŽDÝ zápas s Prop-Line `player_aces` trhom vyhodnotili OBA hráči (projekcia z `_projection`) proti VŠETKÝM ponúkaným hraniciam a kanceláriam (`other_books` už existuje po PR #1766). Vyber max. 1 najlepšiu (EV, potom p) na zápas. Za prepínačom `TBT_ACES_LINE_FIRST` + `_OWNER_APPROVED`, default OFF. Výstup označ `selection_tier=line_first`.
b) Kalibrácia: pravdepodobnosť O/U z `_player_ou_probability` over na histórii (CDB: zápasy s esami + Prop-Line closeout/večerný archív `tbt-data/research/propline_closeout`, `propline-evening-odds`). Report: Brier, log loss, spoľahlivostná krivka po 5 p.b., n. Ak nekalibrovaná → izotonická kalibrácia na chronologickom splite. Publikuj len ak kalibrovaná p na teste ≥ 0,60 dáva úspešnosť ≥ 75 % (min. 150 testovacích hraníc, ATP a WTA zvlášť).
c) Pokrytie: zmeraj za posledných 14 dní: koľko zápasov ATP/WTA 250+ malo player_aces hranicu (Prop-Line live, večerný 23:00 archív, RapidAPI tennisapi1). Zisti, či RapidAPI tennisapi1 vracia player aces O/U (1 read-only volanie na 3 zápasy). Ak má, daj ho ako primárny zdroj.
d) Zapni (po mojom OK) `TBT_ACES_REAL_LINE_STRICT=true`.

## 3. TOP a Value
- Zapni postupne (po mojom OK, každé 7 dní, potom porovnanie na výsledkoch): `TBT_RANK_SOURCE=market_anchored` → `TBT_TOP_REQUIRE_MARKET_SIDE=true` → `TBT_TOP_MIN_PICKS=5` + `TBT_TOP_EMERGENCY_FILL=true`.
- Replay report: pre kurzové pásma TOP 1,30–1,40 / 1,40–1,50 / 1,50–1,65 / 1,65–1,80 úspešnosť pri poradí podľa trhu, top 3 a top 5 za deň (vlastné výsledky + historické ATP kurzy oddstrader). Rozhodnutie o definícii TOP je moje.
- Value: rovnaký report pre kurz 1,70–1,80 a > 1,80 s rozdielom kurzov ≤ 15 %. Bez novej logiky, len čísla.

## 4. Viac es
- Po mojom OK `TBT_ACES_MIN_GAP=1.3`. Po 14 dňoch report: úspešnosť top 3/5 za deň vs. predtým.

## 5. KPI na webe (len po mojom OK)
- ROI a yield počítaj len z reálnych bookmaker kurzov (vyraď `local_ace_result_odds` a `price_status=projection_only`). Úspešnosť zo všetkého.
- Pri modelových predikciách stĺpec „KURZ“ → „orient. kurz“.
- KPI za pevné obdobie (30 dní) namiesto `auto` maxima.
- Mobil: posledná záložka (Dvojchyby) je orezaná – oprav horizontálny scroll/fade.

## 6. Prevádzkové chyby (po kroku 1–2)
- `admin-training-worker`: občasný `TimeoutError` pri GitHub API → retry 3× s backoff.
- `Prediction fixture schedule and match status`: 503 pri dispatch gapfill → retry + jasná chyba.
- `PropLine evening odds archive`: padá na assertoch reportu (schema/target_betting_day/…) – zisti, ktorý assert a oprav.
- `Telegram vs website parity`: padá na `assert req=={…}` – oprav alebo uprav test, ak sa zmenil kontrakt.
- `cdb-drive-inbox.yml`: 6 zlyhaní – diagnostika.
- Node 20 deprecation: aktualizuj actions/checkout@v5, setup-python@v6.

## 7. Bezpečnosť (ja)
- Zruš PAT vložený v chate. Zmaž nepoužité secrets: `ADMIN_UID`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.
- Rotácia hesla záloh, potom odstrániť `backup/CDB_OFFSITE_ZIP_PASSWORD_*.txt` z histórie tbt-data.

Poznámky ku všetkým zmenám zapisuj do `Claude/README.md` (tabuľka Zmeny).
