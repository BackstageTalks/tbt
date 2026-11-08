"""Read-only Most Aces display bridge for pre-feature issued ESÁ offers.

The next prediction run publishes independently selected `most_aces` picks.
Until then a deployed UI can display an already-issued O/U card's *frozen*
pre-match ace-leader hint. This is NOT a new market issuance or a settled bet.
Never add these rows to the ledger, saved feed, results, KPI or ROI.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unicodedata


def _aware(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def _issued_leader(row, feed):
    if not isinstance(row, dict) or str(row.get("market") or "") != "aces":
        return None
    if str(row.get("projection_model") or "") != "ace-count-projection-v4":
        return None
    event_id = str(row.get("event_id") or "").strip()
    player1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    player2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    selected_id = str(row.get("selection_id") or "").strip()
    selected = [p for p in (player1, player2) if str(p.get("id") or "").strip() == selected_id]
    if not event_id or len(selected) != 1:
        return None
    # The ball is the original two-player projection leader, never an
    # inferred favourite after seeing actual results.
    def normalized(value):
        raw = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(c.lower() if c.isalnum() else " " for c in raw if not unicodedata.combining(c)).split()

    hint = row.get("aces_superiority_hint") or row.get("projection_subject")
    hint_id = str(row.get("aces_superiority_player_id") or row.get("projection_subject_id") or "").strip()
    selected_name = selected[0].get("name")
    if not ((hint and normalized(hint) == normalized(selected_name))
            or (hint_id and hint_id == selected_id)):
        return None
    try:
        projection = float(row["projection"])
        opponent = float(row["opponent_projection"])
        confidence = float(row["projection_confidence"])
    except (ValueError, TypeError, KeyError):
        return None
    if not (0 <= opponent < projection < 100 and 0.60 <= confidence <= 0.93):
        return None
    scheduled = _aware(row.get("scheduled_at"))
    if scheduled is None:
        return None
    # There are two valid kinds of issuance proof:
    #  1. The row embeds a single frozen published O/U contract; or
    #  2. The original, immutable row was passed through the server-side
    #     issued-authority manifest after deployment. The source asset may
    #     still contain a pending pre-deploy candidate at that instant.
    pubs = row.get("market_publications") or []
    if not isinstance(pubs, list) or len(pubs) > 1:
        return None
    publication = pubs[0] if pubs else None
    if publication is not None:
        if (not isinstance(publication, dict)
                or str(publication.get("section") or "") != "ace"
                or str(publication.get("market") or "") != "aces"
                or str(publication.get("selection_id") or "").strip() != selected_id
                or str(publication.get("publication_status") or "") not in {"pending", "published"}):
            return None
        explicit_issue = _aware(publication.get("issued_at"))
        if publication.get("issued_at") and (explicit_issue is None or explicit_issue >= scheduled):
            return None
        if (str(publication.get("publication_status")) == "published"
                and explicit_issue is not None):
            return event_id, selected_id, publication

    # A pending / absent nested ledger object is *not* proof by itself.
    # In the API this helper is called only after filter_unissued_offers,
    # which has checked every row against the persisted authority receipt.
    issued_generation = _aware(feed.get("generated_at"))
    if (feed.get("publication_authority_status") != "confirmed"
            or issued_generation is None or issued_generation >= scheduled):
        return None
    return event_id, selected_id, publication or {}


def with_issued_ace_leader_signals(payload: dict) -> dict:
    """Use already-visible, pre-match ESÁ balls while no independent issue exists.

    Runs *after* the issued-authority check but *before* per-level filtering.
    A derived row is an explicit non-settleable display signal. When a normal
    Most Aces publication exists for an event, never mix it with its
    fallback ESÁ signal.
    """
    rows = payload.get("ace_picks")
    if not isinstance(rows, list) or not rows:
        return payload
    # An independently issued Most Aces card only supersedes the same event.
    # A global early return would hide every valid ESÁ ball whenever even
    # one other event in the feed has its own Most Aces card.
    independent_events = {
        str(row.get("event_id") or "").strip()
        for row in rows
        if isinstance(row, dict)
        and str(row.get("market") or "").strip().lower() == "most_aces"
        and str(row.get("event_id") or "").strip()
    }
    by_event: dict[str, list[tuple[dict, str, dict]]] = {}
    for row in rows:
        leader = _issued_leader(row, payload)
        if leader is None:
            continue
        event, player, publication = leader
        by_event.setdefault(event, []).append((row, player, publication))
    derived = []
    for event, entries in by_event.items():
        if event in independent_events:
            continue
        # Conflicting player identities, ambiguous publications or duplicate
        # lines are not safe leader predictions. Reject the entire event.
        if len(entries) != 1:
            continue
        original, selected_id, issued = entries[0]
        bridge = deepcopy(original)
        bridge.update({
            "market": "most_aces",
            "market_type": "Most Aces · ESÁ leader signal",
            "projection_metric": "most_aces",
            "projection_kind": "player_most_aces",
            "projection_label": "Viac es · už publikovaný signál ESÁ",
            "price_contract": "player_superiority",
            "price_status": "projection_only",
            "selection_id": selected_id,
            "odds": None,
            "probability": None,
            "edge": None,
            "expected_value": None,
            "market_line": None,
            "ou_side": None,
            "betting": None,
            "market_publications": [],
            "result": None,
            "ace_winner_source": "issued_aces_signal_only",
            "ace_winner_source_publication": str(issued.get("publication_key") or ""),
            "ace_winner_issued": False,
        })
        derived.append(bridge)
    if not derived:
        return payload
    # Never mutate the original issued snapshot or turn a visible signal into
    # a market publication. Normal per-tier access still governs these rows.
    result = dict(payload)
    result["ace_picks"] = rows + derived
    return result
