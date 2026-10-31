"""Chromium geometry gate for the unified mobile prediction cards.

Checks TOP, VALUE, ACCA, DOUBLES, ACES, DOUBLE FAULTS, SETS and GAMES
at 320/390/600px, and protects legacy 768px tablet layout.
No live API, auth privileges or provider quota.
"""
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, browser_path, static_route

WINNERS = ('daily', 'value', 'prime', 'doubles')
PROJECTED = ('ace', 'double_faults', 'games', 'sets')
MARKETS = WINNERS + PROJECTED

SETUP = r"""(market) => {
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
  const projected = ['ace','double_faults','games','sets'].includes(market);
  const rank = '<td class="hub-rank">1</td>';
  const time = '<td class="hub-time"><span class="hub-time-stack"><strong>14:30</strong><small>30.10.26</small><em class="hub-offer-status is-started">ZAČATÉ</em></span></td>';
  const tournament = '<td class="hub-tournament-cell"><span class="hub-tournament"><span class="hub-tournament-badge">ITF</span><span class="hub-tournament-copy"><b>Very Long Tournament in Lyon, France</b><small><span>ATP</span><span>FINAL</span><span>HARD</span><span class="hub-mobile-started is-started">ZAČATÉ</span></small></span></span></td>';
  const match = '<td class="hub-match-cell"><span class="hub-match"><span class="hub-match-player"><span class="hub-match-player-main"><span class="hub-avatar"></span><b>Lorenzo Musetti</b></span></span><span class="hub-match-player"><span class="hub-match-player-main"><span class="hub-avatar"></span><b>Taylor Fritz</b></span></span></span></td>';
  const pick = '<td class="hub-pick"><span class="hub-pick-stack"><small>TOP</small><strong>Taylor Fritz · Over 9.5 Aces for the Final</strong></span></td>';
  const odds = '<td class="hub-odds hub-number-cell"><span class="hub-number-stack"><strong>2.00</strong><small>KURZ</small></span></td>';
  const projection = '<td class="hub-odds hub-number-cell"><span class="hub-number-stack"><strong>9.94</strong><small>PROJEKCIA</small></span></td>';
  const confidence = '<td class="hub-confidence-cell" data-label="BLINQ %"><span class="hub-confidence"><strong>82.3%</strong><i><b style="width:82%"></b></i><small class="hub-data-depth">DATA DEPTH · 100%</small></span></td>';
  const action = '<td class="hub-action-cell'+(projected?' hub-mobile-only':'')+'"><button class="hub-detail" type="button">Detail</button></td>';
  document.querySelector('#dailyHubBody').innerHTML =
    '<tr'+(projected?' data-hub-market="'+market+'"':'')+'>'+
    rank+time+tournament+match+pick+odds+
    (projected?projection+confidence+action:confidence+action)+'</tr>';
}"""

GEOMETRY = r"""() => {
  const q=s=>document.querySelector(s);
  const b=el=>{const r=el.getBoundingClientRect(); return {l:r.left,r:r.right,t:r.top,b:r.bottom,w:r.width,h:r.height}};
  const row=q('#dailyHubBody tr'),items=[...row.cells];
  return {
    viewport:innerWidth,
    overflow:document.documentElement.scrollWidth-innerWidth,
    areas:getComputedStyle(row).gridTemplateAreas,
    row:b(row),
    time:b(items[1]),tournament:b(items[2]),match:b(items[3]),
    pick:b(items[4]),odds:b(items[5]),
    projection:items.length===9?b(items[6]):null,
    confidence:b(items.length===9?items[7]:items[6]),
    action:b(items[items.length-1]),
    detailVisible:getComputedStyle(items[items.length-1]).display!=='none',
    depthHidden:getComputedStyle(row.querySelector('.hub-data-depth')).display==='none',
    startedInline:getComputedStyle(row.querySelector('.hub-mobile-started')).display!=='none',
    startedTimeHidden:getComputedStyle(row.querySelector('.hub-time .hub-offer-status')).display==='none',
  };
}"""

def overlap(a,b):
    return min(a['r'],b['r'])-max(a['l'],b['l'])>2 and min(a['b'],b['b'])-max(a['t'],b['t'])>2

def test_mobile_market_cards():
    with sync_playwright() as p:
        exe=browser_path()
        browser=p.chromium.launch(headless=True, executable_path=exe) if exe else p.chromium.launch(headless=True)
        try:
            for width in (320,390,600,768):
                context=browser.new_context(viewport={'width':width,'height':844},is_mobile=True,has_touch=True)
                page=context.new_page()
                page.route('**/*',static_route)
                page.goto(ORIGIN+'/index.html?lang=sk',wait_until='networkidle')
                for market in MARKETS:
                    page.evaluate(SETUP,market)
                    g=page.evaluate(GEOMETRY)
                    assert g['overflow']<=2,(width,market,g)
                    assert g['row']['w']<=width,(width,market,g)
                    assert g['row']['h']<530,(width,market,'over-tall card',g)
                    assert g['pick']['w']>=100,(width,market,'collapsed prediction',g)
                    if width <= 600 and market in ('daily','value'):
                        assert 'match match' in g['areas'] and 'pick action' in g['areas'],(width,market,g)
                    if width<=600:
                        for name in ('time','confidence','odds','action'):
                            assert g[name]['r']<=g['row']['r']+1,(width,market,name,g)
                        assert g['startedInline'] and g['startedTimeHidden'],(width,market,g)
                        assert g['depthHidden'],(width,market,g)
                        assert g['detailVisible'],(width,market,g)
                        assert g['match']['r']>=g['confidence']['r']-2,(width,market,g)
                        assert g['confidence']['r']<=g['odds']['l']+2,(width,market,g)
                        assert abs(g['pick']['t']-g['action']['t'])<3,(width,market,g)
                        assert abs(g['confidence']['t']-g['odds']['t'])<3,(width,market,g)
                        assert g['action']['b']<=g['odds']['t']+2,(width,market,g)
                        assert not overlap(g['pick'],g['action']),(width,market,g)
                        if market in PROJECTED:
                            assert 'projection' in g['areas'],(width,market,g)
                            assert g['projection']['t']>=g['confidence']['b']-2,(width,market,g)
                            assert not overlap(g['projection'],g['action']),(width,market,g)
                    else:
                        assert not g['startedInline'],(width,market,g)
                        assert not g['detailVisible'] if market in PROJECTED else g['detailVisible']
                    print('mobile-card',width,market,round(g['row']['h']),round(g['pick']['w']))
                context.close()
        finally:
            browser.close()

if __name__=='__main__':
    test_mobile_market_cards()
