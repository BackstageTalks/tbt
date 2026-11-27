"""Display-only fixture context resolved from the caller's authorized feed."""
from datetime import datetime
import math

from tbt.data.court_speed import court_speed_venue_key


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except ValueError:
        return None


def _number(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def match_card_context(result, *, feed=None, event_id="", now):
    context = {"setting": "indoor" if result.get("surface") == "indoor_hard" else None,
               "court_speed": None, "blinq_probability": None, "odds": None, "selection_id": None}
    if not event_id or not isinstance(feed, dict):
        return context
    if event_id in (feed.get("match_statuses") or {}):
        return context
    section_names = ("daily_picks", "prime_picks", "top_daily_picks", "value_picks")
    pair = {str((result.get(side) or {}).get("player_id") or "") for side in ("player1", "player2")}
    if len(pair) != 2 or "" in pair:
        return context
    witnesses, quotes = set(), set()
    for section in (*section_names, "upcoming", "board_upcoming"):
        for row in feed.get(section) or []:
            fixture = row.get("fixture") or row
            if str(row.get("event_id") or fixture.get("event_id") or row.get("id") or "") != event_id:
                continue
            sides = {str((fixture.get(side) or row.get(side) or {}).get("id") or "") for side in ("player1", "player2")}
            start = _time(fixture.get("scheduled_at") or row.get("scheduled_at"))
            tour = str(fixture.get("tour") or row.get("tour") or "").lower()
            surface = str(fixture.get("surface") or row.get("surface") or "").lower().replace(" ", "_")
            state = fixture.get("status") or row.get("status")
            if isinstance(state, dict):
                state = state.get("type")
            if str(state or "").lower() in {"live", "inprogress", "finished", "completed", "cancelled"}:
                continue
            if sides != pair or not start or start <= now or tour != result["tour"] or surface != result["surface"]:
                continue
            venue_key = court_speed_venue_key(tour, fixture.get("tournament") or row.get("tournament"), surface)
            indoor = fixture.get("indoor")
            witnesses.add((start, venue_key, indoor if type(indoor) is bool else None))
            if section not in section_names or row.get("market", "match_winner") != "match_winner":
                continue
            issued = _time(row.get("issued_at"))
            selection = str(row.get("selection_id") or (row.get("betting") or {}).get("selection_id") or row.get("winner_id") or "")
            if row.get("publication_status") != "published" or not issued or issued > now or selection not in pair:
                continue
            probability = _number(row.get("blinq_probability"), 0, 1)
            odds = _number(row.get("odds"), 1, math.inf)
            quotes.add((selection, probability, odds if odds and odds > 1 else None))
    if not witnesses or len({row[0] for row in witnesses}) > 1:
        return context
    if len(quotes) == 1:
        context["selection_id"], context["blinq_probability"], context["odds"] = quotes.pop()
    known_settings = {row[2] for row in witnesses if row[2] is not None}
    if result["surface"] != "indoor_hard" and len(known_settings) == 1:
        context["setting"] = "indoor" if known_settings.pop() else "outdoor"
    keys = {row[1] for row in witnesses if row[1]}
    speed = result.get("_court_speed_display") or {}
    cutoff = _time(speed.get("as_of"))
    start = next(iter(witnesses))[0]
    if len(keys) == 1 and cutoff and cutoff <= now < start:
        prior = (speed.get("venues") or {}).get(keys.pop())
        if prior:
            context["court_speed"] = {**prior, "as_of": speed["as_of"]}
    return context
