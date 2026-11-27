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
      const boxes = new Map([...cards.values()].map(({ card }) => [card, card.getBoundingClientRect()]));
      for (const { card, parent, line } of links) {
        const from = boxes.get(card);
        const to = boxes.get(parent);
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
  }

  function playerLookup(player, tour, comparison) {
    const field = element('div', '', 'bracket-player-lookup');
    const label = element('label', player.name);
    const input = element('input');
    input.type = 'search';
    input.value = player.name;
    label.append(input);
    const search = element('button', copy('Vyhľadať', 'Search', 'Vyhledat'), 'bracket-analysis-action');
    search.type = 'button';
    const select = element('select');
    select.setAttribute('aria-label', copy('Potvrdiť hráča', 'Confirm player', 'Potvrdit hráče') + ' · ' + player.name);
    const hint = element('small');
    hint.setAttribute('role', 'status');
    field.append(label, search, select, hint);
    const reset = () => {
      const placeholder = element('option', copy('Vyberte hráča…', 'Select player…', 'Vyberte hráče…'));
      placeholder.value = '';
      select.replaceChildren(placeholder);
    };
    reset();
    input.addEventListener('input', reset);
    search.addEventListener('click', async () => {
      const query = input.value.trim();
      if (query.length < 2) return;
      reset();
      search.disabled = true;
      hint.textContent = copy('Vyhľadávam…', 'Searching…', 'Vyhledávám…');
      try {
        const result = await comparison.search(query, tour);
        if (!field.isConnected || input.value.trim() !== query) return;
        for (const candidate of (result?.players || [])) {
          if (!candidate.player_id || !candidate.name || candidate.ambiguous_identity) continue;
          const choice = element('option', candidate.name);
          choice.value = candidate.player_id;
          select.append(choice);
        }
        hint.textContent = select.options.length > 1 ? '' : copy(
          'Bez jednoznačnej zhody. Skúste doplniť celé meno.',
          'No unambiguous match. Try entering the full name.',
          'Bez jednoznačné shody. Zkuste doplnit celé jméno.',
        );
      } catch {
        if (field.isConnected) hint.textContent = copy('Vyhľadávanie zlyhalo.', 'Search failed.', 'Vyhledávání selhalo.');
      } finally {
        search.disabled = false;
      }
    });
    return { field, select };
  }

  function analysisPanel(button, match, comparison) {
    const dialog = element('dialog', '', 'bracket-match-panel bracket-analysis-panel');
    const heading = copy('Analýza zápasu', 'Match analysis', 'Analýza zápasu');
    dialog.setAttribute('aria-label', heading);
    const close = element('button', '×', 'bracket-close');
    close.type = 'button';
    close.setAttribute('aria-label', copy('Zavrieť', 'Close', 'Zavřít'));
    close.addEventListener('click', () => dialog.close());
    dialog.append(close, element('h2', heading));
    matchLines(dialog, match);
    const [p1, p2] = match.players;
    const status = element('p', '', 'bracket-status');
    status.setAttribute('role', 'status');
    const output = element('div');
    if (!comparison.allowed()) {
      status.textContent = comparison.accessMessage();
      dialog.append(status);
    } else {
      const context = comparison.context(match);
      const form = element('form', '', 'bracket-analysis-form');
      const fields = element('div', '', 'bracket-analysis-fields');
      const identities = element('div', '', 'bracket-analysis-fields bracket-identity-fields');
      let selected = null;
      const option = (id, name = id) => ({ id, name });
      const unknown = option('', copy('Vyberte…', 'Select…', 'Vyberte…'));
      const tour = choice(copy('Okruh', 'Tour'), [unknown, option('atp', 'ATP'), option('wta', 'WTA')], context.tour, updateFormat);
      const surface = choice(copy('Povrch', 'Surface'), [
        unknown, option('hard', copy('Tvrdý', 'Hard')), option('clay', copy('Antuka', 'Clay')),
        option('grass', copy('Tráva', 'Grass')), option('indoor_hard', copy('Tvrdý v hale', 'Indoor hard')),
      ], context.surface, () => {});
      const format = choice(copy('Max. počet setov', 'Maximum sets', 'Max. počet setů'),
        [unknown, option('3'), option('5')], String(context.bestOf || ''), () => {});
      const tourSelect = tour.querySelector('select');
      const surfaceSelect = surface.querySelector('select');
      const formatSelect = format.querySelector('select');
      for (const select of [tourSelect, surfaceSelect, formatSelect]) select.required = true;
      function updateFormat() {
        identities.replaceChildren();
        selected = null;
        formatSelect.options[2].disabled = tourSelect.value !== 'atp';
        if (tourSelect.value === 'wta') formatSelect.value = '3';
      }
      updateFormat();
      fields.append(tour, surface, format);
      const submit = element('button', copy('Porovnať', 'Compare', 'Porovnat'), 'bracket-analysis-action');
      submit.type = 'submit';
      form.append(fields, identities, submit);
      if (match.winner_id || match.players.some(player => player.score)) {
        dialog.append(element('p', copy(
          'Porovnanie používa aktuálny snapshot Porovnávača.',
          'This comparison uses the current comparator snapshot.',
          'Porovnání používá aktuální snapshot Porovnávače.',
        ), 'bracket-status'));
      }
      dialog.append(form, status, output);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        if (selected && selected.some(lookup => !lookup.select.value)) {
          status.textContent = copy('Potvrďte oboch hráčov.', 'Confirm both players.', 'Potvrďte oba hráče.');
          return;
        }
        submit.disabled = true;
        identities.inert = true;
        fields.inert = true;
        output.replaceChildren();
        status.textContent = copy('Načítavam porovnanie…', 'Loading comparison…', 'Načítám porovnání…');
        try {
          const [left, right] = [p1, p2].map((player, index) => ({
            name: player.name, player_id: selected?.[index].select.value,
          }));
          const result = await comparison.load(left, right, tourSelect.value, surfaceSelect.value, Number(formatSelect.value), match.event_id);
          if (!dialog.open) return;
          comparison.render(output, result);
          status.textContent = '';
        } catch (error) {
          if (!dialog.open) return;
          if ([404, 409].includes(error?.status) && comparison.search && !selected) {
            selected = [p1, p2].map(player => playerLookup(player, tourSelect.value, comparison));
            identities.append(...selected.map(lookup => lookup.field));
          }
          status.textContent = [400, 404, 409].includes(error?.status)
            ? copy('Pre túto dvojicu a okruh sa nepodarilo nájsť jednoznačné údaje.',
              'No unambiguous data were found for this pair and tour.',
              'Pro tuto dvojici a okruh se nepodařilo najít jednoznačné údaje.')
            : error?.status === 403 ? comparison.accessMessage()
              : copy('Porovnanie sa nepodarilo načítať. Skúste znova.',
                'The comparison could not be loaded. Try again.',
                'Porovnání se nepodařilo načíst. Zkuste znovu.');
        } finally {
          submit.disabled = false;
          fields.inert = false;
          identities.inert = false;
        }
      });
    }
    button.closest('.bracket-view').append(dialog);
    dialog.addEventListener('close', () => {
      dialog.remove();
      button.focus();
    }, { once: true });
    dialog.showModal();
    const form = dialog.querySelector('form');
    if (form?.checkValidity()) form.requestSubmit();
  }

  function tournamentStatsButton(panel, sections) {
    if (!Array.isArray(sections) || !sections.length) return;
    const accuracy = sections.find(section => section.id === 'accuracy')?.items?.[0]?.value;
    const button = element('button', '🎯 ' + (accuracy ?? '—'), 'bracket-stats-trigger');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'dialog');
    button.setAttribute('aria-label', copy('Štatistiky turnaja', 'Tournament statistics', 'Statistiky turnaje'));
    button.addEventListener('click', () => {
      const dialog = element('dialog', '', 'bracket-stats-dialog');
      dialog.setAttribute('aria-label', button.getAttribute('aria-label'));
      const close = element('button', '×', 'bracket-close');
      close.type = 'button';
      close.setAttribute('aria-label', copy('Zavrieť', 'Close', 'Zavřít'));
      close.addEventListener('click', () => dialog.close());
      dialog.append(close);
      for (const section of sections) {
        const part = element('section');
        part.append(element('h3', String(section.title ?? '')));
        const list = element('dl');
        for (const item of section.items || []) {
          const value = element('dd', String(item.value ?? '—'));
          if (item.hint) value.append(element('small', String(item.hint)));
          list.append(element('dt', String(item.label ?? '')), value);
        }
        part.append(list);
        dialog.append(part);
      }
      dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right ||
            event.clientY < box.top || event.clientY > box.bottom) dialog.close();
      });
      dialog.addEventListener('close', () => { dialog.remove(); button.focus(); }, { once: true });
      panel.append(dialog);
      dialog.showModal();
    });
    panel.append(button);
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
    tournamentStatsButton(panel, current.tournament_stats);
    if (!draw) {
      panel.append(element('p', copy(
        'Žreb zatiaľ nie je dostupný.',
        'The draw is not available yet.',
        'Los zatím není dostupný.',
      ), 'bracket-status'));
      return;
    }
    selectedDraw = draw.id;
    if (draw.partial) {
      panel.append(element('p', copy(
        'Dostupné zápasy podľa kôl. Ďalšie kolá sa zobrazia po zverejnení.',
        'Available matches by round. Later rounds appear when published.',
        'Dostupné zápasy podle kol. Další kola se zobrazí po zveřejnění.',
      ), 'bracket-status bracket-partial'));
    }

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
      column.append(element('h2', (round.name === 'Final' ? copy('Finále', 'Final') : round.name) || copy('Kolo', 'Round')));
      const cards = element('div', '', 'bracket-round-matches');
      for (const match of round.matches) {
        const card = element(match.pending_slot ? 'div' : 'button', '', 'bracket-match');
        if (match.pending_slot) {
          card.classList.add('bracket-match-pending');
        } else {
          card.type = 'button';
          card.addEventListener('click', () => matchPanel(card, match, view.predictions, view.openDetail));
        }
        matchLines(card, match);
        const slot = element('div', '', 'bracket-match-slot');
        slot.append(card);
        if (!match.pending_slot && view.comparison && match.players.length === 2 &&
            match.players.every(player => player?.id && player.name) &&
            match.players[0].id !== match.players[1].id) {
          const analysis = element('button', copy('Analýza', 'Analysis', 'Analýza'), 'bracket-analysis-action');
          analysis.type = 'button';
          analysis.setAttribute('aria-label', analysis.textContent + ' · ' + match.players.map(player => player.name).join(' – '));
          analysis.addEventListener('click', () => analysisPanel(analysis, match, view.comparison));
          slot.append(analysis);
        }
        cards.append(slot);
        if (match.id) matchCards.set(match.id, { card, parentId: match.parent_id });
      }
      column.append(cards);
      columns.append(column);
    }
    viewport.append(columns);
    panel.append(viewport);
    view.lines = connectMatches(columns, matchCards);
  }

  async function open(host, predictions, openDetail, comparison) {
    if (activeView?.root.parentNode === host && activeView.root.querySelector('dialog[open]')) {
      activeView.predictions = predictions;
      activeView.openDetail = openDetail;
      activeView.comparison = comparison;
      return;
    }
    activeView?.lines?.disconnect();
    const root = element('div', '', 'bracket-view');
    const status = element('p', copy('Načítavam pavúky…', 'Loading draws…', 'Načítám pavouky…'), 'bracket-status');
    status.setAttribute('role', 'status');
    root.append(status);
    host.replaceChildren(root);
    const view = { root, predictions, openDetail, comparison };
    activeView = view;
    try {
      const data = await window.BlinqAuth.tournamentBrackets();
      if (activeView !== view || !root.isConnected) return;
      if (data.schema !== 1 || !Array.isArray(data.tournaments)) throw new Error('Invalid bracket feed');
      // Server decides per level (Admin → Zobrazenie → Analýza v pavúku).
      if (data.analysis_allowed === false) view.comparison = null;
      const tournaments = data.tournaments.slice().sort((a, b) =>
        Number(Boolean(b.draws.length)) - Number(Boolean(a.draws.length)) || a.name.localeCompare(b.name));
      render(view, tournaments);
    } catch {
      if (activeView === view && status.isConnected) {
        status.textContent = copy('Pavúky sú dočasne nedostupné.', 'Draws are temporarily unavailable.', 'Pavouci jsou dočasně nedostupní.');
        const retry = element('button', copy('Skúsiť znova', 'Retry', 'Zkusit znovu'), 'btn btn-ghost');
        retry.type = 'button';
        retry.addEventListener('click', () => open(host, predictions, openDetail, comparison));
        root.append(retry);
      }
    }
  }

  window.BlinqBracket = { open };
})();
