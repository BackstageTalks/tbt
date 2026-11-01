# ACES: locally statistically grounded odds

- The currently approved **1.60–1.80 range** is based on local statistical analysis. Its published numbers are **local statistical working odds, not placeholders**.
- The individual two-decimal value within this range is selected deterministically from the frozen event and selection identifiers (FNV-1a compatible between Python and JavaScript). Do not claim that the exact per-pick cent value is separately model-calibrated or a bookmaker quotation.
- The explicit provenance marker is `local_aces_statistical_v1` (`price_basis` in Telegram receipts); web presentation uses `statistical_ace_odds`. These are separate from source API odds.
- Historic raw odds of exactly 2.00 in the ACES feed are treated as **unverified source values** by the current policy, even if older feed metadata labels them as provider prices. This description applies to the raw **2.00**, not to the local **1.60–1.80** prices.
- The present code preserves genuinely verified non-2.00 bookmaker odds when the provider, market line and capture evidence pass validation. Provider-price evidence and local statistical estimates must remain distinguishable; a future change to their priority requires a separate policy decision.
- Do not overwrite the source price, immutable issuance ledger, CDB, model predictions or already frozen Telegram receipts. Do not present historical illustrations as bettable quotes.
- Keep site, Telegram and result presentation aligned on event + frozen selection identity. Validate future betting days, the range, source retention, price precedence, and a production JS readback before calling a change deployed.

## Player Aces UNDER — offered-line safety buffer

For **future** player-Aces UNDER selections only, require the actual offered bookmaker line to exceed the unchanged count projection by at least **1.0 ace** for projections below 4; **1.5 aces** for projections 4–8 inclusive; **2.0 aces** above 8. Prefer **2.0 / 2.0 / 3.0 aces** respectively only where the real quoted price passes the existing modeled-probability and nonnegative-EV checks. No offered, qualifying line means no UNDER selection; do not invent lines or change the projection.

This is separate from the 1.60–1.80 locally statistically grounded *display price* policy above. The line and EV selection require real provider odds; synthetic/local prices never establish a bettable market. Existing historical publications are immutable. Other markets and ACES OVER/superiority are unaffected.

Introduced by [PR #1174](https://github.com/BackstageTalks/tbt/pull/1174), with regression tests and a read-only historical filter audit. The historical filter test cannot infer the prices of alternative lines that were not actually issued.
