from datetime import datetime, timedelta, timezone
import pytest
from tbt.services import login_metrics as metrics, auth

class Conflict(Exception): status_code=409
class Table:
    def __init__(self): self.rows={}
    def create_entity(self, row):
        key=(row['PartitionKey'],row['RowKey'])
        if key in self.rows: raise Conflict()
        self.rows[key]=row
    def query_entities(self,query_filter):
        partition=query_filter.split("'")[1]
        return [v for (p,r),v in self.rows.items() if p==partition]

@pytest.fixture
def table(monkeypatch):
    t=Table();monkeypatch.setattr(metrics,'_table',lambda _:t);return t

def test_distinct_logins_are_idempotent_and_account_isolated(table):
    now=datetime(2026,10,5,10,tzinfo=timezone.utc)
    first=now.timestamp()-10
    assert metrics.record_login('a',first,now=now)
    assert not metrics.record_login('a',first,now=now)
    assert metrics.record_login('a',first+1,now=now)
    assert metrics.record_login('b',first,now=now)
    stats=metrics.load_login_statistics(['a','b','c'])
    assert [stats[x]['login_count'] for x in ['a','b','c']]==[2,1,0]

@pytest.mark.parametrize('value',[None,'invalid',float('nan'),float('inf'),0])
def test_invalid_or_old_login_does_not_create_event(table,value):
    assert not metrics.record_login('a',value)
    assert not table.rows

def test_pre_tracking_sessions_and_future_tokens_are_not_backfilled(table):
    now=datetime(2026,10,5,10,tzinfo=timezone.utc)
    assert not metrics.record_login('a',datetime(2026,10,3,tzinfo=timezone.utc).timestamp(),now=now)
    assert not metrics.record_login('a',(now+timedelta(hours=1)).timestamp(),now=now)
    assert not table.rows

def test_api_requests_and_token_refresh_do_not_count_as_new_logins(monkeypatch):
    calls=[];user={'id':'a','_auth_time':1791190000}
    auth._LOGIN_OBSERVATIONS.clear()
    monkeypatch.setattr(auth,'auth_provider',lambda _: 'firebase')
    monkeypatch.setattr(auth,'_verify_firebase_user',lambda *a:dict(user))
    monkeypatch.setattr(auth,'_touch_verified_activity',lambda _:None)
    monkeypatch.setattr(metrics,'record_login',lambda *a:calls.append(a))
    for token in ['Bearer first','Bearer first','Bearer refreshed']:
        assert auth.verify_user(token,None)['id']=='a'
    assert len(calls)==1
    user['_auth_time']+=1
    auth.verify_user('Bearer new-login',None)
    assert len(calls)==2
    auth._LOGIN_OBSERVATIONS.clear()

def test_metrics_outage_never_blocks_auth_and_retries(monkeypatch):
    auth._LOGIN_OBSERVATIONS.clear();calls=[]
    monkeypatch.setattr(auth,'auth_provider',lambda _: 'firebase')
    monkeypatch.setattr(auth,'_verify_firebase_user',lambda *a:{'id':'retry','_auth_time':1791190000})
    monkeypatch.setattr(auth,'_touch_verified_activity',lambda _:None)
    def fail(*a):calls.append(a);raise RuntimeError('storage offline')
    monkeypatch.setattr(metrics,'record_login',fail)
    assert auth.verify_user('Bearer a',None)['id']=='retry'
    assert auth.verify_user('Bearer a',None)['id']=='retry'
    assert len(calls)==2
