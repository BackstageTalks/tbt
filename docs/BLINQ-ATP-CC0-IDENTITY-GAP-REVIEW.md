# BlinQ — ATP/Wikidata gap-bridge review (2026-10-12)

Scope: prepare **review-only** candidates for the 606 missing TML ATP player IDs
using independently archived Wikidata CC0 identity links. No name-only
matching, no canonical event assertion, no CDB writer, no model training.

Existing pinned private evidence inputs:

- `blinq-source-evidence-tml-2022-2025-38241050051-1` asset
  `identity-crosswalk-priority-private.jsonl`, SHA-256
  `95fbc94e47cc0e6f664018829ed10b80a76ff96a600dbe563177ad688244bccd`.
- `BackstageTalks/tbt-data` (private) tracked
  `research/player_identity/wikidata-canonical-links.jsonl.gz`.
  Use a **pinned private Git commit** and calculate its SHA-256 inside the
  trusted workspace; do not fetch mutable `main` during a review.
- The 2026-10-09 CC0 crosswalk was built from 993,066 matches, so **every**
  candidate must be revalidated against the newest current CDB snapshot.
  This report does not declare current 2026 canonical truth.

Run on a private workspace with the approved files already present:

```bash
python scripts/review_wikidata_atp_gap_bridge.py \
  --gaps private/identity-crosswalk-priority-private.jsonl \
  --gaps-sha256 95fbc94e47cc0e6f664018829ed10b80a76ff96a600dbe563177ad688244bccd \
  --canonical-wikidata private/wikidata-canonical-links.jsonl.gz \
  --canonical-sha256 "$(sha256sum private/wikidata-canonical-links.jsonl.gz | cut -d' ' -f1)" \
  --out private/review-only-atp-id-gaps
```

The SHA-256 of the Wikidata file **must also be backed by the pinned private
commit** (a calculated digest from arbitrary untrusted bytes is not enough).
Keep `atp-gap-cc0-review-private.jsonl` private. The script only prints
aggregate category counts and prepares candidate records that remain
`write_authorized=false` and `import_ready=false`.

For canonical promotion later, require independent source-to-CDB event ID,
both participant IDs with side orientation, tour, timestamp, winner, score,
source provenance, and a fresh NULL-only check; acquire the global writer
lock, immutable pre-write backup, and independent remote SHA readback.
Source reuse approval by the project owner is recognized; no separate
license re-approval is requested. This utility NEVER applies a write.

No provider API requests, GitHub scheduled jobs, canonical releases,
or training jobs are introduced.
