# Codex code audit fixes (2026-11-27)
- Security/integrity: stricter link validation; marking a message read can no longer overwrite a newer admin edit or resurrect a deleted one (ETag).
- Performance: one less storage read for private image access; bracket stops observing the whole page; card sizes read once per redraw; results paging keeps at most one requested page (≤500 rows) for today/30d.
- UI: mobile match dialog fixes, focus return after Esc; results paging starts a new window after 06:00.
- Repo: 23 retired one-shot .github/*request markers removed (no workflow references them; documented in WORKFLOW_LIFECYCLE.md).
Open (not in this PR): full history scan for result fingerprint, per-instance reset-email rate limit.
Revert: revert this PR.
