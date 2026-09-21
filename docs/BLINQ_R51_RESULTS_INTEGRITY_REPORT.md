# BlinQ 7.3.6 / 736-r51 — Results integrity & projection odds

## Why this release exists
Production review exposed three different issues that looked like one problem:

1. historical Match Winner rows could carry a stale display `selection` while the immutable `selection_id` used for settlement pointed at the other player;
2. provider termination detail such as `status.description = Retired` was discarded by compact history storage, so a later reconcile could grade a retirement as a normal loss;
3. Sets/Games/Aces/Double Faults mixed model confidence/projection values with the place where users expected a bookmaker price.

## Result identity
`selection_id` is now the authoritative Match Winner identity for both settlement and public display. The name in the prediction column and the highlighted player are both resolved from the same player ID. The old green check beside a player was removed and replaced by a neutral `TIP` marker; the opponent is visually de-emphasised.

Future publication candidates also canonicalise the selection name from `selection_id`, preventing a stale label from being frozen into the ledger.

## Retirement / incomplete match settlement
Compact provider history now preserves a tiny `_tbt_termination` marker for Retired, Walkover, Abandoned, Interrupted, Suspended, Postponed and Cancelled endings.

For older rows that already lost the provider text, settlement fails closed when a supposedly completed match has a winner but its structured set score proves that neither side reached the minimum number of sets required to win. Such rows are settled as VOID / SKREČ with 0.00u rather than WIN/LOSS.

The same void rule is applied to Match Winner and projection markets so partial Aces/Games/Sets counts from an abandoned match cannot be graded as a normal HIT/MISS.

## Results table contract
The mixed Results table now has explicit columns:

- Prediction
- Model / BlinQ %
- Odds
- Actual
- Result
- Units / Data Depth

This removes the ambiguous `BlinQ % / projection` and `Odds / actual` pairing.

## Projection odds policy
BlinQ never converts confidence percentages into odds.

A new strict provider-1 enrichment pass runs after the Aces/DF and Sets/Games models have selected their cards. It may attach a price only when an exact provider market is unambiguous:

- Sets/Games: complete two-sided match-total Over/Under market at one line;
- Aces/Double Faults: complete winner-style `Most Aces` / `Most Double Faults` market matching both players.

Player-total O/U Aces markets are deliberately not substituted for the current `which player records more` model. If the provider does not expose the exact matching market, the public odds field remains `—`; no synthetic price is invented.

When a real price is frozen, `price_status = priced_projection` and settlement records flat-1u units. Projection-only rows remain HIT/MISS analytics without betting ROI.

## UI cleanup
- INFO header state now follows the lighter LIVE visual language rather than rendering a separate glowing card.
- Predictions and Results typography received one additional readability step on desktop.
- Projection tabs now have a real Odds column in addition to Projection and Confidence.

## Verification
- repository contract: PASS
- frontend Node contracts: PASS
- focused r48-r51 / Results / projection tests: PASS
- broad Python suite (local environment): 729 passed, 1 skipped, 8 deselected because local `pyarrow` is unavailable
- Azure API smoke test is not runnable locally because `azure.functions` is unavailable; CI installs the project requirements.
