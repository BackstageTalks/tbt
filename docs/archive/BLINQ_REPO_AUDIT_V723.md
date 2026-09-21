# BlinQ repository audit — v7.2.3

## Release

- API/UI release: `7.2.3`
- Asset revision: `7231`
- API contract version: `3.10.0`
- Base: v7.2.2 launch-final

## Final features added

### Native binary banner upload

- New `api/tbt/services/media_storage.py`.
- New admin-only `POST /api/v1/admin/media` raw-binary upload endpoint.
- New public `GET /api/v1/media/{media_id}` same-origin read proxy.
- Private Azure Blob storage; no anonymous container or SAS URL is exposed in banner configuration.
- Accepted formats: PNG/JPEG/WebP/GIF/AVIF, maximum 12 MB.
- Signature checks reject obvious MIME spoofing; SVG is deliberately excluded.
- Admin banner image URL inputs now include a direct file picker/upload action.

### Browser Web Push

- New `api/tbt/services/push_notifications.py`.
- New authenticated `GET /api/v1/push/config`.
- New authenticated ELITE+ `POST/DELETE /api/v1/push/subscription`.
- New `/blinq-sw.js` service worker and PWA manifest.
- Explicit Account-page opt-in; notification permission is requested only from a user action.
- Premium INFO and deterministic LIVE notifications dispatch only after durable insight persistence.
- Duplicate LIVE scans do not create duplicate pushes because the underlying automated insight remains idempotent.
- Subscription entitlements are stored server-side and filtered by current plan/status/expiry.
- Admin accounts can subscribe independently of a paid-plan expiry.

## Diagnostics / safety

- Admin diagnostics reports media storage status and Web Push configuration/storage status.
- Missing media/push configuration is visible as a diagnostics problem instead of failing silently.
- Push failure is best-effort and never rolls back a stored INFO/LIVE message.
- Uploaded media is served with `nosniff` and immutable caching.
- Static Web Apps navigation fallback excludes `.webmanifest` so the manifest is not rewritten to `index.html`.

## Dependencies

Added to `api/requirements.txt`:

- `azure-storage-blob>=12.30.2,<13`
- `pywebpush>=2.4,<3`

VAPID helper: `scripts/generate_webpush_keys.py`.

## Validation

- New/changed v7.2.3 focused tests plus existing release contracts: PASS.
- Broad locally runnable suite: `414 passed, 1 skipped, 8 deselected`.
- The 8 deselected tests are parquet tests requiring local `pyarrow`, absent from this sandbox; CI installs the repository training requirements.
- Azure Functions import smoke cannot be executed in this sandbox because `azure-functions` is not installed locally; GitHub CI installs `api/requirements.txt` before the smoke import.
- Python compileall: PASS.
- `node --check` for `web/app.js`, `web/auth.js`, `web/blinq-sw.js`: PASS.
- JSON validation for Static Web Apps config/manifest/UI config: PASS.

## Production variables added

Media storage (optional override):

- `BLINQ_MEDIA_STORAGE_CONNECTION_STRING`
- `BLINQ_MEDIA_CONTAINER`

Web Push:

- `BLINQ_WEBPUSH_PUBLIC_KEY`
- `BLINQ_WEBPUSH_PRIVATE_KEY`
- `BLINQ_WEBPUSH_SUBJECT`

See `docs/BLINQ_LAUNCH_TODAY_V723.md` for the launch sequence.
