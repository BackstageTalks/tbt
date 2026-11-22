import gzip, json
from datetime import date
from backfill_daily_bulk_odds import run


class Fake:
    request_count = 0
    def events_with_odds_for_status_day(self, day):
        self.request_count += 1
        return {"odds": {"1": {}, "2": {}}}


def test_one_call_per_day_and_no_cdb_writes(tmp_path):
    c = Fake()
    r = run(c, date(2024, 1, 1), date(2024, 1, 3), tmp_path, 10)
    assert r["days"] == 3 and r["events"] == 6 and r["cdb_writes"] == 0
    assert c.request_count == 3
    assert json.load(gzip.open(tmp_path / "2024-01-02.json.gz", "rt")) == {"odds": {"1": {}, "2": {}}}


def test_respects_max_requests(tmp_path):
    r = run(Fake(), date(2024, 1, 1), date(2024, 12, 31), tmp_path, 5)
    assert r["days"] == 5
