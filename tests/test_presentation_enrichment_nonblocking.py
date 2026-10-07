from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_refresh_presentation_enrichment_is_non_blocking():
    source = (ROOT / ".github" / "workflows" / "data.yml").read_text(encoding="utf-8")
    marker = "- name: Refresh presentation metadata for current feed"
    start = source.index(marker)
    block = source[start:source.index("- name: Prepare refreshed serving feed", start)]
    assert "id: presentation_enrichment" in block
    assert "continue-on-error: true" in block
    assert "Record degraded presentation enrichment" in block
    assert "steps.presentation_enrichment.outcome == 'failure'" in block


def test_prepare_feed_keeps_presentation_assets_optional():
    source = (ROOT / "scripts" / "prepare_feed.py").read_text(encoding="utf-8")
    assert "Presentation metadata is optional." in source
    assert "Optional player assets skipped" in source
    assert '"available": False' in source
