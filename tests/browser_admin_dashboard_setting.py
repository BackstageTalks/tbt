"""Offline Chromium: admin KPI selections and unchanged three-card public layout."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        injected = (
            "  window.dashboardHarness={state,renderAdminRoute,wireAdmin,renderDashboardKpis};\n"
            + marker
        )
        route.fulfill(content_type="application/javascript", body=source.replace(marker, injected))
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 950})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.dashboardHarness && dashboardHarness.state.ui")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.getElementById('appShell').hidden=false;
                    document.getElementById('routePanel').hidden=false;
                    document.body.classList.add('blinq-admin');
                    document.body.classList.remove('blinq-home');
                    const t=dashboardHarness;
                    t.state.route='admin';
                    t.state.adminTab='dashboard';
                    const host=document.getElementById('routePanel');
                    host.innerHTML=t.renderAdminRoute();
                    t.wireAdmin();
                }""")
                assert page.locator(".admin-dashboard-slot").count() == 3
                assert page.get_by_text("Dashboard setting").count() >= 1
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="metric"]').select_option("roi")
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]').select_option("30")
                page.locator('[data-admin-kpi-index="1"][data-admin-kpi-field="period"]').select_option("180")
                page.locator('[data-admin-kpi-index="2"][data-admin-kpi-field="metric"]').select_option("yield_units")
                page.locator('[data-admin-kpi-index="2"][data-admin-kpi-field="period"]').select_option("365")
                settings = page.evaluate("dashboardHarness.state.ui.dashboard.kpi_cards")
                assert settings == [
                    {"metric": "roi", "period": "30"},
                    {"metric": "model_success", "period": "180"},
                    {"metric": "yield_units", "period": "365"},
                ], (width, settings)
                assert page.evaluate("""() => [...document.querySelectorAll('.admin-dashboard-slot')]
                    .every(el=>el.scrollWidth<=el.clientWidth+2)"""), width
                page.evaluate("""() => {
                    const h=dashboardHarness;
                    h.state.feed={
                      entitlements:{daily_pick_count:58},daily_picks:[{odds:1.86,surface:'hard'}],
                      dashboard_model_success:{accuracy:.703},
                      performance_windows:{
                        '30':{model:{n:51,accuracy:.67},betting:{
                          overall:{staked_units:10,roi:.125,profit_units:1.25},
                          sections:{top_daily:{n:5,avg_odds:1.77}}
                        }},
                        '180':{model:{n:101,accuracy:.703},betting:{
                          overall:{staked_units:22,roi:.15,profit_units:3.3},
                          sections:{top_daily:{n:7,avg_odds:1.84}}
                        }},
                        '365':{model:{n:141,accuracy:.68},betting:{
                          overall:{staked_units:23,roi:.25,profit_units:5.75},
                          sections:{top_daily:{n:8,avg_odds:1.93}}
                        }}
                      },
                      dashboard_kpi_cards:[
                        {metric:'roi',period:'30',value:.125},
                        {metric:'model_success',period:'180',value:.703},
                        {metric:'yield_units',period:'365',value:5.75}
                      ],
                    };
                    const settled=(event,section,market,correct,odds,status,days=1)=>({
                      event_id:event,
                      scheduled_at:new Date(Date.now()-days*86400000).toISOString(),
                      market_publications:[{
                        issued_at:new Date(Date.now()-(days+1)*86400000).toISOString(),
                        section,market,selection_id:event,correct,
                        price_status:status,odds,
                        result:{correct,staked_units:1,profit_units:correct?.8:-1}
                      }]
                    });
                    h.state.feed.results=[
                      settled('topwin','top_daily','match_winner',true,1.8,'priced'),
                      settled('ace','ace','aces',true,null,'projection_only'),
                      settled('df','double_faults','double_faults',false,null,'projection_only'),
                      settled('sets','sets','sets',true,1.9,'priced_projection'),
                      settled('old-top-loss','top_daily','match_winner',false,2,'priced',10),
                      settled('retired','top_daily','match_winner',false,1.9,'priced')
                    ];
                    h.state.feed.results[5].market_publications[0].result.status='retired';
                    const host=document.getElementById('routePanel');
                    host.innerHTML=h.renderAdminRoute();
                    h.wireAdmin();
                    h.renderDashboardKpis();
                }""")
                values = page.locator("[data-admin-kpi-preview]")
                assert [v.inner_text() for v in values.all()] == [
                    "12.5%", "70.3%", "+5.75u"
                ]
                # Unsaved choices must preview a different period immediately;
                # only the admin preview changes, not the three public cards.
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="metric"]').select_option("avg_odds")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "1.77"
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]').select_option("365")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "1.93"
                assert page.evaluate("dashboardHarness.state.feed.dashboard_kpi_cards[0].metric") == "roi"
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="metric"]').select_option("roi")
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]').select_option("30")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "12.5%"
                # Results previews use exactly the browser's Results W/L and
                # real-price sample, including unpriced statistical projections.
                choice = page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="metric"]')
                period = page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]')
                choice.select_option("results_success")
                period.select_option("3")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "75.0%"
                period.select_option("all")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "60.0%"
                choice.select_option("results_top_success")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "50.0%"
                period.select_option("3")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "100.0%"
                choice.select_option("results_avg_odds")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "1.85"
                # The original and Results methods remain independent choices
                # with different values for the SAME 30-day sample window.
                options = choice.locator("option").evaluate_all(
                    "(nodes) => Object.fromEntries(nodes.map(n=>[n.value,n.textContent]))"
                )
                assert options["model_success"] == "Úspešnosť (víťazi)"
                assert options["results_success"] == "Úspešnosť (výsledky)"
                assert options["avg_odds"] == "Priemerný kurz (pôvodný TOP)"
                assert options["results_avg_odds"] == "Priemerný kurz (výsledky)"
                visible = choice.locator("option").evaluate_all(
                    "(nodes) => nodes.filter(n => !n.hidden).map(n=>[n.value,n.textContent])"
                )
                assert visible == [
                    ["today_picks", "Dnešné predikcie"],
                    ["model_success", "Úspešnosť (víťazi)"],
                    ["results_success", "Úspešnosť (výsledky)"],
                    ["auto_success", "Úspešnosť (auto)"],
                    ["winner_avg_odds", "Priemerný kurz (víťazi)"],
                    ["results_avg_odds", "Priemerný kurz (výsledky)"],
                    ["auto_avg_odds", "Priemerný kurz (auto)"],
                    ["winner_roi", "ROI (víťazi)"],
                    ["results_roi", "ROI (výsledky)"],
                    ["auto_roi", "ROI (auto)"],
                    ["winner_yield_units", "Yield (víťazi)"],
                    ["results_yield_units", "Yield (výsledky)"],
                    ["auto_yield_units", "Yield (auto)"],
                ]
                assert all("historický súhrn" not in label.lower() for _,label in visible)
                choice.select_option("model_success")
                period.select_option("30")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "67.0%"
                choice.select_option("results_success")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "60.0%"
                choice.select_option("avg_odds")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "1.77"
                choice.select_option("results_avg_odds")
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "1.90"
                # Simulated publication affects only the existing three cards.
                page.evaluate("""() => {
                  const h=dashboardHarness;
                  h.state.ui.dashboard.kpi_cards=[
                    {metric:'results_success',period:'3'},
                    {metric:'results_top_success',period:'3'},
                    {metric:'results_avg_odds',period:'3'}
                  ];
                  h.state.feed.dashboard_kpi_cards=[
                    {metric:'results_success',period:'3',value:.75},
                    {metric:'results_top_success',period:'3',value:1},
                    {metric:'results_avg_odds',period:'3',value:1.85}
                  ];
                  h.renderDashboardKpis();
                }""")
                cards = page.locator("#dashboardKpis .dashboard-kpi")
                assert [c.locator("strong").inner_text() for c in cards.all()] == [
                    "75.0%", "100.0%", "1.85"
                ]
                # Admin differentiates sources; public banner retains simple
                # labels without appending Results to its existing layout.
                assert [c.locator("small").inner_text() for c in cards.all()] == [
                    "ÚSPEŠNOSŤ", "ÚSPEŠNOSŤ", "PRIEMERNÝ KURZ"
                ]
                assert page.locator("#dashboardKpis .dashboard-kpi p").count() == 0
                assert page.locator("#dashboardKpis .dashboard-kpi[title]").count() == 0
                # Restore original published settings: unsaved draft was inert.
                page.evaluate("""() => {
                  const h=dashboardHarness;
                  h.state.ui.dashboard.kpi_cards=[
                    {metric:'roi',period:'30'},
                    {metric:'model_success',period:'180'},
                    {metric:'yield_units',period:'365'}
                  ];
                  h.state.feed.dashboard_kpi_cards=[
                    {metric:'roi',period:'30',value:.125},
                    {metric:'model_success',period:'180',value:.703},
                    {metric:'yield_units',period:'365',value:5.75}
                  ];
                  h.renderDashboardKpis();
                }""")
                cards = page.locator("#dashboardKpis .dashboard-kpi")
                assert cards.count() == 3
                assert [c.locator("strong").inner_text() for c in cards.all()] == [
                    "12.5%", "70.3%", "+5.75u"
                ]
                assert page.locator("#dashboardKpis .dashboard-kpi p").count() == 0
                assert page.locator("#dashboardKpis .dashboard-kpi[title]").count() == 0
                # Unpublished configuration is not the new global default.
                page.evaluate("""() => {
                    const h=dashboardHarness;
                    h.state.ui.dashboard.kpi_cards=[
                      {metric:'today_picks',period:'today'},
                      {metric:'model_success',period:'auto'},
                      {metric:'avg_odds',period:'today'}
                    ];
                    h.state.feed.dashboard_kpi_cards=[
                      {metric:'today_picks',period:'today',value:null},
                      {metric:'model_success',period:'auto',value:.703},
                      {metric:'avg_odds',period:'today',value:null}
                    ];
                    h.renderDashboardKpis();
                    const host=document.getElementById('routePanel');
                    host.innerHTML=h.renderAdminRoute();h.wireAdmin();
                }""")
                assert [c.locator("strong").inner_text() for c in cards.all()] == [
                    "58", "70.3%", "1.86"
                ]
                assert [v.inner_text() for v in page.locator("[data-admin-kpi-preview]").all()] == [
                    "58", "70.3%", "1.86"
                ]
                # Reproduce the reported 3-0 / 100% / 1.52 / 52% ROI case
                # through the same filtered Results calculations as production.
                page.evaluate("""() => {
                  const s=dashboardHarness.state;
                  s.resultsFilters={category:'doubles',window:'all',tour:'',surface:''};
                  s.feed.results=[1.40,1.80,1.36].map((odds,i)=>({
                    event_id:'doubles-audit-'+i,
                    scheduled_at:new Date(Date.now()-86400000).toISOString(),
                    market_publications:[{
                      section:'doubles',market:'match_winner',
                      issued_at:new Date(Date.now()-172800000).toISOString(),
                      selection_id:'team-'+i,price_status:'priced',odds,
                      result:{status:'hit',correct:true,staked_units:1,profit_units:odds-1}
                    }]
                  }));
                  document.getElementById('routePanel').innerHTML=
                    dashboardHarness.renderAdminRoute();
                }""")
                audit = page.locator("[data-admin-roi-audit]")
                assert audit.count() == 1
                assert "52.0%" in audit.inner_text()
                assert "100.0%" in audit.inner_text()
                assert "1.52" in audit.inner_text()
                assert "3.00u" in audit.inner_text()
                assert "+1.56u" in audit.inner_text()
                assert "3" in audit.locator(".admin-roi-audit-grid").inner_text()
                assert audit.locator(".admin-roi-audit-alert").count() == 0
                assert audit.evaluate("(el) => el.scrollWidth<=el.clientWidth+2")
                # Corrupt one old settlement: the diagnostic flags the stale
                # ledger mismatch without silently inventing a new payout.
                page.evaluate("""() => {
                  const s=dashboardHarness.state;
                  s.feed.results[0].market_publications[0].result.profit_units=.20;
                  document.getElementById('routePanel').innerHTML=
                    dashboardHarness.renderAdminRoute();
                }""")
                assert "45.3%" in page.locator("[data-admin-roi-audit]").inner_text()
                assert page.locator(".admin-roi-audit-alert").count() == 1
                # Distinct winner and Results financial samples, plus maximum
                # automatically selected windows. No extra public card/caption.
                page.evaluate("""() => {
                  const h=dashboardHarness,s=h.state,base=Date.now();
                  s.feed.results=[
                    {event_id:'single-win',scheduled_at:new Date(base-86400000).toISOString(),
                     market_publications:[{section:'top_daily',market:'match_winner',
                      selection_id:'single-win',issued_at:new Date(base-172800000).toISOString(),
                      price_status:'priced',odds:2,
                      result:{status:'hit',correct:true,staked_units:1,profit_units:1}}]},
                    {event_id:'single-loss',scheduled_at:new Date(base-86400000).toISOString(),
                     market_publications:[{section:'value',market:'match_winner',
                      selection_id:'single-loss',issued_at:new Date(base-172800000).toISOString(),
                      price_status:'priced',odds:1.8,
                      result:{status:'miss',correct:false,staked_units:1,profit_units:-1}}]},
                    {event_id:'double-win',scheduled_at:new Date(base-86400000).toISOString(),
                     prediction_family:'doubles',
                     market_publications:[{section:'doubles',market:'match_winner',
                      selection_id:'double-win',issued_at:new Date(base-172800000).toISOString(),
                      price_status:'priced',odds:3,
                      result:{status:'hit',correct:true,staked_units:1,profit_units:2}}]},
                    {event_id:'ace-win',scheduled_at:new Date(base-86400000).toISOString(),
                     market_publications:[{section:'ace',market:'aces',selection_id:'ace-win',
                      issued_at:new Date(base-172800000).toISOString(),
                      price_status:'priced_projection',odds:2.2,
                      result:{status:'hit',correct:true,staked_units:1,profit_units:1.2}}]},
                    {event_id:'void',scheduled_at:new Date(base-86400000).toISOString(),
                     market_publications:[{section:'top_daily',market:'match_winner',
                      selection_id:'void',issued_at:new Date(base-172800000).toISOString(),
                      price_status:'priced',odds:1.5,
                      result:{status:'retired',correct:false,staked_units:1,profit_units:-1}}]}
                  ];
                  s.feed.performance_windows={
                    '3':{model:{n:50,accuracy:.61},betting:{overall:{n:3,staked_units:3,roi:.22,profit_units:.66},sections:{top_daily:{n:2,avg_odds:1.7}}}},
                    '7':{model:{n:55,accuracy:.62},betting:{overall:{n:3,staked_units:3,roi:.21,profit_units:.8},sections:{top_daily:{n:2,avg_odds:1.75}}}},
                    '14':{model:{n:60,accuracy:.81},betting:{overall:{n:3,staked_units:3,roi:.20,profit_units:1.1},sections:{top_daily:{n:2,avg_odds:1.8}}}},
                    '30':{model:{n:65,accuracy:.7},betting:{overall:{n:3,staked_units:3,roi:.19,profit_units:1.2},sections:{top_daily:{n:2,avg_odds:1.9}}}}
                  };
                  s.feed.dashboard_kpi_cards=[];
                  s.ui.dashboard.kpi_cards=[
                    {metric:'winner_roi',period:'3'},
                    {metric:'results_roi',period:'3'},
                    {metric:'results_yield_units',period:'3'}
                  ];
                  document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
                  h.wireAdmin();
                }""")
                assert [x.inner_text() for x in page.locator("[data-admin-kpi-preview]").all()] == [
                    "0.0%", "80.0%", "+3.20u"
                ]
                choice = page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="metric"]')
                period = page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]')
                choice.select_option('model_success')
                period.select_option('auto')
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "81.0%"
                assert "14 dní" in page.locator(".admin-dashboard-slot").first.inner_text()
                choice.select_option('roi')
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "22.0%"
                assert "3 dní" in page.locator(".admin-dashboard-slot").first.inner_text()
                choice.select_option('yield_units')
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "+1.20u"
                assert "30 dní" in page.locator(".admin-dashboard-slot").first.inner_text()
                choice.select_option('winner_roi')
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "0.0%"
                choice.select_option('results_roi')
                assert page.locator('[data-admin-kpi-preview="0"]').inner_text() == "80.0%"
                page.evaluate("""() => {
                  const h=dashboardHarness;
                  h.state.ui.dashboard.kpi_cards=[
                    {metric:'winner_roi',period:'auto'},
                    {metric:'results_roi',period:'auto'},
                    {metric:'results_yield_units',period:'auto'}
                  ];
                  h.state.feed.dashboard_kpi_cards=[
                    {metric:'winner_roi',period:'auto',value:0,selected_period:'7',sample:2},
                    {metric:'results_roi',period:'auto',value:.8,selected_period:'7',sample:4},
                    {metric:'results_yield_units',period:'auto',value:3.2,selected_period:'7',sample:4}
                  ];
                  h.renderDashboardKpis();
                }""")
                assert page.locator("#dashboardKpis .dashboard-kpi").count() == 3
                assert [c.locator("strong").inner_text() for c in page.locator("#dashboardKpis .dashboard-kpi").all()] == [
                    "0.0%", "80.0%", "+3.20u"
                ]
                # AUTO now compares the two separate calculation sources,
                # rather than selecting only the best window of one source.
                page.evaluate("""() => {
                  const h=dashboardHarness;
                  h.state.ui.dashboard.kpi_cards=[
                    {metric:'auto_success',period:'auto'},
                    {metric:'auto_avg_odds',period:'auto'},
                    {metric:'auto_roi',period:'auto'}
                  ];
                  h.state.feed.dashboard_kpi_cards=[];
                  document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
                  h.wireAdmin();
                }""")
                previews = page.locator("[data-admin-kpi-preview]").all_inner_texts()
                assert previews == ["81.0%", "2.25", "80.0%"], previews
                slot_text = [x.inner_text() for x in page.locator(".admin-dashboard-slot").all()]
                assert "víťazi" in slot_text[0] and "14 dní" in slot_text[0]
                assert "výsledky" in slot_text[1] and "celé obdobie" in slot_text[1]
                assert "výsledky" in slot_text[2] and "celé obdobie" in slot_text[2]
                assert page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]').is_disabled()
                # Publication sends three final scalars only; dashboard adds
                # no technical description, badges or new public cards.
                page.evaluate("""() => {
                  const h=dashboardHarness;
                  h.state.feed.dashboard_kpi_cards=[
                    {metric:'auto_success',period:'auto',value:.81,selected_source:'model_success',selected_period:'14',sample:60},
                    {metric:'auto_avg_odds',period:'auto',value:2.25,selected_source:'results_avg_odds',selected_period:'all',sample:4},
                    {metric:'auto_roi',period:'auto',value:.8,selected_source:'results_roi',selected_period:'all',sample:4}
                  ];
                  h.renderDashboardKpis();
                }""")
                assert [c.locator("strong").inner_text() for c in page.locator("#dashboardKpis .dashboard-kpi").all()] == [
                    "81.0%", "2.25", "80.0%"
                ]
                assert page.locator("#dashboardKpis .dashboard-kpi p").count() == 0
                assert page.locator("#dashboardKpis .dashboard-kpi[title]").count() == 0
                assert not errors, (width, errors)
                page.close()
            print("Admin Dashboard setting and unchanged public three-card runtime: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
