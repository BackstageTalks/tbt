"""Keep each 7.2.1 version's prospective evidence separate and deduplicated."""
from collections import defaultdict
from tbt.services.frozen_721_research import exclude_repeated_events
from tbt.services.shadow_evaluation import update_shadow_ledger
from settle_frozen_721_shadow import completed_matches_for_pending


def _quarantine_conflicting_provider_events(rows):
    """Fail closed on reused provider IDs without discarding audit evidence.

    An event ID linked to different tour/player identities is untrustworthy.
    Exclude *all* its snapshots from scoring and settlement, including any
    previously settled ones; retain the source rows for later identity review.
    Only the private shadow ledger is affected, never canonical match history.
    """
    by_event = defaultdict(list)
    for row in rows:
        event = str(row.get('event_id') or '').strip()
        if event:
            by_event[event].append(row)
    conflicted = set()
    for event, items in by_event.items():
        identities = {
            (str(r.get('tour') or '').upper(),
             frozenset((str(r.get('player1_id') or ''), str(r.get('player2_id') or ''))))
            for r in items
        }
        if len(identities) > 1:
            conflicted.add(event)

    safe, quarantined = [], []
    for row in rows:
        if str(row.get('event_id') or '').strip() not in conflicted:
            safe.append(row)
            continue
        entry = dict(row)
        if entry.get('status') != 'excluded':
            entry['shadow_status_before_quarantine'] = entry.get('status')
        entry.update(
            status='excluded',
            excluded_reason='conflicting_provider_event_identity',
        )
        quarantined.append(entry)
    return safe, quarantined


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
        rows, quarantined = _quarantine_conflicting_provider_events(rows)
        settled.extend(quarantined)
        if not rows:
            continue
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
    groups.clear()
    result = []
    for row in captured:
        version = str(row.get('challenger_model_version') or '')
        if version.startswith(('v7.2.1-', 'v7.2.2-')):
            groups[(row['production_model_version'], version)].append(row)
        else:
            result.append(row)
    for rows in groups.values():
        rows, quarantined = _quarantine_conflicting_provider_events(rows)
        result.extend(exclude_repeated_events(rows))
        result.extend(quarantined)
    return sorted(result, key=lambda row: (row.get('scheduled_at', ''), row['match_id'],
                                          row.get('challenger_model_version', '')))
