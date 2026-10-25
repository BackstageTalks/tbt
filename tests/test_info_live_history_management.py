"""Durable admin history retention: cross-kind isolation and independent read-back.

Pure in-memory Azure Table emulation; these tests never touch production content.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbt.services import admin_storage as storage


class Table:
    def __init__(self):
        self.rows = {}
        self.fail_tombstones = False

    def upsert_entity(self, entity, mode=None):
        if entity["PartitionKey"] == "live-deletions" and self.fail_tombstones:
            raise OSError("tombstone store unavailable")
        key=(entity["PartitionKey"],entity["RowKey"])
        self.rows[key]=deepcopy(entity) if mode!="merge" else {**self.rows.get(key,{}),**deepcopy(entity)}

    def get_entity(self, partition_key, row_key):
        return deepcopy(self.rows[(partition_key,row_key)])

    def query_entities(self, query_filter=None):
        partition=query_filter.split("'",2)[1] if query_filter else ""
        return [deepcopy(v) for (pk,_),v in self.rows.items() if pk==partition]

    def delete_entity(self,partition_key,row_key):
        del self.rows[(partition_key,row_key)]


@pytest.fixture
def tables(monkeypatch):
    tables={}
    monkeypatch.setattr(storage,"_table",lambda name: tables.setdefault(name,Table()))
    return tables


def _row(table,partition,key,*,dt,kind="",type_="vip",audience="levels"):
    table.upsert_entity({
        "PartitionKey":partition,"RowKey":key,"kind":kind,"type":type_,
        "audience_mode":audience,"created_at":dt,"settled_at":dt,
    })


def _setup(tables):
    tab=tables.setdefault(storage.INSIGHTS_TABLE,Table())
    now=datetime(2026,10,25,12,0,tzinfo=timezone.utc)
    old=(now-timedelta(hours=50)).isoformat()
    recent=(now-timedelta(hours=2)).isoformat()
    # One old+new INFO, one unrelated project message, and one other manual LIVE.
    _row(tab,"insights","msg-info-old",dt=old)
    _row(tab,"insights","msg-info-new",dt=recent)
    _row(tab,"insights","msg-project-old",dt=old,audience="groups")
    _row(tab,"insights","alert-manual-old",dt=old,type_="alert")
    _row(tab,"info-results","info-result-old",dt=old)
    _row(tab,"info-results","info-result-new",dt=recent)
    _row(tab,"info-results","info-result-project",dt=old,audience="groups")
    for kind in ("comeback","set2"):
        prefix="live-comeback" if kind=="comeback" else "live-set2"
        _row(tab,"insights",f"{prefix}-old",dt=old,type_="alert" if kind=="comeback" else "set2")
        _row(tab,"insights",f"{prefix}-new",dt=recent,type_="alert" if kind=="comeback" else "set2")
        _row(tab,"live-results",f"live-result-{kind}-old",dt=old,kind=kind)
        _row(tab,"live-results",f"live-result-{kind}-new",dt=recent,kind=kind)
    _row(tab,"insights","msg-info-unknown",dt="broken")
    return tab,now


def test_info_24h_deletes_only_old_info_and_outcomes_not_projects_or_live(tables):
    t,now=_setup(tables)
    result=storage.cleanup_history("info",older_than_hours=24,now=now,actor_id="admin")
    assert result["deleted_messages"]==1 and result["deleted_results"]==1
    assert result["failed"]==0 and result["unknown_age_skipped"]==1
    assert ("insights","msg-info-old") not in t.rows
    assert ("info-results","info-result-old") not in t.rows
    for key in ("msg-info-new","msg-info-unknown","msg-project-old","alert-manual-old","live-set2-old","live-comeback-old"):
        assert ("insights",key) in t.rows
    assert ("info-results","info-result-project") in t.rows
    assert ("live-results","live-result-comeback-old") in t.rows


@pytest.mark.parametrize("kind",["comeback","set2"])
def test_live_delete_all_scoped_with_tombstones_and_replay_protection(tables,kind):
    t,now=_setup(tables)
    result=storage.cleanup_history(kind,delete_all=True,actor_id="admin",now=now)
    assert result["deleted"]==4 and result["failed"]==0
    prefix="live-comeback" if kind=="comeback" else "live-set2"
    for age in ("old","new"):
        assert ("insights",f"{prefix}-{age}") not in t.rows
        assert ("live-results",f"live-result-{kind}-{age}") not in t.rows
        assert ("live-deletions",f"insight:{prefix}-{age}") in t.rows
        assert ("live-deletions",f"result:live-result-{kind}-{age}") in t.rows
    other="set2" if kind=="comeback" else "comeback"
    assert ("live-results",f"live-result-{other}-old") in t.rows
    assert ("insights","msg-info-old") in t.rows


def test_failed_live_tombstone_never_deletes_protected_row(tables):
    table,now=_setup(tables)
    table.fail_tombstones=True
    result=storage.cleanup_history("comeback",older_than_hours=24,now=now)
    assert result["failed"]==2 and result["deleted"]==0
    assert ("insights","live-comeback-old") in table.rows
    assert ("live-results","live-result-comeback-old") in table.rows


def test_retention_settings_readback_legacy_reset_and_worker(tables):
    assert storage.history_retention_settings()=={"info":0,"comeback":0,"set2":0}
    assert storage.save_info_result_retention(7,actor_id="test")==7
    saved=storage.save_history_retention("info",72,actor_id="admin")
    assert saved["settings"]["info"]==72
    assert storage.info_result_retention_days()==0
    assert storage.save_history_retention("comeback",24,actor_id="admin")["retention_hours"]==24
    assert storage.save_history_retention("set2",168,actor_id="admin")["retention_hours"]==168
    table,now=_setup(tables)
    # All test rows are old in 2026; run at controlled clock by mocking storage clock
    # in this case simply assert the complete, persisted worker contract without
    # assuming the wall clock equals the fixture timestamp.
    outcome=storage.run_history_retention(actor_id="worker")
    assert set(outcome["results"])=={"info","comeback","set2"}
    assert outcome["failed"]==0
    assert set(outcome["settings"])=={"info","comeback","set2"}


@pytest.mark.parametrize("kind,value",[
    ("other",24),("info",-1),("info",1),("comeback",25),
    ("set2","72"),("set2",True),("set2",None),
])
def test_retention_rejects_invalid_inputs(tables,kind,value):
    with pytest.raises(ValueError):
        storage.save_history_retention(kind,value,actor_id="admin")


def test_complete_partition_delete_beyond_admin_preview_limit(tables):
    tab=tables.setdefault(storage.INSIGHTS_TABLE,Table())
    for i in range(310):
        _row(tab,"info-results",f"info-result-mass-{i}",dt="2026-10-01T12:00:00Z")
    result=storage.cleanup_history("info",delete_all=True)
    assert result["deleted_results"]==310 and result["failed"]==0
    assert not tab.rows


def test_frontend_and_scheduled_job_contract():
    root=Path(__file__).resolve().parents[1]
    app=(root/"web/app.js").read_text(encoding="utf-8")
    auth=(root/"web/auth.js").read_text(encoding="utf-8")
    api=(root/"api/function_app.py").read_text(encoding="utf-8")
    schedule=(root/".github/workflows/history-retention.yml").read_text(encoding="utf-8")
    for kind in ("info","comeback","set2"):
        assert f"'{kind}'" in app
    assert 'data-admin-action="history-delete-older"' in app
    assert 'data-admin-action="history-delete-all"' in app
    assert 'data-admin-action="history-retention-save"' in app
    assert 'DELETE HISTORY ' in auth and 'DELETE HISTORY ' in api
    assert 'def internal_history_retention_worker' in api
    assert 'X-Blinq-Worker-Token' in schedule
    assert "workflow_dispatch:" in schedule
    assert "  schedule:" not in schedule
    live=(root/".github/workflows/live-radar.yml").read_text(encoding="utf-8")
    assert "/api/v1/internal/history-retention-worker" in live
    assert "run_history_retention_guarded" in api


def test_admin_history_endpoint_fails_closed_without_confirmation(monkeypatch):
    import function_app as api
    import json

    class Req:
        def __init__(self,method,payload=None):
            self.method=method
            self.payload=payload
        def get_json(self):
            return self.payload

    monkeypatch.setattr(api,"_admin_user",lambda req: ({"id":"admin-test"},None))
    monkeypatch.setattr(api,"history_retention_settings",lambda: {"info":0,"comeback":72,"set2":168})
    calls=[]
    monkeypatch.setattr(api,"cleanup_history",lambda kind,**kwargs: calls.append((kind,kwargs)) or {
        "kind":kind,"deleted":2,"deleted_messages":1,"deleted_results":1,"failed":0
    })
    response=api.admin_history_retention(Req("POST",{
        "kind":"comeback","mode":"all","confirmation":"NO",
    }))
    assert response.status_code==400 and not calls
    response=api.admin_history_retention(Req("POST",{
        "kind":"comeback","mode":"older_than_24h",
        "confirmation":"DELETE HISTORY COMEBACK OLDER_THAN_24H",
    }))
    assert response.status_code==200
    assert json.loads(response.get_body())["deleted"]==2
    assert len(calls)==1 and calls[0][0]=="comeback"
    assert calls[0][1]["older_than_hours"]==24
    assert calls[0][1]["delete_all"] is False


def test_history_worker_is_secret_guarded(monkeypatch):
    import function_app as api

    class Req:
        method="POST"
    calls=[]
    monkeypatch.delenv("BLINQ_LIVE_WORKER_TOKEN",raising=False)
    monkeypatch.setattr(api,"run_history_retention_guarded",lambda: calls.append(True))
    assert api.internal_history_retention_worker(Req()).status_code==503
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN","secret")
    monkeypatch.setattr(api,"_live_worker_token_ok",lambda req: False)
    assert api.internal_history_retention_worker(Req()).status_code==403
    assert not calls
