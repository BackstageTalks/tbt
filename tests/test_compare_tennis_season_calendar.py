"""Offline exact-source and pagination safety tests for season/calendar trial."""
from datetime import date, datetime, timezone

from compare_tennis_season_calendar import compare, probe, native_context


def event(eid, *, unique=77, season=2016, tourney=99,
          timestamp="2016-07-09T14:00:00+00:00", discipline="singles", status="finished"):
    return {
        "id": eid,
        "tournament": {"id": tourney,
                       "uniqueTournament": {"id": unique},
                       "category": {"id": 8}},
        "season": {"id": season},
        "startTimestamp": int(datetime.fromisoformat(timestamp).timestamp()),
        "eventType": discipline, "status": {"type": status},
        "homeTeam": {"id": 11}, "awayTeam": {"id": 12},
    }


def comparison(calendar, season, complete=True):
    return compare(calendar, season, unique_id=77, season_id=2016,
                   first=date(2016, 7, 9), last=date(2016, 7, 10),
                   calendar_calls=4, season_calls=2, complete=complete)


def test_exact_sets_and_same_metadata_are_required():
    a, b = event(7115726), event(7115727)
    good = comparison([a, b], [b, a])
    assert good["status"] == "EXACT_COVERAGE_VERIFIED"
    assert good["calendar_event_ids"] == ["7115726", "7115727"]
    assert good["calendar_requests_including_retries"] == 4
    assert good["season_requests_including_retries"] == 2
    assert good["switch_allowed"] is False
    miss = comparison([a, b], [a])
    assert miss["status"] == "REVIEW_REQUIRED"
    assert miss["calendar_missing_from_season"] == ["7115727"]


def test_unique_tournament_not_ordinary_tournament_id():
    a = event(7115726, unique=77, tourney=99)
    assert native_context(a)["unique_tournament"] == 77
    assert comparison([a], [a])["status"] == "EXACT_COVERAGE_VERIFIED"
    assert comparison([a], [event(7115726, unique=99)])["status"] == "REVIEW_REQUIRED"


def test_postponed_doubles_unknown_and_start_shift_never_auto_promoted():
    a = event(7115726, status="postponed")
    b = event(7115726, discipline="unknown")
    c = event(7115726, timestamp="2016-07-11T11:00:00+00:00")
    assert comparison([a], [a])["status"] == "REVIEW_REQUIRED"
    assert comparison([b], [b])["status"] == "REVIEW_REQUIRED"
    assert comparison([c], [c])["calendar_event_ids"] == []
    assert comparison([event(7115726)], [event(7115726)], complete=False)["status"] == "REVIEW_REQUIRED"


class Provider:
    def __init__(self):
        self.request_count = 0
        self.calls = []
    def _get(self, path, *, enrichment=False):
        self.request_count += 1
        self.calls.append(path)
        if path == "/api/tennis/event/7115726":
            return {"event": event(7115726)}
        if path.endswith("/last/0"):
            return {"events": [event(7115726)]}
        return {"events": []}
    def calendar_categories(self, day):
        self.request_count += 1
        return [{"id": 8}]
    def _category_id(self, obj):
        return obj["id"]
    def category_events(self, category_id, day):
        self.request_count += 1
        return [event(7115726)]


def test_small_probe_starts_at_page_zero_counts_paid_and_stops_on_empty_page():
    p = Provider()
    report = probe(p, "7115726", date(2016, 7, 9), date(2016, 7, 10))
    assert p.calls[1].endswith("/events/last/0")
    assert p.calls[2].endswith("/events/last/1")
    assert report["season_pagination_complete"] is True
    assert report["status"] == "EXACT_COVERAGE_VERIFIED"
    assert p.request_count == 7


def test_incomplete_pages_never_enable_switch():
    class Endless(Provider):
        def _get(self, path, *, enrichment=False):
            self.request_count += 1
            if path.startswith("/api/tennis/event/"):
                return {"event": event(7115726)}
            self.calls.append(path)
            return {"events": [event(7115726)]}
    p = Endless()
    result = probe(p, "7115726", date(2016, 7, 9), date(2016, 7, 10), max_pages=1)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["season_pagination_complete"] is False
