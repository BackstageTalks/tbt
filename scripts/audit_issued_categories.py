"""Read-only all-category issuance audit. Never invent prices or unissued bets."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import json
import math
from statistics import stdev
from pathlib import Path

from _bootstrap import ROOT
from audit_top_reliability import timestamp, number, summarize as base_summary, download, issued_snapshot
from audit_market_reliability import _semantic_key, _betting_day

SECTIONS = {'top_daily', 'prime', 'value', 'ace', 'double_faults', 'sets', 'games', 'doubles'}
VOID = {'void','push','cancelled','canceled','postponed','walkover','walk over','w/o','retired','ret','abandoned','interrupted','suspended','no_action'}


def summarize(entries):
    result = base_summary(entries)
    priced = [r for r in entries if r['correct'] is not None and r['odds'] is not None and r['odds'] > 1]
    profits = [r['odds']-1 if r['correct'] else -1 for r in priced]
    result['yield_small_sample'] = len(priced) < 100
    result['calibration_small_sample'] = result['calibration_n'] < 100
    mean = result['yield_flat_stake']
    error = 1.96*stdev(profits)/math.sqrt(len(profits)) if len(profits)>1 else None
    result['yield_ci95_normal_approximation'] = [mean-error,mean+error] if error is not None else None
    result['uncertainty_note'] = 'Approximate independent-bet interval; correlated same-event bets can make uncertainty larger. Descriptive, not proof of future profitability.'
    return result


def analyze(ledger, now=None):
    now = now or datetime.now(timezone.utc)
    entries = {}
    diagnostics = Counter()
    for row in ledger:
        for pub in row.get('market_publications') or []:
            if not isinstance(pub, dict) or pub.get('section') not in SECTIONS:
                continue
            issued = timestamp(pub.get('issued_at'))
            result = pub.get('result') if isinstance(pub.get('result'),dict) else {}
            scheduled = timestamp(result.get('scheduled_at') or row.get('scheduled_at'))
            if not issued or not scheduled or issued >= scheduled or scheduled >= now or pub.get('excluded_reason') or pub.get('publication_status') in {'pending','expired_unpublished'}:
                diagnostics['excluded_or_unconfirmed'] += 1
                continue
            key = _semantic_key(row,pub)
            if not key:
                diagnostics['missing_identity'] += 1
                continue
            if key in entries:
                diagnostics['duplicate_issued_identity'] += 1
                if entries[key]['issued'] <= issued:
                    continue
            state = str(result.get('status') or '').lower()
            void = state in VOID or result.get('void') is True or result.get('is_void') is True
            correct = result.get('correct') if not void and isinstance(result.get('correct'),bool) else None
            odds = number(pub.get('odds'))
            if odds is None or odds <= 1:
                odds = None
            frozen = issued_snapshot(pub)
            probability = number(frozen.get('blinq_probability')) if frozen else None
            if probability is not None and not .5 <= probability <= 1:
                probability = None
            entries[key] = {'section':pub['section'],'issued':issued,'scheduled':scheduled,
                'day':str(pub.get('betting_day') or _betting_day(issued)),
                'position':number(pub.get('offer_position')),'odds':odds,'correct':correct,
                'probability':probability,'tour':str(row.get('tour') or 'unknown').lower(),
                'surface':str(row.get('surface') or 'unknown'),'void':void}
    rows = list(entries.values())
    output = {'schema':1,'provider_requests':0,'production_mutated':False,
              'generated_at':now.isoformat(),'diagnostics':dict(diagnostics),
              'policy':'Confirmed pre-match issued selections only, deduplicated within section. Flat 1u yield. Missing real odds excluded from yield; voids excluded from wins/losses. Frozen displayed probability only for calibration. No reconstruction of unissued picks or membership history.',
              'sections':{}}
    for section in sorted(SECTIONS):
        selected = [r for r in rows if r['section']==section]
        daily = defaultdict(list)
        for r in selected:
            if r['position'] is not None and r['position'] > 0:
                daily[r['day']].append(r)
        for day_rows in daily.values():
            day_rows.sort(key=lambda r:(r['issued'],r['position']))
        groups = {}
        for field in ['tour','surface']:
            grouped = defaultdict(list)
            for r in selected: grouped[r[field]].append(r)
            groups[field] = {key:summarize(group) for key,group in grouped.items()}
        output['sections'][section] = {'overall':summarize(selected),'void':sum(r['void'] for r in selected),
            'immutable_position_missing':sum(r['position'] is None for r in selected),
            'segments':groups,
            'first_n_offer_position_scenarios':{str(n):summarize([r for r in selected if r['position'] is not None and 0<r['position']<=n]) for n in [1,3,5,10]},
            'first_daily_n_confirmed_position_scenarios':{str(n):summarize([r for day_rows in daily.values() for r in day_rows[:n]]) for n in [1,3,5,10]}}
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-repository', default='BackstageTalks/tbt-data')
    ap.add_argument('--out', default='.cache/tbt/issued-category-audit.json')
    args = ap.parse_args()
    ledger = download(args.data_repository,'tbt-predictions-v1','ledger.json',ROOT/'.cache/tbt/issued-ledger')
    report = analyze(ledger)
    out = Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print(json.dumps({s:r['overall'] for s,r in report['sections'].items()}))


if __name__ == '__main__': main()
