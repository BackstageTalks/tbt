from pathlib import Path
import pandas as pd
import pytest
import restore_wimbledon2023_exact_five as r

def test_missing_rows_are_appended_without_mutating_older_current_rows(tmp_path, monkeypatch):
    ids=sorted(r.TARGET_IDS)
    def rows(keys):
        return pd.DataFrame([{"match_id":k,"tour":"wta","scheduled_at":"2023-07-01",
                              "player1_id":"a","player2_id":"b","winner_id":"a",
                              "player1_name":"A","player2_name":"B","tournament":"Wimbledon",
                              "stats_json":'{"first": 99}' } for k in keys])
    backup=rows(ids+["existing"])
    current=rows(["existing"])
    backup_path=tmp_path/"backup.parquet"; before=tmp_path/"before.parquet"
    after=tmp_path/"restored.parquet"
    backup.to_parquet(backup_path,index=False);current.to_parquet(before,index=False)
    monkeypatch.setattr(r,"BACKUP_SHA",r.sha256(backup_path))
    monkeypatch.setattr(r,"invalid_reason",lambda x: None)
    output=r.build(backup_path,before,after,mode="write")
    assert output["new_rows"]==5 and output["overwritten_existing_values"]==0
    assert output["existing_rows_preserved"]==1
    r.build(backup_path,before,after,mode="verify")
    assert pd.read_parquet(after)["match_id"].tolist()==["existing"]+ids

def test_fails_closed_if_backup_changes(tmp_path):
    src=tmp_path/"fake.parquet";src.write_bytes(b"not the immutable 2023 backup")
    with pytest.raises(ValueError,match="checksum"):
        r.build(src,src,tmp_path/"out.parquet",mode="write")
