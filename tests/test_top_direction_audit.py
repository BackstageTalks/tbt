from copy import deepcopy
from audit_top_direction import ledger_outcome, summarize


def evidence():
    source={"event_id":"event", "scheduled_at":"2026-11-07T12:00:00Z",
            "player1":{"id":"a"},"player2":{"id":"b"}}
    settled={**deepcopy(source),"result":{"winner_id":"a","scheduled_at":source["scheduled_at"]}}
    return source,settled


def test_ledger_join_requires_exact_event_players_date_and_nonvoid_result():
    source,row=evidence()
    assert ledger_outcome(source,row)=="a"
    for mutate in [lambda r:r.update(event_id="other"),lambda r:r["player2"].update(id="c"),
                   lambda r:r["result"].update(status="void"),lambda r:r["result"].update(winner_id="c"),
                   lambda r:r["result"].update(scheduled_at="2026-11-10T12:00:00Z")]:
        bad=deepcopy(row);mutate(bad)
        assert ledger_outcome(source,bad) is None


def test_missing_outcomes_never_count_as_losses_and_small_sample_is_visible():
    common={"quote_ok":True,"odds":1.70,"public":.8}
    result=summarize([{**common,"correct":True},{**common,"correct":None}])
    assert result["candidates"]==2 and result["settled"]==1
    assert result["losses"]==0 and result["profit_units"]==.7
    assert result["wilson_95"][0]<.21
