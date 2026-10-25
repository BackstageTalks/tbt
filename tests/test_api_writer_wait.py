"""Regression tests for safe hourly API writer contention retries."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts.api_writer_wait import wait_for_writer, read_cdb_writer_lock


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/data-hourly-quota-gapfill.yml").read_text(encoding="utf-8")


def test_busy_writer_retries_until_it_frees_without_any_dispatch_or_lock_write():
    now = [datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)]
    states = [["data.yml run=1 status=in_progress"],
              ["data.yml run=1 status=in_progress"], []]
    sleeps = []

    def check():
        return states.pop(0)

    def pause(seconds):
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)

    waited = wait_for_writer(
        check, now[0] + timedelta(minutes=3),
        clock=lambda: now[0], pause=pause,
    )
    assert waited is True
    assert sleeps == [45, 45]
    assert states == []


def test_free_writer_does_not_wait():
    sleeps = []
    now = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    assert wait_for_writer(lambda: [], now + timedelta(minutes=2),
                           clock=lambda: now, pause=sleeps.append) is False
    assert sleeps == []


def test_busy_writer_expires_loudly_and_never_executes_api_requests():
    now = [datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)]
    sleeps = []
    checks = []

    def check():
        checks.append("read_only")
        return ["data.yml run=1 status=in_progress"]

    def pause(seconds):
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)

    with pytest.raises(TimeoutError, match="retry window expired"):
        wait_for_writer(check, now[0] + timedelta(seconds=60),
                        clock=lambda: now[0], pause=pause)
    assert sleeps == [45, 15]
    assert len(checks) == 3


def test_unknown_writer_state_fails_closed():
    def inaccessible_writer_state():
        raise RuntimeError("GitHub status API unavailable")

    now = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="unavailable"):
        wait_for_writer(inaccessible_writer_state, now + timedelta(minutes=1),
                        clock=lambda: now, pause=lambda _: None)


def test_hourly_workflow_rechecks_budget_and_keeps_quota_and_writer_guards():
    # Workflow must load repository files before importing scripts.api_writer_wait.
    checkout = WORKFLOW.index("      - uses: actions/checkout@v4")
    importer = WORKFLOW.index("from scripts.api_writer_wait import wait_for_writer")
    assert checkout < importer
    assert "timeout-minutes: 350" in WORKFLOW
    assert "wait_for_writer(check_writers, retry_deadline)" in WORKFLOW
    assert "now + timedelta(hours=5, minutes=40)" in WORKFLOW
    assert "expected_reset - timedelta(minutes=7)" in WORKFLOW
    assert "if waited:" in WORKFLOW
    delayed = WORKFLOW.split("          if waited:", 1)[1]
    assert "budget_response = get_json(BUDGET_URL, WORKER, worker=True)" in delayed
    assert 'budget.get("provider_plan_limit") != 15000' in delayed
    assert 'budget.get("global_limit") != 14700' in delayed
    assert 'budget.get("reserved_provider_headroom") != 300' in delayed
    assert "remaining != max(0, 14700-spent)" in delayed
    assert "reset.astimezone(timezone.utc) != expected_reset" in delayed
    assert "limit = 3000 if new_day_start else (14700 if final_topup else caps[stage_hour])" in delayed
    assert "min(3000, limit-spent, remaining, history_remaining)" in delayed
    assert "if proposed < 1:" in delayed
    assert '"hourly_autofill": "true"' in delayed
    # Lock acquisition remains with the existing governed data.yml pipeline.
    assert "git/refs" not in delayed
    assert "git/tags" not in delayed


def _private_cdb_responses(*, locked=False, bad_tag=False):
    urls = []
    prefix = "https://api.github.com/repos/BackstageTalks/tbt-data/"
    tag_sha = "a" * 40

    def get(url, token):
        assert token == "private-data-token"
        assert url.startswith(prefix)
        endpoint = url.removeprefix(prefix)
        urls.append(endpoint)
        if endpoint == "git/ref/heads/main":
            return {"ref": "refs/heads/main",
                    "object": {"type": "commit", "sha": "b" * 40}}
        if endpoint == "git/ref/tags/blinq-cdb-global-writer":
            if not locked:
                raise HTTPError(url, 404, "Not Found", {}, None)
            return {"ref": "refs/tags/blinq-cdb-global-writer",
                    "object": {"type": "tag", "sha": tag_sha}}
        if endpoint == "git/tags/" + tag_sha:
            return {"sha": tag_sha, "object": {"type": "commit"},
                    "message": ("owner=invalid"
                                if bad_tag else
                                "owner=BackstageTalks/tbt/actions/runs/123/attempts/1")}
        raise AssertionError(endpoint)

    return get, urls


def test_private_global_writer_tag_is_visible_before_hourly_dispatch():
    get, urls = _private_cdb_responses(locked=True)
    owner = read_cdb_writer_lock(get, "private-data-token")
    assert owner == [
        "CDB global writer tag owner=BackstageTalks/tbt/actions/runs/123/attempts/1"
    ]
    assert urls == [
        "git/ref/heads/main", "git/ref/tags/blinq-cdb-global-writer",
        "git/tags/" + "a" * 40,
    ]


def test_absent_lock_is_valid_only_after_private_repo_authentication():
    get, urls = _private_cdb_responses()
    assert read_cdb_writer_lock(get, "private-data-token") == []
    assert urls == ["git/ref/heads/main", "git/ref/tags/blinq-cdb-global-writer"]


def test_private_data_repo_inaccessible_or_lock_unknown_fails_closed():
    get, _ = _private_cdb_responses()
    with pytest.raises(RuntimeError, match="token unavailable"):
        read_cdb_writer_lock(get, "")
    def denied(url, token):
        raise HTTPError(url, 404, "Not Found", {}, None)
    with pytest.raises(HTTPError) as err:
        read_cdb_writer_lock(denied, "private-data-token")
    assert err.value.code == 404

    def forbidden(url, token):
        if url.endswith("git/ref/heads/main"):
            return {"ref": "refs/heads/main", "object": {"type": "commit"}}
        raise HTTPError(url, 403, "Forbidden", {}, None)
    with pytest.raises(HTTPError) as err:
        read_cdb_writer_lock(forbidden, "private-data-token")
    assert err.value.code == 403


def test_invalid_lock_owner_never_counts_as_unlocked():
    get, _ = _private_cdb_responses(locked=True, bad_tag=True)
    with pytest.raises(RuntimeError, match="ownership evidence"):
        read_cdb_writer_lock(get, "private-data-token")


def test_busy_authoritative_tag_is_polled_until_the_real_owner_releases():
    get, _ = _private_cdb_responses(locked=True)
    available, _ = _private_cdb_responses(locked=False)
    states = [get, get, available]
    now = [datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)]
    waited = wait_for_writer(
        lambda: read_cdb_writer_lock(states.pop(0), "private-data-token"),
        now[0] + timedelta(minutes=3),
        clock=lambda: now[0],
        pause=lambda seconds: now.__setitem__(0, now[0] + timedelta(seconds=seconds)),
    )
    assert waited and not states


def test_hourly_workflow_consults_private_global_lock_before_dispatch():
    assert "CDB_READ_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}" in WORKFLOW
    assert "from scripts.api_writer_wait import read_cdb_writer_lock" in WORKFLOW
    assert "active = read_cdb_writer_lock(get_json, CDB_READ_TOKEN)" in WORKFLOW
    assert WORKFLOW.index("active = read_cdb_writer_lock(") < WORKFLOW.index(
        'for status in ("queued", "pending", "in_progress", "waiting", "requested")'
    )
    assert "wait_for_writer(check_writers, retry_deadline)" in WORKFLOW
