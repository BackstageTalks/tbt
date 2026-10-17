#!/usr/bin/env python3
"""Read-only BlinQ issued-pick reconciliation across ledger, feed and Azure Results.

Never exports player identities; never fetches provider data or updates production.
Fail closed on missing sources and ambiguous issuance, identity, odds and outcome.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
import sys
from typing import Any

SECTIONS = frozenset({'top_daily', 'prime', 'value', 'doubles', 'ace', 'double_faults', 'sets', 'games'})
OU_MARKETS = frozenset({'aces', 'double_faults', 'sets', 'games'})
VOID_STATES = frozenset({'void', 'push', 'cancelled', 'canceled', 'postponed', 'walkover', 'walk over', 'w/o', 'retired', 'ret', 'abandoned', 'interrupted', 'suspended', 'no_action'})
UNISSUED = frozenset({'pending', 'expired_unpublished'})
SOURCE_PRIORITY = ('ledger', 'feed', 'archive')


def at(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        return out.astimezone(timezone.utc) if out.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (ValueError, TypeError):
        return None


def identity(row: dict, pub: dict) -> tuple[str, ...] | None:
    """Stable bet identity; market direction and line are mandatory for O/U."""
    event = str(row.get('event_id') or row.get('id') or row.get('match_id') or '').strip()
    section = str(pub.get('section') or '').strip().lower()
    market = str(pub.get('market') or 'match_winner').strip().lower()
    selection = str(pub.get('selection_id') or pub.get('winner_id') or '').strip().lower()
    if not (event and section in SECTIONS and selection):
        return None
    key = (event, section, market, str(pub.get('projection_scope') or '').strip().lower(),
           str(pub.get('projection_metric') or '').strip().lower(), selection)
    if market in OU_MARKETS:
        contract = str(pub.get('publication_key') or '').strip()
        if contract:
            return (*key, 'publication_key', contract)
        direction = str(pub.get('ou_side') or pub.get('projection_direction') or '').strip().lower()
        line = pub.get('market_line') if market in {'aces', 'double_faults'} else pub.get('reference_projection')
        if not direction or line is None or number(line) is None:
            return None
        return (*key, 'line', str(pub.get('price_contract') or ''), direction, str(number(line)))
    return key


def outcome(pub: dict) -> str:
    result = pub.get('result')
    if not isinstance(result, dict):
        return 'pending'
    state = str(result.get('status') or '').strip().lower()
    is_void = bool(result.get('void') or result.get('is_void') or state in VOID_STATES)
    correct = result.get('correct')
    if is_void and type(correct) is bool:
        return 'conflict'
    if is_void:
        return 'void'
    if type(correct) is bool:
        return 'win' if correct else 'loss'
    return 'pending'


def _iter_publications(rows: list, source: str, counts: Counter):
    for row in rows:
        if not isinstance(row, dict):
            counts[source + '_invalid_rows'] += 1
            continue
        if source == 'archive' and not (row.get('runtime_result_overlay') is True and row.get('archive_source') == 'verified_match_status_snapshot'):
            counts['archive_unverified_origin'] += 1
            continue
        for pub in row.get('market_publications') or []:
            counts[source + '_publications'] += 1
            if not isinstance(pub, dict):
                counts['malformed_publications'] += 1
                continue
            if pub.get('excluded_reason') or pub.get('publication_status') in UNISSUED:
                counts['excluded_unpublished'] += 1
                continue
            key = identity(row, pub)
            if key is None:
                counts['invalid_identity_or_ou_contract'] += 1
                continue
            issued, scheduled = at(pub.get('issued_at')), at(row.get('scheduled_at') or row.get('date'))
            if issued is None:
                counts['missing_immutable_issued_at'] += 1
                continue
            if scheduled is None or issued >= scheduled:
                counts['not_verifiably_pre_match'] += 1
                continue
            if scheduled > datetime.now(timezone.utc):
                counts['not_yet_played'] += 1
                continue
            yield key, row, pub, issued, scheduled


def aggregate(rows: list[dict]) -> dict:
    wins = sum(r['outcome'] == 'win' for r in rows)
    losses = sum(r['outcome'] == 'loss' for r in rows)
    voids = sum(r['outcome'] == 'void' for r in rows)
    pending = sum(r['outcome'] == 'pending' for r in rows)
    priced = [r for r in rows if r['outcome'] in {'win', 'loss'} and r['odds'] is not None]
    profit = sum((r['odds'] - 1) if r['outcome'] == 'win' else -1 for r in priced)
    denom = wins + losses
    return {
        'issued_unique': len(rows), 'distinct_events': len({r['event'] for r in rows}),
        'wins': wins, 'losses': losses, 'voids': voids, 'pending': pending,
        'hit_rate': round(wins / denom, 6) if denom else None,
        'priced_settled': len(priced), 'missing_or_conflicting_odds': denom - len(priced),
        'unit_profit': round(profit, 5),
        'roi_flat_stake': round(profit / len(priced), 6) if priced else None,
    }


def _priced_band(odds: float | None) -> str:
    if odds is None:
        return 'unpriced'
    if odds < 1.50:
        return 'below_1.50'
    if odds < 1.70:
        return 'A_1.50_1.69'
    return 'B_1.70_plus'


def reconcile(ledger: list, feed: dict, archive: list, *, source_sha256: dict | None = None) -> dict:
    if not isinstance(ledger, list) or not isinstance(feed, dict) or not isinstance(archive, list):
        raise ValueError('ledger must be list, feed must be object, archive must be list')
    if not isinstance(feed.get('results', []), list):
        raise ValueError('feed.results must be list')
    counts = Counter()
    by_key: dict[tuple, list] = defaultdict(list)
    for source, rows in (('ledger', ledger), ('feed', feed.get('results') or []), ('archive', archive)):
        for key, row, pub, issued, scheduled in _iter_publications(rows, source, counts):
            by_key[key].append({'source': source, 'row': row, 'pub': pub, 'issued': issued, 'scheduled': scheduled})
    clean = []
    for key, instances in by_key.items():
        sources = {x['source'] for x in instances}
        if 'archive' in sources:
            counts['archive_joined_to_ledger'] += int('ledger' in sources)
            counts['archive_only'] += int('ledger' not in sources and 'feed' not in sources)
        if len(instances) > 1:
            counts['duplicate_publications_joined'] += len(instances) - 1
        if len({i['scheduled'] for i in instances}) > 1:
            counts['scheduled_time_conflicts_quarantined'] += 1
            continue
        outcomes = {outcome(i['pub']) for i in instances} - {'pending'}
        if 'conflict' in outcomes or len(outcomes) > 1:
            counts['settlement_conflicts_quarantined'] += 1
            continue
        sorted_instances = sorted(instances, key=lambda i: (SOURCE_PRIORITY.index(i['source']), i['issued']))
        canonical = sorted_instances[0]
        known_odds = []
        for item in instances:
            odds = number(item['pub'].get('odds'))
            if odds is not None and odds > 1:
                snap = item['pub'].get('issued_snapshot')
                quote_at = at(snap.get('market_captured_at')) if isinstance(snap, dict) and snap.get('market_captured_at') else None
                if isinstance(snap, dict) and snap.get('market_captured_at') and (quote_at is None or quote_at > item['issued']):
                    counts['late_quote_rejected'] += 1
                    continue
                known_odds.append(odds)
        odds_conflict = len({round(odd, 8) for odd in known_odds}) > 1
        if odds_conflict:
            counts['odds_conflicts_excluded_from_roi'] += 1
        # Only published immutable fields can substantiate ROI; an unpriced
        # record can never inherit a quote from an arbitrary current event.
        valid_odds = None if odds_conflict or not known_odds else known_odds[0]
        selected = next(iter(outcomes), 'pending')
        event = key[0]
        row = canonical['row']
        clean.append({
            'event': event, 'section': key[1], 'market': key[2],
            'tour': str(row.get('tour') or 'unknown').strip().lower(),
            'surface': str(row.get('surface') or 'unknown').strip().lower(),
            'scheduled': canonical['scheduled'], 'outcome': selected,
            'odds': valid_odds, 'band': _priced_band(valid_odds),
        })
    sections = {s: aggregate([r for r in clean if r['section'] == s]) for s in sorted(SECTIONS)}
    segments = {}
    for s in sorted(SECTIONS):
        grouped = defaultdict(list)
        for row in clean:
            if row['section'] == s:
                grouped[(row['tour'], row['band'])].append(row)
        segments[s] = {f'{tour}|{band}': aggregate(group) for (tour, band), group in sorted(grouped.items())}
    # Chronological split by scheduled event, never random bet-row shuffling.
    events = sorted({(r['scheduled'], r['event']) for r in clean})
    boundary = events[max(0, int(len(events) * 0.8) - 1)][0] if events else None
    train = [r for r in clean if boundary is not None and r['scheduled'] <= boundary]
    holdout = [r for r in clean if boundary is not None and r['scheduled'] > boundary]
    screening = {}
    for section in sorted(SECTIONS):
        for band, threshold in (('A_1.50_1.69', 0.85), ('B_1.70_plus', 2/3)):
            base = [r for r in clean if r['section'] == section and r['band'] == band]
            tr = aggregate([r for r in train if r['section'] == section and r['band'] == band])
            ho = aggregate([r for r in holdout if r['section'] == section and r['band'] == band])
            all_metrics = aggregate(base)
            # This is only a historical screen. Unseen forward shadow data
            # and exact original hypothesis definitions are required to certify.
            pass_screen = bool(
                all_metrics['distinct_events'] >= 300 and ho['distinct_events'] >= 60
                and all_metrics['hit_rate'] is not None and all_metrics['hit_rate'] >= threshold
                and tr['hit_rate'] is not None and tr['hit_rate'] >= threshold
                and ho['hit_rate'] is not None and ho['hit_rate'] >= threshold
                and tr['roi_flat_stake'] is not None and tr['roi_flat_stake'] > 0
                and ho['roi_flat_stake'] is not None and ho['roi_flat_stake'] > 0
            )
            screening[f'{section}|{band}'] = {
                'historical_screen_pass': pass_screen, 'required_hit_rate': round(threshold, 6),
                'all': all_metrics, 'chronological_train': tr, 'chronological_holdout': ho,
            }
    report = {
        'schema': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'status': 'read_only_reconciliation', 'production_mutated': False, 'provider_requests': 0,
        'sources': {'sha256': source_sha256 or {}, 'azure_archive_loaded': True},
        'input_counters': dict(sorted(counts.items())),
        'total': aggregate(clean), 'sections': sections, 'by_section_tour_price_band': segments,
        'chronological_cutoff_utc': boundary.isoformat() if boundary else None,
        'historical_screen': screening, 'hypotheses_tested': 0,
        'confirmed_strategies': 0,
        'limits': [
            'The 1200 original hypotheses were not supplied; descriptive segment screens are not substitutes.',
            'Historical split is not prospective shadow validation.',
            'Missing issuance time, contract, contradicting result or quote is excluded, never imputed.',
            'One match with several bets is correlated and counts only once towards independent-event minimum.',
            'Original published odds are required. ROI is omitted for unpriced or conflicting quotes.',
            'Do not use this result to deploy a model or claim stable strategy profitability.',
        ],
    }
    return report


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()



def _download_private_release_readonly(repository: str, directory: Path) -> tuple[Path, Path]:
    """Fetch immutable release inputs, without using ReleaseStore's creation path.

    ReleaseStore initializes missing tags by creating them, which is not allowed
    in a read-only audit. A missing tag or checksum mismatch fails closed.
    """
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid private data repository name')
    tag = 'tbt-predictions-v1'
    subprocess.run(['gh', 'api', f'repos/{repository}/releases/tags/{tag}'],
                   check=True, stdout=subprocess.DEVNULL)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('_tbt_bundle_manifest.json', 'ledger.json', 'feed.json'):
        subprocess.run(['gh', 'release', 'download', tag, '--repo', repository,
                        '--pattern', name, '--dir', str(directory), '--clobber'],
                       check=True, stdout=subprocess.DEVNULL)
    manifest = _load(directory / '_tbt_bundle_manifest.json')
    committed = manifest.get('files') if isinstance(manifest, dict) else None
    if not isinstance(committed, dict):
        raise ValueError('Missing immutable release bundle manifest')
    for name in ('ledger.json', 'feed.json'):
        meta = committed.get(name)
        expected = meta.get('sha256') if isinstance(meta, dict) else None
        if not (isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected)):
            raise ValueError(f'Missing release checksum for {name}')
        if _digest(directory / name) != expected:
            raise ValueError(f'Immutable release checksum mismatch for {name}')
    return directory / 'ledger.json', directory / 'feed.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, help='Immutable ledger JSON, or use --from-release')
    parser.add_argument('--feed', type=Path, help='Deployed feed JSON, or use --from-release')
    parser.add_argument('--from-release', action='store_true', help='Download verified tbt-predictions-v1 bundle via existing ReleaseStore')
    parser.add_argument('--data-repository', default='BackstageTalks/tbt-data')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--archive', type=Path, help='JSON array exported read-only from Azure Results')
    group.add_argument('--azure', action='store_true', help='Read Azure Table using runtime read credentials, no writes')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.from_release:
        if args.ledger or args.feed:
            parser.error('--from-release cannot be combined with --ledger/--feed')
        cache = Path(__file__).resolve().parents[1] / '.cache/tbt/reconciled-results/predictions'
        ledger_path, feed_path = _download_private_release_readonly(args.data_repository, cache)
    else:
        if not args.ledger or not args.feed:
            parser.error('both --ledger and --feed are required unless --from-release is set')
        ledger_path, feed_path = args.ledger, args.feed
    ledger, feed = _load(ledger_path), _load(feed_path)
    sha = {'ledger': _digest(ledger_path), 'feed': _digest(feed_path)}
    if args.azure:
        api = Path(__file__).resolve().parents[1] / 'api'
        sys.path.insert(0, str(api))
        from tbt.services.results_archive import load_settled_results_archive
        archive = load_settled_results_archive()
        sha['archive'] = hashlib.sha256(json.dumps(archive, ensure_ascii=False,
                            sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    else:
        archive = _load(args.archive)
        sha['archive'] = _digest(args.archive)
    report = reconcile(ledger, feed, archive, source_sha256=sha)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.out), 'settled': report['total']['wins'] + report['total']['losses'],
                      'priced': report['total']['priced_settled'], 'confirmed_strategies': 0,
                      'quarantine': {k:v for k,v in report['input_counters'].items() if 'conflict' in k or 'rejected' in k}}))


if __name__ == '__main__':
    main()