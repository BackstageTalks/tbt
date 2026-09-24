# R61 preproduction candidate

This PR is one release candidate; it does not authorize or trigger a production deployment.

## Changes

- Remove the older ID-specific four-column KPI rule that defeated later three-column fixes, including its mobile overrides. Use three equal desktop columns and equal full-width mobile cards.
- Restore the original committed `blinq_background.webp`, remove the fixed app-shell watermark as well as the older anti-share layer, and retain the subtle hero watermark. Preserve the dark animated loader and its rounded frame; enlarge its caption.
- Align the hero copy, navigation, KPI/table/community/footer edges; improve supporting typography, community card/button alignment, category lock spacing, empty state, and Detail control. Remove duplicate mobile bottom spacing while reserving room for the bottom navigation.
- Accept safe versioned local photo URLs. Include doubles member IDs from nested market rows in the deployment photo archive selection. Recover a photo by exact player ID when its profile is missing or references an unavailable file, using only files actually deployed.
- Read nested provider market names for ESA/aces prices and reject partial-match (e.g. first-set) ace prices for full-match projections. Keep unavailable exact prices unavailable; never manufacture odds.
- Atomically claim each 7/3-day notice using Azure Table entity versions or Firestore update-time preconditions before SMTP. Recheck paid access against current membership before claiming, skip concurrent claim losers, allow retries after explicit non-delivery, and retain pending claims after ambiguous SMTP exceptions.

## Validation

Offline tests use fixtures and mocks; no paid provider requests, production SMTP, account changes, data refresh, or deployment were performed.

- Full Python suite: 837 passing tests, including 15 new notice/asset/odds regressions.
- JavaScript runtime/auth suites and repository contract audit.
- Browser layout checks at 390, 768, 1440, and 1920 px, plus existing access/odds interaction tests. The new browser gate is included in CI.
- Release and asset cache revision updated to `736-r61`.

## Remaining production readiness evidence

- The fixes reproduce concrete source-level failure cases. Actual missing player IDs and exact ESA provider payloads from the production release have not been supplied/inspected. Availability of a real image or an exact full-match market cannot be guaranteed by CSS or a parser fix. Verify the deployed feed's `player_assets` and projection-odds diagnostics before release approval; do not fetch paid data just to fill these gaps.
- The repository defaults contain two community groups; the browser fixture adds a third to verify equal card geometry. Published group content/settings remain managed by the application.
- An ambiguous SMTP outcome intentionally remains `pending` to avoid duplicate mail. Such a claim needs operator reconciliation against SMTP logs; it must not be cleared automatically. SMTP and Table Storage cannot provide an atomic exactly-once transaction.
- A membership can change immediately after the last pre-send read. Eliminating that final race requires coordinating membership writes and email delivery through a transactional outbox; this PR does not redesign account administration.
- User manual testing was marked complete. CI must be green for the final PR head. No merge or production deployment is part of this change.
