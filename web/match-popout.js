(() => {
  'use strict';

  function safeAsset(value) {
    const url=String(value||'').trim();
    if(!/^\/assets\/[A-Za-z0-9_.\/-]+$/.test(url)||url.split('/').includes('..'))return '';
    return url;
  }

  function handleAssetImageError(event){
    const img=event?.target;
    if(!(img instanceof HTMLImageElement))return;
    if(img.matches('[data-flag-image]')){
      img.hidden=true;
      const fallback=img.nextElementSibling;
      if(fallback)fallback.hidden=false;
      return;
    }
    if(img.matches('[data-tournament-logo]')){
      const host=img.parentElement;
      if(host)host.classList.add('logo-failed');
      img.remove();
      return;
    }
    if(img.matches('[data-player-photo]')){
      const fallback=safeAsset(img.dataset.fallbackSrc||'');
      if(fallback&&img.dataset.fallbackApplied!=='1'&&img.getAttribute('src')!==fallback){
        img.dataset.fallbackApplied='1';
        img.src=fallback;
        return;
      }
      const host=img.parentElement;
      if(host){host.classList.remove('has-photo');host.textContent=img.dataset.fallbackText||'B';}
    }
  }

  document.addEventListener('error',handleAssetImageError,true);
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-match-tab]');
    if(!button||button.dataset.matchLocked==='1')return;
    const id=button.dataset.matchTab;
    document.querySelectorAll('[data-match-tab]').forEach(node=>{
      const active=node===button;
      node.classList.toggle('active',active);
      node.setAttribute('aria-selected',active?'true':'false');
    });
    document.querySelectorAll('[data-match-panel]').forEach(panel=>{
      const active=panel.dataset.matchPanel===id;
      panel.hidden=!active;
      panel.classList.toggle('active',active);
    });
  });
  document.querySelectorAll('[data-match-popout]').forEach(node=>node.remove());
})();
