from probe_itf_stats_availability import run, norm_last


class Fake:
    request_count = 0
    def calendar_categories(self, day):
        self.request_count += 1
        return [{"id": 5, "name": "ITF Men"}, {"id": 6, "name": "ATP"}]
    def _category_id(self, c):
        return c["id"]
    def category_events(self, cid, day):
        self.request_count += 1
        return [{"id": 99, "homeTeam": {"name": "A. Kotzen"}, "awayTeam": {"name": "Ishaan Ravichander"}}]
    def event_statistics(self, eid):
        self.request_count += 1
        return {"statistics": [{"x": 1}]}


def test_probe_matches_by_last_names_and_counts_stats():
    req = {"max_requests": 100, "days": [{"day": "2023-03-27", "matches": [
        {"p1": "Alexander Kotzen", "p2": "Ishaan Ravichander", "tournament": "M15"}]}]}
    r = run(Fake(), req)
    s = r["samples"][0]
    assert s["matched"] == 1 and s["stats_available"] == 1 and r["cdb_writes"] == 0
    assert norm_last("Dino Prižmić") == "prizmic"
