from pathlib import Path

from tbt.data.provider_context import minimize_provider_payload
from tbt.match_format import explicit_best_of_from_event, provider_best_of_from_context


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
MEGA = (ROOT / "scripts/run_mega_data.py").read_text(encoding="utf-8")
SG_SCRIPT = (ROOT / "scripts/enrich_sg_history.py").read_text(encoding="utf-8")


def test_nested_explicit_best_of_is_provider_fact():
    assert explicit_best_of_from_event({"event": {"bestOf": 5}}) == 5
    assert explicit_best_of_from_event({"event": {"sets_to_play": 3}}) == 3


def test_compact_context_preserves_verified_sg_format_provenance():
    raw = {
        "_tbt_score": {
            "schema": 3,
            "event_id": "123",
            "source": "tennisapi1_event_detail",
            "fetched_at": "2026-09-18T12:00:00+00:00",
            "status": "available",
            "best_of": 5,
            "best_of_source": "provider_detail",
            "identity_verified": True,
            "format_verified": True,
            "drop_me": "large",
        },
        "_tbt_match_format": {
            "schema": 2,
            "status": "verified",
            "best_of": 5,
            "source": "provider_detail",
            "drop_me": "large",
        },
    }
    compact = minimize_provider_payload(raw)
    assert compact["_tbt_score"]["best_of"] == 5
    assert compact["_tbt_score"]["identity_verified"] is True
    assert compact["_tbt_score"]["format_verified"] is True
    assert compact["_tbt_match_format"] == {
        "schema": 2,
        "status": "verified",
        "best_of": 5,
        "source": "provider_detail",
    }
    assert provider_best_of_from_context(compact) == 5


def test_sg_rebuild_is_explicit_and_force_refreshes_provider_detail():
    assert "sg-rebuild" in WORKFLOW
    rebuild_branch = WORKFLOW.split('elif [[ "$MODE" == sg-rebuild ]]', 1)[1].split(
        'elif [[ "$MODE" == provider-probe ]]', 1
    )[0]
    assert "--rebuild-existing" in rebuild_branch
    assert "--force-provider-refresh" in rebuild_branch
    assert "sg_projection_dry_run.json" in WORKFLOW


def test_normal_mega_data_does_not_force_refetch_verified_sg_rows():
    # The expensive recurring orchestration must remain incremental/idempotent.
    assert '"scripts/enrich_sg_history.py"' in MEGA
    assert "--force-provider-refresh" not in MEGA
    assert "sg_projection_dry_run.json" in MEGA


def test_sg_script_has_fail_closed_rebuild_contract():
    for token in (
        "provider_score_conflict",
        "--rebuild-existing",
        "--force-provider-refresh",
        "ProviderError",
        "sg_projection_dry_run.json",
    ):
        assert token in SG_SCRIPT
