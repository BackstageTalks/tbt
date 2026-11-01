"""Offline API upgrade checks. Reads JSON only; never imports or writes CDB.

Results describe supplied evidence, never authorize a production write.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp must be an ISO string')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result.astimezone(timezone.utc)


def event_index(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise ValueError('Expected events array')
    result = {}
    for event in payload['events']:
        if not isinstance(event, dict):
            raise ValueError('Invalid event')
        required = ('id', 'home_id', 'away_id', 'scheduled_at', 'discipline', 'tour')
        if any(event.get(key) in (None, '') for key in required):
            raise ValueError('Missing event identity/context')
        if any(isinstance(event[key], bool) or not isinstance(event[key], (str, int))
               for key in ('id', 'home_id', 'away_id')):
            raise ValueError('Invalid ID')
        key = str(event['id'])
        if key in result:
            raise ValueError('Duplicate event ID')
        if str(event['home_id']) == str(event['away_id']):
            raise ValueError('Identical opponents')
        if event['discipline'] not in ('singles', 'doubles') or event['tour'] not in ('ATP', 'WTA'):
            raise ValueError('Unsupported discipline/tour')
        result[key] = (str(event['home_id']), str(event['away_id']),
                       timestamp(event['scheduled_at']), event['discipline'], event['tour'])
    return result


def compare_calendars(before, candidate):
    old, new = event_index(before), event_index(candidate)
    missing = sorted(old.keys() - new.keys())
    added = sorted(new.keys() - old.keys())
    changed = sorted(k for k in old.keys() & new.keys() if old[k] != new[k])
    return {'passed': bool(old) and not (missing or added or changed),
            'baseline_events': len(old), 'candidate_events': len(new),
            'missing_ids': missing, 'added_ids_requiring_review': added,
            'changed_context_ids': changed,
            'scope': 'supplied normalized samples only; not proof of provider completeness'}


def check_point_in_time(payload):
    rows = payload.get('observations') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('Expected non-empty observations array')
    failures = []
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError('Observation must be object')
            kind = row.get('kind')
            if kind not in ('season', 'match_stats', 'pbp', 'odds'):
                raise ValueError('Unsupported observation kind')
            if not row.get('entity_id') or not row.get('source_ref'):
                raise ValueError('Missing identity or evidence reference')
            available = timestamp(row.get('available_at'))
            cutoff = timestamp(row.get('prediction_at'))
            if available >= cutoff:
                raise ValueError('Observation not available before prediction')
            if kind == 'odds':
                quote = timestamp(row.get('provider_quote_at'))
                start = timestamp(row.get('target_match_start'))
                if quote > available or quote >= start or cutoff >= start:
                    raise ValueError('Invalid pre-match quote chronology')
                if row.get('suspended') is not False or row.get('source_id') in (None, ''):
                    raise ValueError('Unconfirmed availability/source')
            else:
                end = timestamp(row.get('coverage_end'))
                if end > available or end >= cutoff:
                    raise ValueError('Future or unfinished coverage')
                if kind in ('match_stats', 'pbp'):
                    if row.get('source_match_id') in (None, '') or row.get('target_match_id') in (None, ''):
                        raise ValueError('Missing source/target match')
                    if str(row['source_match_id']) == str(row['target_match_id']):
                        raise ValueError('Same-match leakage')
                    if row.get('match_finished') is not True:
                        raise ValueError('Source match not confirmed finished')
                if kind == 'pbp' and row.get('completeness_verified') is not True:
                    raise ValueError('PBP completeness not verified')
        except (ValueError, TypeError) as error:
            failures.append({'index': index, 'reason': str(error)})
    return {'passed': not failures, 'observations': len(rows), 'failures': failures,
            'scope': 'chronology of supplied evidence; timestamps/identities require independent provenance verification'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=('calendar', 'point-in-time'))
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    paths = [args.input] + ([args.candidate] if args.candidate else [])
    try:
        raw = [p.read_bytes() for p in paths]
        data = [json.loads(item) for item in raw]
        if args.check == 'calendar':
            if len(data) != 2:
                raise ValueError('Calendar requires --candidate')
            result = compare_calendars(*data)
        else:
            if args.candidate:
                raise ValueError('--candidate only applies to calendar')
            result = check_point_in_time(data[0])
        result['evidence'] = [{'path': str(p), 'sha256': hashlib.sha256(b).hexdigest()}
                              for p, b in zip(paths, raw)]
    except (OSError, ValueError, TypeError) as error:
        result = {'passed': False, 'error': str(error)}
    result.update(check=args.check, production_write_authorized=False, cdb_writes=0)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
