from datetime import date, datetime, timezone
from types import SimpleNamespace

from scripts.integrate_kaggle_research_bundle import (
    _candidate_match,
    _norm_name,
    _parse_date,
    _parse_dt,
)


def test_name_normalization_is_accent_and_punctuation_safe():
    assert _norm_name("Barbora Krejčíková") == "barbora krejcikova"
    assert _norm_name("Jean-Pierre Smith") == "jean pierre smith"


def test_date_parsers_accept_iso_utc():
    assert _parse_date("2026-06-11T12:30:00Z") == date(2026, 6, 11)
    value = _parse_dt("2026-06-11T12:30:00Z")
    assert value == datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)


def test_candidate_match_requires_positive_context():
    match = SimpleNamespace(
        match_id="m1",
        scheduled_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        tour="wta",
        player1_name="Aryna Sabalenka",
        player2_name="Coco Gauff",
        tournament="Berlin",
        surface="Grass",
        round_name="Quarterfinal",
    )
    pair = tuple(sorted((_norm_name(match.player1_name), _norm_name(match.player2_name))))
    index = {(date(2026, 6, 11).isoformat(), pair): [match]}
    linked, reason = _candidate_match(
        source_date=date(2026, 6, 11),
        player1="Coco Gauff",
        player2="Aryna Sabalenka",
        tour="WTA",
        tournament="Berlin",
        surface="Grass",
        round_name="Quarterfinal",
        date_pair=index,
    )
    assert reason is None
    assert linked[0].match_id == "m1"
    assert "date_exact" in linked[1]


def test_candidate_match_rejects_surface_conflict():
    match = SimpleNamespace(
        match_id="m1",
        scheduled_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        tour="atp",
        player1_name="A",
        player2_name="B",
        tournament="Test Open",
        surface="Clay",
        round_name="Final",
    )
    pair = tuple(sorted((_norm_name("A"), _norm_name("B"))))
    index = {(date(2026, 6, 11).isoformat(), pair): [match]}
    linked, reason = _candidate_match(
        source_date=date(2026, 6, 11),
        player1="A",
        player2="B",
        tour="ATP",
        tournament="Test Open",
        surface="Grass",
        round_name="Final",
        date_pair=index,
    )
    assert linked is None
    assert reason == "unmatched"
