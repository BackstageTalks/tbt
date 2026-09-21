# BlinQ v7.2.9 — publication recovery hardening

## Trigger
Azure deploy failed in `prepare_feed.py` with `Market feed/ledger mismatch for ace event 17125475; no unique issued snapshot`.

## Root cause
A legacy projection-only ESA publication could not be mapped to one unique issued snapshot. Blocking the entire site deploy for an ambiguous non-priced projection is unnecessary, while choosing one snapshot would be unsafe.

## Fix
- Odds-backed TOP/PRIME/VALUE behavior is unchanged and remains fail-closed.
- ESA matching now includes projection scope and metric.
- Lifecycle-only duplicate ESA snapshots with identical immutable content are collapsed safely.
- Conflicting or missing legacy ESA snapshots are quarantined at card level; nothing is invented and the ledger is not mutated.
- Deploy logs report how many legacy ESA cards were quarantined.

## Expected recovery
Deploy succeeds without weakening betting-publication integrity. A subsequent refresh regenerates current canonical ESA publication candidates.
