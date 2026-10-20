"""Source-level guard: historical WTA features must never become match stats."""
import csv
import hashlib
from pathlib import Path

import pytest

from scripts.cdb_wta_lookback_guard import inspect, SOURCE_FIELDS


def fixture(tmp_path: Path, *, current='4', historical='12') -> Path:
    path = tmp_path / 'wta.csv'
    fields = sorted(SOURCE_FIELDS)
    row = {k: '' for k in fields}
    row.update({'ID':'1.0', 'GameD':'2018-05-08','Name_1':'A One','Name_2':'B Two',
                'TName':'Test Event','RID_CUR':current,'RID_1':historical,'RID_2':'4',
                'GRes_CUR_1':'1','GRes_1':'0','GRes_2':'1',
                'Serve1st_1':'31','Serve1st_2':'21','Aces_1':'3','Aces_2':'4',
                'ServesTotal_1':'52','ServesTotal_2':'56','Aces_L5_1':'2','Aces_A_1':'4'})
    with path.open('w',encoding='utf-8',newline='') as out:
        writer=csv.DictWriter(out,fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_quarantines_lookback_even_when_current_matches(tmp_path):
    for historical in ('12','4'):
        path = fixture(tmp_path, historical=historical)
        result = inspect(path,sha(path))
        assert result['production_mutated'] is False
        assert result['current_match_stat_values_eligible'] == 0
        assert result['canonical_matches_confirmed'] == 0
        assert result['counts']['rows_2016_2020'] == 1
        if historical=='12':
            assert result['counts']['historical_round_differs_1'] == 1


def test_refuses_unpinned_or_unsupported_source(tmp_path):
    path=fixture(tmp_path)
    with pytest.raises(ValueError,match='SHA'):
        inspect(path,'0'*64)
    path.write_text('match_id,aces\\n1,3\\n')
    with pytest.raises(ValueError,match='schema'):
        inspect(path,sha(path))


def test_malformed_rows_fail_closed(tmp_path):
    path=fixture(tmp_path)
    with path.open('a') as stream:
        stream.write('one,two,three,extra\\n')
    with pytest.raises(ValueError,match='Malformed'):
        inspect(path,sha(path))
