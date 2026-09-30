from datetime import date

from tbt.data.offline_large_tennis_market import (
    BookQuote,
    SourceMoneylineMatch,
    TournamentMeta,
    american_to_decimal,
    build_market_sidecar,
    candidate_link,
    parse_moneyline_row,
    safe_group_match_date,
)


def _tournament():
    return TournamentMeta(
        start_date=date(2011, 5, 22),
        end_date=date(2011, 6, 5),
        tournament="roland-garros",
        surface="clay",
        location="France",
        masters=2000,
    )


def _row(**overrides):
    row = {
        "start_date": "2011-05-22",
        "book_id": "238",
        "tournament": "roland-garros",
        "book_name": "Pinnacle Sports",
        "team1": "rafael-nadal",
        "team2": "andy-murray",
        "price1": "-111.00",
        "price2": "101.00",
        "odds1": "0.5260663507109",
        "odds2": "0.497512437810945",
        "betting_date": "2011-06-03",
    }
    row.update(overrides)
    return row


def test_american_odds_conversion():
    assert abs(american_to_decimal(-111) - (1 + 100 / 111)) < 1e-12
    assert american_to_decimal(101) == 2.01
    assert american_to_decimal(0) is None


def test_moneyline_parser_validates_supplied_implied_probabilities():
    quote = parse_moneyline_row(_row(), row_number=2, tournament=_tournament())
    assert quote is not None
    assert quote.book_name == "Pinnacle Sports"
    assert quote.betting_date == date(2011, 6, 3)
    assert quote.player_a == "andy-murray"
    assert quote.player_b == "rafael-nadal"

    bad = parse_moneyline_row(
        _row(odds1="0.1"),
        row_number=2,
        tournament=_tournament(),
    )
    assert bad is None


def test_safe_group_requires_one_unique_in_window_betting_date():
    tournament = _tournament()
    first = parse_moneyline_row(_row(), row_number=2, tournament=tournament)
    second = parse_moneyline_row(
        _row(book_id="1096", book_name="BetOnline"),
        row_number=3,
        tournament=tournament,
    )
    assert safe_group_match_date([first, second], tournament) == date(2011, 6, 3)

    other_day = parse_moneyline_row(
        _row(book_id="999", betting_date="2011-06-04"),
        row_number=4,
        tournament=tournament,
    )
    assert safe_group_match_date([first, other_day], tournament) is None


def test_candidate_link_is_fail_closed_on_date_tournament_and_surface():
    tournament = _tournament()
    quote = parse_moneyline_row(_row(), row_number=2, tournament=tournament)
    source = SourceMoneylineMatch(
        source_match_id="abc",
        tournament=tournament,
        match_date=date(2011, 6, 3),
        player_a=quote.player_a,
        player_b=quote.player_b,
        quotes=(quote,),
    )
    linked = candidate_link(
        source,
        canonical_date=date(2011, 6, 3),
        canonical_player1="Rafael Nadal",
        canonical_player2="Andy Murray",
        canonical_tournament="Roland Garros",
        canonical_surface="Clay",
    )
    assert linked["accepted"] is True
    assert linked["orientation"] == "swapped"

    assert candidate_link(
        source,
        canonical_date=date(2011, 6, 4),
        canonical_player1="Rafael Nadal",
        canonical_player2="Andy Murray",
        canonical_tournament="Roland Garros",
        canonical_surface="Clay",
    )["accepted"] is False

    assert candidate_link(
        source,
        canonical_date=date(2011, 6, 3),
        canonical_player1="Rafael Nadal",
        canonical_player2="Andy Murray",
        canonical_tournament="Roland Garros",
        canonical_surface="Hard",
    )["accepted"] is False


def test_sidecar_is_benchmark_only_and_excludes_oddsportal_from_real_book_consensus():
    tournament = _tournament()
    pinnacle = parse_moneyline_row(_row(), row_number=2, tournament=tournament)
    generic = parse_moneyline_row(
        _row(
            book_id="-1",
            book_name="OddsPortal",
            price1="-200",
            price2="180",
            odds1=str(200 / 300),
            odds2=str(100 / 280),
        ),
        row_number=3,
        tournament=tournament,
    )
    source = SourceMoneylineMatch(
        source_match_id="abc",
        tournament=tournament,
        match_date=date(2011, 6, 3),
        player_a=pinnacle.player_a,
        player_b=pinnacle.player_b,
        quotes=(pinnacle, generic),
    )
    marker = build_market_sidecar(
        source,
        orientation="swapped",
        source_label="test",
        source_file_sha256="a" * 64,
    )
    assert marker["model_feature_policy"] == "benchmark_only_no_training_feature"
    assert marker["price_kind"] == "historical_moneyline_unspecified_quote_time"
    assert marker["bookmaker_count"] == 1
    assert marker["source_quote_count"] == 2
    assert marker["consensus"]["player1_fair_probability"] == pinnacle.player_b_fair_probability
