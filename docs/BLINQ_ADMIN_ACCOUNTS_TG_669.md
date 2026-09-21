# BlinQ 6.6.9 — Admin Accounts + Manual Telegram Private Operations

## Scope

This release extends the existing Firebase/Azure account administration without changing prediction logic.

### User identity

User-facing identity now uses:

- Firebase `uid`
- email
- `telegram_nick`
- `created_at`
- `last_sign_in_at`
- `email_verified`
- account status

`displayName` is not used as the BlinQ member identity. Registration asks for Telegram nickname instead.

Telegram nickname is intentionally **not verified or linked through Telegram API** in this release. It is a manual operational identifier.

## Admin account operations

The Users / Accounts admin view now supports:

- free text search by email, Telegram nickname or UID
- filtering by Rookie / PRO / ELITE / Legend / GOAT
- filtering by account status
- filtering by Telegram Private state
- date range filtering by created date, expiry date or last login
- sorting by Telegram nickname, level, expiry, created date, last login or email
- quick filters for Active, Expired, ELITE+ Active, TG ADD, TG REMOVE and No Telegram
- copying Telegram nicknames from the currently filtered result set

## Telegram Private group workflow

The Telegram group remains manually managed.

Eligibility rule:

- account status is `active` or `lifetime`
- level is ELITE, Legend or GOAT

The admin stores a manual `tg_private_member` flag and derives an operational state:

- `ADD`: eligible, but not marked as being in TG Private
- `REMOVE`: no longer eligible, but still marked as being in TG Private
- `OK`: eligible and marked as being in TG Private
- `—`: not eligible and not marked as being in TG Private

Typical downgrade flow:

1. ELITE member is marked `In TG Private`.
2. Membership expires or is changed to PRO.
3. Admin list shows `TG REMOVE`.
4. Admin removes the nickname manually from Telegram.
5. Admin clears `In TG Private` on the BlinQ account.

## Stored admin metadata

`BlinQAccounts` now additionally supports:

- `tg_private_member`
- `admin_note`
- `admin_metadata_updated_at`
- `admin_metadata_updated_by`

Azure Table Storage is schemaless, so existing account rows need no migration. Missing values default safely.

## API

Added admin-only endpoint:

`PUT /api/v1/admin/users/{user_id}/metadata`

Accepted mutable fields:

- `tg_private_member` (boolean)
- `admin_note` (string, max 500 chars)

Important account access data (plan, status, expiry, role/payment reference) continues to use the existing access endpoint. Metadata and access remain separate.

Metadata changes are written to the existing admin audit stream.

## Registration

Registration now asks for:

- email
- Telegram nickname
- password

The Telegram nickname is saved to the member profile before email verification. This does not grant membership access. Existing email verification and access checks remain unchanged.

## Release identifiers

- BlinQ release: `6.6.9`
- API version: `3.6.0`
- UI revision: `6.6.9`

## Validation

Targeted admin/account tests: 56 passed.

Firebase web authentication/email verification tests: passed.

Full Python suite: 292 passed; 8 environment-only failures remain because the execution environment does not include the optional `pyarrow` dependency required by Parquet tests. No failing test was attributable to the admin/TG changes.
