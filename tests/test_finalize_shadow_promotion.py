from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts.finalize_shadow_promotion import (
    _build_gate_report,
    _evaluation_disposition,
    _fingerprint,
)


def _row(i, tour, target, candidate, production, elo):
    return {
        "match_id": f"m{i}",
        "scheduled_at": f"2026-10-{6 + (i % 3):02d}T12:00:00+00:00",
        "tour": tour,
        "target_player1_win": target,
        "challenger_player1_probability": candidate,
        "production_player1_probability": production,
        "elo_player1_probability": elo,
    }


def test_shadow_fingerprint_is_order_independent():
    rows = [_row(1, "atp", 1, .7, .6, .55), _row(2, "wta", 0, .3, .4, .45)]
    a = _fingerprint(rows, "prod", "cand")
    b = _fingerprint(list(reversed(rows)), "prod", "cand")
    assert a == b


def test_gate_report_contains_same_cohort_metrics():
    rows = []
    for i in range(240):
        target = i % 2
        good = .75 if target else .25
        weaker = .62 if target else .38
        elo = .58 if target else .42
        rows.append(_row(i, "atp" if i % 2 else "wta", target, good, weaker, elo))
    report = _build_gate_report(
        rows, "prod-v1", "cand-v2",
        as_of=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    assert report["holdout"]["n"] == 240
    assert report["production_holdout"]["n"] == 240
    assert report["elo_baseline_holdout"]["n"] == 240
    assert report["shadow"]["settled_utc_days"] == 3
    assert report["shadow"]["by_tour"] == {"atp": 120, "wta": 120}
    assert report["evaluation_governance"]["eligibility_reason"] is None


def test_shadow_gate_rejects_ongoing_utc_day_without_changing_cohort():
    rows = []
    for i in range(240):
        target = i % 2
        rows.append(_row(i, "atp" if i % 2 else "wta", target,
                         .75 if target else .25,
                         .62 if target else .38,
                         .58 if target else .42))
    report = _build_gate_report(
        rows, "prod-v1", "cand-v2",
        as_of=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
    )
    assert report["holdout"]["n"] == 240
    assert report["shadow"]["settled_utc_days"] == 3
    assert "shadow_holdout_contains_incomplete_utc_day" in (
        report["evaluation_governance"]["eligibility_reasons"]
    )


def test_evaluation_requires_separate_operator_approval():
    assert _evaluation_disposition(True) == "eligible_pending_approval"
    assert _evaluation_disposition(False) == "rejected"


def test_final_shadow_gate_cannot_write_any_model_release():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "finalize_shadow_promotion.py").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "final-shadow-promotion.yml").read_text(encoding="utf-8")
    assert "upload_bundle(" not in script
    assert '"approved_and_promoted"' not in script
    assert '"production_version_after": production_version' in script
    assert '"promotion_requested": False' in script
    assert "eligible_pending_approval|rejected|already_production" in workflow
    assert "approved_and_promoted" not in workflow
    legacy_pipeline = (root / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    args_pos = legacy_pipeline.index("    args = parser.parse_args()")
    guard_pos = legacy_pipeline.index("    if args.promote:", args_pos)
    first_release_io = legacy_pipeline.index("    history_store.download()", args_pos)
    assert args_pos < guard_pos < first_release_io
    assert "verified isolated champion rollback evidence" in legacy_pipeline
