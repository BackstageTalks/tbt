from datetime import datetime, timedelta, timezone
import pytest
from tbt.services.market_selection import annotate_market_publication_candidates
from tbt.services.publication import restore_published_market_snapshots, validate_market_publication_candidate, confirm_market_publications

@pytest.mark.parametrize("market", ["aces", "double_faults"])
def test_priced_player_total_keeps_ev_in_exact_publication_commitment(market):
    now=datetime(2026,10,4,8,tzinfo=timezone.utc)
    base={"event_id":"evt", "scheduled_at":(now+timedelta(hours=5)).isoformat(), "player1":{"id":"a","name":"A"}, "player2":{"id":"b","name":"B"}}
    card={**base,"market":market,"selection_id":"a","selection":"A Over 4.5", "projection":6.,"opponent_projection":2.,"projection_scope":"player","projection_metric":market,"projection_confidence":.78,"projection_label":"Player total","price_contract":"player_total_ou","ou_side":"over","market_line":4.5,"odds":2.,"probability":None,"expected_value":.24,"edge":None,"price_status":"priced_projection"}
    annotated=annotate_market_publication_candidates([base],ace_picks=[card])
    pubs=annotated[0]["market_publication_candidates"]
    assert pubs[0]["expected_value"]==.24
    ledger=[{**base,"market_publications":pubs}]
    quarantined=[]
    feed=restore_published_market_snapshots({"ace_picks":[card]},ledger,quarantine_report=quarantined)
    assert not quarantined
    assert feed["ace_picks"]==[card]
    assert validate_market_publication_candidate(feed,ledger)==1
    confirmed,n=confirm_market_publications(ledger,feed,now=now)
    assert n==1
    assert confirmed[0]["market_publications"][0]["offer_position"]==1


