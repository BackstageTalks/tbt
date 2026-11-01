"""Uploaded ATP 2025 must remain source-only, even with convincing stats."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cdb_uploaded_2025_source_stage import prepare, digest, counts_quality, rates


def row(**changes):
    base = {
        'tourney_id':'2025-test','tourney_date':'20250105','tourney_name':'Example Open',
        'match_num':'1','match_id':'SOURCE001','start_time_utc':'2025-01-06T10:00:00Z',
        'winner_id':'ABCDEFGH','loser_id':'ZYXWVUTS',
        'winner_name':'Winner A.','loser_name':'Loser B.',
        'surface':'Hard','round':'QF','score':'6-4 6-4','best_of':'3',
        'w_ace':'5','w_df':'2','w_svpt':'60','w_1stIn':'40','w_1stWon':'30','w_2ndWon':'12',
        'w_SvGms':'10','w_bpSaved':'2','w_bpFaced':'3',
        'l_ace':'4','l_df':'3','l_svpt':'64','l_1stIn':'42','l_1stWon':'26','l_2ndWon':'10',
        'l_SvGms':'10','l_bpSaved':'4','l_bpFaced':'7',
    }
    base.update(changes)
    return base


def csvfile(tmp_path, rows):
    path = tmp_path/'input.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    return path


def lines(path):
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()]


def test_valid_stats_source_only_no_writer_or_canonical_id(tmp_path):
    source=csvfile(tmp_path,[row()])
    out=tmp_path/'out';report=prepare(source,out,digest(source))
    assert report['counts']['source_only_complete_rows']==1
    assert report['cdb_write_authorized'] is False
    assert report['cdb_enriched_cells']==0
    assert report['production_mutated'] is False
    assert report['api_requests']==0
    stage=lines(out/'source_only.jsonl')
    assert len(stage)==1 and stage[0]['import_ready'] is False
    assert stage[0]['source_id_namespace']=='uploaded-atp-2025-opaque'
    assert stage[0]['source_winner_id']=='ABCDEFGH'
    assert stage[0]['source_event_time_utc']=='2025-01-06T10:00:00+00:00'
    assert stage[0]['observations_winner']['service_points_won']==42/60
    assert stage[0]['observations_winner']['return_points_won']==28/64
    assert stage[0]['observations_loser']['break_point_return_win']==1/3
    assert len(stage[0]['source_record_id'].split(':'))==3


def test_missing_bp_denominator_is_absent_not_zero():
    quality, c = counts_quality(row(w_bpFaced='0',w_bpSaved='0',l_bpFaced='0',l_bpSaved='0'))
    assert quality=='valid'
    output=rates(c)
    for item in output.values():
        assert 'break_point_serve_win' not in item
        assert 'break_point_return_win' not in item


def test_incomplete_and_bad_arithmetic_stay_review(tmp_path):
    a=row(match_id='ONE',match_num='1',w_svpt='')
    b=row(match_id='TWO',match_num='2',w_1stWon='45')
    c=row(match_id='THREE',match_num='3',score='4-6 4-6')
    d=row(match_id='FOUR',match_num='4',start_time_utc='2024-04-01T01:00:00Z')
    source=csvfile(tmp_path,[a,b,c,d])
    result=prepare(source,tmp_path/'out',digest(source))
    assert result['counts'].get('source_only_complete_rows', 0)==0
    assert result['counts']['incomplete_serve_counts']==1
    assert result['counts']['invalid_serve_arithmetic']==1
    assert result['counts']['winner_score_conflict']==1
    assert result['counts']['missing_or_invalid_event_time']==1
    assert len(lines(tmp_path/'out'/'review.jsonl'))==4


def test_duplicates_refuse_entire_stage_no_manifest(tmp_path):
    source=csvfile(tmp_path,[row(),row(match_id='SOURCE002',match_num='1')])
    out=tmp_path/'out'
    with pytest.raises(ValueError,match='Duplicate source'):
        prepare(source,out,digest(source))
    assert not (out/'report.json').exists()


def test_sha_pin_is_required_and_source_is_not_overwritten(tmp_path):
    source=csvfile(tmp_path,[row()])
    with pytest.raises(ValueError,match='differs'):
        prepare(source,tmp_path/'out','0'*64)
    out=tmp_path/'out'
    report=prepare(source,out,digest(source))
    with pytest.raises(ValueError,match='not empty'):
        prepare(source,out,digest(source))
    assert json.loads((out/'report.json').read_text())==report
