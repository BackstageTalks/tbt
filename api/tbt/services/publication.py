"""Lightweight prediction publication state transitions.

This module intentionally depends only on the Python standard library so the
post-deploy confirmation step does not require the training/scientific stack.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _prediction_commitment(row):
    """Return the immutable prediction identity that a public feed commits to.

    Publication is about a concrete pick/probability, not just an event id.
    Mutable lifecycle fields such as ``issued_at``, ``publication_status`` and
    later result data are deliberately excluded.
    """
    if not isinstance(row, dict):
        raise ValueError("Invalid prediction publication row")

    event_id = str(row.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("Prediction publication row is missing event_id")

    player1 = row.get("player1")
    player2 = row.get("player2")
    if not isinstance(player1, dict) or not isinstance(player2, dict):
        raise ValueError(f"Prediction publication row {event_id} is missing players")

    p1_id = str(player1.get("id") or "").strip()
    p2_id = str(player2.get("id") or "").strip()
    if not p1_id or not p2_id or p1_id == p2_id:
        raise ValueError(f"Prediction publication row {event_id} has invalid player identity")

    if player1.get("probability") is None or player2.get("probability") is None:
        raise ValueError(f"Prediction publication row {event_id} is missing probabilities")
    winner_id = str(row.get("winner_id") or "").strip()
    if winner_id not in {p1_id, p2_id}:
        raise ValueError(f"Prediction publication row {event_id} has invalid winner_id")

    scheduled_at = str(row.get("scheduled_at") or "").strip()
    model_version = str(row.get("model_version") or "").strip()
    if not scheduled_at or not model_version:
        raise ValueError(
            f"Prediction publication row {event_id} is missing schedule/model identity"
        )

    return (
        event_id,
        str(row.get("id") or ""),
        scheduled_at,
        model_version,
        str(row.get("created_at") or ""),
        p1_id,
        player1.get("probability"),
        p2_id,
        player2.get("probability"),
        winner_id,
        row.get("confidence"),
    )


def _index_published_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("Published prediction rows must be a list")
    indexed = {}
    for row in rows:
        commitment = _prediction_commitment(row)
        event_id = commitment[0]
        if event_id in indexed:
            raise ValueError(f"Duplicate published prediction event_id: {event_id}")
        indexed[event_id] = commitment
    return indexed


def validate_publication_candidate(feed, ledger):
    """Bind every upcoming feed pick to the exact corresponding ledger pick.

    The serving feed may be a subset of the ledger, but a row that is public
    must commit to the same players, probability, winner, model and schedule as
    the ledger record that will later receive ``issued_at``.
    """
    if not isinstance(feed, dict):
        raise ValueError("Invalid prediction feed")
    upcoming = feed.get("upcoming")
    if not isinstance(upcoming, list):
        raise ValueError("Invalid prediction feed: upcoming")
    if not isinstance(ledger, list):
        raise ValueError("Invalid prediction ledger")

    ledger_index = {}
    for row in ledger:
        if not isinstance(row, dict):
            raise ValueError("Invalid prediction ledger row")
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("Prediction ledger row is missing event_id")
        if event_id in ledger_index:
            raise ValueError(f"Duplicate prediction ledger event_id: {event_id}")
        ledger_index[event_id] = row

    published = _index_published_rows(upcoming)
    for event_id, commitment in published.items():
        ledger_row = ledger_index.get(event_id)
        if ledger_row is None:
            raise RuntimeError(
                f"Prediction feed/ledger mismatch: {event_id} is missing from ledger"
            )
        if _prediction_commitment(ledger_row) != commitment:
            raise RuntimeError(
                f"Prediction feed/ledger mismatch for event {event_id}; "
                "refusing to publish or confirm a different pick"
            )
    return upcoming


def confirm_publication(ledger, published_rows, now=None):
    """Confirm first public availability after a successful deployment.

    Confirmation requires the exact immutable prediction commitment that was
    deployed, not merely a matching event id. If the match has already started,
    the record is excluded rather than backdated. Existing issued_at values are
    immutable.
    """
    now = now or datetime.now(timezone.utc)
    published = _index_published_rows(published_rows)
    confirmed = []
    seen_ledger_ids = set()

    for source in ledger:
        if not isinstance(source, dict):
            raise ValueError("Invalid prediction ledger row")
        row = dict(source)
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("Prediction ledger row is missing event_id")
        if event_id in seen_ledger_ids:
            raise ValueError(f"Duplicate prediction ledger event_id: {event_id}")
        seen_ledger_ids.add(event_id)

        deployed_commitment = published.get(event_id)
        if deployed_commitment is None or row.get("issued_at"):
            confirmed.append(row)
            continue
        commitment = _prediction_commitment(row)
        if deployed_commitment != commitment:
            raise RuntimeError(
                f"Deployed prediction does not match ledger commitment for event {event_id}"
            )

        scheduled_at = datetime.fromisoformat(row["scheduled_at"])
        if scheduled_at <= now:
            row["publication_status"] = "expired_unpublished"
            row["excluded_reason"] = "not_confirmed_before_start"
        else:
            row["issued_at"] = now.isoformat()
            row["publication_status"] = "published"
        confirmed.append(row)
    return sorted(confirmed, key=lambda r: r["scheduled_at"])


_MARKET_SECTION_KEYS = {
    "top_daily": "top_daily_picks",
    "prime": "prime_picks",
    "value": "value_picks",
}


def _market_commitment_from_feed_row(row, section):
    if not isinstance(row, dict):
        raise ValueError("Invalid market publication feed row")
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    event_id = str(row.get("event_id") or "").strip()
    selection_id = str(betting.get("selection_id") or row.get("selection_id") or "").strip()
    market = str(betting.get("market") or row.get("market") or "").strip()
    if not event_id or not selection_id or not market:
        raise ValueError(f"Invalid {section} market publication identity")
    return (
        event_id,
        section,
        market,
        selection_id,
        betting.get("odds") if betting else row.get("odds"),
        betting.get("model_probability") if betting else row.get("probability"),
        betting.get("edge") if betting else row.get("edge"),
        betting.get("expected_value") if betting else row.get("expected_value"),
        betting.get("betting_day") if betting else row.get("betting_day"),
    )


def _market_commitment_from_publication(event_id, publication):
    if not isinstance(publication, dict):
        raise ValueError("Invalid market publication ledger row")
    return (
        str(event_id or "").strip(),
        str(publication.get("section") or "").strip(),
        str(publication.get("market") or "").strip(),
        str(publication.get("selection_id") or "").strip(),
        publication.get("odds"),
        publication.get("model_probability"),
        publication.get("edge"),
        publication.get("expected_value"),
        publication.get("betting_day"),
    )



def _market_publication_is_published(publication):
    return bool(
        isinstance(publication, dict)
        and (
            publication.get("issued_at")
            or publication.get("publication_status") == "published"
        )
    )


def _same_market_offer(event_id, section, commitment, publication):
    """Match the stable offer identity while deliberately ignoring mutable odds.

    A successful public deployment freezes the first auditable price snapshot.
    Later provider refreshes may return a different price for the same event,
    selection, section and betting day; those refreshed values must not silently
    replace the already-issued public commitment.
    """
    if not isinstance(publication, dict):
        return False
    return (
        str(event_id or "").strip() == str(commitment[0] or "").strip()
        and str(publication.get("section") or "").strip() == str(section or "").strip()
        and str(publication.get("market") or "").strip() == str(commitment[2] or "").strip()
        and str(publication.get("selection_id") or "").strip() == str(commitment[3] or "").strip()
        and str(publication.get("betting_day") or "").strip() == str(commitment[8] or "").strip()
    )


def _restore_market_card_snapshot(feed_row, ledger_row, publication):
    """Restore an already-issued market card to its ledger-backed snapshot."""
    betting = dict(feed_row.get("betting") or {})
    snapshot_fields = (
        "market",
        "selection",
        "selection_id",
        "odds",
        "fair_implied_probability",
        "model_probability",
        "edge",
        "expected_value",
        "provider_id",
        "captured_at",
        "betting_day",
    )
    for key in snapshot_fields:
        if key in publication:
            betting[key] = publication.get(key)
    feed_row["betting"] = betting

    # Market cards expose convenience aliases used directly by the web UI.
    alias_map = {
        "market": "market",
        "selection": "selection",
        "selection_id": "selection_id",
        "odds": "odds",
        "edge": "edge",
        "expected_value": "expected_value",
        "fair_implied_probability": "fair_implied_probability",
        "betting_day": "betting_day",
    }
    for target, source in alias_map.items():
        if source in publication:
            feed_row[target] = publication.get(source)
    feed_row["pick"] = publication.get("selection")
    feed_row["probability"] = publication.get("model_probability")

    # Prime cards are rendered from player probabilities/winner_id rather than
    # the market-card aliases, so restore the immutable model commitment too.
    if isinstance(ledger_row, dict):
        feed_row["winner_id"] = ledger_row.get("winner_id")
        feed_row["confidence"] = ledger_row.get("confidence")
        feed_row["model_version"] = ledger_row.get("model_version")
        feed_row["scheduled_at"] = ledger_row.get("scheduled_at", feed_row.get("scheduled_at"))
        for key in ("data_depth", "quality", "signals"):
            if key in ledger_row:
                feed_row[key] = ledger_row.get(key)
        for player_key in ("player1", "player2"):
            frozen = ledger_row.get(player_key)
            current = feed_row.get(player_key)
            if isinstance(frozen, dict) and isinstance(current, dict):
                current["probability"] = frozen.get("probability")

    return feed_row


def reconcile_market_feed_with_ledger(feed, ledger):
    """Repair refresh-time market cards using immutable issued ledger snapshots.

    Pending publications are still allowed to refresh normally. Only an offer
    that has already been successfully issued is frozen. This keeps the public
    feed auditable while allowing a failed private candidate from a prior run to
    recover without deleting or rewriting publication history.
    """
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid market publication artifacts")

    ledger_index = {
        str(row.get("event_id") or "").strip(): row
        for row in ledger
        if isinstance(row, dict) and str(row.get("event_id") or "").strip()
    }
    restored = 0
    for section, key in _MARKET_SECTION_KEYS.items():
        rows = feed.get(key, [])
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise ValueError(f"Invalid market section: {key}")
        for feed_row in rows:
            commitment = _market_commitment_from_feed_row(feed_row, section)
            event_id = commitment[0]
            ledger_row = ledger_index.get(event_id)
            if not isinstance(ledger_row, dict):
                continue

            publications = [
                item
                for item in ledger_row.get("market_publications", []) or []
                if isinstance(item, dict)
            ]
            # Already exact: current pending snapshot or frozen issued snapshot.
            if any(
                _market_commitment_from_publication(event_id, item) == commitment
                for item in publications
            ):
                continue

            issued = [
                item
                for item in publications
                if _market_publication_is_published(item)
                and _same_market_offer(event_id, section, commitment, item)
            ]
            if len(issued) == 1:
                _restore_market_card_snapshot(feed_row, ledger_row, issued[0])
                restored += 1

    if restored:
        meta = feed.setdefault("market_selection", {})
        if isinstance(meta, dict):
            meta["restored_issued_snapshots"] = restored
    return restored


def validate_market_publication_candidate(feed, ledger):
    """Bind every odds-backed section row to an exact ledger snapshot.

    This prevents a Daily / Prime / Value row from being deployed with odds or a
    selection that are not represented in the private publication ledger.
    """
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid market publication artifacts")
    ledger_index = {}
    for row in ledger:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "").strip()
        if event_id:
            ledger_index[event_id] = row

    validated = 0
    for section, key in _MARKET_SECTION_KEYS.items():
        rows = feed.get(key, [])
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise ValueError(f"Invalid market section: {key}")
        for feed_row in rows:
            commitment = _market_commitment_from_feed_row(feed_row, section)
            event_id = commitment[0]
            ledger_row = ledger_index.get(event_id)
            if ledger_row is None:
                raise RuntimeError(f"Market feed/ledger mismatch: {event_id} missing from ledger")
            candidates = [
                item for item in ledger_row.get("market_publications", []) or []
                if isinstance(item, dict)
                and _market_commitment_from_publication(event_id, item) == commitment
            ]
            if not candidates:
                raise RuntimeError(
                    f"Market feed/ledger mismatch for {section} event {event_id}; "
                    "refusing to publish an untracked odds snapshot"
                )
            validated += 1
    return validated


def confirm_market_publications(ledger, deployed_feed, now=None):
    """Confirm section-specific betting publications after deployment."""
    now = now or datetime.now(timezone.utc)
    validate_market_publication_candidate(deployed_feed, ledger)

    deployed = {}
    for section, key in _MARKET_SECTION_KEYS.items():
        for row in deployed_feed.get(key, []) or []:
            commitment = _market_commitment_from_feed_row(row, section)
            deployed[(section, commitment[0])] = commitment

    confirmed = []
    newly_confirmed = 0
    for source in ledger:
        row = dict(source)
        publications = [dict(item) for item in row.get("market_publications", []) or [] if isinstance(item, dict)]
        for publication in publications:
            if publication.get("issued_at") or publication.get("publication_status") == "published":
                continue
            section = str(publication.get("section") or "").strip()
            commitment = deployed.get((section, str(row.get("event_id") or "").strip()))
            if commitment is None:
                continue
            if _market_commitment_from_publication(row.get("event_id"), publication) != commitment:
                continue
            scheduled_at = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
            if scheduled_at.tzinfo is None:
                raise ValueError("Naive market publication schedule")
            if now >= scheduled_at:
                publication["publication_status"] = "expired_unpublished"
                publication["excluded_reason"] = "not_confirmed_before_start"
                continue
            publication["issued_at"] = now.isoformat()
            publication["publication_status"] = "published"
            newly_confirmed += 1
        row["market_publications"] = publications
        confirmed.append(row)
    return confirmed, newly_confirmed
