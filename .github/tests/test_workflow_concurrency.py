from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_production_deploy_does_not_share_history_writer_concurrency():
    ci = _workflow("ci.yml")
    environment = _workflow("environment-enrichment.yml")
    player = _workflow("player-enrichment.yml")

    assert "group: tbt-production-deploy" in ci
    assert "group: tbt-history-data-writer" in environment
    assert "group: tbt-player-assets-writer" in player

    # The deploy job used to share tbt-history-data-writer with the six-hour
    # environment job, which made ordinary web deployments queue for hours.
    deploy_block = ci.split("  deploy:", 1)[1]
    assert "group: tbt-history-data-writer" not in deploy_block
