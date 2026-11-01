"""Integration contract: uploaded match-level CSV -> existing private L2 gate, never a writer."""
from __future__ import annotations
import csv, gzip, io, json, pathlib, sys, zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from cdb_uploaded_2025_source_stage import prepare, digest
from cdb_uploaded_2025_l2_bridge import convert, SOURCE_NAME


def fixture(tmp_path, **changes):
    row = {
        'tourney_id':'2025-example','tourney_date':'20250105','tourney_name':'Example Open',
        'match_num':'1','match_id':'SOURCE001','start_time_utc':'2025-01-06T10:00:00Z',
        'winner_id':'ABCDEFGH','loser_id':'ZYXWVUTS',
        'winner_name':'Winner A.','loser_name':'Loser B.',
        'surface':'Hard','round':'QF','score':'6-4 6-4','best_of':'3',
        'w_ace':'5','w_df':'2','w_svpt':'60','w_1stIn':'40','w_1stWon':'30','w_2ndWon':'12',
        'w_SvGms':'10','w_bpSaved':'2','w_bpFaced':'3',
        'l_ace':'4','l_df':'3','l_svpt':'64','l_1stIn':'42','l_1stWon':'26','l_2ndWon':'10',
        'l_SvGms':'10','l_bpSaved':'4','l_bpFaced':'7',
    }
    row.update(changes)
    original = tmp_path/'original.csv'
    with original.open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    folder=tmp_path/'stage'
    prepare(original,folder,digest(original))
    return original,folder


def getrows(bundle):
    with zipfile.ZipFile(bundle) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read('manifest.json'))
        with gzip.open(io.BytesIO(z.read(SOURCE_NAME)),'rt',newline='') as text:
            return manifest,list(csv.DictReader(text))


def test_converter_exposes_existing_gate_schema_without_authorizing_import(tmp_path):
    original, stage=fixture(tmp_path)
    output=tmp_path/'out.zip'
    report=convert(stage/'report.json',stage/'source_only.jsonl',original,output)
    manifest,rows=getrows(output)
    assert len(rows)==2
    assert report['observed_stat_cells']==16
    assert rows[0]['side']=='winner' and rows[1]['side']=='loser'
    assert rows[0]['source_player_id']=='ABCDEFGH' and rows[1]['source_player_id']=='ZYXWVUTS'
    assert rows[0]['opponent_source_id']==rows[1]['source_player_id']
    assert rows[0]['ace']=='5' and rows[1]['ace']=='4'
    assert rows[0]['service_points_won_pct']==format(42/60,'.17g')
    assert rows[0]['return_points_won_pct']==format(28/64,'.17g')
    assert rows[1]['return_break_points_converted_pct']==format(1/3,'.17g')
    assert rows[0]['complete_match_score']=='True'
    assert rows[0]['source_family']=='uploaded-atp-2025-opaque'
    assert rows[0]['source_archive_sha256']==digest(original)
    assert manifest['import_ready'] is False
    assert manifest['independent_id_witnesses']==0
    assert manifest['cdb_write_authorized'] is False
    assert manifest['cdb_writes']==0
    with pytest.raises(ValueError,match='preexisting'):
        convert(stage/'report.json',stage/'source_only.jsonl',original,output)


def test_zero_breakpoints_are_blank_not_zero_pct(tmp_path):
    original,stage=fixture(tmp_path, w_bpFaced='0',w_bpSaved='0',l_bpFaced='0',l_bpSaved='0')
    _,rows=getrows(tmp_path/'test.zip') if False else (None,None)
    output=tmp_path/'out.zip'
    convert(stage/'report.json',stage/'source_only.jsonl',original,output)
    _,rows=getrows(output)
    assert all(row['break_points_saved_pct']=='' and row['return_break_points_converted_pct']=='' for row in rows)


def test_modified_original_blocked(tmp_path):
    original,stage=fixture(tmp_path)
    original.write_text(original.read_text().replace('ABCDEFGH','OTHERONE'))
    with pytest.raises(ValueError,match='SHA mismatch'):
        convert(stage/'report.json',stage/'source_only.jsonl',original,tmp_path/'out.zip')


def test_forged_stage_values_blocked_even_when_report_hash_updated(tmp_path):
    original,stage=fixture(tmp_path)
    path=stage/'source_only.jsonl'
    row=json.loads(path.read_text())
    row['observations_winner']['aces']=99
    path.write_text(json.dumps(row)+'\n')
    report_file=stage/'report.json'
    report=json.loads(report_file.read_text());report['source_only_file_sha256']=digest(path)
    report_file.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='differ from original'):
        convert(report_file,path,original,tmp_path/'out.zip')


def test_import_ready_forgery_blocked(tmp_path):
    original,stage=fixture(tmp_path)
    path=stage/'source_only.jsonl'
    row=json.loads(path.read_text());row['import_ready']=True
    path.write_text(json.dumps(row)+'\n')
    report_file=stage/'report.json'
    report=json.loads(report_file.read_text());report['source_only_file_sha256']=digest(path)
    report_file.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='Untrusted or allegedly import-ready'):
        convert(report_file,path,original,tmp_path/'out.zip')