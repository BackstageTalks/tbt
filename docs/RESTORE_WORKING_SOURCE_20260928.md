# BlinQ: working source backup and non-destructive restoration (2026-09-28)

## Verified user-supplied backup

The uploaded `funkcna zaloha pred finalnymi zmenami.zip` contains 721 files
under `tbt-main/` (ZIP SHA-256:
`16f83331c8997aa82753d67bb10f864c7cd12364f93c6c9ccdc2826691f9d057`).

Its source is already in Git history at commit
[`6f4ab53de1cac232b39ca121dc1768f8018073dc`](https://github.com/BackstageTalks/tbt/commit/6f4ab53de1cac232b39ca121dc1768f8018073dc),
committed September 26 at 21:07 UTC. The precise Git blob IDs from the ZIP
match that commit:

| File | ZIP and historical Git blob |
|---|---|
| `web/app.js` | `9b79d08f517a0ac575c6ac0382fc794155c8deea` |
| `web/index.html` | `80af61a0eadcad38027d729f8c8a673e8d9b370d` |
| `web/blinq-app.css` | `5f8f3d0563f619ce2d4be3e3fb43485eef7ec4d8` |
| `web/ui-config.json` | `195f518d02dcceb657af96bffeb25aae30c49a90` |
| `web/config/banners.json` | `b19ca5d53a4fb0c17039c73a48cd4caf83ad0ace` |
| `api/function_app.py` | `b4487298dbd7430392da4a30329e71e99dffb6e0` |

Recovery reference branch: `backup/working-source-20260926-2307` pinned to
`6f4ab53`. Do not force-push or delete this backup branch.

## Reapplying later work

The latest `main` is an ancestor-preserving continuation of this backup:
the Git comparison between `6f4ab53` and `9d09343` showed **88 commits
ahead, zero behind**. Replacing current `main` with a ZIP extraction would
delete the later fixes, including mobile Results, INFO/LIVE, admin deletion,
data imports, deployment stamping, and protection against stale CI deployments.

Keep the current source and restore *only missing published content* from a
verified historical Azure UI configuration or an actual admin export/draft.

## Critical limitation of the source ZIP

Neither the source ZIP nor the historical commit contains Azure Table's
`BlinQAdminConfig / runtime / ui-config` entity or files uploaded through
Azure media storage. Their included `web/ui-config.json` and
`web/config/banners.json` are **release defaults**: only HERO_BANNER_1 is
enabled; slots 2–5 have no original custom uploaded images or URLs.
Consequently the source ZIP is not a backup of the site's complete
admin-published visual state. Do **not** claim five banners or original
published custom links are recoverable from it.

## Safe restoration sequence

1. Back up the *current* effective Azure UI config and all existing uploaded
   media before changing or publishing anything. Retain the file timestamp.
2. Look for an older full JSON export, versioned runtime-config snapshot, Azure
   Storage recovery copy, or the original admin browser draft. Compare all five
   banner images/mobile images, texts, links and slot_count before publishing.
3. Import a verified previous configuration into the Admin editor as a **draft**
   first. Check that it preserves the latest access-contract settings and new
   dashboard fields; do not reset the model, data feed, LIVE records, or accounts.
4. Publish only after confirming the old banner content is actually present and
   that Azure storage is available. Verify the exact deployed Git SHA and
   `/follow-the-data/` route against production.
5. Keep a versioned server-side snapshot **before every future Admin Publish**.
   A source-code ZIP or a successful frontend deployment is not a backup of
   Azure-published marketing content.
