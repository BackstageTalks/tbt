from scripts.link_tennis_data_historical_odds import (
    build_sidecar,
    orient_quote,
    preferred_real_quote,
    quote_pairs,
)


def _row(**overrides):
    row = {
        "PSW": "1.80", "PSL": "2.10",
        "B365W": "1.75", "B365L": "2.20",
        "AvgW": "1.78", "AvgL": "2.12",
        "MaxW": "1.83", "MaxL": "2.25",
    }
    row.update(overrides)
    return row


def test_extracts_real_books_and_aggregates():
    quotes = quote_pairs(_row())
    assert {item["code"] for item in quotes} == {"PS", "B365", "Avg", "Max"}
    assert sum(item["quote_kind"] == "bookmaker" for item in quotes) == 2


def test_reference_prefers_pinnacle_then_bet365():
    quotes = quote_pairs(_row())
    assert preferred_real_quote(quotes)["code"] == "PS"
    only_b365 = quote_pairs(_row(PSW="", PSL=""))
    assert preferred_real_quote(only_b365)["code"] == "B365"


def test_swapped_orientation_rewrites_winner_loser_to_player1_player2():
    quote = preferred_real_quote(quote_pairs(_row()))
    oriented = orient_quote(quote, "swapped")
    assert oriented["player1_odds"] == 2.10
    assert oriented["player2_odds"] == 1.80


def test_sidecar_is_benchmark_only_and_contains_no_winner_loser_fields():
    marker = build_sidecar(
        quote_pairs(_row()),
        orientation="direct",
        source_label="operator_supplied_tennis_data",
        source_match_id="abc",
        source_file_sha256="a" * 64,
    )
    assert marker["price_kind"] == "historical_two_way_unspecified_timestamp"
    assert marker["model_feature_policy"] == "benchmark_only_no_same_match_training_feature"
    assert marker["bookmaker_count"] == 2
    encoded = str(marker).lower()
    assert "winner_odds" not in encoded
    assert "loser_odds" not in encoded
    assert marker["quotes"][0]["player1_odds"] > 1.0
    assert marker["quotes"][0]["player2_odds"] > 1.0
