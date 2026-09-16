from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tbt.services.engine import _recent_form_summary


def test_recent_form_presentation_uses_up_to_35_matches():
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    recent = deque()
    for index in range(40):
        recent.append(SimpleNamespace(
            played_at=now - timedelta(days=40-index),
            won=1.0 if index % 2 == 0 else 0.0,
            surface="hard",
        ))
    state = SimpleNamespace(recent=recent)
    summary = _recent_form_summary(state, limit=35)
    assert summary["matches"] == 35
    assert len(summary["sequence"]) == 35


def test_surface_form_filters_before_lxx_sample():
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    recent = deque([
        SimpleNamespace(played_at=now - timedelta(days=i), won=1.0, surface="hard")
        for i in range(12)
    ] + [
        SimpleNamespace(played_at=now - timedelta(days=20+i), won=0.0, surface="clay")
        for i in range(8)
    ])
    state = SimpleNamespace(recent=recent)
    summary = _recent_form_summary(state, surface="hard", limit=35)
    assert summary["matches"] == 12
    assert summary["win_pct"] == 1.0


def test_frontend_contract_uses_lxx_and_ranking_movement():
    text = open("web/app.js", encoding="utf-8").read()
    assert "Form L${Math.round(form.matches)}" not in text  # label is dynamic
    assert "L${Math.round(form.matches)} = ${Math.round(form.winPct*100)}%" in text
    assert "function rankMovement" in text
    assert "previous_rank" in text
    assert "surfaceShortName" in text
