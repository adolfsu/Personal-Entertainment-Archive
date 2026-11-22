const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(files) {
  const ctx = vm.createContext({URL, setTimeout, clearTimeout});
  for (const file of files) vm.runInContext(fs.readFileSync(path.join(__dirname, '../web', file), 'utf8'), ctx);
  return ctx.ArchiveV2;
}

test('browse sessions keep order, navigate, and reconcile deleted works', () => {
  const {browse} = load(['browse-session.js']);
  const session = browse.create(['a', 'b', 'c'], 'b', 'fullscreen');
  assert.equal(session.surface, 'fullscreen');
  assert.equal(browse.adjacent(session, -1), 'a');
  assert.equal(browse.adjacent(session, 1), 'c');
  assert.equal(browse.reconcile(session, ['a', 'c']), true);
  assert.deepEqual(Array.from(session.ids), ['a', 'c']);
  assert.equal(session.currentId, 'c');
  assert.equal(browse.reconcile(session, []), false);
});

test('background loader prefers dedicated image, then local cover, then default', async () => {
  const {backgrounds} = load(['immersive-background.js']);
  const events = [];
  const images = [];
  const loader = backgrounds.createLoader({timeout: 50, imageFactory: () => {
    const image = {naturalWidth: 100, naturalHeight: 100, set src(value) { this.url = value; images.push(this); }, removeAttribute() {}};
    setTimeout(() => image.onload(), 0);
    return image;
  }});
  loader.load({immersiveBackgroundUrl: 'https://example.com/bg.jpg', coverUrl: '/covers/local.jpg'}, (image, kind) => events.push([image && image.url, kind]));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(events, [[null, 'default'], ['https://example.com/bg.jpg', 'dedicated']]);
  assert.equal(images.length, 1);
});

test('immersive content escapes user fields and limits recent records', () => {
  const {immersive} = load(['immersive.js']);
  const html = immersive.workContent({title:'<作品>', summary:'<简介>', rating:8.5, status:'active', userFields:[{key:'进度',value:'2/10'}], experiences:[{id:'1',date:'2026',status:'active',content:'<记录>'}]}, {category:'书',status:'进行中',recordStatus:()=> '进行中'});
  assert.match(html, /&lt;作品&gt;/);
  assert.match(html, /&lt;简介&gt;/);
  assert.match(html, /&lt;记录&gt;/);
  assert.doesNotMatch(html, /<script/i);
});

function backgroundHarness() {
  const {backgrounds} = load(['immersive-background.js']);
  const images = [], displayed = [], timers = new Map();
  let timerId = 0;
  const loader = backgrounds.createLoader({
    imageFactory: () => { const img = {naturalWidth: 100, naturalHeight: 60, removeAttribute() { this.cancelled = true; }}; images.push(img); return img; },
    schedule: (callback, ms) => { timers.set(++timerId, {callback, ms}); return timerId; },
    unschedule: id => timers.delete(id),
  });
  return {loader, images, displayed, timers,
    display: (img, kind) => displayed.push([img?.src || null, kind]),
    tick: ms => { const [id, timer] = [...timers].find(([,item]) => item.ms === ms) || []; assert.ok(timer, `missing ${ms}ms timer`); timers.delete(id); timer.callback(); },
  };
}

test('multiple backgrounds follow saved order, wrap, honor interval, and stop on cancel', () => {
  const h = backgroundHarness(), urls = ['https://example.com/a', 'https://example.com/b', 'https://example.com/c'];
  h.loader.load({immersiveBackgroundUrls: urls}, h.display, {immersive_background_interval: 7});
  assert.equal(h.images[0].src, urls[0]); h.images.at(-1).onload();
  for (const expected of [urls[1], urls[2], urls[0]]) {
    h.tick(7000); assert.equal(h.images.at(-1).src, expected); h.images.at(-1).onload();
  }
  assert.equal(h.displayed.length, 5);
  h.loader.cancel(); assert.equal(h.timers.size, 0);
});
test('background switching respects the new three-second minimum', () => {
  const h = backgroundHarness();
  h.loader.load({immersiveBackgroundUrls:['https://example.com/a','https://example.com/b']}, h.display, {immersive_background_interval:1});
  h.images[0].onload();
  assert.equal([...h.timers.values()].some(timer => timer.ms === 3000), true);
  h.loader.cancel();
});

test('failed slideshow images are skipped while the last visible image stays in place', () => {
  const h = backgroundHarness();
  h.loader.load({immersiveBackgroundUrls:['https://example.com/a','https://example.com/b','https://example.com/c']}, h.display);
  h.images[0].onload(); h.tick(12000); h.images[1].onerror();
  assert.equal(h.images.at(-1).src, 'https://example.com/c');
  assert.equal(h.displayed.at(-1)[0], 'https://example.com/a');
  h.images.at(-1).onload(); h.tick(12000);
  assert.equal(h.images.at(-1).src, 'https://example.com/a');
  h.loader.cancel();
});

test('random backgrounds never immediately repeat and cancelling rejects stale loads', () => {
  const h = backgroundHarness();
  h.loader.load({immersiveBackgroundUrls:['https://example.com/a','https://example.com/b','https://example.com/c']}, h.display, {immersive_background_order:'random', immersive_background_interval:5});
  h.images[0].onload();
  for (let i = 0; i < 15; i++) {
    const previous = h.displayed.at(-1)[0]; h.tick(5000);
    assert.notEqual(h.images.at(-1).src, previous); h.images.at(-1).onload();
  }
  h.tick(5000); const stale = h.images.at(-1).onload;
  h.loader.cancel(); stale();
  assert.equal(h.displayed.length, 17); assert.equal(h.timers.size, 0);
});

test('all failed backgrounds fall back to cover and single images never schedule rotation', () => {
  const h = backgroundHarness();
  h.loader.load({immersiveBackgroundUrls:['https://example.com/a','https://example.com/b'], coverUrl:'/covers/local.jpg'}, h.display);
  h.images[0].onerror(); h.images[1].onerror();
  assert.equal(h.images[2].src, '/covers/local.jpg'); h.images[2].onload();
  assert.deepEqual(h.displayed.at(-1), ['/covers/local.jpg', 'cover']); assert.equal(h.timers.size, 0);
  h.loader.load({immersiveBackgroundUrl:'https://example.com/old.jpg'}, h.display);
  h.images.at(-1).onload(); assert.equal(h.timers.size, 0);
});
