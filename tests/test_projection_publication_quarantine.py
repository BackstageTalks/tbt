"""Keep real ACES/DF bets deployable without making up legacy snapshots."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pipeline import _projection_presentation_integrity
from tbt.services.publication import (
    restore_published_market_snapshots, validate_market_publication_candidate,
)


def _row(event, market, odds=2.0, projection=5.2):
    return {
        "event_id": event, "market": market, "selection_id": "player-1",
        "selection": "A Over 4.5 Aces", "odds": odds,
        "projection": projection, "opponent_projection": 2.3,
        "projection_scope": "player", "projection_metric": market,
        "projection_confidence": .77, "projection_label": "Hráč · Esá",
        "price_status": "priced_projection", "provider_id": 2,
        "captured_at": "2026-09-26T10:00:00Z",
    }


def _publication(row, *, projection=None, issued=None):
    market = row["market"]
    return {
        "publication_key": f"ace:projection:{market}:player:{row['event_id']}:player-1",
        "section": "ace" if market == "aces" else "double_faults",
        "market": market, "selection_id": "player-1", "selection": row["selection"],
        "odds": row["odds"], "model_probability": None, "edge": None,
        "expected_value": None, "betting_day": None,
        "projection": row["projection"] if projection is None else projection,
        "opponent_projection": row["opponent_projection"],
        "projection_scope": row["projection_scope"],
        "projection_metric": row["projection_metric"],
        "projection_confidence": row["projection_confidence"],
        "projection_label": row["projection_label"],
        "issued_at": issued,
        "publication_status": "published" if issued else "pending",
    }


def test_fresh_real_provider_ace_and_df_survive_restore_and_integrity():
    aces = _row("ace-new", "aces")
    df = _row("df-new", "double_faults")
    feed = {"ace_picks": [aces, df], "sg_picks": []}
    ledger = [{"event_id": row["event_id"],
               "market_publications": [_publication(row)]}
              for row in (aces, df)]
    quarantine = []
    restored = restore_published_market_snapshots(feed, ledger,
                                                   quarantine_report=quarantine)
    assert not quarantine
    assert len(restored["ace_picks"]) == 2
    assert validate_market_publication_candidate(restored, ledger) == 2
    report = _projection_presentation_integrity(
        restored, ace_picks=[aces, df], sg_picks=[], quarantined=quarantine,
    )
    assert report["ok"] is True
    assert report["published"]["aces"] == 1
    assert report["published"]["double_faults"] == 1


def test_legacy_conflict_drops_only_ambiguous_ace_and_preserves_safe_df():
    aces = _row("ace-legacy", "aces")
    df = _row("df-new", "double_faults")
    prior = _publication(aces, projection=4.8, issued="2026-09-26T09:00:00Z")
    conflict = _publication(aces, projection=6.2, issued="2026-09-26T09:30:00Z")
    feed = {"ace_picks": [aces, df], "sg_picks": []}
    ledger = [
        {"event_id": aces["event_id"],
         "market_publications": [prior, conflict]},
        {"event_id": df["event_id"],
         "market_publications": [_publication(df)]},
    ]
    quarantine = []
    restored = restore_published_market_snapshots(
        feed, ledger, quarantine_report=quarantine,
    )
    assert [x["market"] for x in restored["ace_picks"]] == ["double_faults"]
    assert quarantine == [{
        "event_id": "ace-legacy", "market": "aces",
        "reason": "ambiguous_issued_legacy_snapshots",
    }]
    assert validate_market_publication_candidate(restored, ledger) == 1
    report = _projection_presentation_integrity(
        restored, ace_picks=[aces, df], sg_picks=[], quarantined=quarantine,
    )
    assert report["ok"] is True
    assert report["ledger_quarantined"]["aces"] == 1
    assert report["published"]["double_faults"] == 1
    assert ledger[0]["market_publications"] == [prior, conflict]


def test_unknown_projection_loss_still_fails_and_never_fakes_a_bet():
    aces = _row("ace-new", "aces")
    with pytest.raises(RuntimeError, match="unexplained selector output loss"):
        _projection_presentation_integrity(
            {"ace_picks": [], "sg_picks": []}, ace_picks=[aces],
        )
    with pytest.raises(RuntimeError, match="unexplained selector output loss"):
        _projection_presentation_integrity(
            {"ace_picks": [], "sg_picks": []}, ace_picks=[aces],
            quarantined=[{"event_id": "some-other", "market": "games"}],
        )
