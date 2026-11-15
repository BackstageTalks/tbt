"""Chromium acceptance: independent today's TOP, ESÁ and VIAC ES cards on mobile/desktop.

Synthetic already-authorized feed, no provider calls or account mutations.
The same browser source, market authenticity guard and Daily Hub DOM are used.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, WEB, browser_path, static_route


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        assert source.count("  boot();") == 1
        route.fulfill(
            content_type="application/javascript",
            body=source.replace(
                "  boot();",
                "  window.blinqOfferTest={state,renderDailyHub,dailyHubRows,marketRows};\n  boot();",
            ),
        )
    else:
        static_route(route)


CHECK = r"""() => {
  const {state:s,renderDailyHub,dailyHubRows}=window.blinqOfferTest;
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelector('#appShell').hidden=false;
  document.querySelector('#predictionsView').hidden=false;
  document.querySelector('#routePanel').hidden=true;
  s.previewPlan=null;
  s.dashboardSearch='';
  s.dailyHubTournament='';
  const schedule='2026-11-15T16:00:00Z';
  const player1={id:'A',name:'Alpha',rank:50};
  const player2={id:'B',name:'Beta',rank:250};
  const base={scheduled_at:schedule,tour:'ATP',tournament:'ATP test',
    surface:'hard',player1,player2,selection_id:'A',selection:'Alpha',
    pick:'Alpha',winner_id:'A'};
  const todayTop=(id,p)=>({...base,event_id:id,market:'match_winner',
    odds:1.65,blinq_probability:p,probability:p,
    betting:{market:'match_winner',odds:1.65,selection_id:'A',selection:'Alpha',
      betting_day:'2026-11-15'}});
  const top=[todayTop('top1',.79),todayTop('top2',.74)];
  const ace={...base,event_id:'ace',market:'aces',price_status:'projection_only',
    price_contract:'player_total_ou',odds:null,
    projection_model:'ace-count-projection-v4',
    projection:8.1,opponent_projection:3.4,projection_confidence:.78};
  const conf=.78,statOdds=Math.round((1.70-.20*(conf-.60)/.33+1e-10)*100)/100;
  const more={...base,event_id:'most-aces',market:'most_aces',
    price_contract:'player_superiority',price_status:'priced_projection',
    odds:statOdds,odds_source:'blinq_statistical',
    price_basis:'blinq_user_most_aces_confidence_band_v1',
    odds_contract_version:'most_aces_local_statistical_v1',
    provider_id:null,captured_at:null,market_line:null,ou_side:null,
    projection_model:'ace-count-projection-v4',
    projection:8.1,opponent_projection:3.4,projection_confidence:conf};
  const allSection=(n)=>({visible_picks:'ALL',blur_remaining:false,
    enabled:true,see_all:true,returned:n,total:n,
    locked_count:0,display_state:'active',slot_states:[]});
  s.feed={account:{plan:'admin',is_admin:true,status:'active'},ready:true,
    daily_picks:top,top_daily_picks:top,prime_picks:[],value_picks:[],
    ace_picks:[ace,more],doubles_picks:[],sg_picks:[],upcoming:[],results:[],
    entitlements:{plan:'admin',sections:{
      daily:allSection(2),ace:allSection(1),ace_winner:allSection(1),
      value:allSection(0),prime:allSection(0)}}};
  const expected={daily:2,ace:1,ace_winner:1,value:0};
  const found={};
  for(const [tab,count] of Object.entries(expected)){
    s.dailyHubTab=tab;
    renderDailyHub();
    const cards=[...document.querySelectorAll('#dailyHubBody tr[data-hub-event]')];
    if(cards.length!==count)throw Error(tab+': cards '+cards.length+' vs '+count);
    if(!document.querySelector('#dailyHubTabs [data-daily-hub-tab="'+tab+'"]'))
      throw Error('Separate Daily Hub tab missing: '+tab);
    found[tab]=cards.map(x=>x.getAttribute('data-hub-event'));
  }
  if(found.ace[0]===found.ace_winner[0])throw Error('VIAC ES was merged into ESÁ');
  if(!found.ace[0]?.includes('ace') || !found.ace_winner[0]?.includes('most-aces'))
    throw Error('Distinct ESÁ / VIAC ES event disappeared');
  // The client must never re-add the second TOP or the premium projections
  // after the server has redacted a ROOKIE offer to a single authorized row.
  s.feed.account={plan:'rookie',status:'active'};
  s.feed.daily_picks=[top[0]];
  s.feed.top_daily_picks=[top[0]];
  s.feed.ace_picks=[];
  const rookie={visible_picks:1,blur_remaining:true,enabled:true,see_all:false,
    returned:1,total:2,locked_count:1,
    display_state:'active',slot_states:['active','blurred']};
  s.feed.entitlements={plan:'rookie',sections:{
    daily:rookie,
    ace:{...allSection(0),visible_picks:0},
    ace_winner:{...allSection(0),visible_picks:0}
  }};
  s.dailyHubTab='daily';renderDailyHub();
  if(dailyHubRows('daily').length!==1
     || document.querySelectorAll('#dailyHubBody tr[data-hub-event]').length!==1)
     throw Error('ROOKIE gained unauthorized TOP cards');
  if(dailyHubRows('ace').length!==0||dailyHubRows('ace_winner').length!==0)
     throw Error('ROOKIE gained unauthorized ESÁ / VIAC ES');
  return found;
}"""


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 1440):
                context = browser.new_context(viewport={"width": width, "height": 900})
                context.route("**/*", route_request)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.blinqOfferTest?.state?.ui?.dashboard?.daily_hub")
                found = page.evaluate(CHECK)
                assert len(found["daily"]) == 2
                assert len(found["ace"]) == 1
                assert len(found["ace_winner"]) == 1
                assert not errors, (width, errors)
                context.close()
        finally:
            browser.close()
    print("PASS today's TOP / ESÁ / VIAC ES DOM, mobile+desktop, admin+rookie boundaries")


if __name__ == "__main__":
    main()
