'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const start = source.indexOf('  function renderTop20MatchCoverage(){');
const end = source.indexOf('  function contentLocale(){', start);
assert.ok(start > 0 && end > start, 'UI helper must exist');
const helper = source.slice(start, end);

const base = {
  event_id: 'shelton-fils',
  player1: {id: 'p1', name: 'Ben Shelton', rank: 12, probability: .5742},
  player2: {id: 'p2', name: 'Arthur Fils', rank: 19, probability: .4258},
  winner_id: 'p1', data_depth: 1, blinq_probability: .5742,
};
function render(feed, offered = {}) {
  const context = {
    state: {feed},
    marketRows: (key) => offered[key] || [],
    normalize: (row) => ({
      p1: row.player1?.name || '?', p2: row.player2?.name || '?',
      pick: row.winner_id === row.player1?.id ? row.player1?.name : row.player2?.name,
      pickId: row.winner_id || '',
      probability: Math.max(row.player1?.probability || 0, row.player2?.probability || 0),
    }),
    lcopy: (_en, sk) => sk,
    escapeHtml: (value) => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  };
  return vm.runInNewContext(helper + '\nrenderTop20MatchCoverage();', context);
}
const fullFeed = {board_meta: {official_prediction: false}, board_upcoming: [], upcoming: [base]};
const visible = render(fullFeed);
assert.ok(visible.includes('Ben Shelton'));
assert.ok(visible.includes('Arthur Fils'));
assert.ok(visible.includes('57.4%'));
assert.ok(visible.includes('Pod hranicou TOP 65 %'));
assert.ok(!visible.includes('Publikovaný TOP tip'));
// No chance of reading hidden full upcoming from a locked lower account.
assert.equal(render({...fullFeed, board_meta: {locked: true}}), '');
assert.equal(render({...fullFeed, upcoming: [{...base, player2: {...base.player2, rank: 51}}]}), '');
assert.ok(render(fullFeed, {top_daily: [{event_id: 'shelton-fils'}]}).includes('Publikovaný TOP tip'));
const malicious = {...base, player1: {...base.player1, name: '<script>bad</script>'}};
assert.ok(!render({...fullFeed, upcoming: [malicious]}).includes('<script>'));
console.log('7.2.1 authorized important-duel display and access isolation: PASS');
