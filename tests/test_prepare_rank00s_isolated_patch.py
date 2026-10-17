"""Synthetic safety tests: rank00s isolated adapter, no private CDB data."""
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_rank00s_isolated_patch as r


def cohort():
    data = {}
    cols = ['match_id','tour','scheduled_at','player1_id','player2_id','player1_rank','player2_rank','stats_json']
    for year in r.PARTITIONS:
        data[year] = pd.DataFrame(columns=cols)
    data[2003] = pd.DataFrame([{'match_id':'match-1', 'tour':'atp',
        'scheduled_at':pd.Timestamp('2003-03-11T12:00:00Z'),
        'player1_id':'can-1','player2_id':'can-2','player1_rank':float('nan'),
        'player2_rank':None,'stats_json':'{"hold":1}'}])
    candidate = {'status':'REVIEW_ONLY_NO_WRITE','canonical_year':2003,'match_id':'match-1',
        'field':'player1_rank','candidate_value':1334,'canonical_player1_id':'can-1',
        'canonical_player2_id':'can-2','canonical_partition_sha256':r.PARTITIONS[2003],
        'source_date':'2003-03-10','source_player_id':'101',
        'expected_current_value':None,'source_csv_sha256':r.SOURCE_CSV_SHA,
        'source_baseline_history_manifest_sha256':r.CANONICAL_MANIFEST_SHA}
    return data,candidate


def test_adds_only_null_on_right_canonical_side():
    before,c = cohort()
    after,n = r.apply_exact(before,[c])
    assert n['rank_cells_added']==1 and n['existing_values_overwritten']==0
    assert after[2003].loc[0,'player1_rank']==1334
    assert pd.isna(after[2003].loc[0,'player2_rank'])
    assert after[2003].loc[0,'stats_json']=='{"hold":1}'
    assert pd.isna(before[2003].loc[0,'player1_rank'])


@pytest.mark.parametrize('edit,error',[
    ({'candidate_value':-4},'bounded integer'),
    ({'candidate_value':True},'bounded integer'),
    ({'candidate_value':33.0},'bounded integer'),
    ({'field':'stats_json'},'candidate key'),
    ({'canonical_year':2004},'provenance'),
    ({'canonical_player2_id':'swapped'},'participant'),
    ({'source_player_id':'104711'},'source player'),
    ({'source_date':'2003-03-11'},'strictly pre-match'),
    ({'source_date':'2003-02-11'},'strictly pre-match'),
    ({'expected_current_value':99},'provenance'),
    ({'canonical_partition_sha256':'a'*64},'provenance'),
    ({'status':'WRITE'},'provenance'),
    ({'source_csv_sha256':'b'*64},'provenance'),
])
def test_rejects_malicious_candidate(edit,error):
    data,c=cohort()
    c.update(edit)
    with pytest.raises(r.GateError,match=error):
        r.apply_exact(data,[c])


def test_reject_duplicate_cell():
    b,c=cohort()
    with pytest.raises(r.GateError,match='duplicate'):
        r.apply_exact(b,[c,c])


def test_reject_nonnull_overwrite():
    b,c=cohort();b[2003].at[0,'player1_rank']=22
    with pytest.raises(r.GateError,match='Non-NULL'):
        r.apply_exact(b,[c])


def test_reject_non_atp_and_missing_other_side():
    b,c=cohort();b[2003].at[0,'tour']='wta'
    with pytest.raises(r.GateError,match='not ATP'):r.apply_exact(b,[c])
    b,c=cohort();b[2003].at[0,'player2_id']=''
    with pytest.raises(r.GateError,match='participant'):r.apply_exact(b,[c])


def test_missing_year_frame_blocks():
    b,c=cohort();del b[2004]
    with pytest.raises(r.GateError,match='ten original years'):r.apply_exact(b,[c])


def test_duplicate_baseline_matches_block():
    b,c=cohort();b[2003] = pd.concat([b[2003],b[2003]],ignore_index=True)
    with pytest.raises(r.GateError,match='duplicate'):r.apply_exact(b,[c])


def test_preflight_stage_and_report_must_match():
    _,c=cohort()
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp);stage=d/'stage.jsonl';report=d/'report.json'
        stage.write_text(json.dumps(c)+'\n',encoding='utf-8')
        digest=r.digest(stage)
        body={'state':'PREPARED_READONLY_NO_CDB_WRITE','history_manifest_sha256':r.CANONICAL_MANIFEST_SHA,
              'source_sha256':r.SOURCE_ZIP_SHA,'canonical_writes':0,'safe_for_production_write':False,
              'stage_sha256':digest,'candidate_cells':1,'crosswalk_players':2}
        report.write_text(json.dumps(body))
        assert len(r.stage_from_preflight(stage,report)[0])==1
        body['history_manifest_sha256']='c'*64;report.write_text(json.dumps(body))
        with pytest.raises(r.GateError,match='stale'):r.stage_from_preflight(stage,report)
        body['history_manifest_sha256']=r.CANONICAL_MANIFEST_SHA;body['candidate_cells']=2
        report.write_text(json.dumps(body))
        with pytest.raises(r.GateError,match='count drift'):r.stage_from_preflight(stage,report)


def test_changed_release_fails_before_parquet_read():
    with tempfile.TemporaryDirectory() as t:
        Path(t,'history_manifest.json').write_text('{}')
        with pytest.raises(r.GateError,match='manifest release changed'):
            r.validate_release_files(t)


def test_output_path_must_not_be_baseline():
    with tempfile.TemporaryDirectory() as t:
        p=Path(t)
        with pytest.raises(r.GateError,match='outside canonical baseline'):
            r.run(baseline_dir=p,stage_path=p/'stage',report_path=p/'report',output_dir=p)


def test_isolated_artifacts_cannot_masquerade_as_canonical_release():
    # A syntactically valid patched Parquet is NOT a permission to publish it.
    import inspect
    source = inspect.getsource(r.run)
    assert "dest = out / f'preview-history-{year}.parquet'" in source
    assert "NOT_FOR_CDB_RELEASE.txt" in source
    assert "dest = out / f'history-{year}.parquet'" not in source
    assert source.index('NOT_FOR_CDB_RELEASE.txt') < source.index("dest = out / f'preview-history-")
