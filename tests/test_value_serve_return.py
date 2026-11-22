from tbt.services import market_selection as ms


def _card(edge, winner="1"):
    return {"serve_return_edge": edge, "winner_id": winner,
            "player1": {"id": "1"}, "player2": {"id": "2"}}


def test_off_by_default(monkeypatch):
    monkeypatch.delenv(ms.ENV_VALUE_SERVE_RETURN, raising=False)
    assert ms.value_serve_return_ok(_card(None))


def test_on_keeps_only_better_serve_return_side(monkeypatch):
    monkeypatch.setenv(ms.ENV_VALUE_SERVE_RETURN, "true")
    assert ms.value_serve_return_ok(_card(0.03, "1"))
    assert not ms.value_serve_return_ok(_card(0.03, "2"))
    assert ms.value_serve_return_ok(_card(-0.02, "2"))
    assert not ms.value_serve_return_ok(_card(None, "1"))
