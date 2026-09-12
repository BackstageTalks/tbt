/* Responsive presentation only. Authentication, entitlements and data remain in app.js. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const compact = () => matchMedia('(max-width: 1023px)').matches;
  let lastFocus, menuOpen = false, publishedAt = '';
  const pageLang=()=>document.documentElement.lang||'sk';
  const isSk=()=>pageLang().toLowerCase().startsWith('sk');
  const isCz=()=>pageLang().toLowerCase().startsWith('cs');
  const uiText=(en,sk,cz)=>isSk()?sk:isCz()?cz:en;

  function closeMenu(restore = true) {
    if (!menuOpen) return;
    menuOpen = false;
    document.body.classList.remove('nav-open');
    const backdrop=$('navBackdrop'),toggle=$('menuToggle'),nav=$('appNavigation'),main=$('mainContent'),tabs=$('mobileTabs');
    if(backdrop)backdrop.hidden=true;
    if(toggle)toggle.setAttribute('aria-expanded','false');
    if(nav){nav.removeAttribute('role');nav.removeAttribute('aria-modal');nav.inert=compact();}
    if(main)main.inert=false;
    if(tabs)tabs.inert=false;
    if (restore && lastFocus?.isConnected) lastFocus.focus();
  }
  function openMenu() {
    if (!compact()) return;
    lastFocus = document.activeElement;
    menuOpen = true;
    document.body.classList.add('nav-open');
    const backdrop=$('navBackdrop'),toggle=$('menuToggle'),nav=$('appNavigation'),main=$('mainContent'),tabs=$('mobileTabs'),close=$('menuClose');
    if(backdrop)backdrop.hidden=false;
    if(toggle)toggle.setAttribute('aria-expanded','true');
    if(nav){nav.inert=false;nav.setAttribute('role','dialog');nav.setAttribute('aria-modal','true');}
    if(main)main.inert=true;
    if(tabs)tabs.inert=true;
    close?.focus();
  }
  function routeChanged(route, focus) {
    closeMenu(false);
    document.body.dataset.currentRoute = route;
    document.querySelectorAll('.nav-link, .mobile-tabs a').forEach(link => {
      const active = link.dataset.route === route;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (focus) {
      window.scrollTo({top: 0, behavior: 'instant'});
      $('pageTitle').focus({preventScroll: true});
    }
  }
  function cardsPerPanel() {
    return Math.max(1, parseInt(getComputedStyle(document.documentElement).getPropertyValue('--cards-per-panel'), 10) || 1);
  }
  function pager(host, page, count) {
    const shell = host.parentElement;
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
    // Preserve real table semantics on desktop and expose column names on narrow screens.
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
      const details = document.createElement('details');
      details.className = 'selection-details';
      const summary = document.createElement('summary');
      summary.textContent = uiText('How these picks are selected','Ako sa tieto tipy vyberajú','Jak se tyto tipy vybírají');
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
      loading: uiText('LIVE · Refreshing…','LIVE · Obnovujem…','LIVE · Obnovuji…'),
      ready: time ? `LIVE · ${time}` : uiText('LIVE · Connected','LIVE · Pripojené','LIVE · Připojeno'),
      stale: time ? `STALE · ${time}` : uiText('STALE · Waiting for update','STARÉ · Čakám na aktualizáciu','STARÉ · Čekám na aktualizaci'),
      error: uiText('REFRESH FAILED','OBNOVENIE ZLYHALO','OBNOVENÍ SELHALO'),
      offline: uiText('OFFLINE · Cached data','OFFLINE · Dáta z cache','OFFLINE · Data z cache')
    }[status] || uiText('LIVE · Connecting…','LIVE · Pripájam…','LIVE · Připojuji…');
    $('syncRefresh').disabled = status === 'loading';
  }
  function refreshFinished() { $('syncRefresh').disabled = false; }
  function init() {
    const skip=document.querySelector('.skip-link'),toggle=$('menuToggle'),close=$('menuClose'),backdrop=$('navBackdrop'),nav=$('appNavigation');
    if(skip)skip.onclick=event=>{event.preventDefault();$('mainContent')?.focus();};
    if(toggle)toggle.onclick=openMenu;
    if(close)close.onclick=()=>closeMenu();
    if(backdrop)backdrop.onclick=()=>closeMenu();
    if(nav)nav.inert=compact();
    matchMedia('(max-width: 1023px)').addEventListener('change', () => {
      closeMenu();
      const nav=$('appNavigation');if(nav)nav.inert=compact();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        if (menuOpen) {event.preventDefault();closeMenu();}
        const menu = $('profileMenu');
        if (!menu.hidden) {menu.hidden = true;$('profileMenuToggle').setAttribute('aria-expanded', 'false');$('profileMenuToggle').focus();}
      }
      if (!menuOpen || event.key !== 'Tab') return;
      const focusable = [...$('appNavigation').querySelectorAll('a[href],button:not(:disabled)')].filter(n => n.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault();last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault();first?.focus();}
    });
    // Swipe is optional; visible arrow buttons remain available to all input types.
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
    // Recover absent market-player photos without inline handlers (CSP compatible).
    document.addEventListener('error', event => {
      const img = event.target;
      if (img.tagName !== 'IMG' || !img.closest('.market-card .player-avatar')) return;
      const avatar = img.parentElement, name = avatar.parentElement.querySelector('.player-name')?.textContent || '?';
      avatar.classList.remove('has-photo');
      avatar.textContent = name.split(/\s+/).slice(0,2).map(s => s[0]).join('').toUpperCase();
    }, true);
  }
  window.BlinqUI = Object.freeze({init, cardsPerPanel, pager, prepareRoute, routeChanged, closeMenu, sync, refreshFinished});
})();
