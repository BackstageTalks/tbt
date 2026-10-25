"""Real Chromium geometry gate for the 25 Oct mobile prediction-card regression.

Renders deterministic Aces/Double Faults/Games/Sets and winner rows against
the committed HTML and CSS at 320, 390 and 768 CSS pixels; never uses a live
API or privileged account.
"""
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, browser_path, static_route


SETUP = """(market) => {
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelector('#appShell').hidden = false;
  document.querySelector('#predictionsView').hidden = false;
  document.querySelector('#routePanel').hidden = true;
  document.body.classList.remove('blinq-route', 'blinq-admin');
  document.body.classList.add('blinq-home', 'bqm-enabled');
  const hub = document.querySelector('#dailyHub');
  hub.hidden = false;
  hub.dataset.tab = market;
  const pick = '<td class="hub-pick"><span class="hub-pick-stack"><small>PREDIKCIA</small><strong>Taylor Fritz · Over 9.5 Aces for the Final</strong></span></td>';
  const odds = '<td class="hub-odds hub-number-cell"><span class="hub-number-stack"><small>KURZ</small><strong>2.00</strong></span></td>';
  const projection = '<td class="hub-odds hub-number-cell"><span class="hub-number-stack"><small>PROJEKCIA</small><strong>9.94</strong></span></td>';
  const confidence = '<td class="hub-confidence-cell"><span class="hub-confidence"><strong>82.3%</strong><i><b style="width:82%"></b></i><small class="hub-data-depth">DATA DEPTH · 100%</small></span></td>';
  const action = '<td class="hub-action-cell"><button class="hub-detail">Detail</button></td>';
  document.querySelector('#dailyHubBody').innerHTML =
    '<tr><td class="hub-rank">1</td>'+
    '<td class="hub-time"><span class="hub-time-stack"><strong>14:30</strong><small>25.10.26</small></span></td>'+
    '<td class="hub-tournament-cell"><div class="hub-tournament"><span class="hub-tournament-badge"></span><span class="hub-tournament-copy"><b>Very Long Tournament in Lyon, France</b><small>ATP · FINAL · HARD</small></span></div></td>'+
    '<td class="hub-match-cell"><div class="hub-match"><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>Lorenzo Musetti</b></span></span><span>vs</span><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>Taylor Fritz</b></span></span></div></td>'+
    pick+odds+(market==='daily'?confidence+action:projection+confidence)+'</tr>';
}"""

GEOMETRY = """() => {
  const q=s=>document.querySelector(s);
  const b=el=>{const r=el.getBoundingClientRect(); return {l:r.left,r:r.right,t:r.top,b:r.bottom,w:r.width,h:r.height}};
  const row=q('#dailyHubBody tr');
  const items=[...row.cells];
  return {
    viewport:innerWidth,
    documentOverflow:document.documentElement.scrollWidth-innerWidth,
    areas:getComputedStyle(row).gridTemplateAreas,
    row:b(row),pick:b(items[4]),odds:b(items[5]),extra:b(items[6]),
    last:b(items[7]),cardWidth:b(row).w
  };
}"""


def overlaps(a, b):
    return min(a['r'], b['r']) - max(a['l'], b['l']) > 2 and min(a['b'], b['b']) - max(a['t'], b['t']) > 2


def test_mobile_market_cards():
    with sync_playwright() as p:
        exe=browser_path()
        browser=p.chromium.launch(headless=True, executable_path=exe) if exe else p.chromium.launch(headless=True)
        try:
            for width in (320,390,768):
                context=browser.new_context(viewport={'width':width,'height':844},is_mobile=True,has_touch=True)
                page=context.new_page()
                page.route('**/*', static_route)
                page.goto(ORIGIN+'/index.html?lang=sk',wait_until='networkidle')
                for market in ('daily','ace','double_faults','games','sets'):
                    page.evaluate(SETUP,market)
                    g=page.evaluate(GEOMETRY)
                    assert g['documentOverflow']<=2,(width,market,g)
                    assert g['row']['w']<=width,(width,market,g)
                    assert g['row']['h']<500,(width,market,'over-tall card',g)
                    assert g['pick']['w']>=100,(width,market,'collapsed prediction',g)
                    if market=='daily':
                        assert g['odds']['t']>=g['pick']['t']-2,(width,market,g)
                        assert not overlaps(g['pick'],g['odds']),(width,market,g)
                        assert not overlaps(g['extra'],g['last']),(width,market,g)
                    else:
                        assert 'projection' in g['areas'],(width,market,g)
                        assert g['pick']['b']<=g['extra']['t']+2,(width,market,g)
                        assert abs(g['odds']['t']-g['extra']['t'])<=3,(width,market,g)
                        assert not overlaps(g['odds'],g['extra']),(width,market,g)
                        assert not overlaps(g['last'],g['extra']),(width,market,g)
                    print('mobile-card',width,market,round(g['row']['h']),round(g['pick']['w']))
                context.close()
        finally:
            browser.close()


if __name__=='__main__':
    test_mobile_market_cards()
