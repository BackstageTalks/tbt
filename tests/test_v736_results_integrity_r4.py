from pathlib import Path

from tbt.services.engine import betting_performance

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _publication(*, key, issued, section="prime", betting_day=None):
    return {
        "publication_key": f"{section}:{key}",
        "selection_key": key,
        "section": section,
        "market": "match_winner",
        "selection": "Alpha",
        "selection_id": "A",
        "betting_day": betting_day,
        "issued_at": issued,
        "publication_status": "published",
        "odds": 1.80,
        "result": {"correct": True, "staked_units": 1.0, "profit_units": 0.8},
    }


def test_results_ui_dedupes_semantically_not_by_legacy_publication_key():
    assert "function canonicalResultPublicationKey" in APP
    assert "eventId}::${market}::${scope}::${metric}::${selection}" in APP
    assert "const key=canonicalResultPublicationKey(row,publication,index)" in APP


def test_all_surfaces_does_not_hide_unknown_surface_results():
    assert 'else if(String(row?.surface||\'\').toLowerCase()===\'unknown\')return false' not in APP
    assert 'Unknown/missing' in APP and 'surface metadata must never hide' in APP


def test_backend_metrics_collapse_legacy_duplicate_publication_keys():
    row = {
        "event_id": "evt-1",
        "market_publications": [
            _publication(
                key="match_winner::evt-1:A",
                issued="2026-09-16T08:00:00+00:00",
            ),
            _publication(
                key="match_winner:2026-09-16:evt-1:A",
                issued="2026-09-16T08:02:00+00:00",
                betting_day="2026-09-16",
            ),
        ],
    }
    metrics = betting_performance([row])
    assert metrics["overall"]["n"] == 1
    assert metrics["overall"]["wins"] == 1
    assert metrics["sections"]["prime"]["n"] == 1
    assert abs(metrics["overall"]["profit_units"] - 0.8) < 1e-12


def test_release_stays_736_and_only_patch_cache_moves_to_r4():
    assert 'data-web-release="7.3.6"' in INDEX
    assert 'content="736-r6"' in INDEX
    assert '/app.js?v=7360&p=6' in INDEX
    assert '/final-polish-736.css?v=7360&p=6' in INDEX
