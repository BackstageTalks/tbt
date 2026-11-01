"""Contract tests for autonomous MoviOdds source ingestion by existing CDB writer."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "scripts")]

from moviodds_cdb_batch import combine_stages, fetch_dates
from moviodds_cdb_format import _digest


def _populate_source(folder, days):
    folder.mkdir(parents=True, exist_ok=True)
    (folder/"report.json").write_text(json.dumps({
        "schema":1,"source":"moviodds",
        "normalized":[{"date_utc":d,"count":len(accepted)+len(rejected)}
                      for d,accepted,rejected in days],
        "unavailable":[{"date_utc":"2026-10-29",
                        "reason":"source_final_scan_unavailable_503"}],
    }))
    return folder


def _add_day(root, day, rows, review):
    f=root/day
    f.mkdir(parents=True)
    (f/"report.json").write_text(json.dumps({
        "schema":1,"source":"moviodds","raw":len(rows)+len(review),
    }))
    (f/"eligible.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows))
    (f/"review.jsonl").write_text("".join(json.dumps(r)+"\n" for r in review))


def _linked(mid, fixture, *, incoming=None, baseline=None):
    return {
        "schema":1,"import_ready":True,"match_id":mid,
        "incoming_stats": incoming or {"p1_aces":3},
        "baseline_stats":baseline or {},
        "provenance":[{"source":"moviodds","source_fixture_id":fixture,
                       "source_sha256":"a"*64}],
    }


def test_combine_keeps_only_verified_null_deltas_and_conserves_rows(tmp_path):
    first=_linked("cdb-1","source-1")
    second=_linked("cdb-2","source-2",incoming={"p2_double_faults":5})
    days=[("2026-10-30",[first],[{"source_fixture_id":"x","reason":"doubles"}]),
          ("2026-10-31",[second],[])]
    source=_populate_source(tmp_path/"source",days)
    stage=tmp_path/"stage"
    for d,ready,review in days: _add_day(stage,d,ready,review)
    out=tmp_path/"out"
    report=combine_stages(source,stage,out)
    assert report["raw"]==3
    assert report["eligible_matches"]==2
    assert report["eligible_new_values"]==2
    assert report["filtered_matches"]==1
    assert report["cdb_values_written"]==0
    assert len((out/"eligible.jsonl").read_text().splitlines())==2


def test_combine_quarantines_cross_day_duplicate_canonical_id(tmp_path):
    days=[("2026-10-30",[_linked("same","f1")],[]),
          ("2026-10-31",[_linked("same","f2")],[])]
    source=_populate_source(tmp_path/"source",days)
    root=tmp_path/"linked"
    for d,ready,review in days: _add_day(root,d,ready,review)
    report=combine_stages(source,root,tmp_path/"out")
    assert report["eligible_matches"]==0
    assert report["cross_day_ambiguous"]==1
    assert report["filtered_matches"]==2
    assert (tmp_path/"out/eligible.jsonl").read_text()==""


def test_combine_rejects_prepopulated_cell_or_dropped_day(tmp_path):
    days=[("2026-10-31",[_linked("cdb-1","f1",baseline={"p1_aces":2})],[])]
    source=_populate_source(tmp_path/"source",days)
    root=tmp_path/"linked"
    _add_day(root,*days[0])
    with pytest.raises(ValueError,match="non-NULL"):
        combine_stages(source,root,tmp_path/"out")
    (root/"2026-10-31/eligible.jsonl").write_text("")
    with pytest.raises(ValueError,match="row conservation"):
        combine_stages(source,root,tmp_path/"out")


def test_fetch_skips_only_protected_503_and_never_invents_empty(tmp_path,monkeypatch):
    import requests
    import moviodds_drive_archive as archive

    def _fetch(*,date_utc,base_url,token):
        if date_utc=="2026-10-29":
            reply=requests.Response()
            reply.status_code=503
            raise requests.HTTPError("Source final scan missing",response=reply)
        return {"schema":1,"source":"moviodds","verified":True,
                "days":[date_utc],"count":0,"records":[]}
    monkeypatch.setattr(archive,"fetch_daily_final",_fetch)
    report=fetch_dates(tmp_path,3,base_url="https://protected.example",token="secret",
                      today=datetime(2026,11,1,tzinfo=timezone.utc))
    assert [r["date_utc"] for r in report["normalized"]]==["2026-10-31","2026-10-30"]
    assert len(report["unavailable"])==1
    assert report["counts"]["normalized_rows"]==0
    assert report["cdb_mutated"] is False


def test_fetch_fails_closed_when_no_source_day_is_verified(tmp_path,monkeypatch):
    import requests
    import moviodds_drive_archive as archive
    def _unavailable(**kw):
        reply=requests.Response()
        reply.status_code=503
        raise requests.HTTPError("Source final scan missing",response=reply)
    monkeypatch.setattr(archive,"fetch_daily_final",_unavailable)
    with pytest.raises(ValueError,match="No verified source days"):
        fetch_dates(tmp_path,2,base_url="https://protected.example",token="secret",
                    today=datetime(2026,11,1,tzinfo=timezone.utc))


def test_fetch_does_not_swallow_auth_error(tmp_path,monkeypatch):
    import requests
    import moviodds_drive_archive as archive
    def _forbidden(**kw):
        reply=requests.Response()
        reply.status_code=403
        raise requests.HTTPError("Forbidden",response=reply)
    monkeypatch.setattr(archive,"fetch_daily_final",_forbidden)
    with pytest.raises(requests.HTTPError):
        fetch_dates(tmp_path,1,base_url="https://protected.example",token="secret",
                    today=datetime(2026,11,1,tzinfo=timezone.utc))


def test_no_more_than_21_days(tmp_path):
    with pytest.raises(ValueError):
        fetch_dates(tmp_path,22,base_url="https://protected.example",token="secret")
