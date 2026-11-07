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
            "  window.zeroAllocationTest={state,renderDailyHub,dailyHubAccessLocked,dailyHubIncludedButUnavailable,adminDailyHubAccessAudit,adminDailyHubAccessAuditHtml,renderAdminLayout};\n  boot();"
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
                    // A visible market with zero unlocked rows and no BLUR
                    // must say that the plan has no access, not blame providers.
                    for(const total of [0,3]){
                      s.feed={
                        account:{plan:'pro',status:'active'},
                        ace_picks:[],doubles_picks:[],sg_picks:[],daily_picks:[],
                        prime_picks:[],value_picks:[],top_daily_picks:[],results:[],
                        entitlements:{plan:'pro',sections:{double_faults:{
                          visible_picks:0,blur_remaining:false,enabled:true,see_all:false,
                          display_state:'active',returned:0,total,locked_count:total,
                          slot_states:Array(total).fill('hidden')
                        }}}
                      };
                      s.dailyHubTab='double_faults';app.renderDailyHub();
                      const proZero=document.querySelector('#dailyHubEmpty');
                      if(!proZero||proZero.hidden||!proZero.textContent.includes('odomknuté'))
                        throw Error('PRO double faults zero rows must explain access, not missing predictions');
                      if(document.querySelector('#dailyHubTabs [data-daily-hub-tab="double_faults"]')?.classList.contains('is-locked')
                         ||document.querySelector('#dailyHubBody tr.hub-row-locked'))
                        throw Error('Unblurred zero-allocation panel must not claim a lock: '+total);
                    }
                    // All market tabs and all paid/free levels: when zero rows
                    // are deliberately hidden instead of blurred, never claim a
                    // provider outage or display a misleading paywall lock.
                    for(const level of levels){
                      for(const tab of ['daily','prime','value',...markets]){
                        for(const total of [0,3]){
                          s.feed={
                            account:{plan:level,status:'active'},
                            daily_picks:[],top_daily_picks:[],prime_picks:[],value_picks:[],
                            ace_picks:[],doubles_picks:[],sg_picks:[],results:[],
                            entitlements:{plan:level,sections:{[tab]:{
                              visible_picks:0,blur_remaining:false,enabled:true,
                              see_all:false,display_state:'active',returned:0,total,
                              locked_count:total,slot_states:Array(total).fill('hidden')
                            }}}
                          };
                          s.dailyHubTab=tab;app.renderDailyHub();
                          const empty=document.querySelector('#dailyHubEmpty');
                          const tabNode=document.querySelector('#dailyHubTabs [data-daily-hub-tab="'+tab+'"]');
                          if(!empty||empty.hidden||!empty.textContent.includes('odomknuté')
                            ||tabNode?.classList.contains('is-locked')
                            ||document.querySelector('#dailyHubBody tr.hub-row-locked'))
                            throw Error('Zero unlocked hidden rows confused with paywall/outage: '+level+'/'+tab+'/'+total);
                        }
                      }
                    }
                    // Admin diagnostics must expose cross-tier inversion, empty
                    // visible markets and SEE ALL on a disabled/blurred panel,
                    // without silently changing membership configuration.
                    const originalDf={...tabs.double_faults.plans.pro};
                    const originalElite={...tabs.double_faults.plans.elite};
                    const originalRookie={...tabs.prime.plans.rookie};
                    const originalPro={...tabs.prime.plans.pro};
                    const originalElitePrime={...tabs.prime.plans.elite};
                    try{
                      Object.assign(tabs.double_faults.plans.pro,{visible_rows:0,blur_remaining:false,display_state:'active'});
                      Object.assign(tabs.double_faults.plans.elite,{visible_rows:0,display_state:'blurred',see_all:true});
                      Object.assign(tabs.prime.plans.rookie,{visible_rows:1,display_state:'active'});
                      Object.assign(tabs.prime.plans.pro,{visible_rows:0,blur_remaining:false,display_state:'active'});
                      Object.assign(tabs.prime.plans.elite,{visible_rows:0,display_state:'blurred'});
                      const issues=app.adminDailyHubAccessAudit();
                      for(const kind of ['empty','hierarchy','contradiction'])
                        if(!issues.some(item=>item.kind===kind))
                          throw Error('Admin audit missed '+kind);
                      if(!issues.some(item=>item.tab==='prime'&&item.plan==='elite'&&item.kind==='hierarchy'))
                        throw Error('Admin hierarchy audit ignored ROOKIE->ELITE gap across PRO');
                      if(!issues.some(item=>item.tab==='double_faults'&&item.plan==='pro'&&item.kind==='empty'))
                        throw Error('Admin audit missed PRO double faults');
                      if(!app.adminDailyHubAccessAuditHtml().includes('Prístupy na kontrolu'))
                        throw Error('Admin diagnostics are not rendered');
                      // Effective zero access can also be caused by row overrides:
                      // the count selector itself can still show 2.
                      Object.assign(tabs.double_faults.plans.pro,{
                        visible_rows:2,blur_remaining:false,display_state:'active',
                        row_overrides:{'1':'hidden','2':'hidden'}
                      });
                      if(!app.adminDailyHubAccessAudit().some(item=>item.tab==='double_faults'&&item.plan==='pro'&&item.kind==='empty'))
                        throw Error('Override-hidden PRO panel escaped audit');
                      const beforePlan=s.adminPlan;s.adminPlan='pro';
                      try{
                        const dfAdminCard=()=>app.renderAdminLayout().split('data-admin-hub-tab-card="double_faults"')[1]?.split('data-admin-hub-global-field="enabled"')[0]||'';
                        if(!dfAdminCard().includes('0 efektívne odomknutých riadkov'))
                          throw Error('Inline warning missed effective zero rows');
                        tabs.double_faults.plans.pro.row_overrides={'1':'active','2':'hidden'};
                        if(app.adminDailyHubAccessAudit().some(item=>item.tab==='double_faults'&&item.plan==='pro'&&item.kind==='empty')
                           ||dfAdminCard().includes('0 efektívne odomknutých riadkov'))
                          throw Error('Inline audit falsely flags one unlocked row');
                      }finally{s.adminPlan=beforePlan;}
                      // Disabled panels must not be reported as visible empty panels.
                      tabs.double_faults.plans.pro.tab_enabled=false;
                      const disabledIssues=app.adminDailyHubAccessAudit();
                      if(disabledIssues.some(item=>item.tab==='double_faults'&&item.plan==='pro'&&item.kind==='empty'))
                        throw Error('Disabled PRO panel was incorrectly flagged as visible');
                    }finally{
                      Object.assign(tabs.double_faults.plans.pro,originalDf);
                      Object.assign(tabs.double_faults.plans.elite,originalElite);
                      Object.assign(tabs.prime.plans.rookie,originalRookie);
                      Object.assign(tabs.prime.plans.pro,originalPro);
                      Object.assign(tabs.prime.plans.elite,originalElitePrime);
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
