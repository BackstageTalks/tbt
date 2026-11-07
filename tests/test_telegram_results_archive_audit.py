"""Read-only Telegram archive diagnostics preserve the strict settlement gate."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from telegram_results_archive_audit import mismatch_reason, verified_aces_actual_evidence


def test_exact_mismatch_is_reported_but_never_graded():
    sent = dict(event_id="123", selection_id="7", section="ace", market="aces",
                publication_key="frozen:key", market_line=4.5,
                projection_direction="over")
    archived = [dict(sent, publication_key="different")]
    assert mismatch_reason(sent, archived)["reason"] == "publication_key_mismatch"
    assert mismatch_reason(sent, [])["reason"] == "no_verified_archive_event"
    assert mismatch_reason(sent, [dict(sent, market_line=6.5)])["reason"] == "market_line_mismatch"
    assert mismatch_reason(sent, [sent]) == {
        "reason": "exact_identity_non_final_or_ambiguous", "candidates": 1,
    }


def test_november_six_receipts_are_in_strict_read_only_audit_scope():
    import json
    from telegram_results_archive_audit import DAYS
    request = json.loads((Path(__file__).resolve().parents[1] /
                          ".github/telegram-results-archive-audit-request.json").read_text())
    assert DAYS == tuple(request["days"])
    assert DAYS[-1] == "2026-11-06"
    assert request["mode"] == "read-only"
    assert request["paid_provider_requests"] == 0
    assert request["telegram_send"] is False
    assert request["cdb_writes"] is False



def test_only_final_same_player_stat_count_qualifies_for_original_aces_line():
    frozen = {"event_id": "123", "selection_id": "7", "section": "ace",
              "market": "aces", "scheduled_at": "2026-11-06T12:00:00+00:00",
              "publication_key": "local-aces-ou-v1:123:7:over:5.5"}
    base = {**frozen, "publication_key": "different-threshold",
            "result": {"actual_count": 8, "runtime_source": "match_status_snapshot",
                       "correct": True}}
    assert verified_aces_actual_evidence(frozen, [base]) == {
        "status": "unique_verified_player_count", "actual_count": 8, "sources": 1,
    }
    for altered in (
        {**base, "selection_id": "other-player"},
        {**base, "scheduled_at": "2026-11-07T12:00:00+00:00"},
        {**base, "result": {**base["result"], "runtime_source": "model_estimate"}},
        {**base, "result": {**base["result"], "actual_count": None}},
        {**base, "result": {**base["result"], "actual_count": 8.5}},
    ):
        assert verified_aces_actual_evidence(frozen, [altered])["status"] == "no_verified_player_count"
    conflicting = {**base, "result": {**base["result"], "actual_count": 9}}
    assert verified_aces_actual_evidence(frozen, [base, conflicting])["status"] == "conflicting_player_counts"
