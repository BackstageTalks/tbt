/* BlinQ mobile presentation adapter, r62. No API, auth or entitlement changes. */
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
  // Keep the original SVG brand image and use its link as the existing
  // responsive/admin menu control. Desktop public logo remains Home.
  const brand = header.querySelector('a.brand');
  const homeLabel = brand?.getAttribute('aria-label') || 'BlinQ home';
  function syncBrandMenu() {
    if (!brand) return;
    if (menuEnabled()) {
      brand.setAttribute('role', 'button');
      brand.setAttribute('aria-haspopup', 'dialog');
      brand.setAttribute('aria-controls', 'bqm-dialog');
      brand.setAttribute('aria-expanded', String(dialog.open));
      brand.setAttribute('aria-label', 'Otvoriť hlavné menu BlinQ');
      brand.classList.add('brand-menu-trigger');
    } else {
      brand.removeAttribute('role');
      brand.removeAttribute('aria-haspopup');
      brand.removeAttribute('aria-controls');
      brand.removeAttribute('aria-expanded');
      brand.setAttribute('aria-label', homeLabel);
      brand.classList.remove('brand-menu-trigger');
    }
  }
  brand?.addEventListener('click', event => {
    if (!menuEnabled()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openMenu('root', false, brand);
  });
  brand?.addEventListener('keydown', event => {
    if (!menuEnabled() || (event.key !== ' ' && event.key !== 'Spacebar')) return;
    event.preventDefault();
    openMenu('root', false, brand);
  });
  const projects = button('', () => {
    const groups = joinedControls();
    if (groups.length === 1) { groups[0].click(); return; }
    if (!mq.matches) {
      const desktopProjects = byId('profileProjectsLink');
      if (available(desktopProjects)) { desktopProjects.click(); return; }
    }
    openMenu(); render('projects');
  });
  // Gold rocket: the existing project-menu action and unread counts are preserved.
  const projectSymbol = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  projectSymbol.setAttribute('viewBox', '0 0 32 32');
  projectSymbol.setAttribute('aria-hidden', 'true');
  projectSymbol.setAttribute('focusable', 'false');
  projectSymbol.classList.add('project-rocket-icon');
  projectSymbol.innerHTML = '<path d="M12.6 21.1 10.9 17.5 14.8 11.7C18.1 7.1 22.4 5.2 27 5c-.2 4.6-2.1 8.9-6.7 12.2l-5.8 3.9-3.6-1.7Z"/><circle cx="21.7" cy="10.7" r="2.35"/><path d="M10.9 17.5 6.1 17.9 3.9 23l8.7-1.9M14.5 21.1 13.4 29l5-2.4 1.9-9.4M7.4 24.6l-3 3"/>';
  projects.append(projectSymbol);
  projects.id = 'bqm-projects';
  projects.setAttribute('aria-label', 'Moje projektové skupiny');
  projects.dataset.navTooltip = 'Moje skupiny';
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
  const scrim = document.createElement('div');
  scrim.id = 'bqm-menu-scrim';
  scrim.hidden = true;
  scrim.setAttribute('aria-hidden', 'true');
  const dialog = document.createElement('dialog');
  dialog.id = 'bqm-dialog'; dialog.setAttribute('aria-label', 'Hlavné menu BlinQ');
  dialog.setAttribute('aria-modal', 'false');
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
  dialog.append(top, nav, note); document.body.append(scrim, dialog);
  scrim.addEventListener('click', () => { if (dialog.open) dialog.close(); });

  // Both entry points share one dialog. The existing controls remain
  // authoritative for permissions, membership and sign-out.
  const profileMenu = byId('profileMenu');
  const profileButton = byId('profileButton');
  const profileToggle = byId('profileMenuToggle');
  let currentLevel = 'root';
  let accountExpanded = false;
  let navigationExpanded = true;
  let lastOpener = brand;
  function enabled() { return (mq.matches || document.body.classList.contains('blinq-admin')) && !shell.hidden; }
  function menuEnabled() { return !shell.hidden; }
  function syncAvatarMenu() {
    for (const control of [profileButton, profileToggle]) {
      if (!control) continue;
      if (menuEnabled()) {
        control.setAttribute('aria-controls', 'bqm-dialog');
        control.setAttribute('aria-haspopup', 'dialog');
        control.setAttribute('aria-expanded', String(dialog.open));
      } else {
        control.setAttribute('aria-controls', 'profileMenu');
        control.removeAttribute('aria-haspopup');
        control.setAttribute('aria-expanded', 'false');
      }
    }
    if (menuEnabled() && profileMenu) profileMenu.hidden = true;
  }
  function onAvatarOpen(event) {
    if (!menuEnabled()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openMenu('root', true, event.currentTarget);
  }
  profileButton?.addEventListener('click', onAvatarOpen, true);
  profileToggle?.addEventListener('click', onAvatarOpen, true);
  function syncMobileIconNav() {
    document.querySelectorAll('[data-mobile-action]').forEach(node => {
      const action = node.dataset.mobileAction;
      if (action === 'live') node.hidden = !available(byId('insightShortcut'));
      if (action === 'upgrade') node.hidden = !available(byId('topUpgradeButton'));
    });
  }
  function sync() {
    document.body.classList.toggle('bqm-enabled', enabled());
    document.body.classList.toggle('bqm-unified-menu', menuEnabled());
    syncProjects();
    syncMobileIconNav();
    if (!menuEnabled() && dialog.open) dialog.close();
    syncBrandMenu();
    syncAvatarMenu();
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
    if (level !== 'root') nav.append(button(level === 'community' || level === 'language' ? '← Môj účet' : '← Hlavné menu', () => {
      if (level === 'community' || level === 'language') accountExpanded = true;
      render('root');
    }));
    if (level === 'root') {
      const navHeading = document.createElement('p');
      navHeading.className = 'bqm-section-label';
      navHeading.textContent = 'NAVIGÁCIA';
      nav.append(navHeading);
      nav.append(button('Domov', () => {
        dialog.close();
        document.querySelector('.reference-navigation [data-route="predictions"]')?.click();
      }));
      section('Predikcie', 'predictions');
      nav.append(button('Porovnávač', () => {
        dialog.close();
        document.querySelector('.reference-navigation [data-route="compare"]')?.click();
      }));
      const resultsSource = document.querySelector('.reference-navigation [data-route="results"]');
      const resultsLocked = resultsSource?.classList.contains('access-nav-locked');
      nav.append(button('Výsledky' + (resultsLocked ? ' 🔒' : ''), () => {
        dialog.close();
        // The desktop link may be hidden by presentation settings; its original
        // route handler still enforces the account's results access.
        resultsSource?.click();
      }));
      // Match the locked LIVE header control: the shortcut remains visible
      // to eligible users, but carries an upgrade requirement until unlocked.
      const liveSource = byId('insightShortcut');
      const liveLocked = !!liveSource?.dataset.upgradePlan || !!liveSource?.classList.contains('is-access-locked');
      if (available(liveSource)) {
        nav.append(button('Live radar' + (liveLocked ? ' 🔒' : ''), () => finish(byId('insightShortcut'))));
      }
      if (joinedControls().length) section('Moje skupiny', 'projects');
      proxy('Info', () => byId('insightBell'));
      const divider = document.createElement('div');
      divider.className = 'bqm-menu-divider';
      divider.setAttribute('aria-hidden', 'true');
      nav.append(divider);
      const accountPanel = document.createElement('div');
      accountPanel.id = 'bqm-account-panel';
      accountPanel.className = 'bqm-account-panel';
      const accountToggle = button('Môj účet', () => {
        accountExpanded = !accountExpanded;
        accountPanel.hidden = !accountExpanded;
        accountToggle.setAttribute('aria-expanded', String(accountExpanded));
        accountToggle.classList.toggle('is-open', accountExpanded);
        if (accountExpanded) {
          navigationExpanded = false;
          navigationPanel.hidden = true;
          navigationToggle.setAttribute('aria-expanded', 'false');
          navigationToggle.classList.remove('is-open');
          accountPanel.querySelector('button')?.focus();
        }
      });
      accountToggle.className = 'bqm-account-switch';
      accountToggle.setAttribute('aria-controls', 'bqm-account-panel');
      accountToggle.setAttribute('aria-expanded', String(accountExpanded));
      accountToggle.classList.toggle('is-open', accountExpanded);
      nav.append(accountToggle);
      function accountAction(label, resolve) {
        const source = resolve();
        if (!available(source)) return;
        accountPanel.append(button(label, () => finish(resolve())));
      }
      accountAction('Profil a členstvo', () => byId('profileAccountLink'));
      accountAction('Upgrade', () => byId('topUpgradeButton'));
      if (available(byId('telegramGroupsPanel'))) accountPanel.append(button('Komunita', () => render('community')));
      accountPanel.append(button('Jazyk', () => render('language')));
      accountAction('Admin', () => byId('profileAdminLink'));
      accountAction('Odhlásiť sa', () => byId('headerLogoutButton'));
      accountPanel.hidden = !accountExpanded;
      nav.append(accountPanel);

      // The same menu opens from both controls, but starts in a different
      // section: avatar -> account first, logo -> navigation first.
      // The account is always the upper section, navigation is lower.
      const navigationPanel = document.createElement('div');
      navigationPanel.id = 'bqm-navigation-panel';
      navigationPanel.className = 'bqm-navigation-panel';
      navigationPanel.setAttribute('role', 'group');
      navigationPanel.setAttribute('aria-label', 'Navigácia');
      navHeading.remove();
      while (nav.firstChild !== divider) navigationPanel.append(nav.firstChild);
      divider.remove();
      const navigationToggle = button('Navigácia', () => {
        navigationExpanded = !navigationExpanded;
        navigationPanel.hidden = !navigationExpanded;
        navigationToggle.setAttribute('aria-expanded', String(navigationExpanded));
        navigationToggle.classList.toggle('is-open', navigationExpanded);
        if (navigationExpanded) {
          accountExpanded = false;
          accountPanel.hidden = true;
          accountToggle.setAttribute('aria-expanded', 'false');
          accountToggle.classList.remove('is-open');
          navigationPanel.querySelector('button')?.focus();
        }
      });
      navigationToggle.className = 'bqm-navigation-switch';
      navigationToggle.setAttribute('aria-controls', 'bqm-navigation-panel');
      navigationToggle.setAttribute('aria-expanded', String(navigationExpanded));
      navigationToggle.classList.toggle('is-open', navigationExpanded);
      navigationPanel.hidden = !navigationExpanded;
      nav.append(navigationToggle, navigationPanel);
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
    if (level === 'root' && accountExpanded) {
      nav.querySelector('#bqm-account-panel button')?.focus();
    } else if (level === 'root' && navigationExpanded) {
      nav.querySelector('#bqm-navigation-panel button')?.focus();
    } else {
      nav.querySelector('button')?.focus();
    }
  }
  function openMenu(level = 'root', expandAccount = false, opener = brand) {
    if (!menuEnabled()) return;
    if (dialog.open) dialog.close();
    accountExpanded = Boolean(expandAccount);
    navigationExpanded = !accountExpanded;
    lastOpener = opener || brand;
    dialog.dataset.anchor = [profileButton, profileToggle].includes(lastOpener) ? 'account' : 'brand';
    scrim.hidden = false;
    dialog.show(); document.body.classList.add('bqm-menu-open');
    toggle.setAttribute('aria-expanded', 'true');
    syncBrandMenu();
    syncAvatarMenu();
    render(level);
  }
  dialog.addEventListener('close', () => {
    scrim.hidden = true;
    document.body.classList.remove('bqm-menu-open'); toggle.setAttribute('aria-expanded', 'false');
    syncBrandMenu();
    syncAvatarMenu();
    if (menuEnabled()) lastOpener?.focus();
  });
  dialog.addEventListener('cancel', event => {
    if (currentLevel !== 'root') { event.preventDefault(); render('root'); }
  });
  // A non-modal dialog does not automatically receive the native Escape cancel.
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !dialog.open) return;
    event.preventDefault(); event.stopPropagation();
    if (currentLevel !== 'root') render('root');
    else dialog.close();
  }, true);
  window.addEventListener('hashchange', () => { if (dialog.open) dialog.close(); });
  mq.addEventListener('change', sync);
  const groupBar = byId('projectGroupBar');
  if (groupBar) new MutationObserver(syncProjects).observe(groupBar, {childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden']});
  const adminLink = byId('profileAdminLink');
  if (adminLink) new MutationObserver(syncProjects).observe(adminLink, {attributes:true,attributeFilter:['hidden']});
  const liveSource = byId('insightShortcut');
  if (liveSource) new MutationObserver(syncMobileIconNav).observe(liveSource, {attributes:true,attributeFilter:['hidden','disabled']});
  const upgradeSource = byId('topUpgradeButton');
  if (upgradeSource) new MutationObserver(syncMobileIconNav).observe(upgradeSource, {attributes:true,attributeFilter:['hidden','disabled']});
  document.querySelectorAll('[data-mobile-action]').forEach(node => node.addEventListener('click', () => {
    const action = node.dataset.mobileAction;
    if (action === 'live') finish(byId('insightShortcut'));
    if (action === 'upgrade') finish(byId('topUpgradeButton'));
  }));
  new MutationObserver(sync).observe(shell, { attributes: true, attributeFilter: ['hidden'] });
  new MutationObserver(() => {
    if (document.body.classList.contains('bqm-enabled') !== enabled()) sync();
  }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  sync();
})();
