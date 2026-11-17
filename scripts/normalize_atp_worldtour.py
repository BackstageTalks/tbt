"""Source-only, deterministic ATP World Tour 2016-22 -> existing CDB linker CSV.

The input is the immutable upstream source tree.  No CDB read/write, API or
new canonical writer.  ATP tournament *start* dates are never match dates.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

SCORES = ('2010-2019', '2020-2022')
TYPES = {'ATP 250', 'ATP 500', 'Masters 1000', 'Grand Slam', 'ATP Finals',
         'ATP Cup', 'Next Gen Finals', 'Laver Cup'}
STATS = ('match_id tourney_slug match_stats_url_suffix match_time match_duration '
         'winner_slug winner_serve_rating winner_aces winner_double_faults '
         'winner_first_serves_in winner_first_serves_total winner_first_serve_points_won '
         'winner_first_serve_points_total winner_second_serve_points_won '
         'winner_second_serve_points_total winner_break_points_saved '
         'winner_break_points_serve_total winner_service_games_played winner_return_rating '
         'winner_first_serve_return_won winner_first_serve_return_total '
         'winner_second_serve_return_won winner_second_serve_return_total '
         'winner_break_points_converted winner_break_points_return_total '
         'winner_return_games_played winner_service_points_won winner_service_points_total '
         'winner_return_points_won winner_return_points_total winner_total_points_won '
         'winner_total_points_total loser_slug loser_serve_rating loser_aces '
         'loser_double_faults loser_first_serves_in loser_first_serves_total '
         'loser_first_serve_points_won loser_first_serve_points_total '
         'loser_second_serve_points_won loser_second_serve_points_total '
         'loser_break_points_saved loser_break_points_serve_total loser_service_games_played '
         'loser_return_rating loser_first_serve_return_won loser_first_serve_return_total '
         'loser_second_serve_return_won loser_second_serve_return_total '
         'loser_break_points_converted loser_break_points_return_total loser_return_games_played '
         'loser_service_points_won loser_service_points_total loser_return_points_won '
         'loser_return_points_total loser_total_points_won loser_total_points_total').split()
assert len(STATS) == 59
FIELDS = ('source_record_id tourney_id tourney_date tourney_name surface round best_of '
          'winner_name loser_name winner_id loser_id source_winner_id source_loser_id match_num source_score source_date_kind '
          'w_svpt w_1stIn w_1stWon w_2ndWon w_ace w_df w_bpSaved w_bpFaced '
          'l_svpt l_1stIn l_1stWon l_2ndWon l_ace l_df l_bpSaved l_bpFaced').split()


def _rows(path):
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        yield from csv.reader(stream)


def completed(score, w, l):
    if re.search('[a-zA-Z]', score) or not w.isdigit() or not l.isdigit():
        return False
    w, l = int(w), int(l)
    if w not in (2, 3) or l >= w:
        return False
    sets = score.split()
    if len(sets) != w + l:
        return False
    pairs = []
    for s in sets:
        m = re.fullmatch(r'([0-7])[-]?([0-7])(?:\(\d{1,2}\))?', s)
        if not m:
            return False
        a, b = int(m[1]), int(m[2])
        if max(a, b) < 6 or a == b or (max(a, b) == 6 and abs(a-b) < 2):
            return False
        if max(a, b) == 7 and min(a, b) not in (5, 6):
            return False
        pairs.append((a, b))
    return sum(a>b for a,b in pairs) == w and sum(b>a for a,b in pairs) == l


def valid(s):
    try:
        for key in STATS[7:32] + STATS[34:]:
            if 'rating' not in key and 'slug' not in key and not re.fullmatch(r'\d+', str(s[key])):
                return False
        n = lambda key: int(s[key])
        for prefix in ('winner_', 'loser_'):
            v = lambda k: n(prefix+k)
            if (v('first_serves_in') > v('first_serves_total') or
                v('first_serve_points_won') > v('first_serve_points_total') or
                v('second_serve_points_won') > v('second_serve_points_total') or
                v('first_serves_in') != v('first_serve_points_total') or
                v('first_serves_total') != v('service_points_total') or
                v('first_serves_total')-v('first_serves_in') != v('second_serve_points_total') or
                v('service_points_won') != v('first_serve_points_won')+v('second_serve_points_won') or
                v('break_points_saved') > v('break_points_serve_total') or
                v('break_points_converted') > v('break_points_return_total') or
                v('aces') > v('service_points_total') or
                v('double_faults') > v('service_points_total') or
                v('service_points_won') > v('service_points_total') or
                v('return_points_won') > v('return_points_total')):
                return False
        if (n('winner_break_points_saved')+n('loser_break_points_converted') != n('winner_break_points_serve_total') or
            n('loser_break_points_saved')+n('winner_break_points_converted') != n('loser_break_points_serve_total') or
            n('winner_break_points_return_total') != n('loser_break_points_serve_total') or
            n('loser_break_points_return_total') != n('winner_break_points_serve_total') or
            n('winner_return_points_won') != n('loser_service_points_total')-n('loser_service_points_won') or
            n('loser_return_points_won') != n('winner_service_points_total')-n('winner_service_points_won') or
            n('winner_service_points_total') != n('loser_return_points_total') or
            n('loser_service_points_total') != n('winner_return_points_total') or
            n('winner_total_points_total') != n('loser_total_points_total')):
            return False
        return True
    except (KeyError, ValueError):
        return False


def convert(root: Path, output: Path, report_path: Path):
    root, output, report_path = map(Path, (root, output, report_path))
    scores = collections.defaultdict(list)
    for era in SCORES:
        for a in _rows(root / 'csv/2_match_scores' / f'match_scores_{era}.csv'):
            if len(a) == 36 and a[5][:4] in {str(y) for y in range(2016,2023)} and a[35]:
                scores[a[35]].append(a)
    tournaments = collections.defaultdict(list)
    for era in SCORES:
        for a in _rows(root / 'csv/1_tournaments' / f'tournaments_{era}.csv'):
            if len(a) >= 15 and a[0][:4] in {str(y) for y in range(2016,2023)}:
                tournaments[a[0]].append(a)
    years = collections.defaultdict(collections.Counter)
    output.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    with output.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for year in range(2016, 2023):
            for raw in _rows(root / 'csv/3_match_stats' / f'match_stats_{year}.csv'):
                counter = years[str(year)]
                counter['source_rows'] += 1
                if len(raw) != 59:
                    counter['bad_stat_width'] += 1
                    continue
                s = dict(zip(STATS, raw))
                found = scores.get(s['match_stats_url_suffix'], [])
                if len(found) != 1:
                    counter['score_url_missing_or_ambiguous'] += 1
                    continue
                x = found[0]
                tour = tournaments.get(x[0], [])
                if len(tour) != 1:
                    counter['tourney_missing_or_ambiguous'] += 1
                    continue
                t = tour[0]
                if year != int(x[5][:4]):
                    counter['year_mismatch'] += 1
                    continue
                if x[20] != s['winner_slug'] or x[23] != s['loser_slug']:
                    counter['player_id_mismatch'] += 1
                    continue
                if x[3] != t[5]:
                    counter['tournament_slug_mismatch'] += 1
                    continue
                if not completed(x[27], x[28], x[29]):
                    counter['score_not_proven_complete'] += 1
                    continue
                if not valid(s):
                    counter['stat_invariant_failed'] += 1
                    continue
                if s['match_id'] in seen:
                    counter['duplicate_native_match_id'] += 1
                    continue
                if t[2] not in TYPES:
                    counter['unknown_tournament_type'] += 1
                    continue
                best = '5' if t[2] == 'Grand Slam' or int(x[28]) == 3 else '3'
                if (best == '3' and int(x[28]) != 2 or
                    best == '5' and int(x[28]) not in (2, 3)):
                    counter['score_best_of_inconsistent'] += 1
                    continue
                seen.add(s['match_id'])
                row = dict(source_record_id=s['match_id'], tourney_id=x[0],
                           tourney_date=x[5].replace('.', ''), tourney_name=x[2],
                           surface=t[14], round=x[16], best_of=best,
                           winner_name=x[19], loser_name=x[22], winner_id=x[20],
                           loser_id=x[23], source_winner_id=x[20], source_loser_id=x[23],
                           match_num=x[18], source_score=x[27],
                           source_date_kind='tournament_start')
                for side, p in (('w','winner_'),('l','loser_')):
                    row.update({f'{side}_svpt':s[p+'service_points_total'],
                                f'{side}_1stIn':s[p+'first_serves_in'],
                                f'{side}_1stWon':s[p+'first_serve_points_won'],
                                f'{side}_2ndWon':s[p+'second_serve_points_won'],
                                f'{side}_ace':s[p+'aces'], f'{side}_df':s[p+'double_faults'],
                                f'{side}_bpSaved':s[p+'break_points_saved'],
                                f'{side}_bpFaced':s[p+'break_points_serve_total']})
                writer.writerow(row)
                counter['normalized_rows'] += 1
    report = dict(schema=1, stage='SOURCE_ONLY__NO_CDB_READ_OR_WRITE',
                  output_csv_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  output_rows=sum(v['normalized_rows'] for v in years.values()),
                  year_counts={str(y):dict(years[str(y)]) for y in range(2016, 2023)},
                  source_date_kind='tournament_start', cdb_writes=0, api_requests=0)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(convert(a.source_dir, a.output, a.report), indent=2))
