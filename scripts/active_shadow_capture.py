"""Keep each 7.2.1 version's prospective evidence separate and deduplicated."""
from collections import defaultdict
from tbt.services.frozen_721_research import exclude_repeated_events
from tbt.services.shadow_evaluation import update_shadow_ledger
from settle_frozen_721_shadow import completed_matches_for_pending


def update_active_shadow(ledger, **kwargs):
    groups = defaultdict(list)
    legacy = []
    for row in ledger:
        version = str(row.get('challenger_model_version') or '')
        if version.startswith('v7.2.1-'):
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
    groups.clear()
    result = []
    for row in captured:
        version = str(row.get('challenger_model_version') or '')
        if version.startswith('v7.2.1-'):
            groups[(row['production_model_version'], version)].append(row)
        else:
            result.append(row)
    for rows in groups.values():
        result.extend(exclude_repeated_events(rows))
    return sorted(result, key=lambda row: (row.get('scheduled_at', ''), row['match_id'],
                                          row.get('challenger_model_version', '')))
