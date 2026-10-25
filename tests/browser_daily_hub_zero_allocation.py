"""Real-browser regression: Daily Offer tab locks follow level policy, not market totals."""
from __future__ import annotations

import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

MARKETS=("ace", "double_faults", "doubles", "sets", "games")
LEVELS=("rookie", "pro", "elite", "legend", "goat")


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8").replace(
            "  boot();",
            "  window.zeroAllocationTest={state,renderDailyHub,dailyHubAccessLocked,dailyHubIncludedButUnavailable};\n  boot();"
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390, 1440):
                context=browser.new_context(viewport={"width":width,"height":920})
                context.route("**/*",route_request)
                page=context.new_page()
                errors=[]
                page.on("pageerror",lambda error: errors.append(str(error)))
                page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
                page.wait_for_function("window.zeroAllocationTest?.state?.ui?.dashboard?.daily_hub")
                result=page.evaluate("""({markets,levels})=>{
                    const app=window.zeroAllocationTest, s=app.state;
                    const tabs=s.ui.dashboard.daily_hub.tabs;
                    const mkEnt=(rule,total=0)=>({
                        visible_picks:rule.visible_rows,blur_remaining:rule.blur_remaining,
                        enabled:rule.tab_enabled!==false,see_all:rule.see_all,
                        display_state:rule.display_state,returned:0,total,
                        locked_count:total,
                        slot_states:Array(total).fill('blurred'),row_overrides:rule.row_overrides||{}
                    });
                    const observed=[];
                    s.previewPlan=null;s.dailyHubExpanded=false;s.dashboardSearch='';s.dailyHubTournament='';
                    for(const level of levels){
                      for(const tab of markets){
                        const rule=tabs[tab].plans[level];
                        if(!rule||rule.tab_enabled===false||rule.display_state==='hidden')continue;
                        for(const total of [0,3]){
                          s.feed={
                            account:{plan:level,status:'active'},
                            daily_picks:[],top_daily_picks:[],prime_picks:[],value_picks:[],
                            ace_picks:[],doubles_picks:[],sg_picks:[],upcoming:[],results:[],
                            entitlements:{plan:level,sections:{[tab]:mkEnt(rule,total)}}
                          };
                          s.dailyHubTab=tab;app.renderDailyHub();
                          const tabNode=document.querySelector('#dailyHubTabs [data-daily-hub-tab="'+tab+'"]');
                          if(!tabNode)throw Error(level+'/'+tab+': missing tab');
                          const locked=tabNode.classList.contains('is-locked');
                          const tbodyLocked=!!document.querySelector('#dailyHubBody tr.hub-row-locked');
                          const allocated=String(rule.visible_rows).toUpperCase()==='ALL'||Number(rule.visible_rows)>0;
                          const expected=rule.display_state==='blurred'||(!allocated&&rule.blur_remaining!==false);
                          if(locked!==expected||tbodyLocked!==expected)
                            throw Error(level+'/'+tab+'/'+total+': expected lock='+expected+' tab='+locked+' row='+tbodyLocked);
                          if(expected&&tabNode.dataset.upgradePlan===level)
                            throw Error('Self-upgrade paywall '+level+'/'+tab);
                          observed.push(level+'/'+tab+'/'+total+':'+(locked?'locked':'empty'));
                        }
                      }
                    }
                    // Provider has no offer, even though one row is allocated:
                    // no paid upgrade is justified, at any membership level.
                    for(const level of levels){
                      for(const tab of markets){
                        s.feed={
                          account:{plan:level,status:'active'},ace_picks:[],doubles_picks:[],sg_picks:[],
                          daily_picks:[],prime_picks:[],value_picks:[],results:[],
                          entitlements:{plan:level,sections:{[tab]:{
                            visible_picks:1,blur_remaining:true,enabled:true,see_all:false,
                            display_state:'active',returned:0,total:0,locked_count:0,slot_states:[]
                          }}}
                        };
                        s.dailyHubTab=tab;app.renderDailyHub();
                        const tabNode=document.querySelector('#dailyHubTabs [data-daily-hub-tab="'+tab+'"]');
                        if(tabNode?.classList.contains('is-locked')||document.querySelector('#dailyHubBody tr.hub-row-locked'))
                          throw Error('Missing data must not paywall an allocated row: '+level+'/'+tab);
                        if(document.querySelector('#dailyHubEmpty')?.hidden)
                          throw Error('Missing data needs honest empty state: '+level+'/'+tab);
                      }
                    }
                    // Admin remains unrestricted with an empty provider market.
                    s.feed={account:{plan:'admin',is_admin:true,status:'active'},
                      ace_picks:[],doubles_picks:[],sg_picks:[],upcoming:[],results:[],entitlements:{sections:{}}};
                    s.previewPlan=null;
                    for(const tab of markets){
                      s.dailyHubTab=tab;app.renderDailyHub();
                      if(document.querySelector('#dailyHubTabs [data-daily-hub-tab="'+tab+'"]')?.classList.contains('is-locked'))
                        throw Error('Admin cannot be paywalled: '+tab);
                    }
                    return observed;
                }""",{"markets":list(MARKETS),"levels":list(LEVELS)})
                assert len(result)>=20,(width,result)
                assert not errors,(width,errors)
                context.close()
        finally:
            browser.close()
    print("Daily hub zero-allocation access: all levels, empty/nonempty markets and mobile/desktop PASS")


if __name__=="__main__":
    main()
