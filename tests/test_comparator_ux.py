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
    assert "major&&s.tour==='atp'&&s.bestOfAuto" in app
    assert "s.bestOfAuto=false;s.result=null;s.error='';refresh();" in app


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
    assert "/blinq-app.css?v=7360&p=61&compare=4" in html
    assert "/app.js?v=7360&p=61&compare=5" in html


def test_comparator_player_suggestions_bind_after_async_insertion():
    app = Path("web/app.js").read_text(encoding="utf-8")
    wire = app.split("function wireComparator()", 1)[1].split("function renderRoute(", 1)[0]
    # Results are injected via innerHTML *after* the initial DOM was wired.
    # Clicks must therefore be handled by the stable form, not the absent buttons.
    assert "form.addEventListener('click',event=>" in wire
    assert "event.target.closest('[data-comparator-select]')" in wire
    assert "host.querySelectorAll('[data-comparator-select]')" not in wire


def test_comparator_search_rejects_stale_results_and_displays_failures():
    app = Path("web/app.js").read_text(encoding="utf-8")
    wire = app.split("function wireComparator()", 1)[1].split("function renderRoute(", 1)[0]
    assert "const requestSeq=++s.searchSeq[side]" in wire
    assert "s.searchSeq[side]===requestSeq" in wire
    assert "input.value.trim()===query" in wire
    assert "if(!isCurrent())return;" in wire
    assert "status===401?" in wire
    assert "status===403?" in wire
    assert "status===429?" in wire
    assert 'role="alert"' in wire
    assert 'No players found.' in wire


def test_comparator_route_hides_decoration_and_keeps_error_inside_form():
    app = Path("web/app.js").read_text(encoding="utf-8")
    route = app.split("function setRoute(route,push=true)", 1)[1].split("function metricCards(", 1)[0]
    render = app.split("function renderComparatorRoute()", 1)[1].split("function wireComparator()", 1)[0]
    assert "pageEyebrow.hidden=route==='results'||route==='compare'" in route
    assert "pageSubtitle.hidden=route==='results'||route==='compare'" in route
    assert "document.body.classList.toggle('blinq-compare',route==='compare')" in route
    assert "body.blinq-compare .footer-system-dot{display:none}" in Path("web/blinq-app.css").read_text(encoding="utf-8")
    assert 'class="comparator-inline-message"' in render
    assert "state-card comparator-error" not in render


def test_comparator_search_groups_do_not_merge_canonical_ids():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "function comparatorPlayerGroups(rows)" in app
    assert "group.rows.length>1" in app
    assert "historical(a)-historical(b)" in app
    assert "data-comparator-expand" in app
    assert "comparator-search-alternates" in app
    assert "zápasov v DB" in app
    assert "Rôzne canonical ID; záznamy nie sú zlúčené." in app
