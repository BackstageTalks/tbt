from __future__ import annotations

from datetime import datetime, timezone

from tbt.repositories.supabase import SupabaseRepository


class _Response:
    def __init__(self, rows, status_code=200, text=""):
        self._rows = rows
        self.status_code = status_code
        self.text = text
        self.is_error = status_code >= 400

    def json(self):
        return self._rows


class _Client:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.calls = []

    def get(self, url, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers, "params": dict(params or {})})
        return _Response(self.chunks.pop(0))


def _repo_without_init():
    repo = object.__new__(SupabaseRepository)
    repo.base = "https://example.test/rest/v1"
    repo._headers = lambda write=False, prefer=None: {"apikey": "x"}
    return repo


def _row(match_id: str, scheduled_at: str, winner_id: str | None):
    return {
        "match_id": match_id,
        "tour": "atp",
        "scheduled_at": scheduled_at,
        "player1_id": "p1",
        "player1_name": "P1",
        "player2_id": "p2",
        "player2_name": "P2",
        "winner_id": winner_id,
        "surface": "hard",
        "provider_payload": {},
        "stats": {},
    }


def test_keyset_scan_uses_primary_key_without_completed_filter():
    repo = _repo_without_init()
    repo.client = _Client(
        [
            [_row("a", "2026-01-02T00:00:00+00:00", "p1"), _row("b", "2026-01-01T00:00:00+00:00", None)],
            [_row("c", "2026-01-03T00:00:00+00:00", "p2")],
        ]
    )

    rows = repo._select_match_rows_keyset(page_size=2)

    assert [r["match_id"] for r in rows] == ["a", "b", "c"]
    assert repo.client.calls[0]["params"]["order"] == "match_id.asc"
    assert "winner_id" not in repo.client.calls[0]["params"]
    assert repo.client.calls[1]["params"]["match_id"] == "gt.b"


def test_get_completed_matches_filters_locally_and_preserves_chronology():
    repo = _repo_without_init()
    repo._select_match_rows_keyset = lambda: [
        _row("c", "2026-01-03T00:00:00+00:00", "p2"),
        _row("a", "2026-01-01T00:00:00+00:00", "p1"),
        _row("b", "2026-01-02T00:00:00+00:00", None),
    ]

    matches = repo.get_completed_matches(
        before=datetime(2026, 1, 3, tzinfo=timezone.utc)
    )

    assert [m.match_id for m in matches] == ["a"]
