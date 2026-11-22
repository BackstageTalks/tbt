from tbt.services import ace_selection as acs


def test_aces_preferred_gap_parsing(monkeypatch):
    monkeypatch.delenv(acs.ENV_ACES_MIN_GAP, raising=False)
    assert acs.aces_preferred_gap() is None
    for bad in ("", "x", "0.5", "9"):
        monkeypatch.setenv(acs.ENV_ACES_MIN_GAP, bad)
        assert acs.aces_preferred_gap() is None
    monkeypatch.setenv(acs.ENV_ACES_MIN_GAP, "1.3")
    assert acs.aces_preferred_gap() == 1.3
