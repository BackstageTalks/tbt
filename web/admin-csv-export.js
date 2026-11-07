/* Read-only CSV exports for the BlinQ admin. No new provider calls or writes. */
(function (root, build) {
  'use strict';
  const api = build();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.BlinqAdminCsv = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  const CATEGORY_NAMES = Object.freeze({
    top_daily: 'TOP', prime: 'ACCA', value: 'Value', doubles: 'Štvorhra',
    ace: 'Esá', double_faults: 'Dvojchyby', sets: 'Sety', games: 'Gamy',
  });
  const MAIN_COLUMNS = [
    'Kategória', 'Kategória_kód', 'Dátum_zápasu', 'Event_ID',
    'Okruh', 'Turnaj', 'Povrch', 'Kolo', 'Hráč_1', 'Hráč_2',
    'Trh', 'Predikcia', 'Výber_ID', 'Model_pravdepodobnosť_%',
    'Projekcia', 'Hranica', 'Smer', 'Kurz', 'Stav_kurzu',
  ];
  const RESULT_COLUMNS = [
    ...MAIN_COLUMNS, 'Zobrazený_kurz', 'Kurz_UI_typ', 'Zobrazená_predikcia', 'Zobrazené_jednotky', 'Výsledok', 'Dôvod_výsledku', 'Skutočná_hodnota',
    'Jednotky', 'Publikované', 'Model_verzia',
  ];
  const PREDICTION_COLUMNS = [
    ...MAIN_COLUMNS, 'Publikované', 'Model_verzia',
  ];

  const str = value => value == null ? '' : String(value);
  const first = (...values) => values.find(value => value !== undefined && value !== null && value !== '') ?? '';
  const names = value => (Array.isArray(value) ? [...new Set(value.filter(Boolean))] : [])
    .map(category => CATEGORY_NAMES[category] || category).join(' | ');
  function percent(value) {
    if (value === '' || value == null) return '';
    const n = Number(value);
    return Number.isFinite(n) ? (n >= 0 && n <= 1 ? n * 100 : n) : '';
  }
  function flatten(value, prefix, target, depth = 0) {
    if (value === null || value === undefined) return;
    if (Array.isArray(value)) {
      target[prefix] = JSON.stringify(value);
    } else if (typeof value === 'object' && depth < 6) {
      for (const [key, child] of Object.entries(value)) {
        flatten(child, prefix + '.' + key, target, depth + 1);
      }
    } else if (typeof value === 'object') {
      target[prefix] = JSON.stringify(value);
    } else {
      target[prefix] = value;
    }
  }
  function baseRow(match, categoryCodes, publication, pick) {
    const p = publication || {}, settled = publication != null, player1 = match?.player1 || {}, player2 = match?.player2 || {};
    const rawProbability = settled ? p.model_probability : first(match?.blinq_probability, match?.probability, match?.win_probability);
    return {
      'Kategória': names(categoryCodes),
      'Kategória_kód': categoryCodes.join(' | '),
      'Dátum_zápasu': first(match?.scheduled_at, match?.date, match?.start_time),
      'Event_ID': first(match?.event_id, match?.id, match?.match_id),
      'Okruh': first(match?.tour, match?.circuit),
      'Turnaj': first(match?.tournament, match?.competition),
      'Povrch': str(match?.surface),
      'Kolo': str(match?.round),
      'Hráč_1': first(player1.name, match?.player1_name, match?.p1),
      'Hráč_2': first(player2.name, match?.player2_name, match?.p2),
      'Trh': settled ? str(p.market) : first(match?.market, match?.betting?.market),
      'Predikcia': first(pick, p.selection, p.pick, match?.pick, match?.selection),
      'Výber_ID': settled ? first(p.selection_id, p.pick_id) : first(match?.selection_id, match?.winner_id),
      'Model_pravdepodobnosť_%': percent(rawProbability),
      'Projekcia': settled ? first(p.projection) : first(match?.projection),
      'Hranica': settled ? first(p.market_line) : first(match?.market_line, match?.line),
      'Smer': settled ? str(p.ou_side) : str(match?.ou_side),
      // Actual recorded prices only. Never turn an indicative/illustrative estimate into bookmaker odds.
      'Kurz': settled ? first(p.odds) : first(match?.odds, match?.betting?.odds),
      'Stav_kurzu': settled ? str(p.price_status) : str(match?.price_status),
    };
  }

  function resultRows(entries) {
    if (!Array.isArray(entries)) return [];
    return entries.map(entry => {
      const match = entry.row || {}, pub = entry.publication || {}, result = pub.result || {};
      const categoryCodes = Array.isArray(entry.categories) ? entry.categories :
        [first(pub.section, pub.market)].filter(Boolean);
      const out = baseRow(match, categoryCodes, pub, first(entry.pick, pub.selection, pub.pick));
      out['Zobrazený_kurz'] = first(entry.displayOdds);
      out['Kurz_UI_typ'] = first(entry.displayOddsType);
      out['Zobrazená_predikcia'] = first(entry.displayPrediction);
      out['Zobrazené_jednotky'] = first(entry.displayUnits);
      out['Výsledok'] = first(entry.outcome?.kind, result.status, result.outcome, result.settlement);
      out['Dôvod_výsledku'] = first(result.reason, result.void_reason, result.settlement_reason);
      out['Skutočná_hodnota'] = first(result.actual_count, result.actual, result.value);
      out['Jednotky'] = first(result.profit_units);
      out['Publikované'] = str(pub.issued_at);
      out['Model_verzia'] = first(pub.model_version, match.model_version);
      flatten(match, 'src_zápas', out);
      flatten(pub, 'src_publikácia', out);
      return out;
    });
  }
  function predictionRows(items) {
    if (!Array.isArray(items)) return [];
    return items.map(item => {
      const match = item.row || {};
      const category = str(item.category);
      const out = baseRow(match, category ? [category] : [], null, item.pick);
      out['Publikované'] = first(match.issued_at, match.published_at);
      out['Model_verzia'] = str(match.model_version);
      flatten(match, 'src_predikcia', out);
      return out;
    });
  }

  function csvCell(value) {
    if (value === null || value === undefined || (typeof value === 'number' && !Number.isFinite(value))) value = '';
    let s = typeof value === 'object' ? JSON.stringify(value) : String(value);
    // Prevent spreadsheet formulas executing when values originate from external match data.
    if (typeof value === 'string' && /^[\s]*[=+\-@]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function serialize(rows, kind) {
    if (!Array.isArray(rows)) throw new TypeError('CSV rows must be an array');
    if (kind !== 'results' && kind !== 'predictions') throw new TypeError('Unknown CSV export');
    const fixed = kind === 'results' ? RESULT_COLUMNS : PREDICTION_COLUMNS;
    const extra = [...new Set(rows.flatMap(row => Object.keys(row || {})))]
      .filter(column => !fixed.includes(column)).sort((a, b) => a.localeCompare(b, 'sk'));
    const columns = [...fixed, ...extra];
    // UTF-8 BOM and semicolon delimiter open correctly in Slovak Excel.
    return '\uFEFF' + [columns, ...rows.map(row => columns.map(column => row?.[column] ?? ''))]
      .map(values => values.map(csvCell).join(';')).join('\r\n') + '\r\n';
  }
  function download(kind, rows) {
    if (!Array.isArray(rows) || !rows.length) throw new Error('Nie sú dostupné riadky na export.');
    const filename = 'blinq_' + (kind === 'results' ? 'vysledky' : 'predikcie') +
      '_' + new Date().toISOString().slice(0, 10) + '.csv';
    const blob = new Blob([serialize(rows, kind)], {type: 'text/csv;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    try { link.click(); } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }
    return {filename, count: rows.length};
  }
  return {resultRows, predictionRows, serialize, download};
});
