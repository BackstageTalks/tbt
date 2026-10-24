"""No raw loss examples may escape the read-only production audit."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from datetime import datetime, timezone
from audit_champion_weakness_current import compact


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
