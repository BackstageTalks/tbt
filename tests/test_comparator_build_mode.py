from pathlib import Path


def test_comparator_build_mode_is_provider_free_and_deployable():
    workflow = Path(".github/workflows/data.yml").read_text(encoding="utf-8")
    script = Path("scripts/build_comparator_artifact.py").read_text(encoding="utf-8").lower()

    assert "comparator-build" in workflow
    assert "python scripts/build_comparator_artifact.py" in workflow
    assert "contains(github.event.head_commit.message, '[comparator-build]')" in workflow

    for forbidden in (
        "rapidtennisclient",
        "proplineclient",
        "rapidapi_key",
        "request_budget",
        "provider.matches_for_day",
        "provider.upcoming",
    ):
        assert forbidden not in script

    assert '"provider_api_requests": 0' in script
    assert "persisted_readback" in script
    assert "tbt-model-production-v1" in script
    assert "tbt-data-v1" in script
    assert "tbt-predictions-v1" in script
    assert "upload_bundle([out])" in script
