"""Keep each 7.2.1 version's prospective evidence separate and deduplicated."""
import json
from collections import defaultdict
from tbt.services.frozen_721_research import exclude_repeated_events
from tbt.services.shadow_evaluation import update_shadow_ledger
from settle_frozen_721_shadow import completed_matches_for_pending


def _shadow_key(row):
    return (str(row.get('match_id') or ''),
            str(row.get('production_model_version') or ''),
            str(row.get('challenger_model_version') or ''))


def _shadow_identity(row):
    return (str(row.get('tour') or '').upper(),
            frozenset((str(row.get('player1_id') or ''),
                       str(row.get('player2_id') or ''))))


def _quarantine_new_identity_conflicts(prior, captured):
    """Reject only NEW ambiguous shadow claims; never change previous evidence.

    An already-persisted conflicting cohort remains an error, not something to
    silently clean up. The strict frozen-cohort dedup gate stays unchanged.
    """
    prior_keys = {_shadow_key(row) for row in prior}
    by_event = defaultdict(list)
    for row in captured:
        event = str(row.get('event_id') or '').strip()
        if event:
            key = (str(row.get('production_model_version') or ''),
                   str(row.get('challenger_model_version') or ''), event)
            by_event[key].append(row)

    rejected = set()
    conflicts = 0
    for group in by_event.values():
        if len({_shadow_identity(row) for row in group}) <= 1:
            continue
        old = [row for row in group if _shadow_key(row) in prior_keys]
        if len({_shadow_identity(row) for row in old}) > 1:
            raise ValueError("Conflicting persisted provider event identities in shadow cohort")
        new = [row for row in group if _shadow_key(row) not in prior_keys]
        if not new or any(row.get('status') != 'pending' for row in new):
            raise ValueError("Unexpected non-pending shadow identity conflict")
        # No pre-existing claim: keep NONE of the competing new identities.
        # With a prior claim: retain it unchanged and reject all new variants.
        rejected.update(id(row) for row in new)
        conflicts += 1
    return ([row for row in captured if id(row) not in rejected],
            {"conflicting_events": conflicts, "quarantined_new_rows": len(rejected)})


def update_active_shadow(ledger, **kwargs):
    groups = defaultdict(list)
    legacy = []
    for row in ledger:
        version = str(row.get('challenger_model_version') or '')
        if version.startswith(('v7.2.1-', 'v7.2.2-')):
            groups[(row['production_model_version'], version)].append(row)
        else:
            legacy.append(row)
    completed = list(kwargs.get('completed_matches', ()))
    settled = update_shadow_ledger(legacy, completed_matches=completed, now=kwargs['now'])
    for rows in groups.values():
        rows = exclude_repeated_events(rows)
        accepted, audit = completed_matches_for_pending(rows, completed, kwargs['now'])
        updated = update_shadow_ledger(rows, completed_matches=accepted, now=kwargs['now'])
        for row in updated:
            evidence = audit['provider_alias_evidence'].get(row['match_id'])
            if evidence and row.get('status') in {'settled', 'void', 'excluded'}:
                row['settlement_identity'] = evidence
        settled.extend(updated)
    # Capture now, without re-settling rows through the weaker legacy ID join.
    kwargs['completed_matches'] = ()
    captured = update_shadow_ledger(settled, **kwargs)
    captured, quarantine = _quarantine_new_identity_conflicts(settled, captured)
    if quarantine["quarantined_new_rows"]:
        print(json.dumps({
            "warning": "new_shadow_provider_identity_quarantined",
            **quarantine,
            "prior_evidence_preserved": True,
            "provider_requests": 0,
        }, sort_keys=True), flush=True)
    groups.clear()
    result = []
    for row in captured:
        version = str(row.get('challenger_model_version') or '')
        if version.startswith(('v7.2.1-', 'v7.2.2-')):
            groups[(row['production_model_version'], version)].append(row)
        else:
            result.append(row)
    for rows in groups.values():
        result.extend(exclude_repeated_events(rows))
    return sorted(result, key=lambda row: (row.get('scheduled_at', ''), row['match_id'],
                                          row.get('challenger_model_version', '')))
