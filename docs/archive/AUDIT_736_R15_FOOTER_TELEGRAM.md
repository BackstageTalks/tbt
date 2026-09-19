# BlinQ 7.3.6-r15 — footer + Telegram community panel

## Runtime changes
- The old generic benefit/intelligence rail stays removed from runtime markup.
- Footer keeps only a visible BlinQ watermark, UI release stamp and language selector.
- New Telegram groups panel is rendered below the prediction board.
- Telegram panel defaults live in `web/config/telegram-groups.json`.
- Admin now has a dedicated **Telegram** section where groups, labels, URLs, minimum level and visibility can be edited.
- Admin Telegram edits are published through the existing durable UI configuration storage (`BLINQ_STORAGE_CONNECTION_STRING`).
- Locked Telegram groups use the normal BlinQ upgrade flow; Admin has unrestricted visibility.

## Security note
Do not store a long-lived private Telegram invite URL in browser-visible configuration. For private VIP groups use a request/contact URL or bot link and grant membership separately.

## Release/cache
- release: 7.3.6
- patch: 736-r15
- asset patch query: p=15
