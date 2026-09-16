# BlinQ UI/code audit — 6.5.53

## Root causes found

1. **The previous “final” stylesheet did not actually own the cascade.** `premium.css` contains selectors such as `body#blinqPremium#blinqPremium ... !important`. The late `final-ui.css` used only one ID, so many of its rules lost even though it was loaded later and also used `!important`.
2. **The hero override targeted the wrong DOM class.** Runtime markup is `.dashboard-hero-copy`; the previous late override styled `.hero-copy`. That made the biggest visual block look unchanged.
3. **The desktop responsive breakpoint was too aggressive.** At widths around 1200–1260 px, older responsive rules rearranged the search/header before the intended mobile breakpoint.
4. **Player identity was rendered as one text string.** Flag/rank/tour could not be styled reliably. 6.5.53 renders them as separate semantic spans.
5. **The legacy CSS stack is very large and repetitive.** `styles.css`, `responsive.css`, `premium.css` and `premium-v2.css` contain historical overlapping definitions. 6.5.53 does not delete those files because route/admin/detail functionality still depends on them, but the public home now has an authoritative final layer with equal/higher specificity and regression tests.
6. **Admin persistence is infrastructure-backed.** Editing works in the UI and browser draft even if Azure Table Storage is down; global publish requires `BLINQ_ADMIN_STORAGE_CONNECTION_STRING` or `AzureWebJobsStorage`. This is intentionally not faked with an ephemeral server file.

## Visual contract applied

- One desktop header row: logo / 3 premium promo slots / plans-admin-account.
- One navigation row with search on the right; BTTS excluded from the tennis primary navigation.
- Existing tennis-ball hero asset remains the hero visual; copy is `Dáta. Analýza. / Lepšie rozhodnutia.`
- Daily Picks is the main dashboard content and uses tournament identity, player photo, flag, ranking, odds, BlinQ %, data and Detail.
- No old six-panel grid on the home route.
- Full-width intelligence strip.
- Gold BlinQ VIP rail.
- Compact footer.
- Account stays a modal, not a full page workspace.
- Admin remains a real control center with Banners & links as the default tab.

## Data contract retained

Tournament logos use the same-origin backend proxy. The backend asks TennisApi for `/tournament/{id}/image/dark` first, then `/image`. The RapidAPI key never reaches the browser. Missing presentation data falls back visually; no model inputs are fabricated.
