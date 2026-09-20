/* BlinQ responsive helpers — 7.3.6-r28. Active responsive/table/sync behaviour only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let publishedAt = '';
  const pageLang=()=>document.documentElement.lang||'sk';
  const isSk=()=>pageLang().toLowerCase().startsWith('sk');
  const isCz=()=>pageLang().toLowerCase().startsWith('cs');
  const uiText=(en,sk,cz)=>isSk()?sk:isCz()?cz:en;


  function routeChanged(route, focus) {
    document.body.dataset.currentRoute = route;
    document.querySelectorAll('.mobile-tabs a').forEach(link => {
      const active = link.dataset.route === route;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (focus) {
      window.scrollTo({top: 0, behavior: 'instant'});
      $('pageTitle')?.focus({preventScroll: true});
    }
  }

  function cardsPerPanel() {
    return Math.max(1, parseInt(getComputedStyle(document.documentElement).getPropertyValue('--cards-per-panel'), 10) || 1);
  }

  function pager(host, page, count) {
    const shell = host?.parentElement;
    if(!shell) return;
    let label = shell.querySelector('.page-position');
    if (!label) {
      label = document.createElement('span');
      label.className = 'page-position';
      label.setAttribute('role', 'status');
      shell.appendChild(label);
    }
    label.textContent = `${page + 1} / ${count}`;
    label.hidden = count <= 1;
    shell.classList.toggle('has-pages', count > 1);
  }

  function prepareRoute(host) {
    if(!host) return;
    host.querySelectorAll('.picks-table, .results-table').forEach(table => {
      table.setAttribute('role', 'table');
      table.querySelectorAll('thead,tbody').forEach(group => group.setAttribute('role', 'rowgroup'));
      table.querySelectorAll('tr').forEach(row => row.setAttribute('role', 'row'));
      table.querySelectorAll('td').forEach(cell => cell.setAttribute('role', 'cell'));
      const headers = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
      table.querySelectorAll('tbody tr').forEach(row => {
        [...row.children].forEach((cell, i) => cell.dataset.label = headers[i] || '');
      });
      table.querySelectorAll('th').forEach(th => {th.setAttribute('scope', 'col');th.setAttribute('role', 'columnheader');});
    });
    host.querySelectorAll('.route-rules').forEach(rule => {
      if(rule.closest('.selection-details')) return;
      const details = document.createElement('details');
      details.className = 'selection-details';
      const summary = document.createElement('summary');
      summary.textContent = uiText('How these predictions are selected','Ako sa tieto predikcie vyberajú','Jak se tyto predikce vybírají');
      rule.replaceWith(details);
      details.append(summary, rule);
    });
  }

  function sync(status, generatedAt) {
    if (generatedAt) publishedAt = generatedAt;
    const node = $('syncStatus');
    if (!node) return;
    let time = '';
    if (publishedAt && Number.isFinite(Date.parse(publishedAt))) {
      time = new Intl.DateTimeFormat(document.documentElement.lang || 'en', {hour: '2-digit', minute: '2-digit'}).format(new Date(publishedAt));
    }
    node.dataset.state = status;
    node.textContent = {
      loading: uiText('DATA · Refreshing…','DÁTA · Obnovujem…','DATA · Obnovuji…'),
      ready: time ? `${uiText('DATA','DÁTA','DATA')} · ${time}` : uiText('DATA · Connected','DÁTA · Pripojené','DATA · Připojeno'),
      stale: time ? `STALE · ${time}` : uiText('STALE · Waiting for update','STARÉ · Čakám na aktualizáciu','STARÉ · Čekám na aktualizaci'),
      error: uiText('REFRESH FAILED','OBNOVENIE ZLYHALO','OBNOVENÍ SELHALO'),
      offline: uiText('OFFLINE · Cached data','OFFLINE · Dáta z cache','OFFLINE · Data z cache')
    }[status] || uiText('DATA · Connecting…','DÁTA · Pripájam…','DATA · Připojuji…');
    const refresh=$('syncRefresh'); if(refresh) refresh.disabled = status === 'loading';
  }

  function refreshFinished() { const refresh=$('syncRefresh'); if(refresh) refresh.disabled = false; }

  let viewportRaf=0;
  function syncViewportState(){
    cancelAnimationFrame(viewportRaf);
    viewportRaf=requestAnimationFrame(()=>{
      const vv=window.visualViewport;
      const width=Math.round(vv?.width||window.innerWidth||document.documentElement.clientWidth||0);
      const height=Math.round(vv?.height||window.innerHeight||document.documentElement.clientHeight||0);
      const mobile=width<=900;
      document.documentElement.style.setProperty('--bq-viewport-height',`${height}px`);
      document.body.classList.toggle('blinq-mobile-layout',mobile);
      const keyboardOpen=Boolean(mobile&&vv&&window.innerHeight&&vv.height<window.innerHeight*.78);
      document.body.classList.toggle('blinq-mobile-keyboard-open',keyboardOpen);
    });
  }

  function init() {
    syncViewportState();
    window.addEventListener('resize',syncViewportState,{passive:true});
    window.addEventListener('orientationchange',syncViewportState,{passive:true});
    window.visualViewport?.addEventListener('resize',syncViewportState,{passive:true});
    window.visualViewport?.addEventListener('scroll',syncViewportState,{passive:true});
    const skip=document.querySelector('.skip-link');
    if(skip)skip.onclick=event=>{event.preventDefault();$('mainContent')?.focus();};

    document.querySelectorAll('.pick-carousel-shell, .market-carousel-shell').forEach(shell => {
      let start = null;
      shell.addEventListener('pointerdown', event => {
        if (event.pointerType !== 'touch' || event.target.closest('button,a')) return;
        start = {x: event.clientX, y: event.clientY};
      }, {passive: true});
      shell.addEventListener('pointerup', event => {
        if (!start) return;
        const dx = event.clientX - start.x, dy = event.clientY - start.y;
        start = null;
        if (Math.abs(dx) < 55 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        const button = shell.querySelector(dx < 0 ? '[data-market-next],#nextPick' : '[data-market-prev],#prevPick');
        if (button && !button.hidden && !button.disabled) button.click();
      }, {passive: true});
      shell.addEventListener('pointercancel', () => {start = null;}, {passive: true});
    });

    document.addEventListener('error', event => {
      const img = event.target;
      if (img.tagName !== 'IMG' || !img.closest('.market-card .player-avatar')) return;
      // Player photos rendered by app.js have a deterministic two-stage fallback:
      // provider/local photo -> gender-aware missing_foto asset -> initials.
      // Do not let the responsive compatibility handler short-circuit that flow.
      if (img.matches('[data-player-photo]')) return;
      const avatar = img.parentElement, name = avatar.parentElement.querySelector('.player-name')?.textContent || '?';
      avatar.classList.remove('has-photo');
      avatar.textContent = name.split(/\s+/).slice(0,2).map(s => s[0]).join('').toUpperCase();
    }, true);
  }

  window.BlinqUI = Object.freeze({init, cardsPerPanel, pager, prepareRoute, routeChanged, sync, refreshFinished});
})();
