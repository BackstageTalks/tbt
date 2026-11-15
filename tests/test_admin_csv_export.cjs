'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const csv = require('../web/admin-csv-export.js');

const publication = {
  section: 'top_daily', market: 'match_winner', issued_at: '2026-11-07T09:00:00Z',
  selection_id: 'p1', selection: 'Vzor A', model_probability: 0.76, odds: 1.81,
  result: {status: 'hit', profit_units: 0.81, reason: ''},
};
const match = {
  event_id: 'm-1', scheduled_at: '2026-11-07T12:00:00Z',
  tour: 'ATP', surface: 'hard', tournament: 'Fixture', round: 'R32',
  player1: {id: 'p1', name: 'Vzor A'}, player2: {id: 'p2', name: 'Vzor B'},
  market_publications: [publication], nested: {source: 'archive'},
};
const entry = {
  row: match, publication, categories: ['top_daily', 'value'],
  pick: 'Vzor A', outcome: {kind: 'win'}, displayOdds: '1.81',
  displayOddsType: 'publikovany_kurz', displayPrediction: '76%',
  displayUnits: 0.81,
};
const results = csv.resultRows(Array.from({length: 121}, (_, i) => ({
  ...entry, row: {...match, event_id: 'm-' + i},
})));
assert.equal(results.length, 121, 'no hidden UI page-size cap');
assert.equal(results[0]['Kategória'], 'TOP | Value');
assert.equal(results[0]['Kategória_kód'], 'top_daily | value');
assert.equal(results[0]['Výsledok'], 'win');
assert.equal(results[0]['Jednotky'], 0.81);
assert.equal(results[0]['Zobrazené_jednotky'], 0.81);
assert.equal(results[0]['Zobrazený_kurz'], '1.81');
assert.equal(results[0]['Model_pravdepodobnosť_%'], 76);
assert.equal(results[0]['src_zápas.nested.source'], 'archive');
assert.equal(results[0]['src_publikácia.result.profit_units'], 0.81);
assert.equal(JSON.parse(results[0]['src_zápas.market_publications'])[0].selection_id, 'p1');

const projections = csv.resultRows([{
  row: {...match, odds: 1.22}, publication: {
    section: 'ace', market: 'aces', selection_id: 'p1',
    projection: 7.1, market_line: 6.5, ou_side: 'over',
    odds: null, price_status: 'projection_only', issued_at: publication.issued_at,
    result: {status: 'loss', profit_units: null, actual_count: 4},
  }, categories: ['ace'], outcome: {kind: 'loss'},
  displayOdds: '1.60', displayOddsType: 'historicky_ilustracny_kurz',
  displayUnits: -1,
}]);
assert.equal(projections[0]['Kurz'], '', 'never substitute unrelated match-winner odds into Aces');
assert.equal(projections[0]['Zobrazený_kurz'], '1.60');
assert.equal(projections[0]['Kurz_UI_typ'], 'historicky_ilustracny_kurz');
assert.equal(projections[0]['Projekcia'], 7.1);
assert.equal(projections[0]['Hranica'], 6.5);
assert.equal(projections[0]['Skutočná_hodnota'], 4);

const predictions = csv.predictionRows([
  {category: 'top_daily', pick: 'Vzor A', row: {...match, odds: 2.11, probability: .7}},
  {category: 'prime', pick: 'Vzor B', row: {...match, odds: 1.25, probability: .83}},
  {category: 'double_faults', pick: 'Over 3.5', row: {
    ...match, market: 'double_faults', projection: 4.8, odds: null, price_status: 'projection_only',
  }},
]);
assert.equal(predictions.length, 3);
assert.deepEqual(predictions.map(r => r['Kategória']), ['TOP', 'ACCA', 'Dvojchyby']);
assert.equal(predictions[0]['Model_pravdepodobnosť_%'], 70);
assert.equal(predictions[2]['Kurz'], '');
assert.equal(predictions[2]['Projekcia'], 4.8);
assert.equal(predictions[2]['Stav_kurzu'], 'projection_only');

// Full-period predictions join immutable historical publications with the
// current (not yet settled) offer. Preserve each genuinely separate category.
const older = [
  {row: {...match, event_id: 'historic-1'}, publication, category: 'top_daily', pick: 'Vzor A'},
  {row: {...match, event_id: 'historic-1'}, publication: {...publication, section:'value'}, category: 'value', pick: 'Vzor A'},
  {row: {...match, event_id: 'historic-2'}, publication: {
    ...publication, section:'ace_winner', market:'most_aces', selection_id:'p2',
    selection:'Vzor B', result:{status:'hit', correct:true},
  }, category:'ace_winner', pick:'Vzor B · Viac es'},
  {row: {...match, event_id: 'historic-3'}, publication: {
    ...publication, section:'ace', market:'aces', selection_id:'p1',
    price_contract:'player_total_ou', market_line:4.5, ou_side:'over',
  }, category:'ace', pick:'Vzor A · Over 4.5 Aces'},
  {row: {...match, event_id: 'historic-3'}, publication: {
    ...publication, section:'ace', market:'aces', selection_id:'p1',
    price_contract:'player_total_ou', market_line:5.5, ou_side:'under',
  }, category:'ace', pick:'Vzor A · Under 5.5 Aces'},
];
const current = [
  {row: {...match, event_id:'historic-1', winner_id:'p1'}, category:'top_daily', pick:'Vzor A'},
  {row: {...match, event_id:'current-1', winner_id:'p2'}, category:'prime', pick:'Vzor B'},
];
const combined = csv.mergePredictionInputs(older, current);
assert.equal(combined.length, 6, 'same published bet deduped; distinct category and O/U lines preserved');
assert.equal(csv.mergePredictionInputs(older, current).length, 6, 'stable idempotent export');
const historicalRows = csv.predictionRows(combined);
assert.equal(historicalRows.filter(row=>row['Zdroj_záznamu']==='archív publikácií').length, 5);
assert.equal(historicalRows.filter(row=>row['Zdroj_záznamu']==='aktuálna ponuka').length, 1);
assert.equal(historicalRows[2]['Kategória'], 'Viac es');
assert.equal(historicalRows[0]['Publikované'], publication.issued_at);
assert.equal(historicalRows[0]['Model_pravdepodobnosť_%'], 76);
assert.equal(historicalRows[0]['src_publikácia.section'], 'top_daily');
assert.equal(historicalRows[0]['src_publikácia.result.status'], undefined,
  'post-match results must stay in the separate Results export');
assert.equal(historicalRows[0]['src_predikcia.market_publications'], undefined);
assert.equal(historicalRows[5]['Publikované'], '', 'current unissued date is never fabricated');

const malicious = csv.predictionRows([{category: 'value', row: {
  ...match, player1: {name: '=HYPERLINK("http://attack")'},
  tournament: 'Tournament; "quoted"\nsecond line',
}}]);
const text = csv.serialize(malicious, 'predictions');
assert.ok(text.startsWith('\uFEFF"Kategória";'), 'Slovak Excel UTF-8 and semicolon convention');
assert.match(text, /"'=HYPERLINK\(""http:\/\/attack""\)"/, 'spreadsheet formula injection blocked');
assert.match(text, /"Tournament; ""quoted""\nsecond line"/, 'CSV escapes delimiter, quotes, newline');
assert.equal(text.split('\r\n').length - 1, 2, 'one data row without false splitting');
const complete = csv.serialize(results, 'results');
assert.equal(complete.split('\r\n').length - 1, 122, '121 results and header');
assert.ok(complete.includes('"src_publikácia.result.profit_units"'));
assert.throws(() => csv.download('results', []), /Nie sú dostupné/);
assert.throws(() => csv.serialize([], 'unknown'), /Unknown CSV export/);

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
assert.ok(html.indexOf('/admin-csv-export.js') < html.indexOf('/app.js?'), 'export module loaded before app');
for (const needle of [
  'function adminCsvResultsEntries()', 'function adminCsvPredictionInputs()',
  'function renderAdminDataExport()', 'function adminDownloadCsv(kind)',
  'settledPublishedEntries(state.feed?.results||[],',
  'window.BlinqAdminCsv.mergePredictionInputs(historical,current)',
  'state.feed?.results_boot_partial',
  'state.feed?.results_archive_unavailable', 'state.feed?.results_exclusions_unavailable',
  'dataexport:renderAdminDataExport', 'data-admin-export-csv="results"',
  'data-admin-export-csv="predictions"', 'csvButton.dataset.adminExportCsv',
]) assert.ok(app.includes(needle), 'missing integration: ' + needle);
console.log('Admin Results + predictions CSV contract: PASS');
