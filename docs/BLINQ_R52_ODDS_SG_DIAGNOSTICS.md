# BlinQ 7.3.6 r52 — projection odds + SG diagnostics

## Why SG reported 19,509 `provider_error`

The mega-data run processed 22,203 S/G candidates but issued only 2,660 provider requests. In r51, `ScoreEnricher` raised the same generic `ProviderError` both for genuine provider/network failures and for a successful/cached event detail whose player IDs did not match the historical row. Because cached event details do not consume a new provider request, the very large gap between `provider_error` count and request count shows that identity mismatches dominated the generic bucket.

r52 changes the contract:

- event/player identity mismatch is persisted fail-closed as `_tbt_score.status = identity_mismatch`;
- the expected and observed player IDs are stored under `_tbt_event_identity`;
- recent mismatches return `cached_identity_mismatch` on later runs instead of being reported as a provider/API failure again;
- genuine provider errors are split into 429, HTTP 4xx, transport/5xx and other buckets.

No identity mismatch is accepted as valid score data.

## Projection odds

r51 already introduced strict exact-market price attachment, but the Total Games provider line was not read from `choiceGroup`. The provider contract states that `choiceGroup` carries the Total Games line. r52 adds `choiceGroup` / `choice_group` to line parsing.

This enables a real provider market such as:

- Total games won
- Over / Under
- choiceGroup = 20.5
- real decimal price

to attach to a Games projection without modifying the model projection itself.

r52 also records `observed_market_names_top40` and per-market `unpriced_reasons` in the projection odds report. This is especially important for Sets, Aces and Double Faults, where the current provider contract does not guarantee the exact market required by the model.

Rules remain fail-closed:

- Games/ Sets require an exact match-total O/U market;
- Aces / Double Faults require the exact player-superiority market matching the current model selection;
- a different player total, line or market is never substituted;
- confidence is never converted into synthetic odds.

## Historical Results

Legacy projection publications that were issued without a captured provider price cannot be safely repriced after the match. r52 therefore renders missing or invalid projection odds as `—`, never `0.00`.

New projection publications can carry real odds when the exact provider market exists at publication time. Their settlement can then calculate real flat-1u units.
