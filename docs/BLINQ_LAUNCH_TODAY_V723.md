# BlinQ v7.2.3 — launch-final runbook

v7.2.3 extends v7.2.2 with the final two requested launch features: direct binary banner upload and opt-in browser Web Push for Premium INFO / Comeback LIVE.

## Included in v7.2.3

- Admin banner/media fields have a native **Nahrať obrázok** action. PNG, JPG, WebP, GIF and AVIF are accepted up to 12 MB. SVG is intentionally rejected.
- Uploaded images are stored in a private Azure Blob container and exposed through an opaque same-origin `/api/v1/media/<id>` read URL. No public Blob container or SAS URL is required in banner configuration.
- ELITE / Legend / GOAT (and admin) can enable browser push from the Account page.
- Web Push uses the browser Push API + a same-origin service worker (`/blinq-sw.js`) and VAPID keys.
- Newly created Premium INFO messages send push after durable message persistence. Editing an existing message does not generate a duplicate push.
- New deterministic LIVE alerts send push only when the alert is first created. Existing LIVE idempotency remains intact.
- Expired/downgraded subscriptions are filtered server-side. Admin access changes synchronize stored push entitlements.
- Admin diagnostics now exposes media-storage and Web-Push readiness explicitly.
- All v7.2.2 launch work remains: GAMES/SETS model projections, ESA, LIVE Set-2 projection/odds parser, launch gate, final refresh in mega-data, support email hook and deploy smoke support.

## Runtime settings — binary media

No extra setting is normally required if `AzureWebJobsStorage` already points to a writable Storage Account. Resolution order is:

1. `BLINQ_MEDIA_STORAGE_CONNECTION_STRING`
2. `BLINQ_ADMIN_STORAGE_CONNECTION_STRING`
3. `AzureWebJobsStorage`

Optional:

- `BLINQ_MEDIA_CONTAINER=blinq-media`

The container remains private; BlinQ serves uploaded images through its own API proxy.

## Runtime settings — Web Push

Generate one VAPID pair once after installing API requirements:

```bash
python scripts/generate_webpush_keys.py
```

Store the generated values in production app settings:

- `BLINQ_WEBPUSH_PUBLIC_KEY=<generated public key>`
- `BLINQ_WEBPUSH_PRIVATE_KEY=<generated private key>`
- `BLINQ_WEBPUSH_SUBJECT=mailto:<real operator/support email>`

Treat the private key as a secret. Do not commit generated keys to the repository. Do not rotate the VAPID pair casually; existing browser subscriptions are bound to the application-server key and must be re-subscribed after rotation.

Push subscriptions use the same durable admin store as the rest of BlinQ (`azure_table` preferred, Firestore fallback).

## Parallel launch tracks

### Track A — CI / code

Upload v7.2.3 to a branch and run normal CI. CI must be green before merge/deploy.

### Track B — data

While CI runs, run GitHub Actions → Tennis data and predictions:

- mode: `mega-data`
- max_requests: `10000`
- lookback_days: `1095`
- ace_target_samples: `18`
- ace_lookback_days: `550`
- sg_target_samples: `24`
- sg_lookback_days: `730`
- promote: `false`

Do not run another provider-heavy writer in parallel. The mega run already includes the protected final refresh, production preflight and consolidated launch gate.

### Track C — runtime configuration

Configure media storage and VAPID Web Push while A/B run. Existing RapidAPI/Firebase/storage/deploy settings stay unchanged.

For optional support e-mail also set:

- `RESEND_API_KEY`
- `BLINQ_SUPPORT_TO_EMAIL`
- optional `BLINQ_SUPPORT_FROM_EMAIL`

For post-deploy CI smoke, set GitHub variable:

- `TBT_PRODUCTION_URL=https://<production-host>`

## Final deploy/smoke

After CI and mega-data finish:

1. Review `launch_gate.md`; history/preflight must not be blocked.
2. Deploy v7.2.3 after the mega-data final refresh so the newest feed is packaged.
3. Admin → diagnostics should report persistent admin storage and media storage available; Web Push should be enabled after VAPID variables are present.
4. Admin → Bannery: upload one test PNG/WebP directly from disk, save the banner, then reload the public page and verify the same-origin media URL renders.
5. On an ELITE+/admin account open Account → LIVE & INFO PUSH and enable notifications from the explicit button.
6. Publish one test Premium INFO item and verify both the in-app notification and browser notification.
7. Run `Scan LIVE teraz`; no candidates is valid when no eligible live PRIME match exists.
8. Smoke login/dashboard/ESA/GAMES/SETS/INFO/LIVE/support/admin before merging the branch to production.

## Intentionally not included

- Automatic payments/reconciliation — explicitly not required for this launch.
- Doubles model — remains disabled until a separate pair/team model is validated.
- Fabricated bookmaker odds — GAMES/SETS/ESA remain honest projection layers unless real provider odds are available.
