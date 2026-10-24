"""No raw loss examples may escape the read-only production audit."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from datetime import datetime, timezone
from audit_champion_weakness_current import compact, compare_published_to_market


def test_compact_omits_private_loss_rows_and_preserves_model_pair():
    top = {"window_days":45,"overall":{"settled":1,"hit_rate":0.0},
           "diagnostics":{"missing":0},
           "coverage":{"betting_day_counts":{"2026-10-24":1},"active_betting_days":1},
           "subgroups":{"competition":{"ATP":{"settled":1}},
                        "confidence_band":{},"ranking_1000":{},
                        "surface_evidence":{},"rank_and_surface":{},"stats":{}},
           "production_model_vs_history":{"history_ahead_of_training":True}}
    loss = {"window_days":21,"overall":{"settled":1},
            "by_section":{"TOP":{"settled":1}},
            "by_competition":{"ATP":{"settled":1}},
            "rule_simulations":[],"diagnostics":{},
            "losses":[{"player":"DO_NOT_EXPORT","event_id":"private-event"}]}
    shadow = {"eligible_settled":2,"overall":{"n":2},
              "eligible_rows_by_utc_day":{"2026-10-24":2}}
    report=compact(top,loss,shadow,version_breakdown={"current_version":"pinned-champ","current_45_days":{"settled":1}},ledger_sha="a",model_sha="b",history_sha="c",
                   now=datetime(2026,10,24,tzinfo=timezone.utc))
    serialized=json.dumps(report)
    assert "DO_NOT_EXPORT" not in serialized
    assert "private-event" not in serialized
    assert "betting_day_counts" not in serialized
    assert "eligible_rows_by_utc_day" not in serialized
    assert report["published_top"]["overall"]["settled"]==1
    assert report["published_top_value_losses"]["discarded_individual_loss_examples"]==1
    assert report["provider_requests"]==0
    assert report["production_mutated"] is False


def test_market_brier_compared_on_identical_real_quote_population():
    rows=[]
    for day in range(1,15):
        rows.append({"correct":bool(day%2),"probability":.9,
                     "implied_probability":.55,"implied_source":"both_sides_no_vig",
                     "betting_day":f"2026-10-{day:02d}"})
    result=compare_published_to_market(rows)
    assert result["n"] == 14
    assert result["blinq_minus_market_brier"] > 0
    assert result["paired_brier_daily_block_ci95"] is not None
    assert result["not_a_prospective_new_selector"] is True
    rows[0]["implied_source"]="one_side_raw_with_margin"
    assert compare_published_to_market(rows)["n"] == 13
