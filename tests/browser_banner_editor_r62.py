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
