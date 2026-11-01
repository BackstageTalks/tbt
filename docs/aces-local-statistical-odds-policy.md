# ACES: locally statistically grounded odds

- The currently approved **1.60–1.80 range** is based on local statistical analysis. Its published numbers are **local statistical working odds, not placeholders**.
- The individual two-decimal value within this range is selected deterministically from the frozen event and selection identifiers (FNV-1a compatible between Python and JavaScript). Do not claim that the exact per-pick cent value is separately model-calibrated or a bookmaker quotation.
- The explicit provenance marker is `local_aces_statistical_v1` (`price_basis` in Telegram receipts); web presentation uses `statistical_ace_odds`. These are separate from source API odds.
- Historic raw odds of exactly 2.00 in the ACES feed are treated as **unverified source values** by the current policy, even if older feed metadata labels them as provider prices. This description applies to the raw **2.00**, not to the local **1.60–1.80** prices.
- The present code preserves genuinely verified non-2.00 bookmaker odds when the provider, market line and capture evidence pass validation. Provider-price evidence and local statistical estimates must remain distinguishable; a future change to their priority requires a separate policy decision.
- Do not overwrite the source price, immutable issuance ledger, CDB, model predictions or already frozen Telegram receipts. Do not present historical illustrations as bettable quotes.
- Keep site, Telegram and result presentation aligned on event + frozen selection identity. Validate future betting days, the range, source retention, price precedence, and a production JS readback before calling a change deployed.
