# Live Tennis API integration

BlinQ has a server-side Live Tennis API key in the GitHub Actions secret
`LIVE_TENNIS_API_KEY`.

The runtime integration remains deliberately narrow:

- current `live` and `upcoming` match lists;
- fixtures;
- one-match point-in-time score snapshots;
- provider `/usage` for quota verification.

Historical point-by-point acquisition is handled by a separate controlled
research workflow. The public Zenodo sample was audited first and added zero new
quality-ready canonical matches, so the paid history path is permitted when the
provider reports the expected 1,000 calls/day entitlement.

## Quota safety

The provider `/usage` response is authoritative for the active plan. The
runtime client keeps a default 20-call process cap and 20-call reserve, but now
accepts controlled jobs up to 1,000 configured calls/day. A research job must
still set its own lower cap and reserve, verify the provider quota before any
billable work, and perform no automatic retries for billable requests.

The paid-history importer keeps a 200-call daily reserve and uses at most 700
billable calls per closeout run. It requests only matches that the provider marks
point-complete and that map exactly to one canonical BlinQ match still missing
serve/return quality. Raw paid tapes are kept private and are not redistributed
publicly.
