from pathlib import Path

WORKFLOW = Path(".github/workflows/wimbledon-research.yml")
REQUEST = Path(".github/wimbledon-research-request.json")
PIN = "2e7db5b3d505c92a60edd4528f88f443adfcf196"


def test_wimbledon_research_workflow_is_pinned_and_not_model_promoted():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert PIN in text
    assert "tbt-wimbledon-research-v1" in text
    assert "research_only_not_promoted; sparse grass-specific historical prior" in text
    assert "api_requests" in text
    assert "TENNIS_API" not in text
    assert "RAPIDAPI" not in text


def test_wimbledon_request_keeps_research_only_policy():
    text = REQUEST.read_text(encoding="utf-8")
    assert '"policy": "research_only_not_promoted"' in text
    assert "No production model wiring" in text
