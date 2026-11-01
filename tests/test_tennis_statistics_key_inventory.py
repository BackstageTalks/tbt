"""Read-only statistics key inventory coverage."""
from tbt.providers.statistics import inventory_statistics_keys, parse_statistics


def test_inventory_includes_unknown_keys_on_partial_success():
    payload = {"statistics": [
        {"period": "ALL", "groups": [{"statisticsItems": [
            {"key": "aces", "home": "4", "away": "3"},
            {"key": "netPointsWon", "home": "2/4", "away": "1/3"},
        ]}]},
        {"period": "1ST", "groups": [{"statisticsItems": [
            {"key": "aces", "home": "1", "away": "2"},
            {"key": "setOnlyUnknown", "home": "1", "away": "1"},
        ]}]},
    ]}
    report = inventory_statistics_keys(payload)
    assert report == {
        "supported": ["aces"],
        "unsupported": ["netpointswon"],
        "set_only": ["aces", "setonlyunknown"],
        "invalid_envelope": False,
    }
    assert parse_statistics(payload, home_is_player1=True)["p1_aces"] == 4


def test_inventory_rejects_invalid_envelope_and_leaks_no_values():
    assert inventory_statistics_keys({"statistics": "bad"})["invalid_envelope"] is True
    payload = {"statistics": [{"period": "ALL", "groups": [
        {"statisticsItems": [{"key": "SecretLookingName", "home": "private-value"}]}
    ]}]}
    report = inventory_statistics_keys(payload)
    assert report["unsupported"] == ["secretlookingname"]
    assert "private-value" not in str(report)


def test_inventory_never_promotes_set_only_to_whole_match():
    payload = {"statistics": [{"period": "SET 1", "groups": [
        {"statisticsItems": [{"key": "firstServePoints", "home": "1/2"}]}
    ]}]}
    assert inventory_statistics_keys(payload)["supported"] == []
    assert inventory_statistics_keys(payload)["set_only"] == ["firstservepoints"]
