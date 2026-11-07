"""Read-only Telegram archive diagnostics preserve the strict settlement gate."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from telegram_results_archive_audit import mismatch_reason


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
