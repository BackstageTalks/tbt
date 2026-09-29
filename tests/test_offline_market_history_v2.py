from datetime import date

from tbt.data.offline_market_history import (
    build_market_history_marker,
    candidate_link,
    clean_market_history_marker,
    parse_valuebet_row,
)


def _row(**overrides):
    row = {
        "match_id": "776535",
        "date": "2025-01-01 02:00:00",
        "tournoi": "Canberra Challenger",
        "tournoi_id": "13999",
        "categorie": "Challenger",
        "genre": "atp",
        "surface": "dur",
        "tour": "12",
        "joueur1": "Harold Mayot",
        "joueur1_id": "23072",
        "joueur2": "Daniel Elahi Galan",
        "joueur2_id": "3186",
        "cote1_ouverture": "1.658",
        "cote2_ouverture": "2.250",
        "cote1_cloture": "1.680",
        "cote2_cloture": "2.240",
        "vainqueur_id": "23072",
    }
    row.update(overrides)
    return row


def test_valuebet_parser_keeps_opening_and_closing():
    parsed = parse_valuebet_row(_row(), row_number=2)
    assert parsed is not None
    assert parsed.tour == "atp"
    assert parsed.source_match_id == "776535"
    assert parsed.opening["player1_odds"] == 1.658
    assert parsed.closing["player2_odds"] == 2.24
    assert parsed.winner == "Harold Mayot"


def test_valuebet_candidate_links_exact_evidence_and_orients_market():
    source = parse_valuebet_row(_row(), row_number=2)
    linked = candidate_link(
        source,
        canonical_tour="atp",
        canonical_date=date(2025, 1, 1),
        canonical_player1="Daniel Elahi Galan",
        canonical_player2="Harold Mayot",
        canonical_winner="Harold Mayot",
        canonical_tournament="Canberra Challenger",
        canonical_surface="Hard",
        canonical_round="Final",
    )
    assert linked["accepted"] is True
    assert linked["orientation"] == "swapped"
    assert linked["opening"]["player1_odds"] == 2.25
    assert linked["opening"]["player2_odds"] == 1.658
    assert linked["closing"]["player1_odds"] == 2.24
    assert linked["closing"]["player2_odds"] == 1.68


def test_market_history_marker_explicitly_blocks_closing_as_feature():
    source = parse_valuebet_row(_row(), row_number=2)
    linked = candidate_link(
        source,
        canonical_tour="atp",
        canonical_date=date(2025, 1, 1),
        canonical_player1="Harold Mayot",
        canonical_player2="Daniel Elahi Galan",
        canonical_winner="Harold Mayot",
        canonical_tournament="Canberra Challenger",
        canonical_surface="Hard",
        canonical_round="Final",
    )
    marker = build_market_history_marker(
        source=source,
        linked=linked,
        source_label="valuebetennis_cc_by_4",
        source_file_sha256="a" * 64,
    )
    cleaned = clean_market_history_marker(marker)
    assert cleaned is not None
    assert cleaned["closing_semantics"] == "last_recorded_before_match"
    assert cleaned["model_feature_policy"] == "opening_only_candidate; closing_validation_only"


def test_valuebet_row_without_any_two_sided_market_is_rejected():
    parsed = parse_valuebet_row(
        _row(
            cote1_ouverture="",
            cote2_ouverture="",
            cote1_cloture="",
            cote2_cloture="",
        ),
        row_number=2,
    )
    assert parsed is None
