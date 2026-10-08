from pathlib import Path


def test_comparator_uses_plain_max_sets_not_bo_labels():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "Max. počet setov" in app
    assert "Maximum sets" in app
    assert ">BO3<" not in app
    assert ">BO5<" not in app
    assert "comparatorDefaultBestOf" in app
    assert "comparatorGrandSlamContext" in app


def test_comparator_grand_slam_defaults_are_tour_safe():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "Wimbledon" in app
    assert "Roland Garros" in app
    assert "Australian Open" in app
    assert "US Open" in app
    assert "String(tour||'').toLowerCase()!=='atp'" in app
    assert "state.comparator.tour==='wta'&&Number(state.comparator.bestOf)!==3" in app


def test_comparator_autocompletes_canonical_player_names():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "function comparatorAutoPlayer" in app
    assert "function comparatorSelectPlayer" in app
    assert "const automatic=comparatorAutoPlayer(query,s.search[side])" in app
    assert "Vyber oboch hráčov z ponuky, aby sa doplnilo celé meno." in app
    assert "comparator-player-confirmed" in app


def test_comparator_copy_is_not_duplicated_inside_form():
    app = Path("web/app.js").read_text(encoding="utf-8")
    render = app.split("function renderComparatorRoute()", 1)[1].split("function wireComparator()", 1)[0]
    assert "BLINQ INTELLIGENCE" not in render
    assert "canonical histórie" not in render
    assert "provider API" not in render
    assert "Compare any two canonical" not in app
    assert "Vyber dvoch hráčov, povrch a maximálny počet setov." in app


def test_comparator_assets_are_cache_busted():
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert "/blinq-app.css?v=7360&p=61&compare=2" in html
    assert "/app.js?v=7360&p=61&compare=2" in html
