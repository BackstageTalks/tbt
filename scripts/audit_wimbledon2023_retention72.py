"""Read-only exact 72-cell 2023 Wimbledon retention proof after five-match recovery."""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

PREWRITE_SHA = '25202f79e5e4c8bcdc728ca5b35fa1e47d6238233e336d1b69fa2e2ac2648284'
CURRENT_SHA = '64db4d54926b8cc410cb39207d48fe34bc7ede60d5e6aa0c79c4db7d398e7966'
FIRST_SHA = '0ce1feea000a5b0424da4be2c2c561dab00bec803048db5485ab7084d325ad50'
EXTENDED_SHA = 'f9b54f5680a27684c1ae8d57095ed7170b04fed771c42416c4e639b1b5d18d07'
TARGET_IDS = frozenset(('30a913dc3fa280dbf4838d9d',
'93e0cf24456ba6f6bb83fe8b', '9be0b0ae278ac43da93b6419',
'5a07b3bb8817fd24d70ececa', 'd70725c4dace6ab1811b0360'))
FIRST = {'p1_aces', 'p2_aces', 'p1_double_faults', 'p2_double_faults'}
EXTENDED = {f'p{side}_{field}' for side in (1,2) for field in (
    'winners', 'unforced_errors', 'net_points', 'net_points_won',
    'break_points', 'break_points_won')}
SOURCE_FAMILY = 'figshare_wimbledon_2023_momentum'
SOURCE_SHA = '19507e156e6ff307027d39e44000ac446a564f87b3c8d59a5225dc6d1674c512'


def hash_file(path: Path) -> str:
    h=sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):
            h.update(block)
    return h.hexdigest()


def require_sha(path: Path, required: str):
    if hash_file(path)!=required:
        raise ValueError(f'SHA256_DRIFT:{path.name}')


def load_observations(path: Path, digest: str) -> list[dict]:
    require_sha(path,digest)
    rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    if not rows or any(not isinstance(r,dict) for r in rows):
        raise ValueError('CORRUPT_OBSERVATION_ROWS')
    return rows


def integer(v):
    if isinstance(v,bool) or v is None:
        raise ValueError('NON_INTEGER_OBSERVATION')
    try:
        n=float(v)
    except (TypeError,ValueError,OverflowError):
        raise ValueError('NON_INTEGER_OBSERVATION')
    if not n.is_integer() or not 0<=n<=200:
        raise ValueError('NON_INTEGER_OBSERVATION')
    return int(n)


def expected_values(first: list[dict], extended: list[dict]) -> dict:
    if len(first)!=20 or len(extended)!=60:
        raise ValueError('SOURCE_OBSERVATION_COUNT_DRIFT')
    expected={};seen=set();first_matches=set();ext_matches=set()
    for family,rows,allowed,expected_ready in (
        ('ace_df',first,FIRST,12), ('advanced',extended,EXTENDED,60)):
        ready=0
        for obs in rows:
            mid=str(obs.get('canonical_match_id') or '')
            field=obs.get('field')
            if mid not in TARGET_IDS or field not in allowed or (
                obs.get('source_id')!=SOURCE_FAMILY
                or (obs.get('source_version') or {}).get('content_sha256')!=SOURCE_SHA
                or (obs.get('provenance') or {}).get('raw_content_sha256')!=SOURCE_SHA
                or obs.get('scope')!='whole_match'):
                raise ValueError('UNVERIFIED_SOURCE_OBSERVATION')
            key=(mid,field)
            if key in seen:
                raise ValueError('DUPLICATE_SOURCE_CELL')
            seen.add(key)
            state=(obs.get('validation') or {}).get('state')
            if state not in ('READY_MISSING','ALREADY_PRESENT'):
                raise ValueError('NONREADY_SOURCE_OBSERVATION')
            if state!='READY_MISSING':
                if family!='ace_df':
                    raise ValueError('UNEXPECTED_ADVANCED_PRESENT_CELL')
                continue
            ready+=1
            expected[key]=integer(obs.get('value'))
            (first_matches if family=='ace_df' else ext_matches).add(mid)
        if ready!=expected_ready:
            raise ValueError('EXPECTED_READY_CELL_COUNT_DRIFT')
    if len(first_matches)!=3 or ext_matches!=TARGET_IDS or len(expected)!=72:
        raise ValueError('SOURCE_MATCH_ID_COVERAGE_DRIFT')
    return expected


def verify_retention_rows(current: dict[str,dict], expected: dict) -> dict:
    if len(expected)!=72:
        raise ValueError('EXPECTED_72_VALUES')
    found_matches=set();fields=Counter()
    for (mid,field),val in expected.items():
        if mid not in current:
            raise ValueError('MISSING_RESTORED_MATCH')
        raw=current[mid].get('stats_json')
        if not isinstance(raw,str):
            raise ValueError('NON_JSON_CANONICAL_STAT')
        stats=json.loads(raw)
        if not isinstance(stats,dict) or field not in stats or stats[field] is None:
            raise ValueError('MISSING_2023_STAT_CELL')
        if integer(stats[field])!=val:
            raise ValueError('CHANGED_2023_STAT_CELL')
        found_matches.add(mid);fields[field]+=1
    if found_matches!=TARGET_IDS:
        raise ValueError('RESTORED_MATCH_COVERAGE_DRIFT')
    return {'status':'EXACT_72_HISTORIC_CELLS_RETAINED','verified_values':72,
            'verified_matches':len(found_matches),'per_field_verified':dict(sorted(fields.items()))}


def run(prewrite:Path, current:Path, first:Path, extended:Path, report:Path):
    require_sha(prewrite,PREWRITE_SHA)
    require_sha(current,CURRENT_SHA)
    expected=expected_values(load_observations(first,FIRST_SHA),load_observations(extended,EXTENDED_SHA))
    import pandas as pd
    prior=pd.read_parquet(prewrite,engine='pyarrow')
    now=pd.read_parquet(current,engine='pyarrow')
    if (len(prior)!=107760 or len(now)!=107765 or
            list(prior.columns)!=list(now.columns) or not prior.dtypes.equals(now.dtypes)):
        raise ValueError('YEAR_PARQUET_SCHEMA_OR_COUNT_DRIFT')
    for name,frame in (('prior',prior),('current',now)):
        if (frame.match_id.isna().any() or frame.match_id.duplicated().any()
                or (frame.match_id.astype(str)=='').any()):
            raise ValueError('INVALID_CANONICAL_MATCH_ID_'+name)
    prior_ids=set(prior.match_id)
    current_ids=set(now.match_id)
    if not prior_ids.issubset(current_ids) or current_ids-prior_ids!=TARGET_IDS:
        raise ValueError('UNEXPECTED_RESTORATION_ROW_DIFF')
    before_shared=prior.set_index('match_id',drop=False).sort_index()
    after_shared=now[now.match_id.isin(prior_ids)].set_index('match_id',drop=False).sort_index()
    pd.testing.assert_frame_equal(before_shared,after_shared,check_exact=True)
    target=now[now.match_id.isin(TARGET_IDS)].set_index('match_id',drop=False)
    result=verify_retention_rows(target.to_dict('index'),expected)
    result.update({'schema':1,'prewrite_sha256':PREWRITE_SHA,
        'current_sha256':CURRENT_SHA,'first_observation_sha256':FIRST_SHA,
        'extended_observation_sha256':EXTENDED_SHA,
        'existing_rows_exactly_preserved':len(prior),
        'restored_rows_exactly_5':len(current_ids-prior_ids),
        'existing_values_overwritten':0,'cdb_writes':0,
        'model_training':False,'provider_api_requests':0,
        'note':'Read-only exact full-row parity against pinned prewrite year, plus source-observation-to-current exact 72 values. No model-use authorization.'})
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('prewrite','current','first','extended','report'):
        ap.add_argument('--'+key,required=True,type=Path)
    x=ap.parse_args()
    result=run(x.prewrite,x.current,x.first,x.extended,x.report)
    print('WIMBLEDON2023_RETENTION72 '+json.dumps({k:v for k,v in result.items() if k!='per_field_verified'},sort_keys=True))


if __name__=='__main__':
    main()
