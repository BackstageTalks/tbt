"""Offline banner editor browser regression; no external or paid APIs."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

def route_request(route):
    if urlparse(route.request.url).path == '/app.js':
        source=(WEB/'app.js').read_text(encoding='utf-8')
        needle='  boot();'
        assert source.count(needle)==1
        source=source.replace(needle,'  window.bannerHarness={state,heroSlideHtml,renderAdminBanners,wireAdmin,syncAdminHeroPreview,setSelectedElement,renderUpgradeTierCard};\n'+needle)
        route.fulfill(content_type='application/javascript',body=source)
    else:
        static_route(route)

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=os.getenv('BLINQ_BROWSER') or browser_path())
        try:
            page=browser.new_page(viewport={'width':1440,'height':900})
            page.route('**'+'/'+'*',route_request)
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(ORIGIN+'/index.html?lang=sk',wait_until='networkidle')
            page.wait_for_function('window.bannerHarness && bannerHarness.state.ui?.elements?.HERO_BANNER_2')
            first=page.evaluate('''() => {
              const h=bannerHarness,s=h.state;
              s.route='admin';s.adminTab='banners';s.selectedElement='HERO_BANNER_1';
              s.ui.hero_banner.slot_count=2;s.ui.hero_banner.auto_rotate=true;s.ui.hero_banner.rotation_seconds=3;
              s.ui.elements.HERO_BANNER_1.content={enabled:true,type:'promo',eyebrow:'',headline:'Prvý banner',text:'',accent_text:'Telegram Community',image_url:'/assets/hero-reference-exact-v680.webp'};
              s.ui.elements.HERO_BANNER_2.content={enabled:true,type:'promo',eyebrow:'',headline:'Druhý banner',text:'Podnadpis',accent_text:'Telegram Community',image_url:'/assets/hero-reference-exact-v680.webp'};
              const html=h.heroSlideHtml({id:'HERO_BANNER_1',...s.ui.elements.HERO_BANNER_1},0);
              if(html.includes('Telegram Community')||html.includes('<p>'))throw Error('legacy accent or empty subtitle appeared');
              const host=document.getElementById('routePanel');
              host.hidden=false;document.getElementById('appShell').hidden=false;
              document.body.classList.add('blinq-admin');
              host.innerHTML=h.renderAdminBanners();h.wireAdmin();
              return {selected:s.selectedElement,preview:s.adminPreviewIndex,
                desktop:host.querySelector('[data-admin-preview-card="desktop"]').innerText,
                mobile:host.querySelector('[data-admin-preview-card="mobile"]').innerText,
                colors:host.querySelectorAll('[data-simple-banner-field="headline_color"],[data-simple-banner-field="text_color"],[data-simple-banner-field="eyebrow_color"]').length};
            }''')
            assert first['selected']=='HERO_BANNER_1',first
            assert first['preview']==0,first
            assert 'Prvý banner' in first['desktop'] and 'Prvý banner' in first['mobile'],first
            assert first['colors']==3,first
            studio=page.evaluate("""() => {
              const editor=document.querySelector('.admin-banner-workbench');
              const panels=[...editor.querySelectorAll('.admin-banner-device-panel')];
              const numbers=[...editor.querySelectorAll('.admin-banner-number-control input[type="number"]')];
              const rect=element=>element.getBoundingClientRect();
              return {
                panels:panels.length,
                desktopFields:panels[0]?.querySelectorAll('fieldset').length,
                mobileFields:panels[1]?.querySelectorAll('fieldset').length,
                desktopFieldsExist:Boolean(panels[0]?.querySelector('[data-simple-banner-field="desktop_social_x"]')),
                mobileFieldsExist:Boolean(panels[1]?.querySelector('[data-simple-banner-field="mobile_social_x"]')),
                desktopTop:rect(panels[0]).top,mobileTop:rect(panels[1]).top,
                panelWidth:rect(panels[0]).width,
                numericCount:numbers.length,
                numericHeight:rect(numbers[0]).height,
                background:getComputedStyle(editor,'::before').backgroundImage
              };
            }""")
            assert studio['panels']==2 and studio['desktopFields']==4 and studio['mobileFields']==4,studio
            assert studio['desktopFieldsExist'] and studio['mobileFieldsExist'],studio
            assert abs(studio['desktopTop']-studio['mobileTop'])<5 and studio['panelWidth']>350,studio
            assert studio['numericCount']==18 and studio['numericHeight']>=44,studio
            assert 'blinq_page_background.webp' in studio['background'],studio
            page.evaluate("""() => {
              const s=bannerHarness.state;
              const c=s.ui.elements.HERO_BANNER_1.content;
              c.social_telegram_text='Telegram';
              c.social_telegram_link='https://t.me/example';
              bannerHarness.state.adminPreviewIndex=0;
              bannerHarness.syncAdminHeroPreview();
            }""")
            social=page.evaluate("""() => ({
              desktop:document.querySelector('[data-admin-preview-card="desktop"] .hero-social-link.social-telegram')?.textContent.trim(),
              mobile:document.querySelector('[data-admin-preview-card="mobile"] .hero-social-link.social-telegram')?.textContent.trim()
            })""")
            assert social['desktop']=='Telegram' and social['mobile']=='Telegram',social
            layout=page.evaluate("""() => {
              const s=bannerHarness.state,c=s.ui.elements.HERO_BANNER_1.content;
              c.desktop_social_layout='column';c.mobile_social_layout='column';
              bannerHarness.syncAdminHeroPreview();
              const d=document.querySelector('[data-admin-preview-card="desktop"] .hero-social-links');
              const m=document.querySelector('[data-admin-preview-card="mobile"] .hero-social-links');
              return {
                desktopDirection:getComputedStyle(d).flexDirection,
                desktopWrap:getComputedStyle(d).flexWrap,
                mobileDirection:getComputedStyle(m).flexDirection,
                mobileWrap:getComputedStyle(m).flexWrap
              };
            }""")
            assert layout['desktopDirection']=='column' and layout['desktopWrap']=='nowrap',layout
            assert layout['mobileDirection']=='column' and layout['mobileWrap']=='nowrap',layout
            shadow=page.evaluate("""() => {
              const opacity=mode=>Number(getComputedStyle(document.querySelector('[data-admin-preview-card="'+mode+'"] .lean-admin-preview'),'::before').opacity);
              const edit=(field,value)=>{
                const input=document.querySelector('[data-simple-banner-field="'+field+'"]');
                if(!input)throw Error('Missing shadow setting: '+field);
                input.value=String(value);
                input.dispatchEvent(new Event('input',{bubbles:true}));
              };
              const initial={desktop:opacity('desktop'),mobile:opacity('mobile')};
              edit('desktop_shadow_strength',0);
              const disabled={desktop:opacity('desktop'),mobile:opacity('mobile')};
              edit('mobile_shadow_strength',4);
              const separate={desktop:opacity('desktop'),mobile:opacity('mobile')};
              const state=bannerHarness.state,content=state.ui.elements.HERO_BANNER_1.content;
              const html=bannerHarness.heroSlideHtml({id:'HERO_BANNER_1',...state.ui.elements.HERO_BANNER_1},0);
              const doc=document.createElement('div');doc.innerHTML=html;
              const inline=doc.firstElementChild.style;
              return {initial,disabled,separate,stored:{desktop:content.desktop_shadow_strength,mobile:content.mobile_shadow_strength},
                production:{desktop:inline.getPropertyValue('--hero-shadow-desktop-opacity'),mobile:inline.getPropertyValue('--hero-shadow-mobile-opacity')}};
            }""")
            assert abs(shadow['initial']['desktop']-1)<.001 and abs(shadow['initial']['mobile']-1)<.001,shadow
            assert shadow['disabled']['desktop']==0 and abs(shadow['disabled']['mobile']-1)<.001,shadow
            assert shadow['separate']['desktop']==0 and abs(shadow['separate']['mobile']-.4)<.001,shadow
            assert shadow['stored']=={'desktop':0,'mobile':4},shadow
            assert shadow['production']=={'desktop':'0','mobile':'0.4'},shadow
            # Regression: preview gradient and strength must match the *published*
            # banner, not a lighter preview-only overlay.
            def gradient_parity():
                return page.evaluate("""() => {
                  const host=document.querySelector('#dashboardHero');
                  if(!host)throw Error('Public hero container missing');
                  const previous=host.innerHTML;
                  const entry=bannerHarness.state.ui.elements.HERO_BANNER_1;
                  host.innerHTML=bannerHarness.heroSlideHtml({id:'HERO_BANNER_1',...entry},0);
                  try {
                    const publicHero=host.querySelector('.hero-slide');
                    const mode=innerWidth<=700?'mobile':'desktop';
                    const preview=document.querySelector('[data-admin-preview-card="'+mode+'"] .lean-admin-preview');
                    const live=getComputedStyle(publicHero,'::after');
                    const draft=getComputedStyle(preview,'::before');
                    return {viewport:innerWidth,mode,
                      publicGradient:live.backgroundImage,
                      previewGradient:draft.backgroundImage,
                      publicOpacity:live.opacity,previewOpacity:draft.opacity,
                      publicLayer:live.display,previewLayer:draft.display};
                  } finally {host.innerHTML=previous;}
                }""")
            desktop_parity=gradient_parity()
            assert desktop_parity['publicGradient']==desktop_parity['previewGradient'],desktop_parity
            assert desktop_parity['publicOpacity']==desktop_parity['previewOpacity'],desktop_parity
            assert desktop_parity['previewOpacity']=='0',desktop_parity
            # The published mobile-only media rules exclude admin mode; temporarily
            # leave admin mode so both samples use the same public viewport styles.
            page.set_viewport_size({'width':390,'height':900})
            page.evaluate("document.body.classList.remove('blinq-admin')")
            mobile_parity=gradient_parity()
            page.evaluate("document.body.classList.add('blinq-admin')")
            page.set_viewport_size({'width':1440,'height':900})
            assert mobile_parity['publicGradient']==mobile_parity['previewGradient'],mobile_parity
            assert mobile_parity['publicOpacity']==mobile_parity['previewOpacity'],mobile_parity
            assert mobile_parity['previewOpacity']=='0.4',mobile_parity
            # Regression: real DOM positions must move when each mode's X/Y inputs change.
            movement=page.evaluate("""() => {
              const s=bannerHarness.state,c=s.ui.elements.HERO_BANNER_1.content;
              c.social_youtube_link='https://youtube.com/example';
              c.social_youtube_text='YouTube';
              s.adminPreviewIndex=0;
              bannerHarness.syncAdminHeroPreview();
              const coords=mode=>{
                const card=document.querySelector('[data-admin-preview-card="'+mode+'"] .lean-admin-preview');
                const group=card.querySelector('.hero-social-links');
                const root=card.getBoundingClientRect(),box=group.getBoundingClientRect();
                return {x:box.left-root.left,y:box.top-root.top,width:root.width,height:root.height,
                  position:getComputedStyle(group).position,
                  direction:getComputedStyle(group).flexDirection,
                  wrap:getComputedStyle(group).flexWrap};
              };
              const edit=(field,value)=>{
                const input=document.querySelector('[data-simple-banner-field="'+field+'"]');
                if(!input)throw Error('Missing banner control '+field);
                input.value=String(value);
                input.dispatchEvent(new Event('input',{bubbles:true}));
              };
              edit('desktop_social_x',10);edit('desktop_social_y',14);
              edit('mobile_social_x',7);edit('mobile_social_y',16);
              const startDesktop=coords('desktop'),startMobile=coords('mobile');
              edit('desktop_social_x',48);edit('desktop_social_y',61);
              const desktop=coords('desktop'),mobileUnaffected=coords('mobile');
              edit('mobile_social_x',38);edit('mobile_social_y',64);
              const mobile=coords('mobile');
              const desktopLinks=[...document.querySelectorAll('[data-admin-preview-card="desktop"] .hero-social-link')];
              const stacked=desktopLinks.length===2 &&
                desktopLinks[1].getBoundingClientRect().top>desktopLinks[0].getBoundingClientRect().top;
              const height=+getComputedStyle(document.querySelector('[data-simple-banner-field="desktop_social_x"]')).height.replace('px','');
              const minus=document.querySelector('[data-simple-banner-field="desktop_social_x"]').parentElement.querySelector('[data-banner-step="-1"]');
              const plus=document.querySelector('[data-simple-banner-field="desktop_social_x"]').parentElement.querySelector('[data-banner-step="1"]');
              s.adminPreviewPinnedId=null;
              s.adminPreviewPaused=false;
              return {startDesktop,startMobile,desktop,mobileUnaffected,mobile,stacked,height,
                stepperButtons:Boolean(minus&&plus)};
            }""")
            assert movement['desktop']['position']=='absolute',movement
            assert movement['desktop']['x']-movement['startDesktop']['x']>movement['desktop']['width']*.32,movement
            assert movement['desktop']['y']-movement['startDesktop']['y']>movement['desktop']['height']*.35,movement
            assert abs(movement['mobileUnaffected']['x']-movement['startMobile']['x'])<2,movement
            assert abs(movement['mobileUnaffected']['y']-movement['startMobile']['y'])<2,movement
            assert movement['mobile']['x']-movement['startMobile']['x']>movement['mobile']['width']*.25,movement
            assert movement['mobile']['y']-movement['startMobile']['y']>movement['mobile']['height']*.38,movement
            assert movement['stacked'] and movement['height']>=44 and movement['stepperButtons'],movement
            page.wait_for_timeout(3300)
            second=page.evaluate('''() => ({selected:bannerHarness.state.selectedElement,
                preview:bannerHarness.state.adminPreviewIndex,
                desktop:document.querySelector('[data-admin-preview-card="desktop"]')?.innerText,
                mobile:document.querySelector('[data-admin-preview-card="mobile"]')?.innerText})''')
            assert second['selected']=='HERO_BANNER_1',second
            assert second['preview']==1,second
            assert 'Druhý banner' in second['desktop'] and 'Druhý banner' in second['mobile'],second
            page.evaluate('''() => {
              const input=document.querySelector('[data-simple-banner-field="headline"]');
              input.value='Zmenený nadpis';input.dispatchEvent(new Event('input',{bubbles:true}));
              if(bannerHarness.state.selectedElement!=='HERO_BANNER_1')throw Error('editor changed');
              bannerHarness.state.adminPreviewIndex=0;bannerHarness.syncAdminHeroPreview();
              if(!document.querySelector('[data-admin-preview-card="desktop"]').innerText.includes('Zmenený nadpis'))throw Error('preview did not update');
              const color=document.querySelector('[data-simple-banner-field="headline_color"]');
              color.value='#303030';color.dispatchEvent(new Event('change',{bubbles:true}));
            }''')
            final=page.evaluate('''() => ({stored:bannerHarness.state.ui.elements.HERO_BANNER_1.content.headline_color,
                current:document.querySelector('[data-simple-banner-field="headline"]')?.value,
                style:document.querySelector('[data-admin-preview-card="desktop"] .lean-admin-preview')?.getAttribute('style')})''')
            assert final['stored']=='#303030',final
            assert final['current']=='Zmenený nadpis',final
            assert '--creative-headline-color:#303030' in final['style'],final
            # A selected unpublished banner must be previewable independently of
            # the public rotation, and each font-size change must be visible.
            edited=page.evaluate('''() => {
              const h=bannerHarness,s=h.state;
              s.ui.hero_banner.slot_count=1;
              h.setSelectedElement('HERO_BANNER_2');
              const preview=()=>document.querySelector('[data-admin-preview-card="desktop"] .lean-admin-preview');
              const heading=()=>parseFloat(getComputedStyle(document.querySelector('[data-admin-preview-card="desktop"] .admin-hero-preview-copy strong')).fontSize);
              const small=document.querySelector('[data-simple-banner-field="desktop_headline_size"]');
              small.value='24';small.dispatchEvent(new Event('change',{bubbles:true}));
              const first=heading();
              const big=document.querySelector('[data-simple-banner-field="desktop_headline_size"]');
              big.value='72';big.dispatchEvent(new Event('change',{bubbles:true}));
              const second=heading();
              const mobileSize=document.querySelector('[data-simple-banner-field="mobile_headline_size"]');
              mobileSize.value='18';mobileSize.dispatchEvent(new Event('change',{bubbles:true}));
              const mobileHeading=parseFloat(getComputedStyle(document.querySelector('[data-admin-preview-card="mobile"] .admin-hero-preview-copy strong')).fontSize);
              const socialX=document.querySelector('[data-simple-banner-field="desktop_social_x"]');
              socialX.value='61';socialX.dispatchEvent(new Event('input',{bubbles:true}));
              const socialY=document.querySelector('[data-simple-banner-field="mobile_social_y"]');
              socialY.value='22';socialY.dispatchEvent(new Event('input',{bubbles:true}));
              const note=h.renderUpgradeTierCard('pro',s.ui.plans.pro,0,false,-1);
              const custom=h.renderUpgradeTierCard('pro',{...s.ui.plans.pro,note:'Vlastná poznámka'},0,false,-1);
              return {
                selected:s.selectedElement,pinned:s.adminPreviewPinnedId,paused:s.adminPreviewPaused,
                previewSlot:preview()?.dataset.previewSlot,
                previewStyle:preview()?.getAttribute('style'),
                first,second,mobileHeading,
                desktopSocialX:s.ui.elements.HERO_BANNER_2.content.desktop_social_x,
                mobileSocialY:s.ui.elements.HERO_BANNER_2.content.mobile_social_y,
                obsoleteNote:note.includes('Full core predictions and tournaments.'),
                customNote:custom.includes('Vlastná poznámka')
              };
            }''')
            assert edited['selected']=='HERO_BANNER_2' and edited['pinned']=='HERO_BANNER_2',edited
            assert edited['paused'] and edited['previewSlot']=='HERO_BANNER_2',edited
            assert '--creative-headline-size:72px' in edited['previewStyle'],edited
            assert edited['second']>edited['first'],edited
            assert edited['mobileHeading']<edited['second'],edited
            assert str(edited['desktopSocialX'])=='61' and str(edited['mobileSocialY'])=='22',edited
            assert not edited['obsoleteNote'] and edited['customNote'],edited
            assert not errors,errors
            print('PASS: live carousel, text, grayscale and no hidden accent')
        finally:
            browser.close()

if __name__=='__main__':
    main()
