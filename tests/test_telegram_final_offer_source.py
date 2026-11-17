"""BlinQ Telegram is authorized by one sealed final private offer, not Azure visibility."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_publication_barrier as barrier
import telegram_offer_publisher as tg
from tbt.services.publication import final_offer_digest


NOW = datetime(2026, 11, 18, 5, 25, tzinfo=timezone.utc)
DAY = "2026-11-18"


def sealed_offer():
    snapshot = {
        "schema": 1,
        "confirmed_only": True,
        "betting_day": DAY,
        "generated_at": "2026-11-18T05:15:00+00:00",
        "source_feed_generated_at": "2026-11-18T05:01:00+00:00",
        "market_selection": {
            "top_daily_rule": {"policy": "sports_tiered_top5_60_v24"},
        },
        "top_daily_picks": [],
        "value_picks": [],
        "ace_picks": [],
        "prime_picks": [],
        "sg_picks": [],
        "doubles_picks": [],
        "totals": {
            key: 0 for key in (
                "top_daily_picks", "value_picks", "ace_picks",
                "prime_picks", "sg_picks", "doubles_picks",
            )
        },
    }
    snapshot["final_offer"] = {
        "schema": 1, "status": "final",
        "betting_day": DAY, "confirmed_at": snapshot["generated_at"],
        "premium_sha256": final_offer_digest(snapshot),
        "issuer_run_id": 11,
    }
    return snapshot


def run(id_, created, state="completed"):
    return {"id": id_, "head_branch": "main",
            "created_at": created, "status": state}


def job(status="completed", conclusion="success",
        completed_at="2026-11-18T05:21:00Z"):
    return {"name": "Deploy current prediction generation",
            "status": status, "conclusion": conclusion,
            "completed_at": completed_at}


def test_final_signed_snapshot_is_sufficient_without_web_readback():
    snapshot = sealed_offer()
    result = barrier.verify_final_offer_snapshot(snapshot, NOW)
    assert result["status"] == "final_private_offer_verified"
    assert result["premium_sha256"] == snapshot["final_offer"]["premium_sha256"]
    history = {
        "data.yml": [{"run": run(11, "2026-11-18T05:00:00Z"),
                      "jobs": [job()]}],
        "ci.yml": [],
    }
    assert barrier.assess_final_offer_writers(history, snapshot) == {
        "status": "final_private_offer_writers_idle",
        "betting_day": DAY,
        "confirmed_at": snapshot["generated_at"],
    }


def test_unconfirmed_or_unsealed_snapshot_never_authorizes_telegram():
    snapshot = sealed_offer()
    for changed in (
        {**snapshot, "confirmed_only": False},
        {**snapshot, "final_offer": None},
        {**snapshot, "betting_day": "2026-11-17"},
        {**snapshot, "source_feed_generated_at": None},
    ):
        with pytest.raises((RuntimeError, ValueError, TypeError)):
            barrier.verify_final_offer_snapshot(changed, NOW)


def test_post_confirmation_new_pick_or_policy_change_invalidates_seal():
    snapshot = sealed_offer()
    snapshot["top_daily_picks"].append({"event_id": "new-after-final"})
    snapshot["totals"]["top_daily_picks"] += 1
    with pytest.raises(RuntimeError, match="certificate"):
        barrier.verify_final_offer_snapshot(snapshot, NOW)
    snapshot = sealed_offer()
    snapshot["market_selection"]["top_daily_rule"]["policy"] = "legacy"
    with pytest.raises(RuntimeError, match="certificate"):
        barrier.verify_final_offer_snapshot(snapshot, NOW)


def test_wrong_section_total_is_rejected_even_with_a_recomputed_digest():
    snapshot = sealed_offer()
    snapshot["totals"]["top_daily_picks"] = 1
    with pytest.raises(RuntimeError, match="incomplete"):
        barrier.verify_final_offer_snapshot(snapshot, NOW)


def test_active_publisher_prevents_early_telegram_regardless_of_seal():
    snapshot = sealed_offer()
    history = {
        "data.yml": [{"run": run(11, "2026-11-18T05:00:00Z",
                                 state="in_progress"),
                      "jobs": [job(status="in_progress", conclusion=None)]}],
        "ci.yml": [],
    }
    with pytest.raises(RuntimeError, match="still running"):
        barrier.assess_final_offer_writers(history, snapshot)


def test_newer_publication_requires_a_new_final_snapshot():
    snapshot = sealed_offer()
    history = {
        "data.yml": [{"run": run(12, "2026-11-18T05:20:00Z"),
                      "jobs": [job()]}],
        "ci.yml": [],
    }
    with pytest.raises(RuntimeError, match="newer publication"):
        barrier.assess_final_offer_writers(history, snapshot)


def test_other_writer_started_before_final_but_finished_after_is_blocked():
    """A concurrent deployment may finish after the offer was sealed."""
    source = sealed_offer()
    history = {
        "data.yml": [
            {"run": run(11, "2026-11-18T05:00:00Z"), "jobs": [job()]},
            {"run": run(22, "2026-11-18T05:10:00Z"),
             "jobs": [job(completed_at="2026-11-18T05:18:00Z")]},
        ],
        "ci.yml": [],
    }
    with pytest.raises(RuntimeError, match="newer publication"):
        barrier.assess_final_offer_writers(history, source)


def test_pending_ci_with_possible_deploy_blocks_sending():
    snapshot = sealed_offer()
    history = {
        "data.yml": [],
        "ci.yml": [{"run": run(13, "2026-11-18T05:20:00Z",
                             state="in_progress"),
                   "jobs": [{"name": "checks", "status": "in_progress"}]}],
    }
    with pytest.raises(RuntimeError, match="possible publisher"):
        barrier.assess_final_offer_writers(history, snapshot)


def test_pre_send_rejects_replaced_snapshot_before_any_telegram_request(tmp_path, monkeypatch):
    offer = sealed_offer()
    ident = f"{DAY}:daily:0620"
    tmp_path.joinpath("ready").write_text(ident, encoding="utf-8")
    tmp_path.joinpath("state.json").write_text(json.dumps({
        "attempts": {ident: {"snapshot_sha256": "0" * 64}},
    }), encoding="utf-8")
    monkeypatch.setenv("TGB", "test-telegram-credential")
    monkeypatch.setenv("TGCH", "test-chat")
    monkeypatch.setattr(tg, "snapshot", lambda *_: offer)
    monkeypatch.setattr(barrier, "verify_live_publication_barrier",
                        lambda *_a, **_kw: {"status": "final_private_offer_writers_idle"})
    calls = []
    monkeypatch.setattr(tg.urllib.request, "urlopen", lambda *_a, **_kw: calls.append(True))
    with pytest.raises(RuntimeError, match="snapshot changed after reservation"):
        tg.send(SimpleNamespace(output=str(tmp_path), now=NOW.isoformat(),
                                config_url="https://example.test/api/v1/ui-config"))
    assert calls == []


def test_workflow_waits_for_private_finality_and_never_requires_live_offer(tmp_path):
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/telegram-daily-offer.yml").read_text()
    assert "MORNING_FINAL_OFFER" in workflow
    assert "MORNING_WRITER_FINALITY" in workflow
    assert "MORNING_SITE_PARITY" not in workflow
    assert "prepare --daily --verify-site" not in workflow
    assert "final_offer_only=True" in workflow
    legacy = (root / ".github/workflows/telegram-offer.yml").read_text()
    assert "BLINQ_GITHUB_ACTIONS_TOKEN: ${{ github.token }}" in legacy
    publisher = (root / "scripts/telegram_offer_publisher.py").read_text()
    assert 'if not repost and day(now) >= EXACT_DAILY_FENCE_FROM:' in publisher
    assert '":repost:" not in reserved_id' in publisher
