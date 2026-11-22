const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');

function app(fetch) {
  const elements = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      hidden: true, innerHTML: '', className: '', style: {setProperty() {}},
      classList: { contains: () => false, toggle() {}, add() {}, remove() {} },
      setAttribute() {}, addEventListener() {}, querySelectorAll: () => [],
    });
    return elements.get(selector);
  };
  const context = vm.createContext({
    fetch, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    getComputedStyle: () => ({gridTemplateColumns:"150px 150px"}),
    localStorage: { getItem: () => null },
    requestAnimationFrame: callback => callback(),
    window: { addEventListener() {} },
    document: { querySelector: element, querySelectorAll: () => [], addEventListener() {} },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'web/presentation-core.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'web/exhibit-cards.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'web/immersive-audio.js'), 'utf8'), context);
  const source = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
  vm.runInContext(source.replace(/applyAppearance\(false\);\s*boot\(\);\s*$/, ''), context);
  vm.runInContext('renderTabs=()=>{};renderStatusChips=()=>{};renderStats=()=>{};', context);
  return { run: code => vm.runInContext(code, context), elements };
}
const response = data => ({ ok: true, json: async () => data });
const snapshot = score => ({ works: [{ id: 'w', title: '作品', rating: score }],
  series: [{ id: 's', name: '系列', memberCount: 1, avgRating: score }], settings: {}, undoAvailable: true });

test('successful writes refresh works and authoritative series, previews do not', async () => {
  const calls = [];
  const a = app(async (url) => {
    calls.push(url);
    return response(url === '/api/bootstrap' ? snapshot(9) : { ok: true, work: { id: 'w', rating: 9 } });
  });
  a.run('renderWall=()=>{}');
  await a.run('api("/api/works/w/rating", {method:"POST",body:{score:9}})');
  assert.equal(a.run('S.series[0].avgRating'), 9);
  assert.equal(a.run('S.works[0].rating'), 9);
  await a.run('api("/api/tmdb/preview", {method:"POST",body:{}})');
  assert.deepEqual(calls, ['/api/works/w/rating', '/api/bootstrap', '/api/tmdb/preview']);
});

test('write requests and snapshots are serialized; later state wins', async () => {
  const calls = [];
  let score = 0;
  const a = app(async (url, opts) => {
    calls.push(url);
    if (url !== '/api/bootstrap') score = JSON.parse(opts.body).score;
    await new Promise(resolve => setTimeout(resolve, 5));
    return response(url === '/api/bootstrap' ? snapshot(score) : { ok: true });
  });
  a.run('renderWall=()=>{}');
  await a.run('Promise.all([api("/api/works/w/rating",{method:"POST",body:{score:4}}),api("/api/works/w/rating",{method:"POST",body:{score:8}})])');
  assert.deepEqual(calls, ['/api/works/w/rating', '/api/bootstrap', '/api/works/w/rating', '/api/bootstrap']);
  assert.equal(a.run('S.series[0].avgRating'), 8);
});

test('saved mutation stays successful when refresh fails; retry updates both collections', async () => {
  let unavailable = true;
  let writes = 0;
  const a = app(async url => {
    if (url === '/api/bootstrap') {
      if (unavailable) throw Error('offline');
      return response(snapshot(7));
    }
    writes++;
    return response({ ok: true, work: { id: 'w', rating: 7 } });
  });
  a.run('renderWall=()=>{}');
  const result = await a.run('api("/api/works/w",{method:"PATCH",body:{title:"作品"}})');
  assert.equal(result.ok, true);
  assert.equal(a.run('S.syncPending'), true);
  assert.equal(a.elements.get('#syncNotice').hidden, false);
  unavailable = false;
  assert.equal(await a.run('reloadAll()'), true);
  assert.equal(writes, 1);
  assert.equal(a.run('S.syncPending'), false);
  assert.equal(a.run('S.series[0].avgRating'), 7);
});

test('failed mutation does not refresh and does not poison the queue', async () => {
  let count = 0;
  const a = app(async url => {
    if (url === '/api/bootstrap') return response(snapshot(6));
    count++;
    return response(count === 1 ? { ok: false, error: 'rejected' } : { ok: true });
  });
  a.run('renderWall=()=>{}');
  assert.equal((await a.run('api("/api/works",{method:"POST",body:{}})')).ok, false);
  assert.equal((await a.run('api("/api/works",{method:"POST",body:{}})')).ok, true);
  assert.equal(a.run('S.works[0].rating'), 6);
});

test('malformed snapshot preserves the previous complete state', async () => {
  const a = app(async () => response({ works: [], ok: true }));
  a.run('S.works=[{id:"old"}];S.series=[{id:"old-series"}];S.syncPending=true');
  assert.equal(await a.run('reloadAll()'), false);
  assert.equal(a.run('S.works[0].id'), 'old');
  assert.equal(a.run('S.series[0].id'), 'old-series');
});

test('an empty library can show empty series, but active filters do not leak them', () => {
  const a = app(async () => response({}));
  a.run('S.series=[{id:"empty",name:"空系列",memberCount:0,members:[],catMix:[],baseStatus:"not_started",baseStatusLabel:"未开始"}];renderWall()');
  assert.match(a.elements.get('#wall').innerHTML, /data-sid="empty"/);
  a.run('S.filters.time="y";renderWall()');
  assert.doesNotMatch(a.elements.get('#wall').innerHTML, /data-sid="empty"/);
  a.run('S.filters.time="all";S.filters.group="flat";renderWall()');
  assert.doesNotMatch(a.elements.get('#wall').innerHTML, /data-sid="empty"/);
});

test('non-home work entry opens immersive browsing while home keeps the drawer', () => {
  const a = app(async () => response({}));
  a.run('S.works=[{id:"w",title:"作品",category:"book"}];let opened=[];openDrawer=id=>opened.push("drawer:"+id);ensureImmersive=()=>{immersiveView={isOpen:()=>false,open:(ids,id,surface,source)=>opened.push(`immersive:${id}:${surface}:${source}`)}}');
  a.run('S.view="home";openCurrentWork("w")');
  a.run('S.view="archive";openCurrentWork("w")');
  assert.deepEqual(Array.from(a.run('opened')), ['drawer:w','immersive:w:fullscreen:全部作品']);
});

test('all persisted entity mutation routes share the update entry', () => {
  const a = app(async () => response({}));
  for (const route of ['/api/works/w/refill','/api/series/s/members','/api/tmdb/import',
    '/api/import','/api/import-records','/api/undo','/api/backups/restore','/api/clear-data','/api/recover/new-start']) {
    assert.equal(a.run(`ArchiveV2.core.isMutation(${JSON.stringify(route)},"POST")`), true);
  }
  for (const route of ['/api/search','/api/resolve','/api/tmdb/preview','/api/youshu/preview','/api/backups/preview']) {
    assert.equal(a.run(`ArchiveV2.core.isMutation(${JSON.stringify(route)},"POST")`), false);
  }
});
