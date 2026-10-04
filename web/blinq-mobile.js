/* BlinQ mobile presentation adapter, r61. No API, auth or entitlement changes. */
(() => {
  'use strict';
  if (window.__blinqMobileInstalled) return;
  const header = document.querySelector('#appShell .header-top');
  const shell = document.getElementById('appShell');
  if (!header || !shell || !window.HTMLDialogElement) return;
  window.__blinqMobileInstalled = true;
  const mq = matchMedia('(max-width: 900px)');
  const byId = id => document.getElementById(id);
  const button = (text, action) => {
    const node = document.createElement('button');
    node.type = 'button'; node.textContent = text;
    node.addEventListener('click', action); return node;
  };
  const toggle = button('☰', () => openMenu());
  toggle.id = 'bqm-toggle'; toggle.className = 'bqm-toggle';
  toggle.setAttribute('aria-label', 'Otvoriť menu');
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', 'bqm-dialog');
  header.prepend(toggle);
  const projects = button('', () => {
    const groups = joinedControls();
    if (groups.length === 1) { groups[0].click(); return; }
    if (!mq.matches) {
      const desktopProjects = byId('profileProjectsLink');
      if (available(desktopProjects)) { desktopProjects.click(); return; }
    }
    openMenu(); render('projects');
  });
  const projectSymbol = document.createElement('img');
  projectSymbol.src = '/assets/project-pp.svg';
  projectSymbol.alt = '';
  projectSymbol.width = 24; projectSymbol.height = 24;
  projects.append(projectSymbol);
  projects.id = 'bqm-projects';
  projects.setAttribute('aria-label', 'Moje projektové skupiny');
  header.querySelector('.header-actions').prepend(projects);
  function joinedControls() {
    return Array.from(document.querySelectorAll('#projectGroupBar [data-project-group-open]')).filter(available);
  }
  function syncProjects() {
    const groups = joinedControls();
    projects.hidden = !groups.length;
    const unread = groups.reduce((sum, node) => sum + (Number(node.querySelector('b')?.textContent) || 0), 0);
    const displayUnread = unread > 99 ? '99+' : String(unread);
    projects.dataset.unread = unread ? displayUnread : '';
    projects.setAttribute('aria-label', 'Moje projektové skupiny' + (unread ? ', ' + displayUnread + ' neprečítaných' : ''));
    projects.classList.toggle('has-unread', unread > 0);
    document.body.classList.toggle('bqm-project-admin', available(byId('profileAdminLink')));
  }
  const dialog = document.createElement('dialog');
  dialog.id = 'bqm-dialog'; dialog.setAttribute('aria-label', 'Hlavné menu BlinQ');
  const top = document.createElement('div'); top.className = 'bqm-top';
  const close = button('×', () => dialog.close()); close.setAttribute('aria-label', 'Zavrieť menu');
  const logo = document.createElement('img');
  logo.src = header.querySelector('.brand img')?.getAttribute('src') || '/assets/blinq_logo.svg';
  logo.alt = 'BlinQ';
  const home = document.createElement('a');
  home.href = '#predictions';
  home.dataset.route = 'predictions';
  home.setAttribute('aria-label', 'BlinQ · hlavná stránka');
  home.style.justifySelf = 'center';
  home.append(logo);
  home.addEventListener('click', () => dialog.close());
  top.append(close, home);
  const nav = document.createElement('nav'); nav.setAttribute('aria-label', 'Mobilná navigácia');
  const note = document.createElement('p'); note.className = 'bqm-note'; note.setAttribute('role', 'status');
  dialog.append(top, nav, note); document.body.append(dialog);

  // Keep account actions in the original avatar menu and reuse existing handlers.
  const profileMenu = byId('profileMenu');
  function avatarAction(label, action) {
    const item = button(label, () => {
      byId('profileButton')?.click();
      action();
    });
    item.className = 'bqm-avatar-action';
    profileMenu?.insertBefore(item, byId('headerLogoutButton'));
    return item;
  }
  const avatarUpgrade = avatarAction('Upgrade', () => byId('topUpgradeButton')?.click());
  const avatarCommunity = avatarAction('Komunita', () => openMenu('community'));
  avatarAction('Jazyk', () => openMenu('language'));
  function syncAvatarActions() {
    avatarUpgrade.hidden = !available(byId('topUpgradeButton'));
    avatarCommunity.hidden = !available(byId('telegramGroupsPanel'));
  }
  if (profileMenu) new MutationObserver(syncAvatarActions).observe(profileMenu, {attributes:true,attributeFilter:['hidden']});

  let currentLevel = 'root';
  function enabled() { return (mq.matches || document.body.classList.contains('blinq-admin')) && !shell.hidden; }
  byId('profileButton')?.addEventListener('click', event => {
    if (!enabled() || mq.matches) return;
    event.stopImmediatePropagation();
    byId('profileMenuToggle')?.click();
  }, true);
  function sync() {
    document.body.classList.toggle('bqm-enabled', enabled());
    syncProjects();
    if (!enabled() && dialog.open) dialog.close();
  }
  function available(node) { return node && !node.hidden && !node.disabled && node.getAttribute('aria-disabled') !== 'true'; }
  function finish(node) {
    // Resolve and use the original control: its access checks and listeners remain authoritative.
    if (!available(node)) { note.textContent = 'Táto položka momentálne nie je dostupná.'; return; }
    dialog.close(); node.click();
  }
  function proxy(label, resolve) {
    if (!available(resolve())) return;
    nav.append(button(label, () => finish(resolve())));
  }
  function section(label, level) { nav.append(button(label + ' ›', () => render(level))); }
  function render(level) {
    currentLevel = level; nav.replaceChildren(); note.textContent = '';
    if (level !== 'root') nav.append(button(level === 'community' || level === 'language' ? '← Menu účtu' : '← Hlavné menu', event => {
      event.stopPropagation();
      if (level === 'community' || level === 'language') { dialog.close(); byId('profileButton')?.click(); }
      else render('root');
    }));
    if (level === 'root') {
      nav.append(button('Späť na hlavnú stránku', () => {
        dialog.close();
        header.querySelector('.brand')?.click();
      }));
      section('Predikcie', 'predictions');
      const resultsSource = document.querySelector('.reference-navigation [data-route="results"]');
      const resultsLocked = resultsSource?.classList.contains('access-nav-locked');
      nav.append(button('Výsledky' + (resultsLocked ? ' 🔒' : ''), () => {
        dialog.close();
        // The desktop link may be hidden by presentation settings; its original
        // route handler still enforces the account's results access.
        resultsSource?.click();
      }));
      proxy('Live radar', () => byId('insightShortcut'));
      if (joinedControls().length) section('Moje skupiny', 'projects');
      proxy('Info', () => byId('insightBell'));
    } else if (level === 'predictions') {
      proxy('Všetky predikcie', () => document.querySelector('.reference-navigation [data-route="predictions"]'));
      document.querySelectorAll('#dailyHubTabs [data-daily-hub-tab]').forEach(source => {
        const key = source.dataset.dailyHubTab;
        const label = source.querySelector('.daily-hub-tab-copy > span')?.textContent || source.textContent;
        const menuLabel = label.trim() + (source.classList.contains('is-locked') ? ' 🔒' : '');
        nav.append(button(menuLabel, () => {
          const original = Array.from(document.querySelectorAll('#dailyHubTabs [data-daily-hub-tab]')).find(n => n.dataset.dailyHubTab === key);
          if (!available(original)) { render('predictions'); return; }
          dialog.close();
          document.querySelector('.reference-navigation [data-route="predictions"]')?.click();
          // Routing can replace the tab nodes synchronously.
          Array.from(document.querySelectorAll('#dailyHubTabs [data-daily-hub-tab]')).find(n => n.dataset.dailyHubTab === key)?.click();
        }));
      });
    } else if (level === 'membership') {
      proxy('Upgrade', () => byId('topUpgradeButton'));
    } else if (level === 'projects') {
      joinedControls().forEach(source => nav.append(button(source.querySelector('strong')?.textContent || source.textContent.trim(), () => {
        const id = source.dataset.projectGroupOpen;
        const fresh = joinedControls().find(node => node.dataset.projectGroupOpen === id);
        if (fresh) finish(fresh); else render('projects');
      })));
      if (!joinedControls().length) note.textContent = 'Zatiaľ nie si členom projektovej skupiny.';
    } else if (level === 'account') {
      proxy('Môj účet', () => byId('profileAccountLink'));
      proxy('Admin', () => byId('profileAdminLink'));
      proxy('Odhlásiť sa', () => byId('headerLogoutButton'));
    } else if (level === 'language') {
      document.querySelectorAll('#footerLanguages a').forEach(source => proxy(source.textContent.trim(), () => source));
    } else if (level === 'community') {
      document.querySelectorAll('#telegramGroupsPanel .tg-group-card').forEach(card => {
        const label = card.querySelector('.tg-group-copy strong')?.textContent || 'Telegram';
        const action = card.querySelector('a.tg-group-cta,button.tg-group-cta');
        if (action) proxy(label, () => action);
        else { const unavailable = button(label + ' · nedostupné', () => {}); unavailable.disabled = true; nav.append(unavailable); }
      });
    }
    nav.querySelector('button')?.focus();
  }
  function openMenu(level = 'root') {
    if (!enabled()) return;
    dialog.showModal(); document.body.classList.add('bqm-menu-open');
    toggle.setAttribute('aria-expanded', 'true'); render(level);
  }
  dialog.addEventListener('close', () => {
    document.body.classList.remove('bqm-menu-open'); toggle.setAttribute('aria-expanded', 'false');
    if (enabled()) toggle.focus();
  });
  dialog.addEventListener('cancel', event => {
    if (currentLevel !== 'root') { event.preventDefault(); render('root'); }
  });
  window.addEventListener('hashchange', () => { if (dialog.open) dialog.close(); });
  mq.addEventListener('change', sync);
  const groupBar = byId('projectGroupBar');
  if (groupBar) new MutationObserver(syncProjects).observe(groupBar, {childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden']});
  const adminLink = byId('profileAdminLink');
  if (adminLink) new MutationObserver(syncProjects).observe(adminLink, {attributes:true,attributeFilter:['hidden']});
  new MutationObserver(sync).observe(shell, { attributes: true, attributeFilter: ['hidden'] });
  new MutationObserver(() => {
    if (document.body.classList.contains('bqm-enabled') !== enabled()) sync();
  }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  sync();
})();
