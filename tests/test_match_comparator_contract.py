from pathlib import Path


def test_match_comparator_release_and_runtime_contract():
    pipeline = Path("scripts/pipeline.py").read_text(encoding="utf-8")
    deploy = Path("scripts/prepare_feed.py").read_text(encoding="utf-8")
    api = Path("api/function_app.py").read_text(encoding="utf-8")
    runtime = Path("api/tbt/services/comparator_runtime.py").read_text(encoding="utf-8")
    app = Path("web/app.js").read_text(encoding="utf-8")
    auth = Path("web/auth.js").read_text(encoding="utf-8")

    assert '"comparator.json.gz"' in pipeline
    assert 'remove_names=("comparator.json.gz",)' in pipeline
    assert 'COMPARATOR_ASSET = "comparator.json.gz"' in deploy
    assert 'gzip.open(source, "rt"' in deploy
    assert 'COMPARATOR = Path(__file__).parent / "data/comparator.json.gz"' in api
    assert 'route="v1/comparator/players"' in api
    assert 'route="v1/comparator/compare"' in api
    assert '_COMPARATOR_RESULT_TTL_SECONDS = 5 * 60' in api
    assert '_COMPARATOR_RATE_MAX_REQUESTS = 60' in api

    # Public request-time evaluator remains provider-free and training-stack-free.
    lowered = runtime.lower()
    for forbidden in ("rapidapi", "httpx", "pandas", "numpy", "sklearn", "joblib"):
        assert forbidden not in lowered

    assert "compare:['MATCH COMPARATOR'" in app
    assert "if(route==='compare')" in app
    assert "BlinqAuth.comparatorPlayers" in app
    assert "BlinqAuth.comparatorCompare" in app
    assert "async function comparatorPlayers" in auth
    assert "async function comparatorCompare" in auth


def test_comparator_header_icon_is_not_hardcoded_before_asset_approval():
    html = Path("web/index.html").read_text(encoding="utf-8")
    # The approved icon can later link here with data-route="compare".
    assert 'data-route="compare"' not in html
