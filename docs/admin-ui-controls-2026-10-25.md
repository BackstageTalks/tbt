# BlinQ Admin — INFO/LIVE, account activity and ACCA controls

This release note documents the admin UX and stats changes merged on 25 October 2026.

## INFO/LIVE message headings

In Admin → INFO & LIVE, the optional **Nadpis** field provides a dropdown with two independent presets: **Premium** and **FREE**. Choose either, both, or neither, then optionally add your own heading in **Vlastný text**. The live preview shows the exact title, for example `Premium · FREE · Dnešný zápas`. The total heading length remains limited to 140 characters.

The heading labels are presentation text **only**. Message distribution/entitlements still depend on the separate INFO/LIVE audience controls. Messages with body only or screenshots only remain valid. Existing titles can still be edited.

## Account activity

The five summary cards in Admin → Accounts → Account Activity switch between distinct views: Telegram cleanup queue, paid-to-ROOKIE transitions, SMTP accepted, SMTP failed and SMTP pending. The panel also retains an **Ostatné udalosti** view and a separately collapsed operational log retention/delete area.

## ACCA

The global **ACCA aktívna** switch controls both presentation visibility and the ACCA contribution to STATS. When the category is globally disabled, ACCA results are omitted from statistics even if the separate STATS-only exclusion checkbox was unchecked. While ACCA is enabled, **Vylúčiť ACCA zo STATS** can exclude ACCA from STATS without hiding it from the site.

Exclusion occurs before Results deduplication in both client and server KPI calculations, so other published categories on the same match stay counted. Immutable historical Results and underlying CDB data are not deleted or rewritten.

## Operational verification

Relevant pull requests: #993, #994 and #995. Only an exact-SHA production deploy and read-back verifies that the changes reached Azure; green tests and merge status alone are not proof of deployment.
