# BlinQ recovery

Authoritative pre-cleanup snapshot (2026-10-01):

- Full app snapshot: branch `backup/pre-cleanup-2026-10-01`
- Pinned app SHA: `6ef716dc47d0b75f181a90fcb3c6962d194e944d`
- Private recovery bundle: `BackstageTalks/tbt-data`, branch `recovery/pre-cleanup-2026-10-01`
- Recovery folder: `recovery/2026-10-01-pre-cleanup/`

Restore order:

1. Branch/reset from the pinned SHA or backup branch.
2. Deploy web and API from that exact revision.
3. Confirm Azure runtime UI storage is available and runtime-configured before replacing it with repository defaults.
4. Verify Firebase auth, Azure storage/media, prediction feed, TOP/PRIME/VALUE/DOUBLES, match-status, Telegram panel and shared API budget.
5. Reapply intentionally retained open PRs by the head SHAs recorded in the private recovery manifest.

The private recovery bundle contains the full repository tree/blob SHAs, UI/card/content/membership/Telegram/banner configs, the pre-cleanup workflow inventory, critical operating limits and required secret names. Secret values are never stored in Git.
