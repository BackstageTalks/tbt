# BlinQ 7.3.6-r11

- Restored cinematic animated loader as a full-bleed background (no boxed card).
- Removed BlinQ Support UI/API; Telegram is the support channel.
- Admin storage diagnostics now focus on Admin config + INFO + LIVE only.
- ROOKIE admin preview now applies draft daily-hub SHOW/BLUR/HIDE rules instead of inheriting the admin server entitlement.
- Removed dead legacy banner-editor helper code; the visible Hero carousel editor is the current banner configuration.
- One durable storage setting is enough: BLINQ_STORAGE_CONNECTION_STRING can point at an existing Azure Storage account. Firestore remains an alternative fallback.
