from datetime import datetime, timezone
from types import SimpleNamespace

from tbt.data.player_identity import build_crosswalk
from tbt.data.wta_rank_history import WTARankHistory


def test_identity_crosswalk_prefers_unique_exact_alias():
    canonical=[{
        "canonical_player_id":"99","tour":"wta","name":"Lucie Safarova",
        "aliases":["Lucie Šafářová"],"birth_date":"","country_code":"CZ"
    }]
    sackmann=[
        {"sackmann_player_id":"123","name":"Lucie Safarova","normalized_name":"lucie safarova",
         "short_key":"l safarova","birth_date":"19870204","country_code":"CZ","hand":"L"}
    ]
    rows,report=build_crosswalk(canonical,sackmann)
    assert report["resolved"]==1
    assert rows[0]["sackmann_player_id"]=="123"
    assert rows[0]["evidence"]=="unique_exact_alias"


def test_duplicate_name_requires_disambiguation():
    canonical=[{
        "canonical_player_id":"10","tour":"wta","name":"Ana Silva",
        "aliases":["Ana Silva"],"birth_date":"20010102","country_code":"BR"
    }]
    sackmann=[
        {"sackmann_player_id":"1","name":"Ana Silva","normalized_name":"ana silva","short_key":"a silva",
         "birth_date":"19900101","country_code":"PT","hand":"R"},
        {"sackmann_player_id":"2","name":"Ana Silva","normalized_name":"ana silva","short_key":"a silva",
         "birth_date":"20010102","country_code":"BR","hand":"R"},
    ]
    rows,report=build_crosswalk(canonical,sackmann)
    assert report["resolved"]==1
    assert rows[0]["sackmann_player_id"]=="2"
    assert rows[0]["evidence"]=="exact_alias_plus_dob"


def test_rank_history_uses_crosswalk_id_before_name():
    rows=[
        {"date":datetime(2024,12,30).date(),"rank":20,"points":1000,
         "name":"Different Published Name","sackmann_player_id":"777"}
    ]
    history=WTARankHistory(rows,canonical_to_sackmann={"42":"777"})
    snap=history._snapshot(
        "Completely Different Name",
        datetime(2025,1,2,tzinfo=timezone.utc).date(),
        player_id="42",
    )
    assert snap is not None
    assert snap["rank"]==20
