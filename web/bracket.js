(() => {
  'use strict';

  const copy = (sk, en, cs = sk) => document.documentElement.lang.startsWith('sk') ? sk :
    document.documentElement.lang.startsWith('cs') ? cs : en;
  const title = () => copy('Pavúk turnaja', 'Tournament draw', 'Pavouk turnaje');

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function wireMobileMenu() {
    const observer = new MutationObserver(() => {
      const panel = document.querySelector('#bqm-dialog[open] #bqm-navigation-panel');
      if (!panel || panel.querySelector('.bracket-mobile-entry')) return;
      const button = element('button', title(), 'bracket-mobile-entry');
      button.type = 'button';
      const results = [...panel.querySelectorAll('button')].find(node => node.textContent.trim().startsWith('Výsledky'));
      if (results) {
        button.className = results.className + ' bracket-mobile-entry';
        results.after(button);
      } else {
        panel.append(button);
      }
      button.addEventListener('click', () => {
        panel.closest('dialog').querySelector('.bqm-top button')?.click();
        document.querySelector('.reference-navigation [data-route="bracket"]')?.click();
      });
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['open'] });
  }

  let selectedTournament = '';
  let selectedDraw = '';
  let activeView = null;

  function bracketTabs(view, tournaments, current, panel) {
    const tabs = element('div', '', 'bracket-tournaments');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', copy('Aktuálne turnaje', 'Current tournaments', 'Aktuální turnaje'));
    const select = index => {
      selectedTournament = tournaments[index].id;
      selectedDraw = '';
      render(view, tournaments);
      view.root.querySelector('[aria-selected="true"]')?.focus();
    };
    tournaments.forEach((item, index) => {
      const tab = element('button', item.name || copy('Turnaj', 'Tournament'), 'bracket-tournament');
      tab.type = 'button';
      tab.id = 'bracket-tab-' + index;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', panel.id);
      tab.setAttribute('aria-selected', String(item === current));
      tab.tabIndex = item === current ? 0 : -1;
      if (item === current) panel.setAttribute('aria-labelledby', tab.id);
      tab.addEventListener('click', () => select(index));
      tab.addEventListener('keydown', event => {
        const targets = {
          ArrowLeft: (index - 1 + tournaments.length) % tournaments.length,
          ArrowRight: (index + 1) % tournaments.length,
          Home: 0,
          End: tournaments.length - 1,
        };
        if (!Object.hasOwn(targets, event.key)) return;
        event.preventDefault();
        select(targets[event.key]);
      });
      tabs.append(tab);
    });
    return tabs;
  }

  function connectMatches(board, cards) {
    const links = [];
    for (const { card, parentId } of cards.values()) {
      const parent = cards.get(parentId)?.card;
      if (!parent) continue;
      const line = element('span', '', 'bracket-link');
      line.setAttribute('aria-hidden', 'true');
      board.append(line);
      links.push({ card, parent, line });
    }
    if (!links.length) return;
    const layout = () => {
      const frame = board.getBoundingClientRect();
      for (const { card, parent, line } of links) {
        const from = card.getBoundingClientRect();
        const to = parent.getBoundingClientRect();
        const y1 = from.top + from.height / 2;
        const y2 = to.top + to.height / 2;
        line.style.left = (from.right - frame.left) + 'px';
        line.style.top = (Math.min(y1, y2) - frame.top) + 'px';
        line.style.width = Math.max(0, to.left - from.right) + 'px';
        line.style.height = Math.abs(y1 - y2) + 'px';
        line.classList.toggle('bracket-link-up', y2 < y1);
      }
    };
    const observer = new ResizeObserver(layout);
    observer.observe(board);
    for (const { card } of cards.values()) observer.observe(card);
    return observer;
  }

  function choice(label, items, selected, onChange) {
    const field = element('label', label, 'bracket-choice');
    const select = element('select');
    for (const item of items) {
      const option = element('option', item.name);
      option.value = item.id;
      select.append(option);
    }
    select.value = selected;
    select.addEventListener('change', () => onChange(select.value));
    field.append(select);
    return field;
  }

  function playerLine(player, won) {
    const line = element('span', '', 'bracket-player');
    const name = element('span', player?.name || copy('Zatiaľ neurčený', 'To be determined', 'Zatím neurčený'));
    if (won) {
      line.classList.add('bracket-winner');
      name.setAttribute('aria-label', copy('Víťaz: ', 'Winner: ', 'Vítěz: ') + name.textContent);
    }
    line.append(name, element('span', String(player?.score ?? ''), 'bracket-score'));
    return line;
  }

  function matchLines(node, match) {
    for (const player of match.players) {
      node.append(playerLine(player, Boolean(match.winner_id && match.winner_id === player.id)));
    }
  }

  function matchPanel(button, match, predictions, openDetail) {
    const dialog = element('dialog', '', 'bracket-match-panel');
    dialog.setAttribute('aria-label', copy('Zápas', 'Match'));
    const close = element('button', '×', 'bracket-close');
    close.type = 'button';
    close.setAttribute('aria-label', copy('Zavrieť', 'Close', 'Zavřít'));
    close.addEventListener('click', () => dialog.close());
    dialog.append(close, element('h2', copy('Zápas', 'Match')));
    matchLines(dialog, match);

    const rows = match.event_id ? predictions.filter(row =>
      String(row?.event_id || row?.id || '') === match.event_id &&
      !row.locked && !row.blurred && !row.redacted) : [];
    const markets = new Map([
      ['match_winner', copy('Víťaz', 'Winner', 'Vítěz')],
      ['aces', copy('Esá', 'Aces', 'Esa')],
      ['most_aces', copy('Viac es', 'Most aces', 'Více es')],
      ['double_faults', copy('Dvojchyby', 'Double faults')],
      ['sets', copy('Sety', 'Sets')],
      ['games', copy('Gamy', 'Games')],
    ]);
    const shown = new Set();
    const list = element('dl', '', 'bracket-predictions');
    for (const row of rows) {
      const market = String(row.market || 'match_winner').toLowerCase();
      const selection = row.selection || row.pick || row.predicted_winner_name;
      if (!markets.has(market) || shown.has(market) || typeof selection !== 'string' || !selection.trim()) continue;
      shown.add(market);
      list.append(element('dt', markets.get(market)), element('dd', selection));
      if (shown.size === 4) break;
    }
    if (shown.size) dialog.append(element('h3', copy('Predikcie', 'Predictions', 'Predikce')), list);
    if (rows.length && openDetail) {
      const detail = element('button', copy('Detail zápasu', 'Match details'), 'btn btn-ghost');
      detail.type = 'button';
      detail.addEventListener('click', () => {
        dialog.close();
        openDetail(rows[0]);
      });
      dialog.append(detail);
    }

    const comparison = element('section', '', 'bracket-comparison');
    comparison.append(element('h3', copy('Porovnanie', 'Comparison', 'Porovnání')));
    comparison.append(element('div', '', 'bracket-comparison-content'));
    dialog.append(comparison);

    button.closest('.bracket-view').append(dialog);
    const anchor = button.getBoundingClientRect();
    dialog.style.setProperty('--bracket-x', Math.round(anchor.right) + 'px');
    dialog.style.setProperty('--bracket-y', Math.round(anchor.top) + 'px');
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right ||
          event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    dialog.addEventListener('close', () => {
      dialog.remove();
      if (!document.querySelector('#matchDialog[open]')) button.focus();
    }, { once: true });
    dialog.showModal();
    const [p1, p2] = match.players;
    if (p1?.name && p2?.name) window.BlinqBracket.onCompare?.(p1, p2);
  }

  function render(view, tournaments) {
    view.lines?.disconnect();
    view.root.replaceChildren();
    const current = tournaments.find(item => item.id === selectedTournament) || tournaments[0];
    if (!current) {
      view.root.append(element('p', copy('Dnes nie je dostupný žiadny pavúk.', 'No draws are available today.', 'Dnes není dostupný žádný pavouk.'), 'bracket-status'));
      return;
    }
    selectedTournament = current.id;
    const draw = current.draws.find(item => item.id === selectedDraw) || current.draws[0];
    const panel = element('div', '', 'bracket-panel');
    panel.id = 'bracket-active-tournament';
    panel.setAttribute('role', 'tabpanel');
    panel.tabIndex = 0;
    view.root.append(bracketTabs(view, tournaments, current, panel), panel);
    if (!draw) {
      panel.append(element('p', copy(
        'Žreb zatiaľ nie je dostupný.',
        'The draw is not available yet.',
        'Los zatím není dostupný.',
      ), 'bracket-status'));
      return;
    }
    selectedDraw = draw.id;
    if (current.draws.length > 1) {
      const draws = current.draws.map((item, index) => ({
        ...item, name: item.name || copy('Žreb ', 'Draw ', 'Los ') + (index + 1),
      }));
      const controls = element('div', '', 'bracket-controls');
      controls.append(choice(copy('Žreb', 'Draw', 'Los'), draws, draw.id, id => {
        selectedDraw = id;
        render(view, tournaments);
        view.root.querySelector('select')?.focus();
      }));
      panel.append(controls);
    }
    const viewport = element('div', '', 'bracket-viewport');
    viewport.tabIndex = 0;
    viewport.setAttribute('role', 'region');
    viewport.setAttribute('aria-label', title());
    const columns = element('div', '', 'bracket-rounds');
    const matchCards = new Map();
    for (const round of draw.rounds) {
      const column = element('section', '', 'bracket-round');
      column.append(element('h2', round.name || copy('Kolo', 'Round')));
      const cards = element('div', '', 'bracket-round-matches');
      for (const match of round.matches) {
        const card = element('button', '', 'bracket-match');
        card.type = 'button';
        matchLines(card, match);
        card.addEventListener('click', () => matchPanel(card, match, view.predictions, view.openDetail));
        cards.append(card);
        if (match.id) matchCards.set(match.id, { card, parentId: match.parent_id });
      }
      column.append(cards);
      columns.append(column);
    }
    viewport.append(columns);
    panel.append(viewport);
    view.lines = connectMatches(columns, matchCards);
  }

  async function open(host, predictions, openDetail) {
    if (activeView?.root.parentNode === host && activeView.root.querySelector('dialog[open]')) {
      activeView.predictions = predictions;
      activeView.openDetail = openDetail;
      return;
    }
    activeView?.lines?.disconnect();
    const root = element('div', '', 'bracket-view');
    const status = element('p', copy('Načítavam pavúky…', 'Loading draws…', 'Načítám pavouky…'), 'bracket-status');
    status.setAttribute('role', 'status');
    root.append(status);
    host.replaceChildren(root);
    const view = { root, predictions, openDetail };
    activeView = view;
    try {
      const response = await fetch('/api/v1/brackets', { cache: 'no-store' });
      if (!response.ok) throw new Error('Bracket feed unavailable');
      const data = await response.json();
      if (activeView !== view || !root.isConnected) return;
      if (data.schema !== 1 || !Array.isArray(data.tournaments)) throw new Error('Invalid bracket feed');
      const tournaments = data.tournaments.slice().sort((a, b) =>
        Number(Boolean(b.draws.length)) - Number(Boolean(a.draws.length)) || a.name.localeCompare(b.name));
      render(view, tournaments);
    } catch {
      if (activeView === view && status.isConnected) {
        status.textContent = copy('Pavúky sú dočasne nedostupné.', 'Draws are temporarily unavailable.', 'Pavouci jsou dočasně nedostupní.');
        const retry = element('button', copy('Skúsiť znova', 'Retry', 'Zkusit znovu'), 'btn btn-ghost');
        retry.type = 'button';
        retry.addEventListener('click', () => open(host, predictions, openDetail));
        root.append(retry);
      }
    }
  }

  window.BlinqBracket = { open, onCompare: null };
  wireMobileMenu();
})();
