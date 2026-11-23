import gzip, json
from datetime import date
from itf_week_gapfill_stage import run


class Fake:
    request_count = 0
    request_limit = None
    def calendar_categories(self, day):
        self.request_count += 1
        return [{"id": 5, "name": "ITF Men"}]
    def _category_id(self, c): return c["id"]
    def category_events(self, cid, day):
        self.request_count += 1
        if day.day != 1: return []
        return [{"id": 77, "homeTeam": {"name": "Ishaan Ravichander"}, "awayTeam": {"name": "A. Kotzen"}},
                {"id": 78, "homeTeam": {"name": "X Same"}, "awayTeam": {"name": "Y Dup"}},
                {"id": 79, "homeTeam": {"name": "X Same"}, "awayTeam": {"name": "Y Dup"}}]
    def event_statistics(self, eid):
        self.request_count += 1
        return {}


def test_links_unique_pair_skips_ambiguous_no_cdb_writes(tmp_path, monkeypatch):
    import tbt.providers.statistics as st
    monkeypatch.setattr(st, "parse_statistics", lambda p, home_is_player1: {"p1_service_points_won": 0.6, "home_p1": home_is_player1})
    weeks = {date(2023, 5, 1): [{"match_id": "hist-js:1", "p1": "Alexander Kotzen", "p2": "Ishaan Ravichander"},
                                {"match_id": "hist-js:2", "p1": "X Same", "p2": "Y Dup"}]}
    r = run(Fake(), weeks, tmp_path, 500)
    assert r["linked"] == 1 and r["ambiguous"] == 1 and r["cdb_writes"] == 0
    row = json.loads(gzip.open(tmp_path / "staging.jsonl.gz", "rt").readline())
    assert row["provider_event_id"] == 77 and row["stats"]["home_p1"] is False
