const {test} = require('node:test');
const assert = require('node:assert/strict');
const home = require('../web/home-feed.js');

test('home feed keeps only active, visible works and sorts by latest activity', () => {
  const works = [
    {id:'old',status:'active',createdAt:'2025-01-01'},
    {id:'hidden',status:'active',updatedAt:'2026-11-20'},
    {id:'recent',status:'active',lastExperienceAt:'2026-11-21T10:00:00'},
    {id:'done',status:'completed',updatedAt:'2026-11-22'},
    {id:'metadata',status:'active',createdAt:'2026-11-01',updatedAt:'2026-11-22'},
  ];
  assert.deepEqual(home.activeWorks(works, ['hidden']), [works[4], works[2], works[0]]);
});

test('hidden IDs are trimmed, validated, deduplicated, and do not mutate their source', () => {
  const source = [' a ', '', 'a', null, 4, 'b'];
  const before = source.slice();
  assert.deepEqual(home.normalizeHidden(source), ['a', 'b']);
  assert.deepEqual(source, before);
  assert.deepEqual(home.normalizeHidden({}), []);
});

test('hiding is idempotent and restoring removes the ID', () => {
  const source = ['a', 'b', 'a'];
  assert.deepEqual(home.setHidden(source, 'b', true), ['a', 'b']);
  assert.deepEqual(home.setHidden(source, 'c', true), ['a', 'b', 'c']);
  assert.deepEqual(home.setHidden(source, 'a', false), ['b']);
  assert.deepEqual(home.setHidden(source, '', true), ['a', 'b']);
  assert.deepEqual(source, ['a', 'b', 'a']);
});

test('hidden works can be listed for a restore interface, including completed items', () => {
  const works = [{id:'a',status:'active'}, {id:'b',status:'completed'}];
  assert.deepEqual(home.hiddenWorks(works, ['b', 'missing']), [works[1]]);
});

test('recent sorting is stable when dates are missing or invalid', () => {
  const works = [{id:'a'}, {id:'b',updatedAt:'invalid'}, {id:'c',createdAt:'2026-01-01'}];
  assert.deepEqual(home.sortRecent(works), [works[2], works[0], works[1]]);
});
