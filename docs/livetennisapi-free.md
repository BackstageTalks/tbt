# Live Tennis API FREE integration

BlinQ has a server-side Live Tennis API FREE key in the GitHub Actions secret
`LIVE_TENNIS_API_KEY`.

The FREE integration is deliberately narrow:

- current `live` and `upcoming` match lists;
- fixtures;
- one-match point-in-time score snapshots;
- provider `/usage` for quota verification.

It does **not** request historical point-by-point tapes. The WTA 2025 reconstructed
research cut and any future ATP/WTA reconstructed cuts remain offline research
datasets under their own access terms.

## Quota safety

The account currently has a 100 calls/day allowance. The client checks the
provider's quota-exempt `/usage` endpoint before billable work, keeps a default
20-call daily reserve, caps a process at 20 billable calls, performs no automatic
retries for billable requests, and fails closed when quota state cannot be
verified.

No scheduled consumer is enabled by this integration. This is intentional while
the main TennisAPI provider is under the 2026-10-06 emergency pause. Any later
scheduled Live Tennis API collector should use this client rather than raw HTTP
calls, and should have its own tighter run-level cap.
