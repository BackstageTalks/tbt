"""Lightweight prediction publication state transitions.

This module intentionally depends only on the Python standard library so the
post-deploy confirmation step does not require the training/scientific stack.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
from zoneinfo import ZoneInfo


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
    "doubles": "doubles_picks",
    # Projection-only markets are frozen at deploy time so Results can later
    # grade the exact projection that users actually saw.
    "ace": "ace_picks",
    "double_faults": "ace_picks",
    "sets": "sg_picks",
    "games": "sg_picks",
}


def _section_feed_rows(feed, section, key):
    rows = feed.get(key, [])
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError(f"Invalid market section: {key}")
    if section in {"ace", "double_faults", "sets", "games"}:
        expected_market = "aces" if section == "ace" else section
        return [
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("market") or "").strip().lower() == expected_market
        ]
    return rows


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
        # Projection identity. These are None for Match Winner publications.
        row.get("projection"),
        row.get("opponent_projection"),
        row.get("projection_scope"),
        row.get("projection_metric"),
        row.get("projection_confidence"),
        row.get("projection_label"),
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
        publication.get("projection"),
        publication.get("opponent_projection"),
        publication.get("projection_scope"),
        publication.get("projection_metric"),
        publication.get("projection_confidence"),
        publication.get("projection_label"),
    )


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
        for feed_row in _section_feed_rows(feed, section, key):
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


def restore_published_market_snapshots(feed, ledger):
    """Reuse a uniquely identified issued snapshot; never rewrite the ledger.

    Current predictions may drift after an offer was issued. Only a published
    snapshot with the same event/section/market/selection/betting day may replace
    that presentation. Unknown, pending-only or ambiguous mismatches still fail.
    """
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid market publication artifacts")
    result = deepcopy(feed)
    index = {}
    for row in ledger:
        if not isinstance(row, dict):
            continue
        event = str(row.get("event_id") or "").strip()
        if event in index:
            raise ValueError(f"Duplicate publication ledger event: {event}")
        index[event] = row
    for section, key in _MARKET_SECTION_KEYS.items():
        key_present = key in result
        rows = _section_feed_rows(result, section, key)

        # Odds-backed bets remain strictly fail-closed: a deployment must never
        # guess which price/probability users were shown. Projection-only ESA
        # cards are different: legacy ledgers can contain more than one issued
        # snapshot for the same event/player/metric because early schemas had no
        # betting-day identity. When such a legacy row cannot be resolved
        # uniquely, omit only that projection from the serving feed rather than
        # blocking the entire application deployment. Nothing is rewritten in
        # the ledger, and no projection is invented. A fresh refresh will create
        # the canonical v2 publication candidate.
        restored_rows = []
        for row in rows:
            commitment = _market_commitment_from_feed_row(row, section)
            publications = [p for p in index.get(commitment[0], {}).get("market_publications", []) or [] if isinstance(p, dict)]
            if any(_market_commitment_from_publication(commitment[0], p) == commitment for p in publications):
                restored_rows.append(row)
                continue

            matches = []
            for publication in publications:
                stored = _market_commitment_from_publication(commitment[0], publication)
                same_identity = stored[:4] == commitment[:4] and stored[8] == commitment[8]
                # Projection scope + metric are part of the semantic identity.
                # They disambiguate e.g. player aces from any future totals.
                if section in {"ace", "double_faults", "sets", "games"}:
                    same_identity = (
                        same_identity
                        and stored[11] == commitment[11]
                        and stored[12] == commitment[12]
                    )
                if same_identity and publication.get("issued_at") and publication.get("publication_status") == "published":
                    matches.append(publication)

            if section in {"ace", "double_faults", "sets", "games"} and matches:
                # Multiple ledger rows are safe only when they encode exactly the
                # same immutable projection snapshot. Collapse lifecycle-only
                # duplicates; never choose between conflicting projections.
                unique = {}
                for publication in matches:
                    signature = _market_commitment_from_publication(commitment[0], publication)
                    unique.setdefault(signature, publication)
                matches = list(unique.values())

            if len(matches) != 1:
                if section in {"ace", "double_faults", "sets", "games"}:
                    # Fail closed at card granularity for legacy projection
                    # corruption. The rest of the site remains deployable and a
                    # subsequent refresh regenerates a clean publication row.
                    continue
                raise RuntimeError(f"Market feed/ledger mismatch for {section} event {commitment[0]}; no unique issued snapshot")

            snapshot = matches[0]
            betting = row.get("betting")
            if isinstance(betting, dict):
                for field in ("odds", "model_probability", "edge", "expected_value", "fair_implied_probability", "captured_at", "provider_id", "selection"):
                    betting[field] = deepcopy(snapshot.get(field))
            for field, source in (("probability", "model_probability"), ("odds", "odds"), ("edge", "edge"), ("expected_value", "expected_value"), ("fair_implied_probability", "fair_implied_probability"), ("pick", "selection"), ("selection", "selection")):
                if field in row or not betting:
                    row[field] = deepcopy(snapshot.get(source))
            # Prime cards read player probabilities rather than the flattened
            # market probability. Keep both presentations of this offer aligned.
            probability = snapshot.get("model_probability")
            players = [row.get("player1"), row.get("player2")]
            if isinstance(probability, (int, float)) and 0 <= probability <= 1 and all(isinstance(p, dict) for p in players):
                selected = [p for p in players if str(p.get("id")) == commitment[3]]
                if len(selected) == 1:
                    for player in players:
                        player["probability"] = probability if player is selected[0] else 1 - probability
                    row["confidence"] = max(probability, 1 - probability)
            if section in {"ace", "double_faults", "sets", "games"}:
                for field in (
                    "projection", "opponent_projection", "reference_projection", "market_line",
                    "projection_gap", "projection_scope", "projection_metric",
                    "projection_direction", "projection_confidence", "projection_label",
                    "projection_kind", "projection_subject", "projection_samples",
                    "projection_unit", "best_of", "data_depth", "price_status",
                    "provider_id", "captured_at", "odds_market_name",
                ):
                    if field in snapshot:
                        row[field] = deepcopy(snapshot.get(field))
            restored_rows.append(row)

        if key_present:
            if key in {"sg_picks", "ace_picks"}:
                expected_market = "aces" if section == "ace" else section
                untouched = [
                    item for item in result.get(key, []) or []
                    if not isinstance(item, dict)
                    or str(item.get("market") or "").strip().lower() != expected_market
                ]
                result[key] = untouched + restored_rows
            else:
                result[key] = restored_rows
    validate_market_publication_candidate(result, ledger)
    return result



def _row_betting_day(row, *, timezone_name="Europe/Bratislava", start_hour=6):
    """Resolve one public row to the BlinQ betting day (06:00 local boundary)."""
    if not isinstance(row, dict):
        return ""
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    explicit = str(row.get("betting_day") or betting.get("betting_day") or "").strip()
    if explicit:
        return explicit
    raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
    if not raw:
        return ""
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return ""
    zone = ZoneInfo(timezone_name)
    local = moment.astimezone(zone)
    boundary = local.replace(hour=int(start_hour), minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.date().isoformat()


def _current_betting_day(now, *, timezone_name="Europe/Bratislava", start_hour=6):
    if now.tzinfo is None:
        raise ValueError("carry-forward now must be timezone-aware")
    zone = ZoneInfo(timezone_name)
    local = now.astimezone(zone)
    boundary = local.replace(hour=int(start_hour), minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.date().isoformat()


def carry_forward_betting_day_market_rows(
    feed, prior_feed, ledger, *, now=None, timezone_name="Europe/Bratislava", start_hour=6
):
    """Keep already-issued daily market rows visible for the whole betting day.

    The live refresh may stop returning an event as soon as it starts.  That is
    correct for provider discovery but wrong for the product's daily published
    offer: users must still be able to see what BlinQ published earlier that
    morning.  This helper therefore carries only rows with *issued* publication
    evidence from the previous deployed candidate, preserves their original
    order/snapshot, and appends genuinely new current-day candidates afterwards.

    Pending/unconfirmed rows are never carried after they disappear, so a failed
    deployment cannot accidentally publish a pick for the first time after start.
    """
    if not isinstance(feed, dict) or not isinstance(prior_feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid daily snapshot artifacts")
    now = now or datetime.now(timezone.utc)
    day = _current_betting_day(now, timezone_name=timezone_name, start_hour=start_hour)
    result = deepcopy(feed)

    ledger_index = {}
    for source in ledger:
        if not isinstance(source, dict):
            continue
        event_id = str(source.get("event_id") or "").strip()
        if event_id:
            ledger_index[event_id] = source

    report = {"betting_day": day, "carried": {}, "new": {}, "total": {}}
    processed_keys = set()
    for section, key in _MARKET_SECTION_KEYS.items():
        # ace/double_faults and games/sets share one physical feed list. Process
        # each list once, while still checking each row against its own section.
        if key in processed_keys:
            continue
        processed_keys.add(key)
        current_rows = result.get(key) if isinstance(result.get(key), list) else []
        prior_rows = prior_feed.get(key) if isinstance(prior_feed.get(key), list) else []

        def row_section(row):
            market = str((row.get("betting") or {}).get("market") if isinstance(row.get("betting"), dict) else row.get("market") or "").strip().lower()
            market = market or str(row.get("market") or row.get("projection_metric") or "").strip().lower()
            if key == "ace_picks":
                return "double_faults" if market == "double_faults" else "ace" if market == "aces" else ""
            if key == "sg_picks":
                return market if market in {"games", "sets"} else ""
            return {"top_daily_picks":"top_daily","prime_picks":"prime","value_picks":"value","doubles_picks":"doubles"}.get(key, "")

        def issued_exact(row):
            sec = row_section(row)
            if not sec:
                return False
            try:
                commitment = _market_commitment_from_feed_row(row, sec)
            except ValueError:
                return False
            source = ledger_index.get(commitment[0]) or {}
            for publication in source.get("market_publications", []) or []:
                if not isinstance(publication, dict):
                    continue
                if not publication.get("issued_at") or str(publication.get("publication_status") or "") != "published":
                    continue
                try:
                    if _market_commitment_from_publication(commitment[0], publication) == commitment:
                        return True
                except ValueError:
                    continue
            return False

        def identity(row):
            sec = row_section(row)
            if not sec:
                return None
            event_id = str(row.get("event_id") or "").strip()
            # Freeze one public choice per event+section+betting-day. If the
            # model/provider later changes selection/line, yesterday's public
            # commitment must not silently mutate during the same day.
            return (event_id, sec, _row_betting_day(row, timezone_name=timezone_name, start_hour=start_hour))

        kept=[]; seen=set(); carried=0
        for row in prior_rows:
            if not isinstance(row, dict):
                continue
            if _row_betting_day(row, timezone_name=timezone_name, start_hour=start_hour) != day:
                continue
            if not issued_exact(row):
                continue
            ident=identity(row)
            if not ident or ident in seen:
                continue
            kept.append(deepcopy(row)); seen.add(ident); carried += 1

        new_count=0
        for row in current_rows:
            if not isinstance(row, dict):
                continue
            if _row_betting_day(row, timezone_name=timezone_name, start_hour=start_hour) != day:
                continue
            ident=identity(row)
            if not ident or ident in seen:
                continue
            kept.append(deepcopy(row)); seen.add(ident); new_count += 1

        result[key] = kept
        report["carried"][key] = carried
        report["new"][key] = new_count
        report["total"][key] = len(kept)

    result["market_selection"] = {
        **(result.get("market_selection") or {}),
        "daily_offer_snapshot": report,
    }
    return result, report

def confirm_market_publications(ledger, deployed_feed, now=None):
    """Confirm section-specific betting publications after deployment."""
    now = now or datetime.now(timezone.utc)
    validate_market_publication_candidate(deployed_feed, ledger)

    deployed = set()
    for section, key in _MARKET_SECTION_KEYS.items():
        for row in _section_feed_rows(deployed_feed, section, key):
            commitment = _market_commitment_from_feed_row(row, section)
            deployed.add(commitment)

    confirmed = []
    newly_confirmed = 0
    for source in ledger:
        row = dict(source)
        publications = [dict(item) for item in row.get("market_publications", []) or [] if isinstance(item, dict)]
        for publication in publications:
            if publication.get("issued_at") or publication.get("publication_status") == "published":
                continue
            section = str(publication.get("section") or "").strip()
            commitment = _market_commitment_from_publication(row.get("event_id"), publication)
            if section not in _MARKET_SECTION_KEYS or commitment not in deployed:
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
